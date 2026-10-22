import csv
import io
import json
import os
import re
from datetime import date, timedelta
import httpx
from .db import connect, secret
from .imports import dimensions, number, ImportError

ENDPOINT = 'https://stats.unityads.unity3d.com/advertiser/v2/organizations/{org}/reports/acquisitions'


def parse_report(payload, content_type):
    if 'json' in content_type:
        body = json.loads(payload)
        rows = body if isinstance(body, list) else body.get('data')
        if not isinstance(rows, list):
            raise ImportError('Unity: неизвестная структура JSON; данные не изменены.')
    else:
        reader = csv.DictReader(io.StringIO(payload.lstrip('\ufeff')))
        fields = set(reader.fieldnames or [])
        required = [('timestamp', 'date'), ('creativePackId', 'creative_pack_id'), ('country', 'countryCode'), ('spend',), ('installs',)]
        if any(not fields.intersection(names) for names in required):
            raise ImportError('Unity: неизвестные заголовки CSV; данные не изменены.')
        rows = list(reader)
    result = {}
    for row in rows:
        # Unity creative packs are the stable creative key used throughout this app.
        def field(*names):
            for name in names:
                if name in row:
                    return row[name]
            raise ImportError('Unity: отсутствует поле ' + names[0])
        key = dimensions(field('timestamp', 'date'), field('creativePackId', 'creative_pack_id'), field('country', 'countryCode'))
        spend, installs = number(field('spend')), number(field('installs'), True)
        if key in result:
            old = result[key]
            result[key] = (old[0] + spend, old[1] + installs)
        else:
            result[key] = (spend, installs)
    return [(*k, *v) for k, v in result.items()]


def configured():
    return bool(os.getenv('UNITY_ORG_ID') and secret('UNITY_API_KEY'))


def sync_unity():
    if not configured():
        return {'configured': False, 'rows': 0}
    org = os.environ['UNITY_ORG_ID']
    if not re.fullmatch(r'[A-Za-z0-9-]+', org):
        raise ValueError('UNITY_ORG_ID: недопустимый формат')
    days = max(1, min(int(os.getenv('SYNC_LOOKBACK_DAYS', '7')), 90))
    today = date.today()
    with connect() as conn:
        # Session lock prevents overlapping manual and scheduled requests.
        if not conn.execute('SELECT pg_try_advisory_lock(871231) AS locked').fetchone()['locked']:
            return {'busy': True, 'rows': 0}
        try:
            conn.execute('''INSERT INTO sync_state(id,last_attempt) VALUES(1,now())
                ON CONFLICT(id) DO UPDATE SET last_attempt=now()''')
            conn.commit()
            params = {'apikey': secret('UNITY_API_KEY'), 'start': (today-timedelta(days=days)).isoformat() + 'T00:00:00Z',
                'end': today.isoformat() + 'T00:00:00Z', 'scale': 'day', 'groupBy': 'creativePack,country', 'fields': 'spend,installs'}
            with httpx.Client(timeout=120, follow_redirects=False) as client:
                response = client.get(ENDPOINT.format(org=org), params=params, headers={'Accept': 'text/csv'})
            if response.status_code != 200:
                # Never include the URL/body: URL contains API credentials.
                raise ImportError(f'Unity API вернул HTTP {response.status_code}; проверьте доступ и параметры отчёта.')
            if len(response.content) > 50_000_000:
                raise ImportError('Unity: отчёт превышает 50 MB; сократите период.')
            rows = parse_report(response.text, response.headers.get('content-type', ''))
            lower = today-timedelta(days=days)
            if any(not lower <= row[0] < today for row in rows):
                raise ImportError('Unity: дата вне запрошенного периода; данные не изменены.')
            with conn.cursor() as cur:
                cur.executemany('''INSERT INTO unity_daily VALUES(%s,%s,%s,%s,%s)
                    ON CONFLICT(day,creative,geo) DO UPDATE SET spend=excluded.spend,installs=excluded.installs''', rows)
            conn.execute('INSERT INTO imports(source,rows) VALUES(%s,%s)', ('unity', len(rows)))
            conn.execute('UPDATE sync_state SET last_success=now(),error=NULL WHERE id=1')
            conn.commit()
            return {'configured': True, 'rows': len(rows)}
        except Exception as exc:
            conn.rollback()
            message = str(exc) if isinstance(exc, ImportError) else 'Unity: ошибка соединения или формата отчёта. Проверьте настройки.'
            conn.execute('UPDATE sync_state SET error=%s WHERE id=1', (message,))
            conn.commit()
            raise ImportError(message) from None
        finally:
            conn.execute('SELECT pg_advisory_unlock(871231)')
