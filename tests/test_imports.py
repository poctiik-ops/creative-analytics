import pytest
from app.imports import parse_keitaro, ImportError
from app.unity import parse_report

CSV = b'date,creative_id,geo,offer,clicks,deposits,revenue\n2026-10-19,pack-1,br,Offer A,100,4,99999\n'

def test_csv_ignores_revenue_and_normalizes():
    rows = parse_keitaro(CSV)
    assert len(rows[0]) == 6
    assert rows[0][1:] == ('pack-1','BR','Offer A',100,4)

@pytest.mark.parametrize('value',[b'-1',b'1.5',b'NaN',b'Infinity'])
def test_invalid_counts(value):
    with pytest.raises(ImportError):
        parse_keitaro(CSV.replace(b',100,',b','+value+b','))

def test_duplicate_grain_rejected():
    with pytest.raises(ImportError,match='Повторяется'):
        parse_keitaro(CSV+CSV.splitlines()[1]+b'\n')

def test_empty_rejected():
    with pytest.raises(ImportError):parse_keitaro(CSV.splitlines()[0]+b'\n')

def test_unicode_semicolon():
    assert parse_keitaro('дата;креатив;страна;оффер;клики;депозиты\n2026-10-19;p;de;Тест;3;1'.encode())[0][2]=='DE'

def test_unity_csv_and_extra_dimensions():
    rows=parse_report('timestamp,creativePackId,country,spend,installs\n2026-10-19T00:00:00Z,p,US,2.5,10\n2026-10-19T00:00:00Z,p,US,1.5,2','text/csv')
    assert len(rows)==1 and rows[0][3:]==(4,12)

def test_unknown_unity_schema_fails_closed():
    with pytest.raises(ImportError):parse_report('{"unexpected": []}','application/json')


def test_unity_html_is_not_empty_success():
    with pytest.raises(ImportError):parse_report('<html>error</html>', 'text/html')
