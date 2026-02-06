EFRIS PDF Report Viewer (Streamlit)

Quick local UI to browse and export data from your SQLite database, with From/To date filters on the "Activity Date" column.

Setup
- Create and activate a virtual environment:
  - Linux/macOS: `python3 -m venv .venv && source .venv/bin/activate`
  - Windows (PowerShell): `python -m venv .venv; .venv\\Scripts\\Activate.ps1`
- Install dependencies: `pip install -r streamlit_app/requirements.txt`

Configure
- Option A (recommended): copy `streamlit_app/.env.example` to `.env` and set:
  - `DB_FILEPATH` to the absolute path of your `EFRIS PDF Report.db`
  - `TABLE_NAME` (default: `EfrisPdfReport`)
- Option B: set these in the app sidebar when it runs.

Run
- Start the app: `streamlit run streamlit_app/app.py`
- Open the provided local URL in your browser.

Usage
- In the left sidebar, confirm the database path and table name.
- Pick the From and To dates for "Activity Date".
- (Optional) filter by TIN or Assessment Number.
- View results and click "Download CSV" to export.

Notes
- The app opens the SQLite database in read-only mode and never modifies it.
- If your dates are stored as text like `DD/MM/YYYY`, the app converts them for filtering; unparseable rows are excluded by the date filter.

