import os
import re
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
shipments_folder = "shipments"
shipments_csv_folder = "shipments_csv"
output_folder = "output"

# Column mappings (Reference & Events)
REF_UPC_COL = "Case UPC"
REF_LP_COL = "DBW Group"
EVENT_LP_COL = "L5 Promoted Product Group Code"   # Events column name

# Shipment mapping (UPDATED to your headers)
SHIP_LP_ALIASES = [
    "L5 PROMOTED PRODUCT GROUP CODE",
    "L5_PROMOTED_PRODUCT_GROUP_CODE (2)",
]
SHIP_TACTIC_COL = "TACTIC ID"

# Candidate shipment date columns (not used for sorting now, but kept for parsing)
SHIP_DATE_CANDIDATES = [
    "SHIP DATE", "INVOICE DATE", "PROMO SHIP END DATE", "TACTIC SHIP END DATE",
    "PROMO SHIP START DATE", "TACTIC SHIP START DATE",
]

# Event columns shown by default (falls back gracefully if missing)
EVENT_DISPLAY_COLS = [
    "Tactic ID", "Promo ID", "L6 Planning Account",
    "Tactic Type", "L5 Promoted Product Group",
    "Payment Type", "Promo Name", "Discount Type",
    "Tactic Performance Start Date", "Tactic Performance End Date",
    "Discount Rate", "Settled Spend $", "Planned Spend $", "Remaining Spend $",
]

# Compact filters in events table (order matters for cascading)
COMPACT_FILTER_COLS = [
    "Tactic ID", "Promo ID", "L6 Planning Account",
    "Tactic Type", "Payment Type",
    "Tactic Performance Start Date", "Tactic Performance End Date",
    "Discount Rate"
]

# --- Exact shipment column order as you provided ---
# (We will not drop anything; if a column is missing in a file, it is just skipped.)
SHIP_ALL_COLUMNS = [
    "SALES ORG CODE", "TACTIC ID", "TACTIC TYPE", "DISCOUNT TYPE", "DISCOUNT RATE",
    "PROMOTION ID", "PROMOTION NAME",
    "L1 TOTAL COMPANY CODE", "L1 TOTAL COMPANY NAME",
    "L2 PRODUCT SUMMARY CODE", "L2 PRODUCT SUMMARY NAME",
    "L3 PLANNING PRODUCT CODE", "L3 PLANNING PRODUCT NAME",
    "L4 SUB PLANNING PRODUCT CODE", "L4 SUB PLANNING PRODUCT NAME",
    "L5 PROMOTED PRODUCT GROUP CODE", "L5 PROMOTED PRODUCT GROUP NAME",
    "ITEM NUMBER", "PAYMENT TYPE",
    "TACTIC SHIP START DATE", "TACTIC SHIP END DATE",
    "PROMO SHIP START DATE", "PROMO SHIP END DATE",
    "INVOICE NUMBER", "CASE PACK", "INVOICE DATE", "SHIP DATE",
    "L6 PLANNING ACCOUNT CODE", "L6 PLANNING ACCOUNT NAME",
    "CUSTOMER PO NUMBER", "INVOICE LINE NUMBER", "INVOICE LINE SEQ",
    "SALES INVOICE AMT", "SALES INVOICE QTY", "ACTUAL LIST AMT",
    "L1 SALES BUSINESS UNIT CODE", "L1 SALES BUSINESS UNIT NAME",
    "L2 SALES SEGMENT CODE", "L2 SALES SEGMENT NAME",
    "L3 SALES DIVISION CODE", "L3 SALES DIVISION NAME",
    "L4 SALES REGION CODE", "L4 SALES REGION NAME",
    "L5 SALES MARKET CODE", "L5 SALES MARKET NAME",
    "L7 SUB PLANNING ACCOUNT CODE", "L7 SUB PLANNING ACCOUNT NAME",
    "L8 SHIP TO CODE", "L8 SHIP TO NAME",
    "ITEM NAME", "DOLLAR OFF RATE", "PERCENT OFF RATE", "FIXED AMOUNT RATE",
    "ALLOWED BASED ON DISCOUNT RATE",
    # CASE expression header (add several likely forms so we won’t miss it)
    'case when [DISCOUNT TYPE]="Fixed" then [DISCOUNT RATE] else NULL END',
    'case \nwhen [DISCOUNT TYPE]="Fixed" then [DISCOUNT RATE]\nelse NULL \nEND',
    'case when [DISCOUNT TYPE]=""Fixed"" then [DISCOUNT RATE] else NULL END',
    "10 Digit UPC", "CNSMR_DISPLAY_FLAG", "USER_NAME",
    "L5_PROMOTED_PRODUCT_GROUP_CODE (2)", "L5_PROMOTED_PRODUCT_GROUP_NAME (2)",
    "L6_PLANNING_ACCOUNT_NAME (2)", "Org ID",
]

# Make folders if missing
os.makedirs(ref_csv_folder, exist_ok=True)
os.makedirs(events_csv_folder, exist_ok=True)
os.makedirs(shipments_csv_folder, exist_ok=True)
os.makedirs(output_folder, exist_ok=True)

# ========================== Helper Functions ==========================
@st.cache_data(show_spinner=False)
def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df

def drop_index_like_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Remove 'index' / 'Unnamed: n' artifacts."""
    cols_to_drop = []
    for c in df.columns:
        c_str = str(c)
        if c_str.strip().lower() == "index":
            cols_to_drop.append(c)
        if re.match(r"^Unnamed:\s*\d+\s*$", c_str):
            cols_to_drop.append(c)
    if cols_to_drop:
        df = df.drop(columns=list(set(cols_to_drop)), errors="ignore")
    return df

def to_csv(df: pd.DataFrame, name: str) -> str:
    df_clean = drop_index_like_columns(df)
    path = os.path.join(output_folder, name)
    df_clean.to_csv(path, index=False)
    return path

def safe_subset(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    use_cols = [c for c in cols if c in df.columns]
    return df[use_cols] if use_cols else df

def reorder_columns(df: pd.DataFrame, preferred_order: list) -> pd.DataFrame:
    """Reorder df so preferred_order columns (if present) come first in that order; keep the rest after."""
    head = [c for c in preferred_order if c in df.columns]
    tail = [c for c in df.columns if c not in head]
    return df[head + tail]

def coalesce_series(df: pd.DataFrame, cols: list) -> pd.Series:
    """First non-null across the listed columns."""
    present = [c for c in cols if c in df.columns]
    if not present:
        return pd.Series([None] * len(df), index=df.index)
    s = df[present[0]]
    for c in present[1:]:
        s = s.combine_first(df[c])
    return s

@st.cache_data(show_spinner=False)
def convert_excels_to_csv(src: str, dst: str):
    """Convert all Excel files in `src` to CSV in `dst` (skips if already converted)."""
    if not os.path.isdir(src):
        return []
    for file in os.listdir(src):
        if file.endswith((".xlsx", ".xls")) and not file.startswith("~$"):
            src_path = os.path.join(src, file)
            csv_name = os.path.splitext(file)[0] + ".csv"
            csv_path = os.path.join(dst, csv_name)
            if not os.path.exists(csv_path):
                try:
                    if file.lower().endswith(".xlsx"):
                        df = pd.read_excel(src_path, engine="openpyxl")
                    else:  # .xls
                        df = pd.read_excel(src_path, engine="xlrd")
                    df = clean_dataframe(df)
                    df.to_csv(csv_path, index=False)
                except Exception as e:
                    st.warning(f"Could not convert {src_path}: {e}")
    return sorted([f for f in os.listdir(dst) if f.endswith(".csv")])

@st.cache_data(show_spinner=False)
def load_csvs_as_df(folder: str, files: list) -> pd.DataFrame:
    """Load selected CSV files from a folder into a single DataFrame."""
    dfs = []
    for file in files:
        full = os.path.join(folder, file)
        try:
            df = pd.read_csv(full)
        except Exception:
            df = pd.read_csv(full, encoding="latin-1")
        df = clean_dataframe(df)
        df = drop_index_like_columns(df)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def get_events_for_lps(events_view: pd.DataFrame, lps: list) -> pd.DataFrame:
    if not lps or events_view.empty or EVENT_LP_COL not in events_view.columns:
        return pd.DataFrame()
    return events_view[events_view[EVENT_LP_COL].astype(str).isin(lps)].copy()

def parse_event_dates_inplace(df: pd.DataFrame):
    for col in ["Tactic Performance Start Date", "Tactic Performance End Date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

def detect_shipment_date_col(df: pd.DataFrame):
    for cand in SHIP_DATE_CANDIDATES:
        if cand in df.columns:
            return cand
    return None

# =========================== Session State ============================
if "search_submitted" not in st.session_state:
    st.session_state.search_submitted = False
if "linked_event_tactics" not in st.session_state:
    st.session_state.linked_event_tactics = []
if "linked_effective_lps" not in st.session_state:
    st.session_state.linked_effective_lps = []

# ================= Load Files (Reference & Events) =================
ref_csv_list = convert_excels_to_csv(ref_folder, ref_csv_folder)
events_csv_list = convert_excels_to_csv(events_folder, events_csv_folder)

selected_ref_csvs = st.multiselect("Select reference CSV file(s)", ref_csv_list, default=ref_csv_list)
selected_events_csvs = st.multiselect("Select events CSV file(s)", events_csv_list, default=events_csv_list)

reference_db = load_csvs_as_df(ref_csv_folder, selected_ref_csvs)
events_db = load_csvs_as_df(events_csv_folder, selected_events_csvs)

# Normalize key columns safely
if not reference_db.empty and REF_UPC_COL in reference_db.columns:
    reference_db[REF_UPC_COL] = reference_db[REF_UPC_COL].astype(str).str.zfill(5).str.strip()
if not reference_db.empty and REF_LP_COL in reference_db.columns:
    reference_db[REF_LP_COL] = reference_db[REF_LP_COL].astype(str).str.strip()
if not events_db.empty and EVENT_LP_COL in events_db.columns:
    events_db[EVENT_LP_COL] = events_db[EVENT_LP_COL].astype(str).str.strip()
if not events_db.empty:
    parse_event_dates_inplace(events_db)

# ================= Load Shipment Files =================
shipments_csv_list = convert_excels_to_csv(shipments_folder, shipments_csv_folder)
selected_shipments_csvs = st.multiselect(
    "Select shipment CSV file(s)", shipments_csv_list, default=shipments_csv_list
)
shipments_db = load_csvs_as_df(shipments_csv_folder, selected_shipments_csvs)

# Normalize shipment key columns (we keep ALL columns; no dropping/coalescing)
if not shipments_db.empty:
    # Parse any shipment date column (for future use/robustness)
    ship_date_col = detect_shipment_date_col(shipments_db)
    if ship_date_col:
        shipments_db[ship_date_col] = pd.to_datetime(shipments_db[ship_date_col], errors="coerce")

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
    if not df_ref.empty:
        if upc_list and REF_UPC_COL in df_ref.columns:
            df_ref = df_ref[df_ref[REF_UPC_COL].isin(upc_list)]
        if lp_list and REF_LP_COL in df_ref.columns:
            df_ref = df_ref[df_ref[REF_LP_COL].isin(lp_list)]

    st.subheader("Reference Matches")
    if df_ref.empty:
        st.info("No reference matches found with the provided UPC/LP.")
    st.dataframe(drop_index_like_columns(df_ref), use_container_width=True, hide_index=True)

    # LP selection from reference results
    lps_from_ref = df_ref[REF_LP_COL].dropna().astype(str).unique().tolist() if (not df_ref.empty and REF_LP_COL in df_ref.columns) else []
    selected_lps = st.multiselect("LP(s) from results", lps_from_ref, default=lps_from_ref)
    effective_lps = list(set((selected_lps or []) + lp_list))

    # ----------------------------- Connected Events -----------------------------
    events_match = pd.DataFrame()
    if effective_lps and not events_db.empty:
        events_match = get_events_for_lps(events_db, effective_lps)
        if events_match.empty:
            st.info("No events found for the selected LP(s).")
            st.session_state.linked_event_tactics = []
            st.session_state.linked_effective_lps = list(effective_lps)
        else:
            st.markdown("### Connected Events")

            # Curated vs full (optional)
            show_full = st.checkbox("Show full table (all columns)", value=False, key="events_show_full")
            df_display = events_match.copy() if show_full else safe_subset(events_match, EVENT_DISPLAY_COLS)
            parse_event_dates_inplace(df_display)

            # --- Cascading filters: only show available values ---
            cols_to_filter = [c for c in COMPACT_FILTER_COLS if c in df_display.columns]
            filter_values = {}
            df_work = df_display.copy()  # progressively filtered left -> right

            if cols_to_filter:
                filter_cols = st.columns(len(cols_to_filter))
                for i, col_name in enumerate(cols_to_filter):
                    with filter_cols[i]:
                        if col_name in ["Tactic Performance Start Date", "Tactic Performance End Date"]:
                            val = st.date_input(f"{col_name}", value=None, key=f"ev_f_{col_name}")
                            filter_values[col_name] = val if val else None
                            if val is not None:
                                if not pd.api.types.is_datetime64_any_dtype(df_work[col_name]):
                                    df_work[col_name] = pd.to_datetime(df_work[col_name], errors="coerce")
                                cmp_ts = pd.to_datetime(val)
                                if col_name == "Tactic Performance Start Date":
                                    df_work = df_work[df_work[col_name] >= cmp_ts]
                                else:
                                    df_work = df_work[df_work[col_name] <= cmp_ts]
                        else:
                            options = (
                                df_work[col_name]
                                .dropna()
                                .astype(str)
                                .str.strip()
                                .unique()
                                .tolist()
                            )
                            options = sorted(options)
                            sel = st.selectbox(
                                f"{col_name}",
                                [""] + options,  # "" = no filter
                                index=0,
                                key=f"ev_f_{col_name}"
                            )
                            filter_values[col_name] = sel.strip() if str(sel).strip() != "" else None
                            if filter_values[col_name] is not None:
                                df_work = df_work[df_work[col_name].astype(str).str.strip() == filter_values[col_name]]

            # Final filtered events
            df_filtered = df_work

            # --- Link Events -> Shipments (tactics + lps) ---
            selected_event_tactic = None
            if "Tactic ID" in filter_values and filter_values["Tactic ID"]:
                selected_event_tactic = str(filter_values["Tactic ID"]).strip()
            event_tactics_current = []
            if "Tactic ID" in df_filtered.columns:
                event_tactics_current = (
                    df_filtered["Tactic ID"].dropna().astype(str).str.strip().unique().tolist()
                )
            if selected_event_tactic:
                st.session_state["linked_event_tactics"] = [selected_event_tactic]
            else:
                st.session_state["linked_event_tactics"] = sorted(event_tactics_current)
            st.session_state["linked_effective_lps"] = list(effective_lps)

            # Show + export events
            df_events_show = drop_index_like_columns(df_filtered)
            st.dataframe(df_events_show, use_container_width=True, height=500, hide_index=True)
            path_ev = to_csv(df_events_show, "search_result_events.csv")
            st.caption(f"Saved filtered events to: `{path_ev}`")

    # --------------------------- Shipment Validation ---------------------------
    st.markdown("---")
    st.header("Shipment Validation")

    if shipments_db.empty:
        st.info("No shipment data loaded yet. Drop Excel files into the 'shipments' folder.")
    else:
        shipments_view = shipments_db.copy()

        # Pull LP(s) + connected event Tactic IDs from session
        effective_lps_linked = st.session_state.get("linked_effective_lps", [])
        event_tactics_linked = st.session_state.get("linked_event_tactics", [])

        # 1) Filter by LP(s) from results (coalesce across both LP alias columns)
        if effective_lps_linked:
            lp_coal = coalesce_series(shipments_view, SHIP_LP_ALIASES).astype(str).str.strip()
            shipments_view = shipments_view[lp_coal.isin(effective_lps_linked)]
        else:
            st.info("No LP(s) from results available to filter shipments.")
            shipments_view = shipments_view.iloc[0:0]

        # 2) Filter by connected Events' Tactic IDs
        if not shipments_view.empty:
            if event_tactics_linked and SHIP_TACTIC_COL in shipments_view.columns:
                shipments_view[SHIP_TACTIC_COL] = shipments_view[SHIP_TACTIC_COL].astype(str).str.strip()
                shipments_view = shipments_view[shipments_view[SHIP_TACTIC_COL].isin(event_tactics_linked)]
            else:
                st.info("No connected event Tactic ID(s) detected; shipments filtered to none.")
                shipments_view = shipments_view.iloc[0:0]

        # 3) Sort by coalesced LP -> TACTIC ID (as requested)
        if not shipments_view.empty:
            shipments_view["__LP_SORT__"] = coalesce_series(shipments_view, SHIP_LP_ALIASES).astype(str).str.strip()
            sort_cols = ["__LP_SORT__"] + ([SHIP_TACTIC_COL] if SHIP_TACTIC_COL in shipments_view.columns else [])
            shipments_view = shipments_view.sort_values(sort_cols, ascending=[True] * len(sort_cols), kind="mergesort")
            shipments_view.drop(columns=["__LP_SORT__"], inplace=True, errors="ignore")

        # 4) Keep ALL shipment columns, but order them to your exact header first
        df_ship_show = drop_index_like_columns(shipments_view)
        df_ship_show = reorder_columns(df_ship_show, SHIP_ALL_COLUMNS)

        # Display (no index), then export (no index, no index-like columns)
        st.dataframe(df_ship_show, use_container_width=True, height=500, hide_index=True)
        path_out = to_csv(df_ship_show, "shipment_validation_filtered.csv")
        st.caption(f"Saved filtered shipments to: `{path_out}`")

        