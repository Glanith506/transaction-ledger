"""Transaction ledger API backed by Supabase PostgreSQL."""

import os
from contextlib import asynccontextmanager, contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field


# Load backend/.env without overriding Render environment variables.
load_dotenv(
    Path(__file__).resolve().parents[1] / ".env",
    override=False,
)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
MAX_BALANCE_CENTS = 9_000_000_000_000_000


SCHEMA = """
CREATE TABLE IF NOT EXISTS public.accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
        CHECK (char_length(btrim(name)) BETWEEN 1 AND 100),
    balance BIGINT NOT NULL DEFAULT 0
        CHECK (balance BETWEEN 0 AND 9000000000000000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS public.transactions (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES public.accounts(id),
    type TEXT NOT NULL CHECK (type IN ('credit', 'debit')),
    amount BIGINT NOT NULL
        CHECK (amount > 0 AND amount <= 100000000000),
    description TEXT NOT NULL DEFAULT ''
        CHECK (char_length(description) <= 500),
    reference_id TEXT NOT NULL
        CHECK (char_length(btrim(reference_id)) BETWEEN 1 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT unique_account_reference
        UNIQUE (account_id, reference_id)
);

CREATE INDEX IF NOT EXISTS ledger_history
    ON public.transactions (
        account_id,
        created_at DESC,
        id DESC
    );

CREATE OR REPLACE FUNCTION public.ledger_reject_transaction_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Transactions are immutable'
        USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER IF EXISTS ledger_transactions_immutable
    ON public.transactions;

CREATE TRIGGER ledger_transactions_immutable
    BEFORE UPDATE OR DELETE ON public.transactions
    FOR EACH ROW
    EXECUTE FUNCTION public.ledger_reject_transaction_change();

ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
"""


@contextmanager
def connect(*, snapshot=False):
    if not DATABASE_URL:
        raise RuntimeError(
            "Set DATABASE_URL in backend/.env or Render Environment."
        )

    with psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=10,
        sslmode=os.getenv("DB_SSLMODE", "require"),
        prepare_threshold=None,
    ) as db:
        if snapshot:
            db.execute(
                "SET TRANSACTION ISOLATION LEVEL "
                "REPEATABLE READ READ ONLY"
            )
        else:
            db.execute(
                "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
            )

        db.execute("SET LOCAL lock_timeout = '10s'")
        db.execute("SET LOCAL statement_timeout = '20s'")
        db.execute("SET LOCAL TIME ZONE 'UTC'")

        # Commit on success, roll back on error, then close.
        yield db


def initialize():
    with connect() as db:
        db.execute(
            "SELECT pg_advisory_xact_lock(190278411)"
        )
        db.execute(SCHEMA)


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(
    title="Transaction Ledger API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip().rstrip("/")
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(HTTPException)
async def api_error(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": str(exc.status_code),
                "message": exc.detail,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    fields = [
        {
            "field": ".".join(map(str, error["loc"])),
            "message": error["msg"],
        }
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Please check the submitted values.",
                "fields": fields,
            }
        },
    )


@app.exception_handler(psycopg.errors.UniqueViolation)
async def duplicate_error(request, exc):
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "409",
                "message": (
                    "A transaction with this reference already "
                    "exists for this account."
                ),
            }
        },
    )


@app.exception_handler(psycopg.Error)
async def database_error(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": (
                    "The database is busy or unavailable. "
                    "Please try again."
                ),
            }
        },
    )


class Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class AccountInput(Input):
    name: str = Field(
        min_length=1,
        max_length=100,
    )


class TransactionInput(Input):
    type: Literal["credit", "debit"]

    amount: Decimal = Field(
        gt=0,
        le=Decimal("1000000000"),
        max_digits=12,
        decimal_places=2,
    )

    description: str = Field(
        default="",
        max_length=500,
    )

    reference_id: str = Field(
        min_length=1,
        max_length=100,
    )


class TransferInput(Input):
    source_account_id: str = Field(min_length=1)
    destination_account_id: str = Field(min_length=1)

    amount: Decimal = Field(
        gt=0,
        le=Decimal("1000000000"),
        max_digits=12,
        decimal_places=2,
    )

    reference_id: str = Field(
        min_length=1,
        max_length=100,
    )

    description: str = Field(
        default="",
        max_length=500,
    )


def money(value):
    return format(Decimal(value) / 100, ".2f")


def account(db, account_id, *, lock=False):
    sql = (
        "SELECT * FROM public.accounts "
        "WHERE id = %s"
    )

    if lock:
        sql += " FOR UPDATE"

    row = db.execute(
        sql,
        (account_id,),
    ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Account not found.",
        )

    return row


def account_json(row):
    return {
        **row,
        "balance": money(row["balance"]),
        "created_at": row["created_at"].isoformat(),
    }


def transaction_json(row):
    return {
        **row,
        "amount": money(row["amount"]),
        "created_at": row["created_at"].isoformat(),
    }


def post(
    db,
    account_id,
    kind,
    amount_cents,
    description,
    reference,
):
    # Lock the account before checking funds and references.
    row = account(
        db,
        account_id,
        lock=True,
    )

    duplicate = db.execute(
        """
        SELECT 1
        FROM public.transactions
        WHERE account_id = %s
          AND reference_id = %s
        """,
        (account_id, reference),
    ).fetchone()

    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=(
                "A transaction with this reference already "
                "exists for this account."
            ),
        )

    if kind == "debit" and row["balance"] < amount_cents:
        raise HTTPException(
            status_code=409,
            detail="Insufficient balance.",
        )

    change = (
        amount_cents
        if kind == "credit"
        else -amount_cents
    )

    if row["balance"] + change > MAX_BALANCE_CENTS:
        raise HTTPException(
            status_code=409,
            detail="Account balance limit exceeded.",
        )

    transaction = db.execute(
        """
        INSERT INTO public.transactions (
            id,
            account_id,
            type,
            amount,
            description,
            reference_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            str(uuid4()),
            account_id,
            kind,
            amount_cents,
            description,
            reference,
        ),
    ).fetchone()

    db.execute(
        """
        UPDATE public.accounts
        SET balance = balance + %s
        WHERE id = %s
        """,
        (change, account_id),
    )

    return transaction_json(transaction)


@app.get("/api/health")
def health():
    with connect() as db:
        db.execute("SELECT 1")

    return {
        "status": "ok",
        "database": "postgresql",
    }


@app.post("/api/accounts", status_code=201)
def create_account(body: AccountInput):
    with connect() as db:
        row = db.execute(
            """
            INSERT INTO public.accounts (id, name)
            VALUES (%s, %s)
            RETURNING *
            """,
            (str(uuid4()), body.name),
        ).fetchone()

        return account_json(row)


@app.get("/api/accounts")
def list_accounts():
    with connect() as db:
        rows = db.execute(
            """
            SELECT *
            FROM public.accounts
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()

        return [
            account_json(row)
            for row in rows
        ]


@app.get("/api/accounts/{account_id}/balance")
def balance(account_id: str):
    with connect() as db:
        row = account(db, account_id)

        return {
            "account_id": account_id,
            "balance": money(row["balance"]),
        }


@app.post(
    "/api/accounts/{account_id}/transactions",
    status_code=201,
)
def create_transaction(
    account_id: str,
    body: TransactionInput,
):
    with connect() as db:
        return post(
            db,
            account_id,
            body.type,
            int(body.amount * 100),
            body.description,
            body.reference_id,
        )


@app.get("/api/accounts/{account_id}/transactions")
def history(
    account_id: str,
    type: Literal["credit", "debit"] | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    with connect(snapshot=True) as db:
        account(db, account_id)

        clause = "account_id = %s"
        args = [account_id]

        if type:
            clause += " AND type = %s"
            args.append(type)

        total = db.execute(
            (
                "SELECT COUNT(*) AS total "
                "FROM public.transactions WHERE "
                + clause
            ),
            args,
        ).fetchone()["total"]

        rows = db.execute(
            (
                "SELECT * FROM public.transactions WHERE "
                + clause
                + " ORDER BY created_at DESC, id DESC"
                + " LIMIT %s OFFSET %s"
            ),
            args + [limit, (page - 1) * limit],
        ).fetchall()

        return {
            "items": [
                transaction_json(row)
                for row in rows
            ],
            "current_page": page,
            "page_size": limit,
            "total_records": total,
            "total_pages": (total + limit - 1) // limit,
        }


@app.post("/api/transfers", status_code=201)
def transfer(body: TransferInput):
    if body.source_account_id == body.destination_account_id:
        raise HTTPException(
            status_code=422,
            detail="Choose two different accounts.",
        )

    with connect() as db:
        # A consistent lock order prevents reverse-transfer deadlocks.
        account_ids = sorted([
            body.source_account_id,
            body.destination_account_id,
        ])

        for account_id in account_ids:
            account(
                db,
                account_id,
                lock=True,
            )

        amount_cents = int(body.amount * 100)

        debit = post(
            db,
            body.source_account_id,
            "debit",
            amount_cents,
            body.description,
            body.reference_id,
        )

        credit = post(
            db,
            body.destination_account_id,
            "credit",
            amount_cents,
            body.description,
            body.reference_id,
        )

        return {
            "debit": debit,
            "credit": credit,
        }