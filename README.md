# Transaction Ledger

A small account ledger with a React interface and a Python API. You can open an account, add credits and debits, review its history, and transfer funds to another account.

## Stack

- React 19 and Vite for the frontend
- Python 3.11+, FastAPI and Pydantic for the API
- SQLite for persistent storage
- pytest and HTTPX for API tests
- Docker Compose for an optional container setup

The frontend and backend live in separate folders. No paid service or API key is needed.

## Run locally

Install Python 3.11 or newer and Node.js 20.19 or newer. Open two terminals from the extracted project folder.

In the first terminal:

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Then start the API:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

In the second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173. API documentation is at http://localhost:8000/docs.

The database is created automatically at `backend/data/ledger.sqlite3`. Accounts start empty; create an account and record a credit before trying a debit. The amounts are generic monetary units because the supplied brief does not specify a currency.

## Account dashboard

New accounts appear immediately in **Your accounts**, with their balance, creation date and a short ID. Select a card to see that account's balance and transaction history. Search accounts by name or ID when the list grows.

The transaction form includes **Apply to account**. Choose the account there before submitting a credit or debit. Account cards and this dropdown stay in sync. Transfers have separate source and destination selectors. The account ID shown in dropdowns helps distinguish accounts with the same name.

The overview shows the number of accounts and their combined balance. **Refresh balances** fetches current data from the API. **Export page CSV** downloads only the currently displayed history page, including the account and transaction IDs. Use the history filter and pagination to select the records you need.

Accounts and transactions are stored in `backend/data/ledger.sqlite3` by default. They survive server restarts. When updating an existing installation, stop both servers and replace the frontend source files. Do not delete or overwrite your existing `backend/data` folder. If moving the full project, copy that folder into the new backend directory before starting the API.

## Try the main flow

1. Create two accounts.
2. Credit the first account with 100, using reference `opening-001`.
3. Debit 30 with reference `expense-001`. Its balance should be 70.
4. Submit `expense-001` again. The API rejects the duplicate and leaves the balance alone.
5. Transfer 20 to the second account with a fresh reference. The balances should be 50 and 20.
6. Filter the transaction history by credit or debit and change the page size.

## API routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness check |
| POST | `/api/accounts` | Create an account with a name |
| GET | `/api/accounts` | List accounts for the UI |
| GET | `/api/accounts/{id}/balance` | Read current balance |
| POST | `/api/accounts/{id}/transactions` | Record a credit or debit |
| GET | `/api/accounts/{id}/transactions` | Read filtered, paginated history |
| POST | `/api/transfers` | Transfer between two accounts |

Example account body:

```json
{"name":"Robin Noronha"}
```

Example transaction body:

```json
{"type":"credit","amount":"100.00","description":"Opening deposit","reference_id":"opening-001"}
```

Example transfer body:

```json
{"source_account_id":"SOURCE_ID","destination_account_id":"DESTINATION_ID","amount":"20.00","reference_id":"move-001","description":"Savings"}
```

History accepts `type=credit` or `type=debit`, `page` (starting at 1), and `limit` (1–100). Its response includes `items`, `current_page`, `page_size`, `total_records`, and `total_pages`. Empty histories have zero total pages. Out-of-range pages return an empty list.

Money is returned as a decimal string, such as `"70.00"`. Send decimal strings when possible to avoid floating-point rounding in client code. Inputs support up to two decimal places and a maximum transaction amount of 1,000,000,000 units. Account balances are capped at 90,000,000,000,000 units.

Successful creates return 201. Missing accounts return 404. Duplicate references and insufficient funds return 409. Invalid inputs return 422. Error responses use an `error` object with a `code` and `message`; validation errors also include `fields`.

## Why the ledger stays consistent

Amounts are stored as integer cents. Account creation accepts only a name, so callers cannot supply an ID, initial balance, or timestamp.

SQLite's `BEGIN IMMEDIATE` reserves the writer before checking the balance. The entry and balance update either commit together or roll back together. This also prevents two simultaneous debits from spending the same balance. SQLite serializes writers, which is a reasonable tradeoff for a small assessment project. A higher-volume service would benefit from PostgreSQL and row-level locking.

A unique database constraint covers `(account_id, reference_id)`. The same reference can be used on different accounts. Repeated submissions return a conflict without adding another entry. Transfers use that reference on both accounts, so it must be unused on both. If either side fails, both sides roll back.

Transactions have no update or delete endpoint. Database triggers also block direct updates and deletions of transaction rows. History is sorted by creation time descending, with ID as a deterministic tie-breaker. All timestamps are generated by the server in UTC.

## Tests and production build

From `backend`, with the virtual environment active:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

From `frontend`:

```bash
npm run build
npm run preview
```

The tests cover validation, duplicate handling, balance calculations, filtering, pagination, immutable entries, transfer rollback, database failure rollback and concurrent requests.

## Configuration

Examples are included in both folders. They are reference files, not required for the default setup.

The backend reads `LEDGER_DB` and `CORS_ORIGINS` from the process environment. Set them in your shell before starting Uvicorn; it does not load `.env` automatically. `CORS_ORIGINS` is a comma-separated list of allowed frontend origins.

Vite loads a frontend `.env` file automatically. Set `VITE_API_URL` if the API is hosted somewhere other than `http://localhost:8000/api`, then restart Vite or rebuild.

The interface uses Google Fonts when available and falls back to system fonts offline.

## Docker option

With Docker installed, run this from the project root:

```bash
docker compose up --build
```

Open http://localhost:5173. Database data is retained in a named Docker volume. Stop with `docker compose down`; add `-v` only if you want to delete that database.

## Assignment coverage

All five supplied pages have been reviewed. The implementation covers account creation, credits and debits, duplicate references per account, balances, filtered and paginated history, immutable transactions, validation, consistent errors, and atomic transfers. Page 5 permits any backend framework and database; this project uses Python/FastAPI and SQLite, with the requested React frontend.

The source code is in `frontend/` and `backend/`. Setup instructions are above. API examples are in [docs/API.md](docs/API.md), and the complete machine-readable contract is in [docs/openapi.json](docs/openapi.json). Design assumptions are recorded in [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md).

This is a local assessment project. Authentication, permissions and real payment processing are outside its scope. Docker configuration is included but should be verified in your own Docker environment.
