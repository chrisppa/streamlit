import os
import sqlite3
import tempfile
import re
import shutil
from datetime import date, datetime, timedelta
from io import BytesIO

import pandas as pd
from urllib.parse import quote
import streamlit as st
from PyPDF2 import PdfReader

# Optional: load .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


st.set_page_config(page_title="EFRIS Report Manager", layout="wide")

# --- 1. Database & Extraction Logic (Backend) ---

def init_db(conn):
    """Ensure the table exists if starting from scratch."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS "EfrisPdfReport" (
            "TIN" TEXT,
            "Taxpayer Name" TEXT,
            "Region" TEXT,
            "Location" TEXT,
            "Risk Source" TEXT,
            "Risk" TEXT,
            "Activity" TEXT,
            "Activity Date" TEXT,
            "Tax Head" TEXT,
            "Assessment Number" TEXT UNIQUE,
            "Amount Assessed" REAL
        )
    """)
    conn.commit()

def extract_text_from_pdf(file_obj):
    """Extract text from a PDF file object (uploaded file)."""
    try:
        reader = PdfReader(file_obj)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        return ""

def extract_data_from_text(text):
    """Parse text using regex patterns from original script."""
    data = {
        "TIN": "N/A",
        "Taxpayer Name": "N/A",
        "Activity Date": "N/A",
        "Assessment Number": "N/A",
        "Amount Assessed": "N/A"
    }
    
    # TIN
    tin_match = re.search(r'TIN\s*[:\-\s]*(\d{9,15})', text, re.IGNORECASE)
    if tin_match:
        data["TIN"] = tin_match.group(1).strip()
    
    # Trade Name
    tradeName_match = re.search(r'Trade\s*Name\s*[:\s-]*([a-zA-Z0-9\s&,.-]+?)(?=\s*Address|\Z)', text, re.IGNORECASE)
    if tradeName_match:
        data["Taxpayer Name"] = tradeName_match.group(1).strip()

    # Issued Date
    date_match = re.search(r'Issued\s*Date[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})', text, re.IGNORECASE)
    if date_match:
        data["Activity Date"] = date_match.group(1).strip()
        
    # FDN / Assessment Number
    fdn_match = re.search(r'Fiscal\s*Document\s*Number[:\-\s]*(\d{13,20})', text, re.IGNORECASE)
    if fdn_match:
        data["Assessment Number"] = fdn_match.group(1).strip()

    # Net Amount
    tax_match = re.search(r'Tax\s*Amount\s*[:\s]*(\d{1,3}(?:,\d{3})*(?:\.\d{4})?)', text, re.IGNORECASE)
    if tax_match:
        data["Amount Assessed"] = tax_match.group(1).strip()
    
    return data

def process_pdfs_and_update_db(db_path, uploaded_pdfs, progress_callback=None):
    """
    Process list of uploaded PDF files, extract data, and insert into DB.
    Returns: (count_inserted, count_skipped, logs)
    """
    conn = sqlite3.connect(db_path)
    init_db(conn) # Ensure table exists
    cursor = conn.cursor()
    
    inserted_count = 0
    skipped_count = 0
    logs = []

    total_files = len(uploaded_pdfs)
    for i, pdf_file in enumerate(uploaded_pdfs):
        if progress_callback:
            progress_callback(i / total_files)
        text = extract_text_from_pdf(pdf_file)
        if not text:
            logs.append(f"❌ {pdf_file.name}: Could not extract text.")
            skipped_count += 1
            continue

        data_row = extract_data_from_text(text)
        assessment_no = data_row.get('Assessment Number', 'N/A')

        # Skip invalid or missing assessment numbers
        if assessment_no == 'N/A' or not assessment_no.strip():
            logs.append(f"⚠️ {pdf_file.name}: Skipped (No Assessment Number found).")
            skipped_count += 1
            continue

        # Convert Amount
        raw_val = data_row.get('Amount Assessed', 'N/A')
        amount_assessed = None
        if raw_val != 'N/A' and raw_val:
            try:
                amount_assessed = float(raw_val.replace(',', ''))
            except ValueError:
                amount_assessed = None

        # Prepare Tuple
        record = (
            data_row['TIN'],
            data_row['Taxpayer Name'],
            "South Western",    # Region
            "",                 # Location
            "Field Surveillance", # Risk Source
            "",                 # Risk
            "EFRIS Inspection/Spot Check", # Activity
            data_row['Activity Date'],
            "VAT",              # Tax Head
            assessment_no,
            amount_assessed
        )

        # Check for existing record manually (safeguard for DBs without UNIQUE constraint)
        cursor.execute('SELECT 1 FROM "EfrisPdfReport" WHERE "Assessment Number" = ?', (assessment_no,))
        if cursor.fetchone():
            logs.append(f"ℹ️ {pdf_file.name}: Skipped (Assessment {assessment_no} already exists).")
            skipped_count += 1
            continue

        try:
            cursor.execute("""
                INSERT INTO "EfrisPdfReport" (
                    "TIN", "Taxpayer Name", "Region", "Location", 
                    "Risk Source", "Risk", "Activity", "Activity Date", 
                    "Tax Head", "Assessment Number", "Amount Assessed"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, record)
            inserted_count += 1
            logs.append(f"✅ {pdf_file.name}: Added (Assessment {assessment_no})")
        except Exception as e:
            logs.append(f"❌ {pdf_file.name}: Error inserting - {str(e)}")
            skipped_count += 1

    conn.commit()
    conn.close()
    return inserted_count, skipped_count, logs


# --- 2. Helper Functions (Frontend) ---

@st.cache_data(show_spinner=False)
def load_table(db_path: str, table_name: str) -> pd.DataFrame:
    uri = f"file:{quote(db_path, safe='/')}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as conn:
            df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
        return df
    except Exception:
        return pd.DataFrame()

def coerce_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)

def coerce_amount(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        return pd.to_numeric(series.str.replace(",", "", regex=False), errors="coerce")
    return pd.to_numeric(series, errors="coerce")


# --- 3. Main Application ---

def main():
    st.title("EFRIS Report Manager")
    
    # Sidebar: Database Selection
    st.sidebar.header("1. Connect Database")
    
    # Initialize session state for the database path if not present
    if "db_path" not in st.session_state:
        st.session_state["db_path"] = None
    if "temp_db_file" not in st.session_state:
        st.session_state["temp_db_file"] = None

    uploaded_db = st.sidebar.file_uploader("Upload current DB (Optional)", type=["db", "sqlite"], key="db_uploader")
    
    # Handle DB upload
    if uploaded_db:
        # If a new file is uploaded, save it to a temp file
        if st.session_state["temp_db_file"] is None:
            tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
            tfile.write(uploaded_db.getvalue())
            tfile.close()
            st.session_state["temp_db_file"] = tfile.name
            st.session_state["db_path"] = tfile.name
            st.toast("Database loaded successfully!")

    # Fallback to local file if no upload (for local testing)
    if not st.session_state["db_path"]:
        default_db = os.getenv("DB_FILEPATH", "EFRIS PDF Report.db")
        if os.path.exists(default_db):
            st.session_state["db_path"] = default_db

    db_path = st.session_state["db_path"]
    table_name = "EfrisPdfReport"

    if not db_path:
        st.warning("👈 Please upload a database file to start.")
        st.stop()

    # Tabs for main functionality
    tab_view, tab_update = st.tabs(["📊 View Reports", "📥 Update from PDFs"])

    # --- TAB 1: VIEW DATA ---
    with tab_view:
        st.caption(f"Connected to: `{os.path.basename(db_path)}`")
        
        # Load Data
        df = load_table(db_path, table_name)
        
        if df.empty:
            st.info("The database is empty or the table 'EfrisPdfReport' was not found.")
        else:
            # Data Processing for Display
            df["__ActivityDate"] = coerce_dates(df.get("Activity Date", pd.Series()))
            df["__AmountNumeric"] = coerce_amount(df.get("Amount Assessed", pd.Series()))

            # Filters
            c1, c2, c3 = st.columns(3)
            with c1:
                search_text = st.text_input("Search (TIN, Name, Assessment)", placeholder="Type to search...")
            with c2:
                if df["__ActivityDate"].notna().any():
                    min_date, max_date = df["__ActivityDate"].min().date(), df["__ActivityDate"].max().date()
                    date_range = st.date_input("Date Range", [min_date, max_date])
            
            # Apply Filters
            filtered_df = df.copy()
            if search_text:
                mask = filtered_df.astype(str).apply(lambda x: x.str.contains(search_text, case=False)).any(axis=1)
                filtered_df = filtered_df[mask]
            
            if isinstance(date_range, list) and len(date_range) == 2:
                start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1]) + pd.Timedelta(days=1)
                filtered_df = filtered_df[(filtered_df["__ActivityDate"] >= start) & (filtered_df["__ActivityDate"] < end)]

            # Metrics
            m1, m2 = st.columns(2)
            m1.metric("Total Records", len(filtered_df))
            total_amt = filtered_df["__AmountNumeric"].sum()
            m2.metric("Total Amount", f"{total_amt:,.2f}")

            # Display
            display_cols = [c for c in filtered_df.columns if not c.startswith("__")]
            st.dataframe(filtered_df[display_cols], use_container_width=True, height=500)

            # Download CSV
            csv = filtered_df[display_cols].to_csv(index=False).encode('utf-8')
            st.download_button("Download Filtered CSV", csv, "efris_report.csv", "text/csv")


    # --- TAB 2: UPDATE FROM PDFS ---
    with tab_update:
        st.header("Update Database from PDFs")
        st.markdown("Upload new EFRIS PDF reports here. They will be scanned, and valid data will be added to your current database session.")

        uploaded_pdfs = st.file_uploader("Upload PDF Files", type=["pdf"], accept_multiple_files=True)
        
        if uploaded_pdfs:
            if st.button(f"Process {len(uploaded_pdfs)} Files"):
                progress_bar = st.progress(0, text="Starting processing...")
                
                # Create a writable copy if we are using a read-only source? 
                # Actually, if we uploaded a DB, it's already a temp file we can write to.
                # If it's a local file (fallback), we should verify permissions.
                
                inserted, skipped, logs = process_pdfs_and_update_db(
                    db_path, 
                    uploaded_pdfs,
                    progress_callback=lambda p: progress_bar.progress(p, text=f"Processing file {int(p * len(uploaded_pdfs)) + 1} of {len(uploaded_pdfs)}")
                )
                
                progress_bar.progress(1.0, text="Finished!")
                st.success(f"Processing Complete! Added: {inserted} | Skipped: {skipped}")
                
                with st.expander("View Processing Logs"):
                    for log in logs:
                        st.write(log)
                
                # Force reload of data in Tab 1
                load_table.clear()
                st.rerun()

        st.divider()
        st.subheader("Download Updated Database")
        st.markdown("Once you have finished updating, download the new `.db` file to keep your changes.")
        
        # Read the current DB file to bytes for download
        if db_path and os.path.exists(db_path):
            with open(db_path, "rb") as f:
                db_bytes = f.read()
            
            st.download_button(
                label="Download Updated Database (.db)",
                data=db_bytes,
                file_name="EFRIS PDF Report_Updated.db",
                mime="application/x-sqlite3"
            )

if __name__ == "__main__":
    main()