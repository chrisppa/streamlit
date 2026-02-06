import os
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
from urllib.parse import quote
import streamlit as st

# Optional: load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


st.set_page_config(page_title="EFRIS PDF Report Viewer", layout="wide")


@st.cache_data(show_spinner=False)
def load_table(db_path: str, table_name: str) -> pd.DataFrame:
    """Read the full table from SQLite in read-only mode.

    Uses pandas for convenience and returns a DataFrame.
    """
    # Enforce read-only connection
    uri = f"file:{quote(db_path, safe='/')}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
    return df


def coerce_dates(series: pd.Series) -> pd.Series:
    """Convert a date-like text series to pandas datetime (day-first tolerant)."""
    # Try common formats quickly, then fall back to to_datetime with dayfirst
    s = pd.to_datetime(series, errors="coerce", dayfirst=True, infer_datetime_format=True)
    return s


def coerce_amount(series: pd.Series) -> pd.Series:
    """Convert amount-like text to numeric, stripping commas."""
    if series.dtype == object:
        return pd.to_numeric(series.str.replace(",", "", regex=False), errors="coerce")
    return pd.to_numeric(series, errors="coerce")


def main():
    st.title("EFRIS PDF Report Viewer")
    st.caption("Browse and export records from your local SQLite database.")

    # Sidebar configuration
    default_db = os.getenv("DB_FILEPATH", "")
    default_table = os.getenv("TABLE_NAME", "EfrisPdfReport")

    st.sidebar.header("Connection")
    db_path = st.sidebar.text_input(
        "SQLite database path",
        value=default_db,
        placeholder="/path/to/EFRIS PDF Report.db",
        help="Enter the full path to your .db file",
    )
    table_name = st.sidebar.text_input("Table name", value=default_table)

    st.sidebar.header("Filters")
    today = date.today()
    default_start = today - timedelta(days=30)
    date_range = st.sidebar.date_input(
        "Activity Date range",
        value=[default_start, today],
        format="DD/MM/YYYY",
        help="Select From and To dates (inclusive)",
    )

    # Optional quick filters
    with st.sidebar.expander("More filters (optional)"):
        tin_filter = st.text_input("TIN contains", value="")
        assess_filter = st.text_input("Assessment Number contains", value="")

    err = None
    if not db_path:
        err = "Enter a database path to continue."
    elif not os.path.isfile(db_path):
        err = f"Database not found at: {db_path}"

    if err:
        st.info("Provide a valid database path in the sidebar to load data.")
        st.stop()

    try:
        df = load_table(db_path, table_name)
    except Exception as e:
        # Try to give a helpful hint if the table is missing
        try:
            uri = f"file:{quote(db_path, safe='/')}?mode=ro"
            with sqlite3.connect(uri, uri=True) as conn:
                tables = pd.read_sql_query(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;",
                    conn,
                )
            hint = "Available tables: " + ", ".join(tables["name"].tolist()) if not tables.empty else "No tables found."
        except Exception:
            hint = ""
        st.error(f"Failed to load table '{table_name}'. {hint}\n\nDetails: {e}")
        st.stop()

    # Normalize key columns
    activity_col = "Activity Date"
    amount_col = "Amount Assessed"

    if activity_col in df.columns:
        df["__ActivityDate"] = coerce_dates(df[activity_col])
    else:
        st.warning(
            f"Column '{activity_col}' not found. Date filtering disabled."
        )
        df["__ActivityDate"] = pd.NaT

    if amount_col in df.columns:
        df["__AmountNumeric"] = coerce_amount(df[amount_col])
    else:
        df["__AmountNumeric"] = pd.NA

    # Apply filters
    # Date range comes back either as a single date or a list [start, end]
    start_d, end_d = None, None
    if isinstance(date_range, list) and len(date_range) == 2:
        start_d, end_d = date_range
    elif isinstance(date_range, date):
        start_d = end_d = date_range

    if start_d and end_d and df["__ActivityDate"].notna().any():
        start_ts = pd.Timestamp(start_d)
        end_ts = pd.Timestamp(end_d) + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
        df = df[(df["__ActivityDate"] >= start_ts) & (df["__ActivityDate"] <= end_ts)]

    if tin_filter:
        col = "TIN"
        if col in df.columns:
            df = df[df[col].astype(str).str.contains(tin_filter, case=False, na=False)]

    if assess_filter:
        col = "Assessment Number"
        if col in df.columns:
            df = df[df[col].astype(str).str.contains(assess_filter, case=False, na=False)]

    # Summary metrics
    total_rows = len(df)
    total_amount = pd.to_numeric(df["__AmountNumeric"], errors="coerce").sum(min_count=1)

    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", f"{total_rows:,}")
    if pd.notna(total_amount):
        c2.metric("Total Amount Assessed", f"{total_amount:,.2f}")
    if activity_col in df.columns and df["__ActivityDate"].notna().any():
        min_dt = df["__ActivityDate"].min()
        max_dt = df["__ActivityDate"].max()
        c3.metric("Data Date Range", f"{min_dt.date()} → {max_dt.date()}")

    st.divider()
    st.subheader("Results")

    # Display table (hide helper columns)
    display_cols = [c for c in df.columns if not c.startswith("__")]
    st.dataframe(df[display_cols], use_container_width=True)

    # CSV export
    csv_bytes = df[display_cols].to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download CSV",
        data=csv_bytes,
        file_name="efris_report.csv",
        mime="text/csv",
    )

    st.caption("Connected to: " + db_path)


if __name__ == "__main__":
    main()
