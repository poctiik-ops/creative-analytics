import os
import time
from .db import init_db
from .unity import sync_unity

init_db()
while True:
    try:
        result = sync_unity()
        print('Unity sync:', result, flush=True)
    except Exception:
        print('Unity sync failed; see authenticated /api/status for details.', flush=True)
    time.sleep(max(60, int(os.getenv('SYNC_INTERVAL_SECONDS', '3600'))))
