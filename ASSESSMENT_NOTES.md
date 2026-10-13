# Wirewise — Assessment Notes

**Wirewise** is a capital call reconciliation tool for fund administrators: a GP uploads a
bank statement CSV, Wirewise suggests which capital call line item each incoming payment
belongs to and explains why, and the GP approves, rejects or ignores each suggestion.

- Backend: Django 5.2 + Django REST Framework + SQLite
- Frontend: React 18 + Vite (one page)
- No login. The tenant comes from the `X-Organization` header.

---

## 1. Setup from a fresh clone

Prerequisites: **Python 3.11+** and **Node 18+**.

### Backend (terminal 1)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # optional: every value has a working default
python manage.py migrate
python manage.py seed_demo         # the only way the demo data is created
python manage.py runserver 8000
```

### Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

Open <http://localhost:5173>. Pick an organization, then upload
`sample_data/northwind_statement.csv`.

If the API is not on `http://localhost:8000`, create `frontend/.env.local` with
`VITE_API_BASE_URL=http://localhost:<port>/api` and add that origin to
`CORS_ALLOWED_ORIGINS` in `backend/.env`.

### Run the tests — one command

```bash
cd backend && python manage.py test
```

83 tests, about 0.3s. They cover the eight required cases and the rest of the rules; no
test touches the network, and the Airtable client is faked.

### Sample files

| File | What it exercises |
|---|---|
| `sample_data/northwind_statement.csv` | every matching branch, a debit, a duplicate inside the file, and three invalid rows |
| `sample_data/bluebird_statement.csv` | a second tenant reusing the bank reference `FT20260403A` |
| `sample_data/missing_column.csv` | the whole-file rejection (`400`) |

---

## 2. Data model

```
Organization ─┬─ InvestorEntity ──┐
              ├─ CapitalCall ─────┼─ LineItem ──┐
              ├─ BankTransaction ─────────────┬─┴─ Match
              └───────────────────────────────┘
```

| Model | Fields that matter | Notes |
|---|---|---|
| `Organization` | `slug`, `name` | The tenant. `slug` is what the `X-Organization` header carries. |
| `InvestorEntity` | `name`, `normalised_name` | Unique per organization. The normalised form is computed on save. |
| `CapitalCall` | `sequence`, `call_date`, `due_date` | `sequence` is unique per organization ("Capital Call #2"). |
| `LineItem` | `expected_wire_reference`, `normalised_reference`, `amount_called`, `amount_funded`, `status` | `amount_remaining` is derived, never stored. |
| `BankTransaction` | `date`, `description`, `amount`, `type`, `bank_reference`, `status`, `status_reason`, `source_line_number` | `(organization, bank_reference)` is unique — that *is* the duplicate rule. |
| `Match` | `transaction`, `line_item`, `amount`, `reason`, `status` | One row per proposal, each with its own sentence. |

Every model carries its own `organization` foreign key, so scoping is one
`filter(organization=...)` per query rather than a join that is easy to forget.

**Integrity rules enforced by the database, not only by code:**

- `uniq_bank_reference_per_org` — a bank reference cannot be imported twice for one
  organization, and two organizations may share one.
- `line_item_not_overfunded` — a `CHECK` that `amount_funded <= amount_called`.
- `uniq_approved_match_per_transaction` — at most one approved match per transaction.
- `uniq_wire_reference_per_org`, `uniq_line_item_per_call_investor`.

All money is `DecimalField(max_digits=18, decimal_places=2)`, parsed with `Decimal` and
serialised as a JSON **string**. No float touches an amount anywhere in the backend; the
React page converts to a number only to format it for display.

---

## 3. API

Base URL `/api`. Every endpoint except `GET /api/organizations` requires
`X-Organization: <slug>` — missing header `400`, unknown organization `404`, another
organization's record `404` (never `403`, because it is simply not in the queryset).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/organizations` | Organizations for the switcher. No header needed. |
| `GET` | `/api/transactions` | Transactions newest first, each with its matches, reasons and `available_actions`. Optional `?status=needs_review`. |
| `GET` | `/api/line-items` | Line items with called / funded / remaining / status. |
| `POST` | `/api/imports` | `multipart/form-data` with a `file` part. Returns the import summary (`201`). |
| `POST` | `/api/matches/{id}/approve` | Approve a proposed match and fund its line item. |
| `POST` | `/api/matches/{id}/reject` | Reject a proposed match. |
| `POST` | `/api/transactions/{id}/ignore` | Ignore a suggested or needs_review credit. |
| `GET` | `/api/health` | Liveness check. |

### Import response

```json
{
  "imported": 8,
  "duplicates": 1,
  "rows_read": 12,
  "errors": [{ "line": 10, "message": "date '2026-02-30' is not a real calendar date in YYYY-MM-DD form" }],
  "duplicate_rows": [{ "line": 9, "bank_reference": "FT20260403A", "reason": "bank reference also appears on line 2 of this file" }],
  "status_counts": { "suggested": 4, "needs_review": 3, "ignored": 1 }
}
```

### Status codes

`200` action applied · `201` import accepted · `400` missing header, missing column,
empty file, no file attached · `404` unknown organization or a record outside it ·
`409` the action is no longer valid (already approved, overpayment on re-check, ignoring
a reconciled transaction).

### Try it from a terminal

```bash
curl -s localhost:8000/api/line-items -H 'X-Organization: northwind'
curl -s -X POST localhost:8000/api/imports -H 'X-Organization: northwind' \
     -F file=@sample_data/northwind_statement.csv
curl -s -X POST localhost:8000/api/matches/1/approve -H 'X-Organization: northwind'
```

---

## 4. How the code is laid out

```
backend/reconciliation/
├── domain/            pure functions, no database
│   ├── money.py           Decimal parsing and formatting
│   └── normalisation.py   reference / name normalisation, "found" tests
├── services/          all the business rules
│   ├── matching.py        decide() -> status + reasons + proposals
│   ├── importer.py        CSV validation, duplicates, persistence
│   ├── actions.py         approve / reject / ignore
│   └── summaries.py       import summary -> response shape
├── integrations/airtable.py   optional bonus, easy to fake
├── api/               thin views, serializers, tenant resolution, error mapping
├── management/commands/seed_demo.py
└── tests/             83 tests
```

Views resolve the tenant, call one service function and serialize the result. Everything
worth testing lives in `domain/` and `services/`, and `matching.decide` is a pure
function over already-loaded line items, which is why the matching tests are fast and
read like the specification.

**Key decisions**

- *Suggestions are computed once, at import.* The importer loads the organization's line
  items once per file. No approval can happen mid-import, so funded amounts cannot move
  underneath the loop and a given file always produces the same suggestions.
- *Approve is a compare-and-set, not a read-then-write.* Inside one `transaction.atomic()`
  block it (1) claims the match with `UPDATE ... WHERE status='proposed'`, and (2) funds
  the line item with `UPDATE ... WHERE amount_funded <= amount_called - :amount`. If
  either statement updates zero rows, the whole thing rolls back with a `409`. Two
  simultaneous approvals of the same match therefore cannot both fund it — the second
  finds nothing left to claim — and this holds without row locks, which SQLite does not
  provide. The `CHECK` constraint is the final backstop.
- *The transaction-level reason is stored too*, so a `needs_review` row with no matches
  still explains itself ("…the amount 20,000.00 is more than the remaining 15,000.00
  (overpayment)").

---

## 5. Reading the matching rule in the code

`services/matching.py` follows Section 6 step by step:

1. `eligible_line_items` — same organization, remaining above `0.00`, call date on or
   before the transaction date.
2. Reference check against the normalised description **and** the normalised bank
   reference. One hit within remaining → `suggested`; one hit above remaining → no match
   and `needs_review`; several hits → propose all and `needs_review`. Any hit skips step 3.
3. Name-and-exact-amount check. One → `suggested`; several → propose all and
   `needs_review`; none → `needs_review` with no matches.

Normalisation (`domain/normalisation.py`): references keep letters and digits only and
are matched as a substring (`cc-1003` → `CC1003` is found inside `REFCC1003`); names
collapse punctuation to single spaces, drop one trailing `LLC`/`LP`/`LTD`/`INC`, keep
`TRUST`, and are matched on whole words, so `PATEL FAMILY TRUSTEES` is not a hit for
`PATEL FAMILY TRUST`.

---

## 6. Assumptions and interpretations

1. **Entity suffixes are stripped from the investor name, not from the description.**
   Suffix removal is specified as part of handling the entity name. Stripping a trailing
   `LLC` from a description would never help and could hurt, since a bank description
   rarely ends with the entity name.
2. **Amounts are rounded half-up to two decimal places** on import, matching the stored
   precision. `100.005` becomes `100.01` rather than being rejected.
3. **Amount parsing is deliberately generous** about separators, a leading `+`, and
   accounting-style `(500.00)` for a negative, because real bank exports contain all of
   them. Zero and anything non-numeric are still invalid.
4. **Line numbers come from the CSV reader's physical line counter**, so a quoted field
   containing a newline does not throw the reported numbers out.
5. **A completely blank line is skipped silently** rather than reported as an error.
6. **Several problems in one row produce several error entries** for that line, so the GP
   can fix the row in one pass.
7. **Rejecting an already-rejected match, or ignoring an already-ignored transaction,
   returns `409`.** The specification only names the reconciled case; treating every
   stale action the same way is consistent and keeps the UI honest.
8. **Debits are stored as `ignored` and never matched**, and ignoring one returns `409` —
   it is already in its final state.
9. **`GET /api/organizations` is not tenant-scoped.** The switcher has to list the
   organizations before one is chosen; it exposes only slugs and names.
10. **The organization slug is matched case-insensitively** (`NorthWind` works), which
    costs nothing and avoids a confusing `404`.
11. **A file over 10 MB is rejected** (`IMPORT_MAX_UPLOAD_BYTES`). Files of a few thousand
    rows are well inside this.
12. **`seed_demo` never lowers a funded amount.** Re-running it after an approval leaves
    the funding alone; `--reset` rebuilds the demo organizations from scratch.
13. **An amount too large for the column is a row error**, not an import failure. The
    limit is `9,999,999,999,999,999.99`, the largest value `max_digits=18,
    decimal_places=2` holds. This matters: SQLite does not enforce precision, so an
    oversized value would be stored happily and then raise `decimal.InvalidOperation`
    on every later read of that organization's transactions.
14. **A header that names a required column twice rejects the file.** The reader would
    otherwise silently keep whichever column came last, which is a coin toss.
15. **C0 control characters are stripped from every field.** A NUL byte is accepted by
    SQLite but rejected outright by PostgreSQL, and no bank export needs one.

---

## 7. Trade-offs

- **SQLite, not PostgreSQL.** It keeps a fresh clone to one `migrate`. The approval path
  was written so it does not depend on `SELECT ... FOR UPDATE`, which SQLite ignores, so
  it is correct on both and would move to PostgreSQL with only a settings change.
- **Import is synchronous.** Background workers are out of scope, and a few thousand rows
  import in well under a second inside a single transaction.
- **The optional Airtable sync is synchronous too**, runs after the rows are committed,
  and swallows every error — an Airtable outage can only leave a row marked
  `sync_failed`, never fail an import.
- **No pagination.** A statement-sized list renders fine; adding DRF pagination later is
  a two-line change, but it would have added UI complexity that earns nothing here.
- **The React page holds state in `useState` with a full refetch after each action.**
  A data-fetching library would be over-engineering for one page, and refetching keeps
  the funded amounts shown on screen exactly equal to the database's.
- **Match reasons are generated and stored at import**, not rendered at read time, so the
  reason the GP sees is the reason the engine actually used.

---

## 8. Next steps

1. Move to PostgreSQL and add `select_for_update` as a second layer under the
   compare-and-set, plus a load test of concurrent approvals.
2. Let the GP match a `needs_review` payment to a line item by hand, and split one
   overpayment across several line items — today the honest answer is "needs review".
3. Record an audit trail (who approved what, when) once there are users to attribute it to.
4. Paginate and server-side filter the transaction list for statements with 100k rows.
5. Import history: keep a row per upload so a statement can be traced or re-run.
6. Frontend tests (Vitest + Testing Library) for the table's action states.

---

## 9. Optional bonus: Airtable

Configured entirely through environment variables and off by default:

```
AIRTABLE_ENABLED=True
AIRTABLE_API_TOKEN=pat...
AIRTABLE_BASE_ID=app...
AIRTABLE_TABLE_NAME=Needs Review
```

`integrations/airtable.py` exposes `get_client()`, which returns `NullAirtableClient` when
Airtable is not configured, `HttpAirtableClient` when it is, and `FakeAirtableClient` for
tests — `import_statement(..., airtable_client=...)` takes any of them, so no test patches
`requests`. Only `needs_review` transactions are sent, only records are created, and each
row stores `airtable_record_id` and `airtable_sync_status`
(`not_synced` / `synced` / `sync_failed`).

---

## 10. Required test cases

| # | Case | Where |
|---|---|---|
| 1 | A missing column rejects the file and saves nothing | `tests/test_import.py::MissingColumnTests` |
| 2 | Amount parsing, sign/type mismatches, invalid dates, stored as `Decimal` | `tests/test_import.py::RowValidationTests`, `tests/test_normalisation.py::ParseAmountTests` |
| 3 | Duplicates on re-upload and inside one file | `tests/test_import.py::DuplicateTests` |
| 4 | Reference match, including `cc1001` and a partial payment | `tests/test_matching.py::ReferenceMatchTests` |
| 5 | Name and amount match, including several candidates | `tests/test_matching.py::NameAndAmountMatchTests` |
| 6 | An overpayment becomes `needs_review` with no match | `tests/test_matching.py::OverpaymentTests` |
| 7 | Approving funds the line item; a second approval is `409` with no double funding | `tests/test_actions.py::ApproveTests` |
| 8 | Organization isolation for listing and approving (`404`) | `tests/test_scoping.py::IsolationTests` |

---

## 11. Integrity

I confirm that this submission is entirely my own work. I understand every part of it and
can explain, extend or change any line of it live during the interview.
