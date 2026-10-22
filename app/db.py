import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row


def secret(name):
    path = os.getenv(name + '_FILE')
    return Path(path).read_text().strip() if path else os.getenv(name, '')


def connect():
    return psycopg.connect(host=os.getenv('DB_HOST', 'localhost'), port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'analytics'), user=os.getenv('DB_USER', 'analytics'),
        password=secret('DB_PASSWORD'), row_factory=dict_row, connect_timeout=10)


def init_db():
    with connect() as conn:
        # Transaction lock makes simultaneous web/worker startup safe.
        conn.execute('SELECT pg_advisory_xact_lock(871230)')
        conn.execute('''CREATE TABLE IF NOT EXISTS unity_daily (
            day date NOT NULL, creative text NOT NULL, geo text NOT NULL,
            spend numeric(18,6) NOT NULL CHECK(spend>=0), installs bigint NOT NULL CHECK(installs>=0),
            PRIMARY KEY(day,creative,geo))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS keitaro_daily (
            day date NOT NULL, creative text NOT NULL, geo text NOT NULL, offer text NOT NULL,
            clicks bigint NOT NULL CHECK(clicks>=0), deposits bigint NOT NULL CHECK(deposits>=0),
            PRIMARY KEY(day,creative,geo,offer))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS imports (
            id bigserial PRIMARY KEY, source text NOT NULL, fingerprint text,
            rows integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(source,fingerprint))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS sync_state (
            id integer PRIMARY KEY CHECK(id=1), last_attempt timestamptz,
            last_success timestamptz, error text)''')
