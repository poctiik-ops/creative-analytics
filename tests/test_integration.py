import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import connect

pytestmark=pytest.mark.skipif(os.getenv('RUN_DB_TESTS')!='1',reason='Requires disposable PostgreSQL; RUN_DB_TESTS=1')
AUTH=('admin',os.getenv('APP_PASSWORD','test-password-123456789'))

@pytest.fixture
def client():
    with TestClient(app) as client:
        with connect() as conn:
            conn.execute('TRUNCATE unity_daily,keitaro_daily,imports,sync_state RESTART IDENTITY')
        yield client


def test_auth_and_csrf(client):
    assert client.get('/').status_code==401
    assert client.get('/api/dashboard').status_code==401
    assert client.get('/',auth=AUTH).status_code==200
    assert client.post('/api/sync',auth=AUTH,headers={'Origin':'https://evil.test'}).status_code==403


def test_snapshot_idempotency_join_and_rollback(client):
    csv=b'date,creative_id,geo,offer,clicks,deposits,revenue\n2026-10-19,p,BR,A,10,2,99999\n2026-10-19,p,BR,B,20,3,99999\n'
    def upload(data):return client.post('/api/import',auth=AUTH,files={'file':('report.csv',data,'text/csv')})
    assert upload(csv).json()=={'rows':2,'duplicate':False}
    assert upload(csv).json()=={'rows':0,'duplicate':True}
    assert upload(csv.replace(b',10,2,',b',11,2,')).status_code==200
    invalid=csv.replace(b',20,3,',b',20,-3,')
    assert upload(invalid).status_code==422
    with connect() as conn:
        conn.execute("INSERT INTO unity_daily VALUES('2026-10-19','p','BR',100,50)")
        assert conn.execute('SELECT count(*) n FROM imports').fetchone()['n']==2
    result=client.get('/api/dashboard?start=2026-10-19&end=2026-10-19',auth=AUTH).json()
    assert result['total']['spend']==100
    assert result['total']['installs']==50
    assert result['total']['clicks']==31
    assert result['total']['deposits']==5
    assert result['total']['cpi']==2
    assert result['total']['cpa']==20
    assert len(result['offers'])==2
    assert client.get('/api/dashboard?start=2026-10-19&end=2026-10-19&geo=US',auth=AUTH).json()['total'] is None


def test_unmatched_sources_do_not_disappear(client):
    with connect() as conn:
        conn.execute("INSERT INTO unity_daily VALUES('2026-10-19','unity-only','BR',100,10)")
        conn.execute("INSERT INTO keitaro_daily VALUES('2026-10-19','keitaro-only','US','A',20,2)")
    result=client.get('/api/dashboard?start=2026-10-19&end=2026-10-19',auth=AUTH).json()
    assert len(result['creatives'])==2
    assert result['total']['matched_days']==0
    assert result['total']['cpa'] is None
    assert result['total']['deposit_rate'] is None
    assert result['total']['spend']==100


def test_unity_sync_snapshot_and_safe_error(client, monkeypatch):
    from datetime import date,timedelta
    import httpx
    from app import unity
    monkeypatch.setenv('UNITY_ORG_ID','test-org')
    monkeypatch.setenv('UNITY_API_KEY','test-key-not-real')
    monkeypatch.delenv('UNITY_API_KEY_FILE',raising=False)
    day=(date.today()-timedelta(days=1)).isoformat()
    class FakeClient:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,params,headers):
            assert url.endswith('/test-org/reports/acquisitions')
            assert params['scale']=='day'
            return httpx.Response(200,headers={'content-type':'text/csv'},text=f'timestamp,creativePackId,country,spend,installs\n{day},p,BR,10,5\n')
    monkeypatch.setattr(unity.httpx,'Client',FakeClient)
    assert unity.sync_unity()['rows']==1
    assert unity.sync_unity()['rows']==1
    with connect() as conn:
        assert conn.execute('SELECT count(*) n FROM unity_daily').fetchone()['n']==1
        assert conn.execute('SELECT sum(spend) s FROM unity_daily').fetchone()['s']==10
    def denied(self,*args,**kwargs):return httpx.Response(403,text='test-key-not-real')
    monkeypatch.setattr(FakeClient,'get',denied)
    with pytest.raises(ValueError,match='HTTP 403'):unity.sync_unity()
    state=client.get('/api/status',auth=AUTH).json()
    assert 'test-key-not-real' not in str(state)
    assert state['sync']['last_success'] is not None
    assert '403' in state['sync']['error']
    with connect() as conn:
        assert conn.execute('SELECT sum(spend) s FROM unity_daily').fetchone()['s']==10
