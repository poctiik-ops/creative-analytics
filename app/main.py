import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from fastapi import FastAPI, Depends, HTTPException, UploadFile, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from .db import connect, init_db, secret
from .imports import save_keitaro, ImportError
from .unity import sync_unity, configured

@asynccontextmanager
async def lifespan(app):
    if len(secret('APP_PASSWORD')) < 16:
        raise RuntimeError('APP_PASSWORD must contain at least 16 characters')
    init_db()
    yield

app = FastAPI(title='Creative Analytics', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
security = HTTPBasic()


def auth(credentials: HTTPBasicCredentials = Depends(security)):
    if not (secrets.compare_digest(credentials.username.encode(), b'admin') &
            secrets.compare_digest(credentials.password.encode(), secret('APP_PASSWORD').encode())):
        raise HTTPException(401, 'Неверный логин или пароль', headers={'WWW-Authenticate': 'Basic'})


def same_origin(request: Request):
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin.split('://')[-1] != request.headers.get('host')):
        raise HTTPException(403, 'Cross-origin requests forbidden')


@app.get('/health')
def health():
    with connect() as conn:
        conn.execute('SELECT 1')
    return {'status': 'ok'}


@app.get('/', dependencies=[Depends(auth)])
def home():
    return FileResponse('app/static/index.html')


@app.get('/api/status', dependencies=[Depends(auth)])
def status():
    with connect() as conn:
        state = conn.execute('SELECT last_attempt,last_success,error FROM sync_state WHERE id=1').fetchone()
        imports = conn.execute('SELECT source,rows,created_at FROM imports ORDER BY id DESC LIMIT 8').fetchall()
    return {'unity_configured': configured(), 'sync': state, 'imports': imports}


@app.post('/api/import', dependencies=[Depends(auth), Depends(same_origin)])
async def import_csv(file: UploadFile):
    data = await file.read(10_000_001)
    await file.close()
    if len(data) > 10_000_000:
        raise HTTPException(413, 'Максимальный размер CSV — 10 MB')
    try:
        with connect() as conn:
            return save_keitaro(conn, data)
    except ImportError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post('/api/sync', dependencies=[Depends(auth), Depends(same_origin)])
def sync():
    try:
        result = sync_unity()
        if not result.get('configured', True):
            raise HTTPException(409, 'Добавьте UNITY_ORG_ID и файл secrets/unity_api_key на сервере.')
        return result
    except ImportError as exc:
        raise HTTPException(502, str(exc)) from None


@app.get('/api/dashboard', dependencies=[Depends(auth)])
def dashboard(start: date = Query(default=None), end: date = Query(default=None), geo: str = '', search: str = ''):
    end = end or date.today()
    start = start or end-timedelta(days=29)
    if start > end or (end-start).days > 366:
        raise HTTPException(422, 'Выберите период до 367 дней, начало не позже конца.')
    # Aggregate Keitaro offers BEFORE joining Unity so spend/installs never multiply by offer count.
    with connect() as conn:
        rows = conn.execute('''WITH u AS (
            SELECT * FROM unity_daily WHERE day BETWEEN %s AND %s
        ), k AS (
            SELECT day,creative,geo,sum(clicks) clicks,sum(deposits) deposits
            FROM keitaro_daily WHERE day BETWEEN %s AND %s GROUP BY day,creative,geo
        ) SELECT coalesce(u.day,k.day) AS day,coalesce(u.creative,k.creative) creative,
            coalesce(u.geo,k.geo) geo,coalesce(spend,0)::float8 spend,coalesce(installs,0) installs,
            coalesce(clicks,0)::bigint clicks,coalesce(deposits,0)::bigint deposits,
            u.day IS NOT NULL has_unity,k.day IS NOT NULL has_keitaro
            FROM u FULL JOIN k USING(day,creative,geo)
            ORDER BY 1,2,3''', (start,end,start,end)).fetchall()
        offers = conn.execute('''SELECT offer,sum(clicks) clicks,sum(deposits) deposits FROM keitaro_daily
            WHERE day BETWEEN %s AND %s AND (%s='' OR geo=%s)
            AND (%s='' OR strpos(lower(creative),lower(%s))>0)
            GROUP BY offer ORDER BY sum(deposits) DESC,offer LIMIT 30''',
            (start,end,geo.upper(),geo.upper(),search,search)).fetchall()
    geos = sorted({r['geo'] for r in rows})
    rows = [r for r in rows if (not geo or r['geo']==geo.upper()) and search.lower() in r['creative'].lower()]
    def aggregate(keys):
        groups = {}
        for r in rows:
            key = tuple(str(r[k]) for k in keys)
            if key not in groups:
                groups[key] = dict(zip(keys,key),spend=0,installs=0,clicks=0,deposits=0,matched_days=0,days=0)
            g = groups[key]
            for metric in ('spend','installs','clicks','deposits'):
                g[metric] += r[metric]
            g['days'] += 1
            g['matched_days'] += int(r['has_unity'] and r['has_keitaro'])
        for g in groups.values():
            g['cpi'] = g['spend']/g['installs'] if g['installs'] else None
            complete = g['matched_days'] == g['days']
            g['cpa'] = g['spend']/g['deposits'] if complete and g['deposits'] else None
            g['deposit_rate'] = 100*g['deposits']/g['installs'] if complete and g['installs'] else None
        return list(groups.values())
    total = aggregate([])
    return {'start': start, 'end': end, 'geos': geos, 'total': total[0] if total else None,
        'daily': aggregate(['day']), 'creatives': aggregate(['creative']),
        'matrix': aggregate(['creative','geo']), 'countries': aggregate(['geo']), 'offers': offers}

app.mount('/static', StaticFiles(directory='app/static'), name='static')
