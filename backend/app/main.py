"""Small, durable ledger. All monetary writes share one database transaction."""
import os
import sqlite3
from contextlib import contextmanager, asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

DB_PATH = os.getenv('LEDGER_DB', 'data/ledger.sqlite3')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, balance INTEGER NOT NULL DEFAULT 0
 CHECK(balance >= 0), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transactions (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
 type TEXT NOT NULL CHECK(type IN ('credit','debit')),
 amount INTEGER NOT NULL CHECK(amount > 0), description TEXT NOT NULL,
 reference_id TEXT NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(account_id, reference_id));
CREATE INDEX IF NOT EXISTS history ON transactions(account_id, created_at DESC, id DESC);
CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON transactions
 BEGIN SELECT RAISE(ABORT, 'Transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON transactions
 BEGIN SELECT RAISE(ABORT, 'Transactions are immutable'); END;
'''

def initialize():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.executescript(SCHEMA)

@contextmanager
def connect(write=False):
    db = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    db.execute('PRAGMA busy_timeout = 15000')
    try:
        if write:
            db.execute('BEGIN IMMEDIATE')  # Reserve the writer before reading a balance.
        yield db
        if write:
            db.commit()
    except Exception:
        if write:
            db.rollback()
        raise
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app):
    initialize()
    yield

app = FastAPI(title='Transaction Ledger API', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(','), allow_methods=['GET','POST'], allow_headers=['Content-Type'])

@app.exception_handler(HTTPException)
async def api_error(request, exc):
    return JSONResponse(status_code=exc.status_code, content={'error': {'code': str(exc.status_code), 'message': exc.detail}})

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    fields = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in exc.errors()]
    return JSONResponse(status_code=422, content={'error': {'code': 'validation_error', 'message': 'Please check the submitted values.', 'fields': fields}})

@app.exception_handler(sqlite3.OperationalError)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={'error': {'code': 'database_unavailable', 'message': 'The database is busy or unavailable. Please try again.'}})

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class AccountInput(Input):
    name: str = Field(min_length=1, max_length=100)

class TransactionInput(Input):
    type: Literal['credit','debit']
    amount: Decimal = Field(gt=0, le=Decimal('1000000000'), max_digits=12, decimal_places=2)
    description: str = Field(default='', max_length=500)
    reference_id: str = Field(min_length=1, max_length=100)

class TransferInput(Input):
    source_account_id: str
    destination_account_id: str
    amount: Decimal = Field(gt=0, le=Decimal('1000000000'), max_digits=12, decimal_places=2)
    reference_id: str = Field(min_length=1, max_length=100)
    description: str = Field(default='', max_length=500)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')

def money(value):
    return format(Decimal(value) / 100, '.2f')

def account(db, account_id):
    row = db.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Account not found.')
    return row

def account_json(row):
    return {**dict(row), 'balance': money(row['balance'])}

def transaction_json(row):
    return {**dict(row), 'amount': money(row['amount'])}

def post(db, account_id, kind, cents, description, reference):
    row = account(db, account_id)
    if db.execute('SELECT 1 FROM transactions WHERE account_id=? AND reference_id=?', (account_id, reference)).fetchone():
        raise HTTPException(409, 'A transaction with this reference already exists for this account.')
    if kind == 'debit' and row['balance'] < cents:
        raise HTTPException(409, 'Insufficient balance.')
    change = cents if kind == 'credit' else -cents
    if row['balance'] + change > 9000000000000000:
        raise HTTPException(409, 'Account balance limit exceeded.')
    tid = str(uuid4())
    db.execute('INSERT INTO transactions VALUES (?,?,?,?,?,?,?)', (tid, account_id, kind, cents, description, reference, now()))
    db.execute('UPDATE accounts SET balance=balance+? WHERE id=?', (change, account_id))
    return transaction_json(db.execute('SELECT * FROM transactions WHERE id=?', (tid,)).fetchone())

@app.get('/api/health')
def health():
    return {'status': 'ok'}

@app.post('/api/accounts', status_code=201)
def create_account(body: AccountInput):
    aid = str(uuid4())
    with connect(write=True) as db:
        db.execute('INSERT INTO accounts VALUES (?,?,0,?)', (aid, body.name, now()))
        return account_json(account(db, aid))

@app.get('/api/accounts')
def list_accounts():
    with connect() as db:
        return [account_json(r) for r in db.execute('SELECT * FROM accounts ORDER BY created_at DESC')]

@app.get('/api/accounts/{account_id}/balance')
def balance(account_id: str):
    with connect() as db:
        row = account(db, account_id)
        return {'account_id': account_id, 'balance': money(row['balance'])}

@app.post('/api/accounts/{account_id}/transactions', status_code=201)
def create_transaction(account_id: str, body: TransactionInput):
    with connect(write=True) as db:
        return post(db, account_id, body.type, int(body.amount * 100), body.description, body.reference_id)

@app.get('/api/accounts/{account_id}/transactions')
def history(account_id: str, type: Literal['credit','debit'] | None = None,
            page: int = Query(1, ge=1), limit: int = Query(10, ge=1, le=100)):
    with connect() as db:
        db.execute('BEGIN')  # Count and page use the same read snapshot.
        account(db, account_id)
        clause = 'account_id=?' + (' AND type=?' if type else '')
        args = [account_id] + ([type] if type else [])
        total = db.execute('SELECT COUNT(*) FROM transactions WHERE ' + clause, args).fetchone()[0]
        rows = db.execute('SELECT * FROM transactions WHERE ' + clause + ' ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?', args + [limit, (page-1)*limit]).fetchall()
        return {'items': [transaction_json(r) for r in rows], 'current_page': page, 'page_size': limit, 'total_records': total, 'total_pages': (total+limit-1)//limit}

@app.post('/api/transfers', status_code=201)
def transfer(body: TransferInput):
    if body.source_account_id == body.destination_account_id:
        raise HTTPException(422, 'Choose two different accounts.')
    with connect(write=True) as db:
        account(db, body.source_account_id)
        account(db, body.destination_account_id)
        cents = int(body.amount * 100)
        debit = post(db, body.source_account_id, 'debit', cents, body.description, body.reference_id)
        credit = post(db, body.destination_account_id, 'credit', cents, body.description, body.reference_id)
        return {'debit': debit, 'credit': credit}
