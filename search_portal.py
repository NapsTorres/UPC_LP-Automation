import os
import pandas as pd
import streamlit as st

# ----------------------------- Page Setup -----------------------------
st.set_page_config(page_title="UPC / LP Search Portal", layout="wide")
st.title("UPC / LP Search Portal")

# ========================= Configuration ==============================
# Folders
ref_folder = "reference"         # Where your reference Excel files live
ref_csv_folder = "reference_csv" # Where converted reference CSVs are stored
events_folder = "events"         # Where your Events Excel files live
events_csv_folder = "events_csv" # Where converted events CSVs are stored
output_folder = "output"         # For search result exports

# Column names (adjust if your headers differ)
REF_UPC_COL = "Case UPC"
REF_LP_COL  = "DBW Group"                            # LP in reference files
EVENT_LP_COL = "L5 Promoted Product Group Code"      # LP in events files

# Event columns to display (we'll only use those that exist when toggle is OFF)
EVENT_DISPLAY_COLS = [
    "Tactic ID", "Promo ID", "L6 Planning Account",
    "Tactic Type", "L5 Promoted Product Group",
    "Payment Type", "Promo Name", "Discount Type",
    "Tactic Performance Start Date", "Tactic Performance End Date",
    "Discount Rate", "Settled Spend $", "Planned Spend $", "Remaining Spend $",
]

# Ensure folders exist
os.makedirs(ref_csv_folder, exist_ok=True)
os.makedirs(events_csv_folder, exist_ok=True)
os.makedirs(output_folder, exist_ok=True)

# ========================== Helper Functions ==========================
@st.cache_data(show_spinner=False)
def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Drop empty rows/cols and strip whitespace on column headers."""
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df

def to_csv(df: pd.DataFrame, name: str):
    path = os.path.join(output_folder, name)
    df.to_csv(path, index=False)
    return path

def safe_subset(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    use_cols = [c for c in cols if c in df.columns]
    return df[use_cols] if use_cols else df

@st.cache_data(show_spinner=False)
def convert_excels_to_csv(src_folder: str, dst_folder: str) -> list[str]:
    """
    Convert all .xlsx/.xls in src_folder to CSV in dst_folder (skip if exists).
    Returns list of CSV filenames created/available in dst_folder.
    """
    if not os.path.isdir(src_folder):
        return []  # no source folder; handled later

    for file in os.listdir(src_folder):
        if file.endswith((".xlsx", ".xls")) and not file.startswith("~$"):
            src_path = os.path.join(src_folder, file)
            csv_name = os.path.splitext(file)[0] + ".csv"
            csv_path = os.path.join(dst_folder, csv_name)
            if not os.path.exists(csv_path):
                # Read & convert
                try:
                    df = pd.read_excel(src_path, engine="openpyxl")
                    df = clean_dataframe(df)
                    df.to_csv(csv_path, index=False)
                except PermissionError as e:
                    # File open/locked or path issue; surface but continue with others
                    st.warning(f"Could not convert `{src_path}` due to permission error: {e}")
                except Exception as e:
                    st.warning(f"Could not convert `{src_path}`: {e}")
    # Return available CSVs
    return sorted([f for f in os.listdir(dst_folder) if f.endswith(".csv")])

@st.cache_data(show_spinner=False)
def load_csvs_as_df(folder: str, selected_files: list[str]) -> pd.DataFrame:
    dfs = []
    for file in selected_files:
        full = os.path.join(folder, file)
        try:
            tmp = pd.read_csv(full)
        except UnicodeDecodeError:
            # Fallback: try latin-1 if needed
            tmp = pd.read_csv(full, encoding="latin-1")
        tmp = clean_dataframe(tmp)
        dfs.append(tmp)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def get_events_for_lps(events_view: pd.DataFrame, lps: list) -> pd.DataFrame:
    if not lps or events_view.empty:
        return pd.DataFrame(columns=events_view.columns if not events_view.empty else [])
    filt = events_view[EVENT_LP_COL].astype(str).isin([str(x) for x in lps])
    return events_view.loc[filt].copy()

# =========================== Session State ============================
# Persist selections & search submission across reruns
if "selected_lps_from_result" not in st.session_state:
    st.session_state.selected_lps_from_result = []
if "search_submitted" not in st.session_state:
    st.session_state.search_submitted = False

# ================== Step 1: Convert Reference Excels ==================
ref_csv_list = convert_excels_to_csv(ref_folder, ref_csv_folder)

# ==================== Step 2: Convert Events Excels ===================
events_csv_list = convert_excels_to_csv(events_folder, events_csv_folder)

# ================= Step 3: Select Reference CSVs to search ============
if not ref_csv_list:
    st.error(
        "No reference CSVs found. Please put your reference Excel files in "
        f"`{ref_folder}/` so they can be converted to CSVs in `{ref_csv_folder}/`."
    )
    st.stop()

selected_ref_csvs = st.multiselect(
    "Select reference CSV file(s) to search",
    ref_csv_list,
    default=ref_csv_list,
    key="selected_ref_csvs"
)
if not selected_ref_csvs:
    st.warning("Please select at least one reference CSV file")
    st.stop()

# ================== Step 4: Select Events CSVs to use =================
if not events_csv_list:
    st.warning(
        "No events CSVs found. Please add your Events Excel file(s) to "
        f"`{events_folder}/` so they can be converted to CSVs in `{events_csv_folder}/`."
    )
    selected_events_csvs = []
else:
    selected_events_csvs = st.multiselect(
        "Select events CSV file(s) to include",
        events_csv_list,
        default=events_csv_list,
        key="selected_events_csvs"
    )

# =================== Step 5: Load Reference Database ==================
reference_db = load_csvs_as_df(ref_csv_folder, selected_ref_csvs)

# Validate required reference columns
missing_ref_cols = [c for c in (REF_UPC_COL, REF_LP_COL) if c not in reference_db.columns]
if missing_ref_cols:
    st.error(
        "Reference CSV(s) missing required column(s): "
        + ", ".join(f"`{c}`" for c in missing_ref_cols)
    )
    st.stop()

# Normalize key columns in reference
reference_db[REF_UPC_COL] = reference_db[REF_UPC_COL].astype(str).str.zfill(5).str.strip()
reference_db[REF_LP_COL]  = reference_db[REF_LP_COL].astype(str).str.strip()

st.write(
    f"Loaded reference database: **{len(reference_db):,}** rows across "
    f"**{len(selected_ref_csvs)}** file(s)."
)

# ===================== Step 6: Load Events Database ===================
if selected_events_csvs:
    events_db = load_csvs_as_df(events_csv_folder, selected_events_csvs)
    if events_db.empty:
        st.warning("Selected events CSVs loaded empty.")
        events_view = pd.DataFrame()
    else:
        # Normalize LP
        if EVENT_LP_COL in events_db.columns:
            events_db[EVENT_LP_COL] = events_db[EVENT_LP_COL].astype(str).str.strip()
        else:
            st.error(
                f"Events CSV(s) missing the LP column `{EVENT_LP_COL}`.\n\n"
                f"Columns found (first file): {', '.join(events_db.columns[:30])} ..."
            )
            events_db = pd.DataFrame()

        # ---- Toggle for All vs Curated columns ----
        if not events_db.empty and EVENT_LP_COL in events_db.columns:
            show_all = st.checkbox("Show all event columns", value=True, key="show_all_cols")
            if show_all:
                events_view = events_db.copy()
            else:
                events_view = safe_subset(events_db, [EVENT_LP_COL] + EVENT_DISPLAY_COLS)
        else:
            events_view = pd.DataFrame()
else:
    events_view = pd.DataFrame()

# ======================== Step 7: Query Inputs ========================
# Wrap inputs in a form so typing doesn't rerun the whole app
with st.form("search_form", clear_on_submit=False):
    c1, c2 = st.columns(2)
    with c1:
        upc_input = st.text_input("Enter UPC(s) (space-separated, optional)", key="upc_input")
    with c2:
        lp_input = st.text_input("Enter LP(s) (space-separated, optional)", key="lp_input")

    submitted = st.form_submit_button("Search")
    if submitted:
        if not upc_input and not lp_input:
            st.warning("Please enter at least a UPC or an LP.")
            st.stop()
        # Mark that we have an active search
        st.session_state.search_submitted = True

# =================== Step 8: Search & Master–Detail ===================
# Only render results after a search is submitted (prevents jumping)
if st.session_state.search_submitted:

    # Parse inputs for the current render
    upc_list = [str(u).strip().zfill(5) for u in st.session_state.get("upc_input", "").split() if str(u).strip()]
    lp_list_input = [s.strip() for s in st.session_state.get("lp_input", "").split() if s.strip()]

    # ---- Reference filter ----
    ref_view = reference_db.copy()
    if upc_list:
        ref_view = ref_view[ref_view[REF_UPC_COL].isin(upc_list)]
    if lp_list_input:
        ref_view = ref_view[ref_view[REF_LP_COL].isin(lp_list_input)]

    has_ref = not ref_view.empty
    if has_ref:
        st.subheader("Reference Matches")
        st.dataframe(ref_view, use_container_width=True, height=350)
        _ = to_csv(ref_view, "search_result_reference.csv")
    else:
        st.info("No matching results found in reference files.")

    # ---- LP selector (from reference) + auto LP (from input) ----
    st.markdown("### View Connected Events")
    st.caption("Pick LP(s) from the reference results, or use the LP you entered above.")

    lps_from_ref = sorted(ref_view[REF_LP_COL].dropna().astype(str).unique()) if has_ref else []

    # Persist LP selection via session state so it survives reruns
    def _on_lp_change():
        st.session_state.selected_lps_from_result = st.session_state._lp_picker

    # Determine initial defaults:
    # - Use existing persisted selection if present
    # - Else seed with input LPs
    default_lps = st.session_state.selected_lps_from_result or lp_list_input

    st.multiselect(
        "LP(s) from current reference results",
        lps_from_ref if lps_from_ref else default_lps,
        default=[lp for lp in default_lps if (not lps_from_ref) or (lp in lps_from_ref)],
        key="_lp_picker",
        on_change=_on_lp_change
    )

    # Effective LPs to show events for
    effective_lps = st.session_state.selected_lps_from_result or lp_list_input

    # ---- Events view (independent of whether reference matched) ----
    if events_view.empty:
        st.warning("No events dataset loaded. Add Events Excel(s) to `events/` and re-run.")
    else:
        if effective_lps:
            events_match = get_events_for_lps(events_view, effective_lps)
            st.subheader("Connected Events")
            if events_match.empty:
                st.info(f"No events found for LP(s): {', '.join(effective_lps)}")
            else:
                st.dataframe(events_match, use_container_width=True, height=500)
                _ = to_csv(events_match, "search_result_events.csv")
        else:
            st.info("Select LP(s) above or enter LP(s) to view connected events.")