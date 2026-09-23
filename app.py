import io
import json
import os
import re
import secrets
import time
import threading

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file, session

# ──────────────────────────── App setup ────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# ========================= Configuration ==============================
DATA_ROOT = "user_data"   # all per-session folders live under here

REF_UPC_COL   = "Case UPC"
REF_LP_COL    = "DBW Group"
EVENT_LP_COL  = "L5 Promoted Product Group Code"

SHIP_LP_ALIASES = [
    "L5 PROMOTED PRODUCT GROUP CODE",
    "L5_PROMOTED_PRODUCT_GROUP_CODE (2)",
]
SHIP_TACTIC_COL = "TACTIC ID"

SHIP_DATE_CANDIDATES = [
    "SHIP DATE", "INVOICE DATE", "PROMO SHIP END DATE", "TACTIC SHIP END DATE",
    "PROMO SHIP START DATE", "TACTIC SHIP START DATE",
]

EVENT_DISPLAY_COLS = [
    "Tactic ID", "Promo ID", "L6 Planning Account",
    "Tactic Type", "Payment Type", "Promo Name", "Discount Type",
    "Tactic Performance Start Date", "Tactic Performance End Date",
    "L5 Promoted Product Group Code", "Discount Rate",
    "Settled Spend $", "Planned Spend $", "Remaining Spend $",
]

COMPACT_FILTER_COLS = [
    "Tactic ID", "Promo ID", "L6 Planning Account",
    "Tactic Type", "Payment Type",
    "Tactic Performance Start Date", "Tactic Performance End Date",
    "Discount Rate",
]

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
    'case when [DISCOUNT TYPE]="Fixed" then [DISCOUNT RATE] else NULL END',
    'case \nwhen [DISCOUNT TYPE]="Fixed" then [DISCOUNT RATE]\nelse NULL \nEND',
    'case when [DISCOUNT TYPE]=""Fixed"" then [DISCOUNT RATE] else NULL END',
    "10 Digit UPC", "CNSMR_DISPLAY_FLAG", "USER_NAME",
    "L5_PROMOTED_PRODUCT_GROUP_CODE (2)", "L5_PROMOTED_PRODUCT_GROUP_NAME (2)",
    "L6_PLANNING_ACCOUNT_NAME (2)", "Org ID",
]

os.makedirs(DATA_ROOT, exist_ok=True)

# ========================== Per-session folder helpers ==========================

def _sess_id() -> str:
    """Always return the same fixed session ID (single-user local tool)."""
    return "default"


def _sess_dirs(sid: str) -> dict:
    """Return the six folder paths for a given session ID."""
    base = os.path.join(DATA_ROOT, sid)
    return {
        "ref":          os.path.join(base, "reference"),
        "ref_csv":      os.path.join(base, "reference_csv"),
        "events":       os.path.join(base, "events"),
        "events_csv":   os.path.join(base, "events_csv"),
        "shipments":    os.path.join(base, "shipments"),
        "shipments_csv": os.path.join(base, "shipments_csv"),
    }


def _ensure_dirs(sid: str) -> dict:
    dirs = _sess_dirs(sid)
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    return dirs


# ========================== Per-session in-memory DBs ==========================
# { sid: { "ref": DataFrame, "events": DataFrame, "shipments": DataFrame } }
_SESSION_DBS: dict = {}
_DB_LOCK = threading.Lock()


def _get_dbs(sid: str) -> dict:
    with _DB_LOCK:
        if sid not in _SESSION_DBS:
            _SESSION_DBS[sid] = {
                "ref":       pd.DataFrame(),
                "events":    pd.DataFrame(),
                "shipments": pd.DataFrame(),
            }
        return _SESSION_DBS[sid]


# ========================== Helper Functions ==========================

def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(how="all")
    df = df.dropna(axis=1, how="all")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def drop_index_like_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in df.columns
            if str(c).strip().lower() == "index"
            or re.match(r"^Unnamed:\s*\d+\s*$", str(c))]
    return df.drop(columns=list(set(cols)), errors="ignore") if cols else df


def safe_subset(df: pd.DataFrame, cols: list) -> pd.DataFrame:
    use = [c for c in cols if c in df.columns]
    return df[use] if use else df


def reorder_columns(df: pd.DataFrame, preferred: list) -> pd.DataFrame:
    head = [c for c in preferred if c in df.columns]
    tail = [c for c in df.columns if c not in head]
    return df[head + tail]


def coalesce_series(df: pd.DataFrame, cols: list) -> pd.Series:
    present = [c for c in cols if c in df.columns]
    if not present:
        return pd.Series([None] * len(df), index=df.index)
    s = df[present[0]].copy()
    for c in present[1:]:
        s = s.combine_first(df[c])
    return s


def parse_tokens(raw: str) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in re.split(r"[\s,]+", raw) if t.strip()))


def convert_excels_to_csv(src: str, dst: str) -> list[str]:
    if not os.path.isdir(src):
        return []
    for fname in os.listdir(src):
        if fname.endswith((".xlsx", ".xls")) and not fname.startswith("~$"):
            src_path = os.path.join(src, fname)
            csv_path = os.path.join(dst, os.path.splitext(fname)[0] + ".csv")
            if not os.path.exists(csv_path):
                try:
                    engine = "openpyxl" if fname.lower().endswith(".xlsx") else "xlrd"
                    df = pd.read_excel(src_path, engine=engine)
                    clean_dataframe(df).to_csv(csv_path, index=False)
                except Exception:
                    pass
    return sorted(f for f in os.listdir(dst) if f.endswith(".csv"))


def load_csvs(folder: str, files: list) -> pd.DataFrame:
    dfs = []
    for f in files:
        path = os.path.join(folder, f)
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception:
            df = pd.read_csv(path, encoding="latin-1", low_memory=False)
        df = drop_index_like_columns(clean_dataframe(df))
        df["__source__"] = f   # track which file each row came from
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


def parse_event_dates(df: pd.DataFrame) -> pd.DataFrame:
    for col in ("Tactic Performance Start Date", "Tactic Performance End Date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%m/%d/%Y")
    return df


def _csv_list(folder: str) -> list[str]:
    return sorted(f for f in os.listdir(folder) if f.endswith(".csv")) if os.path.isdir(folder) else []


# ========================== Per-session reload helpers ==========================

def _reload_ref(sid: str, dirs: dict):
    convert_excels_to_csv(dirs["ref"], dirs["ref_csv"])
    db = load_csvs(dirs["ref_csv"], _csv_list(dirs["ref_csv"]))
    if not db.empty:
        if REF_UPC_COL in db.columns:
            db[REF_UPC_COL] = db[REF_UPC_COL].astype(str).str.zfill(5).str.strip()
        if REF_LP_COL in db.columns:
            db[REF_LP_COL] = db[REF_LP_COL].astype(str).str.strip()
    _get_dbs(sid)["ref"] = db


def _reload_events(sid: str, dirs: dict):
    convert_excels_to_csv(dirs["events"], dirs["events_csv"])
    db = load_csvs(dirs["events_csv"], _csv_list(dirs["events_csv"]))
    if not db.empty:
        if EVENT_LP_COL in db.columns:
            db[EVENT_LP_COL] = db[EVENT_LP_COL].astype(str).str.strip()
        db = parse_event_dates(db)
        if "Planned Spend $" in db.columns and "Settled Spend $" in db.columns:
            db["Remaining Spend $"] = (
                pd.to_numeric(db["Planned Spend $"], errors="coerce").fillna(0)
                - pd.to_numeric(db["Settled Spend $"], errors="coerce").fillna(0)
            )
    _get_dbs(sid)["events"] = db


def _reload_shipments(sid: str, dirs: dict):
    convert_excels_to_csv(dirs["shipments"], dirs["shipments_csv"])
    db = load_csvs(dirs["shipments_csv"], _csv_list(dirs["shipments_csv"]))
    if not db.empty and SHIP_TACTIC_COL in db.columns:
        db[SHIP_TACTIC_COL] = db[SHIP_TACTIC_COL].astype(str).str.strip()
    _get_dbs(sid)["shipments"] = db


_RELOAD_FNS = {
    "ref":       _reload_ref,
    "events":    _reload_events,
    "shipments": _reload_shipments,
}
_FOLDER_KEYS = {
    "ref":       ("ref",       "ref_csv"),
    "events":    ("events",    "events_csv"),
    "shipments": ("shipments", "shipments_csv"),
}


# ========================== Routes ==========================

_ASSET_VER = str(int(time.time()))


@app.route("/")
def index():
    sid  = _sess_id()
    dirs = _ensure_dirs(sid)
    # Load any pre-existing files for this session on first visit
    dbs = _get_dbs(sid)
    if dbs["ref"].empty and dbs["events"].empty and dbs["shipments"].empty:
        _reload_ref(sid, dirs)
        _reload_events(sid, dirs)
        _reload_shipments(sid, dirs)

    return render_template("index.html",
                           ref_files=_csv_list(dirs["ref_csv"]),
                           events_files=_csv_list(dirs["events_csv"]),
                           ship_files=_csv_list(dirs["shipments_csv"]),
                           asset_ver=_ASSET_VER)


@app.route("/api/search", methods=["POST"])
def api_search():
    sid  = _sess_id()
    dirs = _ensure_dirs(sid)
    dbs  = _get_dbs(sid)
    body = request.get_json(force=True)

    upc_list    = [u.zfill(5) for u in parse_tokens(body.get("upc", ""))]
    lp_list     = parse_tokens(body.get("lp", ""))
    ref_files   = body.get("ref_files",    None)   # None means "all"
    ev_files    = body.get("events_files", None)

    def _filter_source(df, files):
        """Keep only rows whose __source__ is in the checked file list."""
        if files is None or "__source__" not in df.columns:
            return df
        return df[df["__source__"].isin(files)] if files else df.iloc[0:0]

    def _drop_source(df):
        return df.drop(columns=["__source__"], errors="ignore")

    # ── reference ──
    df_ref = _filter_source(dbs["ref"], ref_files)
    df_ref = df_ref if df_ref is dbs["ref"] else df_ref.copy()
    if not df_ref.empty:
        if upc_list and REF_UPC_COL in df_ref.columns:
            df_ref = df_ref[df_ref[REF_UPC_COL].isin(upc_list)]
        if lp_list and REF_LP_COL in df_ref.columns:
            df_ref = df_ref[df_ref[REF_LP_COL].isin(lp_list)]

    lps_from_ref = (
        df_ref[REF_LP_COL].dropna().astype(str).unique().tolist()
        if (not df_ref.empty and REF_LP_COL in df_ref.columns) else []
    )

    # ── events ──
    effective_lps = list(dict.fromkeys(lps_from_ref + lp_list))
    ev_db = _filter_source(dbs["events"], ev_files)

    if ev_db.empty:
        events_match = pd.DataFrame()
    elif effective_lps and EVENT_LP_COL in ev_db.columns:
        events_match = ev_db[ev_db[EVENT_LP_COL].isin(effective_lps)]
    else:
        events_match = ev_db

    filter_options = {}
    for col in COMPACT_FILTER_COLS:
        if col in events_match.columns:
            filter_options[col] = sorted(
                events_match[col].dropna().astype(str).str.strip().unique().tolist()
            )

    ev_clean = _drop_source(drop_index_like_columns(events_match))
    ref_clean = _drop_source(drop_index_like_columns(df_ref))
    return jsonify({
        "ref":            _df_to_records(ref_clean),
        "ref_cols":       list(ref_clean.columns),
        "lps_from_ref":   lps_from_ref,
        "effective_lps":  effective_lps,
        "events":         _df_to_records(ev_clean),
        "events_cols":    list(ev_clean.columns),
        "filter_options": filter_options,
        "event_tactics":  (
            events_match["Tactic ID"].dropna().astype(str).str.strip().unique().tolist()
            if "Tactic ID" in events_match.columns else []
        ),
        "spend": {
            "planned":   float(pd.to_numeric(events_match.get("Planned Spend $"),  errors="coerce").sum()) if "Planned Spend $"  in events_match.columns else 0,
            "settled":   float(pd.to_numeric(events_match.get("Settled Spend $"),  errors="coerce").sum()) if "Settled Spend $"  in events_match.columns else 0,
            "remaining": float(pd.to_numeric(events_match.get("Remaining Spend $"), errors="coerce").sum()) if "Remaining Spend $" in events_match.columns else 0,
        },
    })


@app.route("/api/shipments", methods=["POST"])
def api_shipments():
    sid  = _sess_id()
    dbs  = _get_dbs(sid)
    dirs = _ensure_dirs(sid)
    body = request.get_json(force=True)

    tactic_list   = parse_tokens(body.get("tactic", ""))
    lp_list       = parse_tokens(body.get("lp",     ""))
    item_list     = parse_tokens(body.get("item",   ""))
    event_tactics = body.get("event_tactics", [])
    ship_files    = body.get("ship_files", None)

    raw_sv = dbs["shipments"]
    if "__source__" in raw_sv.columns and ship_files is not None:
        sv = raw_sv[raw_sv["__source__"].isin(ship_files)].copy()
    else:
        sv = raw_sv
    if sv.empty:
        return jsonify({"rows": [], "cols": [], "tactics": []})

    has_direct = bool(tactic_list or lp_list or item_list)

    if has_direct:
        if tactic_list and SHIP_TACTIC_COL in sv.columns:
            sv[SHIP_TACTIC_COL] = sv[SHIP_TACTIC_COL].astype(str).str.strip()
            sv = sv[sv[SHIP_TACTIC_COL].isin(tactic_list)]
        if lp_list:
            lp_s = coalesce_series(sv, SHIP_LP_ALIASES).astype(str).str.strip()
            sv = sv[lp_s.isin(lp_list)]
        if item_list and "ITEM NUMBER" in sv.columns:
            sv["ITEM NUMBER"] = sv["ITEM NUMBER"].astype(str).str.strip()
            sv = sv[sv["ITEM NUMBER"].isin(item_list)]
        active_tactics = (
            tactic_list if tactic_list
            else sv[SHIP_TACTIC_COL].dropna().astype(str).str.strip().unique().tolist()
            if SHIP_TACTIC_COL in sv.columns else []
        )
    else:
        if event_tactics and SHIP_TACTIC_COL in sv.columns:
            sv[SHIP_TACTIC_COL] = sv[SHIP_TACTIC_COL].astype(str).str.strip()
            sv = sv[sv[SHIP_TACTIC_COL].isin(event_tactics)]
        else:
            sv = sv.iloc[0:0]
        active_tactics = event_tactics

    if not sv.empty:
        sv["__LP__"] = coalesce_series(sv, SHIP_LP_ALIASES).astype(str).str.strip()
        sort_cols = ["__LP__"] + ([SHIP_TACTIC_COL] if SHIP_TACTIC_COL in sv.columns else [])
        sv = sv.sort_values(sort_cols, kind="mergesort").drop(columns=["__LP__"])

    sv = reorder_columns(drop_index_like_columns(sv.drop(columns=["__source__"], errors="ignore")), SHIP_ALL_COLUMNS)

    return jsonify({
        "rows":    _df_to_records(sv),
        "cols":    list(sv.columns),
        "tactics": sorted(set(active_tactics)),
    })


@app.route("/api/download_shipments", methods=["POST"])
def download_shipments():
    sid  = _sess_id()
    dbs  = _get_dbs(sid)
    body = request.get_json(force=True)

    filename      = body.get("filename", "shipments_POP.csv")
    single_tactic = body.get("tactic", "")
    tactic_list   = [str(t).strip() for t in body.get("tactic_list",   [])]
    lp_list       = [str(l).strip() for l in body.get("lp_list",       [])]
    item_list     = [str(i).strip() for i in body.get("item_list",     [])]
    event_tactics = [str(t).strip() for t in body.get("event_tactics", [])]

    sv = dbs["shipments"]
    if sv.empty:
        return ("No shipment data loaded.", 404)

    has_direct = bool(tactic_list or lp_list or item_list)
    if has_direct:
        if tactic_list and SHIP_TACTIC_COL in sv.columns:
            sv = sv[sv[SHIP_TACTIC_COL].isin(tactic_list)]
        if lp_list:
            lp_s = coalesce_series(sv, SHIP_LP_ALIASES).astype(str).str.strip()
            sv = sv[lp_s.isin(lp_list)]
        if item_list and "ITEM NUMBER" in sv.columns:
            sv = sv[sv["ITEM NUMBER"].astype(str).str.strip().isin(item_list)]
    else:
        if event_tactics and SHIP_TACTIC_COL in sv.columns:
            sv = sv[sv[SHIP_TACTIC_COL].isin(event_tactics)]
        else:
            sv = sv.iloc[0:0]

    if single_tactic and SHIP_TACTIC_COL in sv.columns:
        sv = sv[sv[SHIP_TACTIC_COL].astype(str).str.strip() == single_tactic.strip()]

    sv = reorder_columns(drop_index_like_columns(sv.drop(columns=["__source__"], errors="ignore")), SHIP_ALL_COLUMNS)
    buf = io.StringIO()
    sv.to_csv(buf, index=False)
    buf.seek(0)
    return send_file(
        io.BytesIO(buf.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


_ALLOWED = {".xlsx", ".xls", ".csv"}


@app.route("/api/files")
def api_files():
    sid  = _sess_id()
    dirs = _ensure_dirs(sid)
    return jsonify({
        "ref":       _csv_list(dirs["ref_csv"]),
        "events":    _csv_list(dirs["events_csv"]),
        "shipments": _csv_list(dirs["shipments_csv"]),
    })


@app.route("/api/upload", methods=["POST"])
def api_upload():
    sid        = _sess_id()
    dirs       = _ensure_dirs(sid)
    folder_key = request.form.get("folder", "")

    if folder_key not in _FOLDER_KEYS:
        return jsonify({"error": "Invalid folder key"}), 400

    src_key, csv_key = _FOLDER_KEYS[folder_key]
    src_folder  = dirs[src_key]
    csv_folder  = dirs[csv_key]

    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file provided"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED:
        return jsonify({"error": f"File type {ext} not allowed"}), 400

    safe_name = re.sub(r"[^\w\-. ]", "_", file.filename)
    save_path  = os.path.join(src_folder if ext in {".xlsx", ".xls"} else csv_folder, safe_name)
    file.save(save_path)

    if ext in {".xlsx", ".xls"}:
        csv_name = os.path.splitext(safe_name)[0] + ".csv"
        csv_path = os.path.join(csv_folder, csv_name)
        try:
            engine = "openpyxl" if ext == ".xlsx" else "xlrd"
            df = pd.read_excel(save_path, engine=engine)
            clean_dataframe(df).to_csv(csv_path, index=False)
        except Exception as e:
            return jsonify({"error": f"Could not convert file: {e}"}), 500

    _RELOAD_FNS[folder_key](sid, dirs)
    return jsonify({
        "ok":        True,
        "ref":       _csv_list(dirs["ref_csv"]),
        "events":    _csv_list(dirs["events_csv"]),
        "shipments": _csv_list(dirs["shipments_csv"]),
    })


@app.route("/api/delete_file", methods=["POST"])
def api_delete_file():
    sid  = _sess_id()
    dirs = _ensure_dirs(sid)
    body = request.get_json(force=True)

    folder_key = body.get("folder", "")
    filename   = body.get("filename", "")

    if folder_key not in _FOLDER_KEYS:
        return jsonify({"error": "Invalid folder key"}), 400
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return jsonify({"error": "Invalid filename"}), 400

    src_key, csv_key = _FOLDER_KEYS[folder_key]
    csv_path = os.path.join(dirs[csv_key], filename)
    if os.path.exists(csv_path):
        os.remove(csv_path)

    base = os.path.splitext(filename)[0]
    for ext in (".xlsx", ".xls"):
        xl_path = os.path.join(dirs[src_key], base + ext)
        if os.path.exists(xl_path):
            os.remove(xl_path)

    _RELOAD_FNS[folder_key](sid, dirs)
    return jsonify({
        "ok":        True,
        "ref":       _csv_list(dirs["ref_csv"]),
        "events":    _csv_list(dirs["events_csv"]),
        "shipments": _csv_list(dirs["shipments_csv"]),
    })


# ── utility ──
def _df_to_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso", default_handler=str))


# ========================== Run ==========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
