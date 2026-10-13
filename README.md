# Wirewise

Capital call reconciliation for fund administrators. A GP uploads a bank statement CSV;
Wirewise suggests which capital call line item each incoming payment belongs to, explains
why, and lets the GP approve, reject or ignore each suggestion. Approving funds the line
item — exactly once.

```bash
# backend
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate && python manage.py seed_demo
python manage.py runserver 8000

# frontend (second terminal)
cd frontend && npm install && npm run dev

# tests
cd backend && python manage.py test
```

Then open <http://localhost:5173> and upload `sample_data/northwind_statement.csv`.

Full write-up — data model, API, assumptions, trade-offs — is in
**[ASSESSMENT_NOTES.md](ASSESSMENT_NOTES.md)**.
