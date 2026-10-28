# Assumptions and decisions

- An account holder name is required, but names do not need to be unique. The server generates a UUID for each account and transaction.
- All accounts use the same unspecified currency. The interface labels amounts as units because the brief does not name a currency or require currency conversion.
- Amounts support two decimal places. They are stored as integer cents and returned as decimal strings. Fractional cents are rejected rather than rounded.
- A transaction amount cannot exceed 1,000,000,000 units. Account balances cannot exceed 90,000,000,000,000 units. These limits keep calculations within the supported integer and client display ranges.
- New accounts always start at zero. Their request bodies cannot contain a balance, ID or timestamp.
- Transaction descriptions are optional, with a 500-character limit. References are required, case-sensitive, trimmed, and limited to 100 characters. Account names are trimmed and limited to 100 characters.
- Duplicate references return HTTP 409, even if the rest of the payload matches. They never change the balance. The same reference can be used on different accounts.
- Transfers use one reference on both affected accounts. It must be unused on both. A collision on either account rolls back the entire transfer.
- Transfers between the same account are rejected. Both accounts must exist, and the source must have sufficient funds.
- Each transfer creates an ordinary debit and credit in the same database transaction. There is no separate transfer resource; the response returns both entries.
- Timestamps are generated in UTC. History is latest-first, with transaction ID used to break timestamp ties.
- Pagination starts at page 1. The default page size is 10, with a maximum of 100. Empty results have zero total pages. A page beyond the last page returns an empty list.
- Transactions are append-only. There are no update or delete routes, and database triggers protect existing entries from updates and deletions.
- SQLite serializes write transactions. This keeps concurrent balance checks and updates consistent for a small local application.
- Authentication, multiple currencies, interest, payment gateways and account deletion were not requested. They are not implemented.
