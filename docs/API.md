# API guide

Base URL: `http://localhost:8000/api`

Interactive documentation: `http://localhost:8000/docs`. The adjacent `openapi.json` is the generated API contract, including every request schema and query parameter.

## Create an account

`POST /accounts`

```json
{"name":"Robin Noronha"}
```

Returns 201 with `id`, `name`, `balance` (always `"0.00"` initially), and `created_at`. Unknown input fields are rejected.

`GET /accounts` returns all accounts, newest first. This extra endpoint supports the frontend account selector.

## Read a balance

`GET /accounts/{account_id}/balance`

```json
{"account_id":"ACCOUNT_UUID","balance":"100.00"}
```

Returns 200, or 404 if the account does not exist.

## Record a transaction

`POST /accounts/{account_id}/transactions`

```json
{"type":"credit","amount":"100.00","description":"Opening deposit","reference_id":"deposit-001"}
```

Returns 201 with `id`, `account_id`, `type`, `amount`, `description`, `reference_id`, and `created_at`. Use `debit` to withdraw funds. Amounts must be positive, finite and have at most two decimal places.

An insufficient balance or duplicate reference returns 409. A rejected entry does not affect the balance or history.

## Read history

`GET /accounts/{account_id}/transactions?type=credit&page=1&limit=10`

Omit `type` to include credits and debits. `page` must be at least 1, and `limit` must be between 1 and 100.

```json
{
  "items": [],
  "current_page": 1,
  "page_size": 10,
  "total_records": 0,
  "total_pages": 0
}
```

Entries in `items` use the transaction response fields above. They are sorted by creation time descending. Invalid query parameters return 422; an unknown account returns 404.

## Transfer funds

`POST /transfers`

```json
{
  "source_account_id":"SOURCE_UUID",
  "destination_account_id":"DESTINATION_UUID",
  "amount":"30.00",
  "reference_id":"transfer-001",
  "description":"Move to savings"
}
```

Returns 201 with `debit` and `credit` transaction objects. Both accounts must exist and be different. The source must have sufficient funds. The reference must be unused on both accounts.

The two transaction entries and both balance updates commit together. Any failure rolls back the whole operation, including a duplicate reference on the destination after the source debit has been attempted.

## Error responses

```json
{"error":{"code":"409","message":"Insufficient balance."}}
```

Validation errors return 422 with code `validation_error`, a message, and a `fields` list containing field names and explanations. Database availability failures return 503 with code `database_unavailable`. Unknown accounts return 404. Unsupported methods on defined routes return 405.

## Health

`GET /health` returns `{"status":"ok"}`. This is a process liveness check, not a database readiness check.
