import os
import pandas as pd
import streamlit as st
from datetime import datetime

# ----------------------------- Page Setup -----------------------------
st.set_page_config(page_title="UPC / LP Search Portal", layout="wide")
st.title("UPC / LP Search Portal")

# ========================= Configuration ==============================
ref_folder = "reference"
ref_csv_folder = "reference_csv"
events_folder = "events"
events_csv_folder = "events_csv"
output_folder = "output"

REF_UPC_COL = "Case UPC"
REF_LP_COL = "DBW Group"
EVENT_LP_COL = "L5 Promoted Product Group Code"

EVENT_DISPLAY_COLS = [
    "Tactic ID", "Promo ID", "L6 Planning Account",
    "Tactic Type", "L5 Promoted Product Group",
    "Payment Type", "Promo Name", "Discount Type",
    "Tactic Performance Start Date", "Tactic Performance End Date",
    "Discount Rate", "Settled Spend $", "Planned Spend $", "Remaining Spend $",
]

COMPACT_FILTER_COLS = [
    "Tactic ID", "Promo ID", "L6 Planning Account",
    "Tactic Type", "Payment Type",
    "Tactic Performance Start Date", "Tactic Performance End Date",
    "Discount Rate"
]

# Make folders if missing
os.makedirs(ref_csv_folder, exist_ok=True)
os.makedirs(events_csv_folder, exist_ok=True)
os.makedirs(output_folder, exist_ok=True)

# ========================== Helper Functions ==========================
@st.cache_data(show_spinner=False)
def clean_dataframe(df):
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df

def to_csv(df, name):
    path = os.path.join(output_folder, name)
    df.to_csv(path, index=False)
    return path

def safe_subset(df, cols):
    use_cols = [c for c in cols if c in df.columns]
    return df[use_cols] if use_cols else df

@st.cache_data(show_spinner=False)
def convert_excels_to_csv(src, dst):
    if not os.path.isdir(src):
        return []
    for file in os.listdir(src):
        if file.endswith((".xlsx", ".xls")) and not file.startswith("~$"):
            src_path = os.path.join(src, file)
            csv_name = os.path.splitext(file)[0] + ".csv"
            csv_path = os.path.join(dst, csv_name)
            if not os.path.exists(csv_path):
                try:
                    df = pd.read_excel(src_path, engine="openpyxl")
                    df = clean_dataframe(df)
                    df.to_csv(csv_path, index=False)
                except Exception as e:
                    st.warning(f"Could not convert {src_path}: {e}")
    return sorted([f for f in os.listdir(dst) if f.endswith(".csv")])

@st.cache_data(show_spinner=False)
def load_csvs_as_df(folder, files):
    dfs = []
    for file in files:
        full = os.path.join(folder, file)
        try:
            df = pd.read_csv(full)
        except:
            df = pd.read_csv(full, encoding="latin-1")
        df = clean_dataframe(df)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def get_events_for_lps(events_view, lps):
    if not lps or events_view.empty:
        return pd.DataFrame()
    return events_view[events_view[EVENT_LP_COL].astype(str).isin(lps)].copy()

# =========================== Session State ============================
if "selected_lps_from_result" not in st.session_state:
    st.session_state.selected_lps_from_result = []
if "search_submitted" not in st.session_state:
    st.session_state.search_submitted = False

# ================= Load Files =================
ref_csv_list = convert_excels_to_csv(ref_folder, ref_csv_folder)
events_csv_list = convert_excels_to_csv(events_folder, events_csv_folder)

selected_ref_csvs = st.multiselect("Select reference CSV file(s)", ref_csv_list, default=ref_csv_list)
selected_events_csvs = st.multiselect("Select events CSV file(s)", events_csv_list, default=events_csv_list)

reference_db = load_csvs_as_df(ref_csv_folder, selected_ref_csvs)
events_db = load_csvs_as_df(events_csv_folder, selected_events_csvs)

# Normalize key columns
reference_db[REF_UPC_COL] = reference_db[REF_UPC_COL].astype(str).str.zfill(5).str.strip()
reference_db[REF_LP_COL] = reference_db[REF_LP_COL].astype(str).str.strip()
if EVENT_LP_COL in events_db.columns:
    events_db[EVENT_LP_COL] = events_db[EVENT_LP_COL].astype(str).str.strip()

# ================= Search Form =================
with st.form("search_form"):
    c1, c2 = st.columns(2)
    with c1:
        upc_input = st.text_input("Enter UPC(s) (space-separated)", value="")
    with c2:
        lp_input = st.text_input("Enter LP(s) (space-separated)", value="")
    submitted = st.form_submit_button("Search")
    if submitted:
        st.session_state.search_submitted = True

# ================= Reference Matches & Events =================
if st.session_state.search_submitted:
    # Process user input
    upc_list = [u.strip().zfill(5) for u in upc_input.split() if u.strip()]
    lp_list = [l.strip() for l in lp_input.split() if l.strip()]

    # Filter reference database
    df_ref = reference_db.copy()
    if upc_list:
        df_ref = df_ref[df_ref[REF_UPC_COL].isin(upc_list)]
    if lp_list:
        df_ref = df_ref[df_ref[REF_LP_COL].isin(lp_list)]

    st.subheader("Reference Matches")
    st.dataframe(df_ref, use_container_width=True)

    # LP selection
    lps_from_ref = df_ref[REF_LP_COL].dropna().unique().tolist()
    selected_lps = st.multiselect("LP(s) from results", lps_from_ref, default=lps_from_ref)
    effective_lps = list(set(selected_lps + lp_list))

    # Events Table
    if effective_lps and not events_db.empty:
        events_match = get_events_for_lps(events_db, effective_lps)
        if events_match.empty:
            st.info("No events found.")
        else:
            st.markdown("### Connected Events")

            # Show full table or curated columns
            show_full = st.checkbox("Show full table (all columns)", value=False)
            if show_full:
                df_display = events_match.copy()
            else:
                df_display = safe_subset(events_match, EVENT_DISPLAY_COLS)

            # --- Compact Filters with Auto-Clear ---
            cols = [c for c in COMPACT_FILTER_COLS if c in df_display.columns]
            filter_values = {}
            filter_cols = st.columns(len(cols))

            for i, col_name in enumerate(cols):
                with filter_cols[i]:
                    # Date filters
                    if col_name in ["Tactic Performance Start Date", "Tactic Performance End Date"]:
                        val = st.date_input(f"{col_name}", value=None, key=f"f_{col_name}")
                        filter_values[col_name] = val if val else None
                    # Dropdown/text filters
                    else:
                        unique_vals = df_display[col_name].dropna().unique().tolist()
                        val = st.selectbox(f"{col_name}", [""] + sorted(unique_vals), index=0, key=f"f_{col_name}")
                        filter_values[col_name] = val.strip() if val.strip() != "" else None

            # Apply filters (ignore blank inputs)
            df_filtered = df_display.copy()
            for col, val in filter_values.items():
                if val is None:
                    continue  # skip blank filters
                if col in ["Tactic Performance Start Date", "Tactic Performance End Date"]:
                    if col == "Tactic Performance Start Date":
                        df_filtered = df_filtered[df_filtered[col] >= val]
                    else:
                        df_filtered = df_filtered[df_filtered[col] <= val]
                else:
                    df_filtered = df_filtered[df_filtered[col].astype(str).str.contains(str(val), case=False, na=False)]

            st.dataframe(df_filtered, use_container_width=True, height=500)
            to_csv(df_filtered, "search_result_events.csv")