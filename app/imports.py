import csv
import hashlib
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation

class ImportError(ValueError):
    pass


def number(value, integer=False):
    try:
        n = Decimal(str(value).strip())
        if not n.is_finite() or n < 0 or n > Decimal('1000000000000') or (integer and n != n.to_integral_value()):
            raise ValueError()
        return int(n) if integer else n
    except (ValueError, InvalidOperation):
        raise ImportError('Показатели должны быть неотрицательными числами; клики, установки и депозиты — целыми.')


def dimensions(day, creative, geo):
    try:
        d = date.fromisoformat(str(day)[:10])
    except ValueError:
        raise ImportError('Дата должна быть в формате YYYY-MM-DD.')
    creative, geo = str(creative).strip(), str(geo).strip().upper()
    if not creative or len(creative) > 200 or not re.fullmatch(r'[A-Z]{2}|ZZ', geo):
        raise ImportError('Нужны ID креатива (до 200 символов) и двухбуквенный GEO.')
    return d, creative, geo


ALIASES = {
    'day': ('date', 'day', 'дата'),
    'creative': ('creative_id', 'creative', 'sub_id_1', 'креатив'),
    'geo': ('country_code', 'country', 'geo', 'страна'),
    'offer': ('offer', 'offer_name', 'оффер'),
    'clicks': ('clicks', 'клики'),
    'deposits': ('deposits', 'conversions', 'депозиты'),
}


def parse_keitaro(data):
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ImportError('Сохраните CSV в UTF-8.')
    delimiter = ';' if text.split('\n')[0].count(';') > text.split('\n')[0].count(',') else ','
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = {h.strip().lower(): h for h in reader.fieldnames or []}
    mapping = {key: next((headers[a] for a in aliases if a in headers), None) for key, aliases in ALIASES.items()}
    missing = [k for k, v in mapping.items() if not v]
    if missing:
        raise ImportError('Отсутствуют колонки: ' + ', '.join(missing))
    result = {}
    for line, raw in enumerate(reader, 2):
        if line > 100001:
            raise ImportError('Максимум 100 000 строк.')
        row = {key: raw.get(header) for key, header in mapping.items()}
        if any(v is None for v in row.values()) or None in raw:
            raise ImportError(f'Строка {line}: неверное количество колонок.')
        try:
            key = (*dimensions(row['day'], row['creative'], row['geo']), row['offer'].strip())
            if not key[3] or len(key[3]) > 300:
                raise ImportError('Название оффера обязательно, до 300 символов.')
            if key in result:
                raise ImportError('Повторяется ключ дата / креатив / GEO / оффер. Экспортируйте агрегированный отчёт без лишних разрезов.')
            result[key] = (number(row['clicks'], True), number(row['deposits'], True))
        except ImportError as exc:
            raise ImportError(f'Строка {line}: {exc}') from exc
    if not result:
        raise ImportError('CSV не содержит данных.')
    return [(*key, *values) for key, values in result.items()]


def save_keitaro(conn, data):
    rows = parse_keitaro(data)
    fingerprint = hashlib.sha256(data).hexdigest()
    # Audit insertion and all updates are one transaction. Concurrent identical uploads serialize here.
    imported = conn.execute('INSERT INTO imports(source,fingerprint,rows) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id',
        ('keitaro', fingerprint, len(rows))).fetchone()
    if not imported:
        return {'rows': 0, 'duplicate': True}
    with conn.cursor() as cur:
        cur.executemany('''INSERT INTO keitaro_daily VALUES(%s,%s,%s,%s,%s,%s)
            ON CONFLICT(day,creative,geo,offer) DO UPDATE SET clicks=excluded.clicks,deposits=excluded.deposits''', rows)
    return {'rows': len(rows), 'duplicate': False}
