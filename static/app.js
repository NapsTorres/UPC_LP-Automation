/* ═══════════════════════════════════════════════════
   UPC / LP Search Portal — app.js
   All interactivity: search, tables, filters, downloads
═══════════════════════════════════════════════════ */

"use strict";

// ── State ──────────────────────────────────────────
let _searchResult   = null;  // last /api/search response
let _shipResult     = null;  // last /api/shipments response
let _eventTactics   = [];    // tactic IDs from events → fed to shipments
let _sortState      = {};    // { tableId: { col, dir } }
let _lastShipSearch = {};    // last shipment search params — replayed on download
let _tableState     = {};    // { tableId: { cols } }
let _filterState    = {};    // { tableId: { colName: Set<string> | null } }
let _baseRows       = {};    // { tableId: row[] } — original unfiltered rows per table
let _originalRows   = {};    // { tableId: row[] } — snapshot at load time, for sort reset

// ── Utilities ──────────────────────────────────────

function spin(id, on) {
  const el = document.getElementById(id);
  if (el) el.style.display = on ? "inline-block" : "none";
}

function show(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? "" : "none";
}

function fmt$(n) {
  return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function checkedValues(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map(x => x.value);
}

function parseInput(raw) {
  // Split on whitespace/commas, strip, deduplicate
  const seen = new Set();
  return raw.split(/[\s,]+/).map(s => s.trim()).filter(s => {
    if (!s || seen.has(s)) return false;
    seen.add(s); return true;
  });
}

// ── Virtual-scroll table ────────────────────────────
// Only the rows visible in the viewport are in the DOM.
// Everything else is represented by a spacer — the browser never has to
// paint thousands of <tr> elements.

const ROW_H       = 29;   // px — must match tbody td height in CSS
const VISIBLE_H   = 320;  // px — scrollable area height (≈ 10 rows)
const OVERSCAN    = 5;    // extra rows rendered above/below visible window

function buildTable(containerId, cols, rows, tableId) {
  const wrap = document.getElementById(containerId);
  if (!cols.length || !rows.length) {
    wrap.innerHTML = `<div class="empty-msg">No data to display.</div>`;
    delete _tableState[tableId];
    delete _filterState[tableId];
    delete _baseRows[tableId];
    delete _originalRows[tableId];
    return;
  }

  _sortState[tableId]   = _sortState[tableId]  || { col: null, dir: 1 };
  _filterState[tableId] = _filterState[tableId] || {};
  _baseRows[tableId]    = rows;
  _originalRows[tableId] = rows;   // snapshot for reset
  _tableState[tableId]  = { cols };

  _renderTable(containerId, tableId);
}

function _filteredRows(tableId) {
  const base    = _baseRows[tableId] || [];
  const filters = _filterState[tableId] || {};
  return base.filter(row =>
    Object.entries(filters).every(([col, vals]) =>
      !vals || vals.size === 0 || vals.has(String(row[col] ?? "").trim())
    )
  );
}

// Convert 0-based index to Excel-style column letter(s): 0→A, 25→Z, 26→AA …
function _colLetter(i) {
  let s = "";
  i++;  // 1-based
  while (i > 0) {
    i--;
    s = String.fromCharCode(65 + (i % 26)) + s;
    i = Math.floor(i / 26);
  }
  return s;
}

function _renderTable(containerId, tableId) {
  const wrap  = document.getElementById(containerId);
  const state = _tableState[tableId];
  if (!state) return;

  const { cols }  = state;
  const rows      = _filteredRows(tableId);
  const total     = rows.length;
  const st        = _sortState[tableId];
  const filters   = _filterState[tableId] || {};

  // ── Build header — two rows: letter row + column-name row ──
  const cornerTh  = `<th class="col-rownum col-letter" rowspan="2" style="width:42px;min-width:42px;text-align:center">#</th>`;
  const letterRow = cols.map((_, i) =>
    `<th class="col-letter" style="text-align:center;width:80px">${_colLetter(i)}</th>`
  ).join("");
  const nameRow = cols.map((c, i) => {
    const sortCls   = st.col === i ? (st.dir === 1 ? "sorted-asc" : "sorted-desc") : "";
    const activeCls = (filters[c] && filters[c].size > 0) ? " col-filtered" : "";
    return `<th class="${sortCls}${activeCls}" data-col="${i}" data-colname="${escHtml(c)}">` +
      `<span class="th-label">${escHtml(c)}</span>` +
      `<span class="th-arrow" title="Filter / Sort">▾</span>` +
      `</th>`;
  }).join("");

  const activeFilters = Object.values(filters).filter(v => v && v.size > 0).length;
  const badge = activeFilters
    ? `<span class="filter-badge">${activeFilters} filter${activeFilters > 1 ? "s" : ""} active
        <button class="filter-badge-clear" onclick="_clearAllColFilters('${containerId}','${tableId}')">✕ clear</button>
       </span>`
    : "";

  const rowCount = `<div class="pager"><span class="pager-info">${total.toLocaleString()} row${total !== 1 ? "s" : ""}</span></div>`;

  // ── Scaffold: fixed-height scroller wrapping a real <table> ──
  wrap.innerHTML = `
    ${badge}
    <div class="table-wrap" id="vs-scroll-${tableId}">
      <table id="${tableId}">
        <thead>
          <tr>${cornerTh}${letterRow}</tr>
          <tr>${nameRow}</tr>
        </thead>
        <tbody id="vs-body-${tableId}"></tbody>
      </table>
    </div>
    ${rowCount}`;

  // ── Wire header interactions (skip the # row-number th which has no data-col) ──
  wrap.querySelectorAll("thead th[data-col]").forEach(th => {
    const colIdx  = parseInt(th.dataset.col);
    const colName = th.dataset.colname;
    th.querySelector(".th-label").addEventListener("click", () => {
      sortTable(tableId, cols, _baseRows[tableId], containerId, colIdx);
    });
    th.querySelector(".th-arrow").addEventListener("click", e => {
      e.stopPropagation();
      openColFilter(e, tableId, colName, containerId);
    });
  });

  // ── Virtual scroll logic ──
  const scroller = document.getElementById(`vs-scroll-${tableId}`);
  const tbody    = document.getElementById(`vs-body-${tableId}`);

  function paintRows() {
    const scrollTop = scroller.scrollTop;
    const startIdx  = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
    const endIdx    = Math.min(total, Math.ceil((scrollTop + VISIBLE_H) / ROW_H) + OVERSCAN);

    const topPad    = startIdx * ROW_H;
    const botPad    = Math.max(0, (total - endIdx) * ROW_H);

    const spanAll = cols.length + 1;  // +1 for row-number column
    let html = `<tr style="height:${topPad}px"><td colspan="${spanAll}" style="padding:0;border:none"></td></tr>`;
    for (let i = startIdx; i < endIdx; i++) {
      const row = rows[i];
      html += `<tr><td class="col-rownum" style="text-align:center;color:#9ca3af;font-size:11px;user-select:none">${i + 1}</td>` +
              cols.map(c => `<td>${escHtml(row[c] ?? "")}</td>`).join("") + "</tr>";
    }
    html += `<tr style="height:${botPad}px"><td colspan="${spanAll}" style="padding:0;border:none"></td></tr>`;
    tbody.innerHTML = html;
  }

  paintRows();
  scroller.addEventListener("scroll", paintRows, { passive: true });

  // ── After rendering the events table, sync shipments ──
  if (tableId === "tbl-events") {
    _syncShipmentsFromEventTable();
  }
  // ── After rendering the shipments table, refresh LP breakdown + total ──
  if (tableId === "tbl-ship") {
    const rows = _filteredRows("tbl-ship");
    const cols = _tableState["tbl-ship"]?.cols || [];
    _renderShipLpBreakdown(rows, cols, _shipSourceTactics);
    _renderShipTotal(rows);
  }
}

// ── LP breakdown: show which searched LPs are in the given rows ──
function _renderLpBreakdown(rows) {
  const breakdown = document.getElementById("ev-lp-breakdown");
  if (!breakdown) return;

  // 1. Find the LP column — try named matches first, then scan values
  const colFilterState = _filterState["tbl-events"] || {};

  // Named candidates
  let lpCol = _eventsAllCols.find(c =>
    c === "L5 Promoted Product Group Code" ||
    (c.toLowerCase().includes("l5") && c.toLowerCase().includes("promoted")) ||
    c.toLowerCase().includes("group code")
  );

  // 2. Build the searched LP list from all sources
  const mainLPs = parseInput(document.getElementById("lp-input")?.value || "");

  // ▾ col filter values for the LP column specifically
  const colFilterLPs = lpCol && colFilterState[lpCol]
    ? [...colFilterState[lpCol]]
    : [];

  // widget filter (_evFilterSel) for the LP column
  const widgetLPs = lpCol && _evFilterSel[lpCol]
    ? [..._evFilterSel[lpCol]]
    : [];

  let searchedLPs = [...new Set([...mainLPs, ...colFilterLPs, ...widgetLPs])];

  // If no LP col found by name yet, scan all column filter values + main LPs
  // to find which column in the data actually contains those values
  if (!lpCol && searchedLPs.length > 0) {
    lpCol = _eventsAllCols.find(c => {
      const sample = _eventsAllRows.slice(0, 100).map(r => String(r[c] ?? "").trim());
      return searchedLPs.some(lp => sample.includes(lp));
    });
  }

  // If still no LP col, try scanning all ▾ filter values against all columns
  if (!lpCol) {
    const allColFilterVals = Object.entries(colFilterState)
      .flatMap(([col, sel]) => sel && sel.size > 0 ? [[col, [...sel]]] : []);
    for (const [col, vals] of allColFilterVals) {
      const sample = _eventsAllRows.slice(0, 20).map(r => String(r[col] ?? "").trim());
      // LP-like pattern: starts with letters followed by numbers
      if (vals.some(v => /^[A-Za-z]{1,4}\d{4,}/.test(v)) && sample.some(s => /^[A-Za-z]{1,4}\d{4,}/.test(s))) {
        lpCol = col;
        searchedLPs = [...new Set([...searchedLPs, ...vals])];
        break;
      }
    }
  }

  if (!lpCol || searchedLPs.length === 0) { breakdown.style.display = "none"; return; }

  // 3. Compare searched LPs against the rows passed in
  const presentSet = new Set(rows.map(r => String(r[lpCol] ?? "").trim()).filter(Boolean));

  const inEvents    = searchedLPs.filter(lp => presentSet.has(lp));
  const notInEvents = searchedLPs.filter(lp => !presentSet.has(lp));

  const inHtml = inEvents.map(lp =>
    `<span style="display:inline-flex;align-items:center;gap:4px;background:#dcfce7;border:1px solid #86efac;border-radius:4px;padding:2px 8px;font-size:11px;margin:2px">✅ ${escHtml(lp)}</span>`
  ).join("");

  const notInHtml = notInEvents.map(lp =>
    `<span style="display:inline-flex;align-items:center;gap:4px;background:#fee2e2;border:1px solid #fca5a5;border-radius:4px;padding:2px 8px;font-size:11px;margin:2px">⚠️ ${escHtml(lp)}</span>`
  ).join("");

  breakdown.style.display = "";
  breakdown.innerHTML = `
    <div style="font-size:12px;font-weight:600;color:#57606a;margin-bottom:6px">🔍 LP check — in these events</div>
    <div style="display:flex;flex-wrap:wrap;gap:4px">${inHtml}${notInHtml}</div>`;
}

function _syncShipmentsFromEventTable() {
  // Skip if user has typed directly in shipment fields
  const hasDirectShipInput = document.getElementById("ship-tactic")?.value.trim()
    || document.getElementById("ship-lp")?.value.trim()
    || document.getElementById("ship-item")?.value.trim();
  if (hasDirectShipInput) return;

  // Get the currently visible rows of the events table (after all col filters applied)
  const visibleRows = _filteredRows("tbl-events");

  // Check if any column filter is active on the events table
  const filters = _filterState["tbl-events"] || {};
  const hasColFilter = Object.values(filters).some(v => v && v.size > 0);

  // Also check widget filters
  const hasWidgetFilter = Object.values(_evFilterSel).some(sel => sel && sel.size > 0);

  if (!hasColFilter && !hasWidgetFilter) {
    // Nothing filtered — clear shipments and LP breakdown
    _eventTactics = [];
    renderShipments({ rows: [], cols: [], tactics: [] });
    _renderLpBreakdown([]);
    return;
  }

  // Extract tactic IDs from visible rows
  const tacticCol = _eventsAllCols.find(c => c.toLowerCase() === "tactic id");
  if (tacticCol) {
    _eventTactics = [...new Set(visibleRows.map(r => String(r[tacticCol] ?? "").trim()).filter(Boolean))];
  }

  _renderLpBreakdown(visibleRows);
  runShipmentSearch();
}

function _clearAllColFilters(containerId, tableId) {
  _filterState[tableId] = {};
  _renderTable(containerId, tableId);
}

// ── Column filter dropdown ──────────────────────────

let _openFilterPanel = null;   // currently open panel element

// ── Detect column data type from sampled values ──────
function _colType(vals) {
  const sample = vals.filter(v => v !== "").slice(0, 20);
  if (!sample.length) return "text";
  const dateRe = /^\d{1,4}[\/\-]\d{1,2}[\/\-]\d{2,4}$|^\w+ \d{1,2},? \d{4}$|\d{4}-\d{2}-\d{2}/;
  const numRe  = /^-?[\d,]+(\.\d+)?%?$/;
  let dates = 0, nums = 0;
  for (const v of sample) {
    if (dateRe.test(v) && !isNaN(Date.parse(v))) dates++;
    else if (numRe.test(v.replace(/,/g, "")))     nums++;
  }
  if (dates >= sample.length * 0.6) return "date";
  if (nums  >= sample.length * 0.6) return "number";
  return "text";
}

function _sortLabels(type) {
  if (type === "date")   return { asc: "↑  Oldest → Newest", desc: "↓  Newest → Oldest" };
  if (type === "number") return { asc: "↑  Smallest → Largest", desc: "↓  Largest → Smallest" };
  return                        { asc: "↑  Sort A → Z",          desc: "↓  Sort Z → A" };
}

function openColFilter(evt, tableId, colName, containerId) {
  if (_openFilterPanel) { _openFilterPanel.remove(); _openFilterPanel = null; }

  const th      = evt.target.closest("th");
  const colIdx  = parseInt(th.dataset.col);
  const cols    = _tableState[tableId]?.cols || [];
  const base    = _originalRows[tableId] || _baseRows[tableId] || [];
  const filters = _filterState[tableId] || {};
  const active  = filters[colName] || new Set();
  const st      = _sortState[tableId] || { col: null, dir: 1 };

  // Unique values sorted A→Z for the checklist
  const vals = [...new Set(base.map(r => String(r[colName] ?? "").trim()))].sort(
    (a, b) => a.localeCompare(b, undefined, { numeric: true })
  );

  const type   = _colType(vals.filter(v => v !== ""));
  const labels = _sortLabels(type);
  const isAsc  = st.col === colIdx && st.dir === 1;
  const isDesc = st.col === colIdx && st.dir === -1;

  // If no filter is active yet, treat every value as checked (all-selected = no filter)
  const allCheckedByDefault = active.size === 0;

  // When a filter IS active: only render the selected values (hide the rest).
  // When no filter: render all values checked.
  const checkedVals   = allCheckedByDefault ? vals : vals.filter(v => active.has(v));
  const uncheckedVals = [];   // never show unselected items on open

  const makeItem = (v, chk, hidden) =>
    `<label class="cf-item"${hidden ? ' style="display:none"' : ''}><input type="checkbox" value="${escHtml(v)}" ${chk}> ${escHtml(v) || "<em style='color:#aaa'>(blank)</em>"}</label>`;

  const checkedHtml   = checkedVals.map(v => makeItem(v, "checked", false)).join("");
  // Render unchecked items hidden so _refreshList can reveal them on search
  const hiddenHtml    = allCheckedByDefault ? "" : vals.filter(v => !active.has(v)).map(v => makeItem(v, "", true)).join("");
  const items = checkedHtml + hiddenHtml;

  const panel = document.createElement("div");
  panel.className = "col-filter-panel";

  panel.innerHTML = `
    <div class="cf-sort-row${isAsc  ? " cf-sort-active" : ""}" data-action="asc">
      <span class="cf-sort-icon"></span>${labels.asc}
    </div>
    <div class="cf-sort-row${isDesc ? " cf-sort-active" : ""}" data-action="desc">
      <span class="cf-sort-icon"></span>${labels.desc}
    </div>
    <div class="cf-sort-row" data-action="reset" style="color:#57606a">
      <span class="cf-sort-icon">↺</span> Clear Sort
    </div>
    <hr class="cf-sort-divider">
    <div class="cf-actions">
      <button class="cf-btn" data-action="selall">Select All</button>
      <button class="cf-btn" data-action="selnone">Clear</button>
    </div>
    <div class="cf-search-wrap"><input class="cf-search" placeholder="Search…"></div>
    ${!allCheckedByDefault ? `<label class="cf-add-toggle"><input type="checkbox" id="cf-add-cb"> Add to existing filter</label>` : ""}
    <div class="cf-list">${items}</div>
    <div class="cf-footer">
      <button class="cf-apply">OK</button>
      <button class="cf-cancel">Cancel</button>
    </div>`;

  // ── Sort rows ──
  panel.querySelectorAll(".cf-sort-row").forEach(row => {
    row.addEventListener("click", () => {
      const action = row.dataset.action;
      if (action === "asc")   sortTable(tableId, cols, _originalRows[tableId] || _baseRows[tableId], containerId, colIdx, 1);
      if (action === "desc")  sortTable(tableId, cols, _originalRows[tableId] || _baseRows[tableId], containerId, colIdx, -1);
      if (action === "reset") resetSort(tableId, containerId);
      closeColFilter();
    });
  });

  // ── Select All / Clear (acts on visible items only) ──
  panel.querySelector("[data-action=selall]").addEventListener("click", () => {
    panel.querySelectorAll(".cf-item:not([style*='display: none']) input, .cf-item:not([style*='display:none']) input").forEach(cb => cb.checked = true);
  });
  panel.querySelector("[data-action=selnone]").addEventListener("click", () => {
    panel.querySelectorAll(".cf-item input").forEach(cb => cb.checked = false);
  });

  // ── Shared helper: check all items whose value exactly matches any of the tokens ──
  function _checkMatched(tokens) {
    const lower = tokens.map(t => t.toLowerCase());
    panel.querySelectorAll(".cf-item input").forEach(cb => {
      if (lower.includes(cb.value.toLowerCase())) cb.checked = true;
    });
  }

  // ── Search box ──
  const cfSearch = panel.querySelector(".cf-search");

  function _refreshList() {
    const raw    = cfSearch.value;
    const tokens = raw.split(/[\s,\n\r]+/).map(t => t.trim()).filter(Boolean);

    panel.querySelectorAll(".cf-item").forEach(li => {
      const cb = li.querySelector("input");
      const lo = cb.value.toLowerCase();

      if (tokens.length === 0) {
        if (allCheckedByDefault) {
          // No active filter — show everything checked
          cb.checked = true;
          li.style.display = "";
        } else {
          // Filter is active — show only the selected values, hide the rest
          const isSelected = active.has(cb.value);
          cb.checked = isSelected;
          li.style.display = isSelected ? "" : "none";
        }
      } else {
        const matches = tokens.some(t => lo.includes(t.toLowerCase()));
        // Only items that match the search are shown AND checked
        cb.checked = matches;
        li.style.display = matches ? "" : "none";
      }

      li.style.opacity = "";
      li.classList.remove("cf-item-checked");
    });
  }

  cfSearch.addEventListener("input", _refreshList);

  // ── Paste: bulk-check all exact matches, keep text, refresh display ──
  cfSearch.addEventListener("paste", e => {
    setTimeout(() => {
      const tokens = cfSearch.value.split(/[\s,\n\r]+/).map(t => t.trim()).filter(Boolean);
      _checkMatched(tokens);
      _refreshList();   // re-render so checked items stay visible
    }, 0);
  });

  // ── OK: apply checked items; merge into existing if "Add to existing filter" is ticked ──
  panel.querySelector(".cf-apply").addEventListener("click", () => {
    const allChecked = [...panel.querySelectorAll(".cf-list input:checked")].map(cb => cb.value);
    const addToggle  = panel.querySelector("#cf-add-cb");
    const addMode    = addToggle && addToggle.checked;

    if (!_filterState[tableId]) _filterState[tableId] = {};

    let finalSet;
    if (addMode) {
      // Merge: existing selections + newly checked items
      finalSet = new Set([...active, ...allChecked]);
    } else {
      finalSet = new Set(allChecked);
    }

    // If everything is selected (or nothing), remove the filter entirely
    _filterState[tableId][colName] = (finalSet.size === 0 || finalSet.size === vals.length) ? null : finalSet;
    _renderTable(containerId, tableId);
    closeColFilter();
  });
  panel.querySelector(".cf-cancel").addEventListener("click", closeColFilter);

  // Run once on open so existing checked items float to top immediately
  _refreshList();

  // Position below the th
  const rect = th.getBoundingClientRect();
  panel.style.top  = (rect.bottom + window.scrollY) + "px";
  panel.style.left = (rect.left   + window.scrollX) + "px";
  document.body.appendChild(panel);
  _openFilterPanel = panel;

  setTimeout(() => {
    document.addEventListener("mousedown", _outsideClick, { once: true });
  }, 0);
}

function _outsideClick(e) {
  if (_openFilterPanel && !_openFilterPanel.contains(e.target)) {
    _openFilterPanel.remove();
    _openFilterPanel = null;
  }
}

function closeColFilter() {
  if (_openFilterPanel) { _openFilterPanel.remove(); _openFilterPanel = null; }
  document.removeEventListener("mousedown", _outsideClick);
}

function sortTable(tableId, cols, rows, containerId, colIdx, dir) {
  const st = _sortState[tableId] || { col: null, dir: 1 };
  if (dir !== undefined) { st.col = colIdx; st.dir = dir; }
  else if (st.col === colIdx) st.dir *= -1;
  else { st.col = colIdx; st.dir = 1; }
  _sortState[tableId] = st;

  const key    = cols[colIdx];
  // Sample values to pick the right comparator
  const sample = rows.slice(0, 20).map(r => String(r[key] ?? "").trim()).filter(Boolean);
  const type   = _colType(sample);

  const sorted = [...rows].sort((a, b) => {
    const av = String(a[key] ?? "").trim();
    const bv = String(b[key] ?? "").trim();
    let cmp;
    if (type === "date") {
      cmp = (Date.parse(av) || 0) - (Date.parse(bv) || 0);
    } else if (type === "number") {
      cmp = (parseFloat(av.replace(/,/g, "")) || 0) - (parseFloat(bv.replace(/,/g, "")) || 0);
    } else {
      cmp = av.localeCompare(bv, undefined, { numeric: true });
    }
    return cmp * st.dir;
  });

  _baseRows[tableId] = sorted;
  _renderTable(containerId, tableId);
}

function resetSort(tableId, containerId) {
  // Clear sort state and restore original insertion order
  _sortState[tableId] = { col: null, dir: 1 };
  // Restore base rows from the last buildTable call (stored in _baseRows before any sort)
  const original = _originalRows[tableId];
  if (original) _baseRows[tableId] = original;
  _renderTable(containerId, tableId);
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Search ─────────────────────────────────────────

async function runSearch(autoLoad) {
  spin("search-spin", true);
  // Clear the tactic field if this is an auto-load (page open) to avoid browser autofill
  if (autoLoad) document.getElementById("ship-tactic").value = "";

  const body = {
    upc:          document.getElementById("upc-input").value,
    lp:           document.getElementById("lp-input").value,
    ref_files:    checkedValues("ref"),
    events_files: checkedValues("events"),
  };

  try {
    const res  = await fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    _searchResult = data;
    renderReference(data);
    renderEvents(data);
    _eventTactics = data.event_tactics || [];
    // Only chain to shipments when the user explicitly clicked Search
    if (!autoLoad && _eventTactics.length) runShipmentSearch();
  } finally {
    spin("search-spin", false);
  }
}

// ── Reference ──────────────────────────────────────

function renderReference(data) {
  buildTable("ref-table-wrap", data.ref_cols, data.ref, "tbl-ref");

  // LP chips
  const chips = document.getElementById("lp-chips");
  if (data.lps_from_ref && data.lps_from_ref.length) {
    chips.innerHTML = data.lps_from_ref.map(lp =>
      `<label class="file-chip"><input type="checkbox" name="lp_ref" value="${escHtml(lp)}" checked onchange="onLpChipChange()"> ${escHtml(lp)}</label>`
    ).join("");
  } else {
    chips.innerHTML = "";
  }
  show("lp-filter-row", false);
}

function onLpChipChange() {
  // Re-run search with updated LP selection
  const selected = checkedValues("lp_ref");
  document.getElementById("lp-input").value = selected.join(" ");
  runSearch();
}

// ── Events ─────────────────────────────────────────

let _eventsAllRows  = [];
let _eventsAllCols  = [];
let _filterOptions  = {};
let _evHiddenCols   = new Set();  // column names toggled off
let _evSortDir      = -1;         // -1 = newest first (desc), 1 = oldest first (asc)

// Keywords that identify a date column — checked in priority order
const _DATE_COL_KEYWORDS = [
  "start date", "end date", "performance start", "performance end",
  "ship start", "ship end", "invoice date", "ship date", "date",
];

function _evSortDateCol() {
  // Return the first column whose lowercased name contains a date keyword
  const lower = _eventsAllCols.map(c => c.toLowerCase());
  for (const kw of _DATE_COL_KEYWORDS) {
    const idx = lower.findIndex(c => c.includes(kw));
    if (idx !== -1) return _eventsAllCols[idx];
  }
  return null;
}

function _sortedEvRows() {
  const col = _evSortDateCol();
  if (!col) return _eventsAllRows;
  return [..._eventsAllRows].sort((a, b) => {
    const av = Date.parse(a[col] ?? "") || 0;
    const bv = Date.parse(b[col] ?? "") || 0;
    return (bv - av) * _evSortDir * -1;   // _evSortDir -1 → newest(desc), 1 → oldest(asc)
  });
}

function _updateEvSortBtn() {
  const btn = document.getElementById("ev-sort-btn");
  if (!btn) return;
  const col = _evSortDateCol();
  if (_evSortDir === -1) {
    btn.textContent = "📅 Newest first ↓";
    btn.style.background = "#3b82d4";
    btn.style.color = "#fff";
  } else {
    btn.textContent = "📅 Oldest first ↑";
    btn.style.background = "#e5e7eb";
    btn.style.color = "#1f2328";
  }
  // Show which column is being sorted in the tooltip
  btn.title = col ? `Sorted by: ${col}` : "No date column found";
}

function toggleEvSort() {
  _evSortDir *= -1;
  _updateEvSortBtn();
  _buildEventsTable();
}

function renderEvents(data) {
  _eventsAllRows = data.events || [];
  _eventsAllCols = data.events_cols || [];
  _filterOptions = data.filter_options || {};

  // Clear widget filter selections when a fresh search is run so the table
  // resets fully (e.g. when the user clears the main UPC/LP input)
  Object.keys(_evFilterSel).forEach(col => { _evFilterSel[col] = new Set(); });

  _rebuildEvColPanel();
  _applyEventFilters();   // route through widget filters so state is always consistent
  _updateEvSortBtn();
  // spend is already recalculated inside _applyEventFilters; also render from data for initial load
  renderSpend(data.spend);
  // Show LP breakdown immediately using all loaded rows (no filter required)
  _renderLpBreakdown(_eventsAllRows);
}

function _visibleEvCols() {
  return _eventsAllCols.filter(c => !_evHiddenCols.has(c));
}

function _buildEventsTable() {
  buildTable("events-table-wrap", _visibleEvCols(), _sortedEvRows(), "tbl-events");
}

// ── Column visibility panel ─────────────────────────

function _rebuildEvColPanel() {
  const panel = document.getElementById("ev-col-panel");
  if (!panel) return;

  // "All / None" row + one checkbox per column
  panel.innerHTML = `
    <div style="display:flex;gap:8px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #f0f0f0">
      <button class="cf-btn" id="ev-col-all">All</button>
      <button class="cf-btn" id="ev-col-none">None</button>
    </div>
    ${_eventsAllCols.map(c => `
      <label style="display:flex;align-items:center;gap:6px;padding:3px 0;font-size:12px;cursor:pointer">
        <input type="checkbox" class="ev-col-cb" data-col="${escHtml(c)}" ${_evHiddenCols.has(c) ? "" : "checked"}>
        ${escHtml(c)}
      </label>`).join("")}`;

  panel.querySelectorAll(".ev-col-cb").forEach(cb => {
    cb.addEventListener("change", () => {
      if (cb.checked) _evHiddenCols.delete(cb.dataset.col);
      else            _evHiddenCols.add(cb.dataset.col);
      _buildEventsTable();
    });
  });

  panel.querySelector("#ev-col-all").addEventListener("click", () => {
    _evHiddenCols.clear();
    panel.querySelectorAll(".ev-col-cb").forEach(cb => cb.checked = true);
    _buildEventsTable();
  });

  panel.querySelector("#ev-col-none").addEventListener("click", () => {
    _eventsAllCols.forEach(c => _evHiddenCols.add(c));
    panel.querySelectorAll(".ev-col-cb").forEach(cb => cb.checked = false);
    _buildEventsTable();
  });
}

function toggleEvColPanel() {
  const panel = document.getElementById("ev-col-panel");
  if (!panel) return;
  const isOpen = panel.style.display !== "none";
  panel.style.display = isOpen ? "none" : "";
  if (!isOpen) {
    // close on outside click
    setTimeout(() => {
      document.addEventListener("mousedown", function _close(e) {
        if (!panel.contains(e.target) && e.target.id !== "ev-col-toggle-btn") {
          panel.style.display = "none";
          document.removeEventListener("mousedown", _close);
        }
      });
    }, 0);
  }
}

// ── Event filter state: col → Set of selected values (null = all) ──
const _evFilterSel = {};   // { col: Set<string> }

function buildEventFilters() {
  const grid = document.getElementById("event-filters");
  grid.innerHTML = "";

  Object.entries(_filterOptions).forEach(([col, opts]) => {
    // Ensure state entry exists
    if (!_evFilterSel[col]) _evFilterSel[col] = new Set();

    const wrapper = document.createElement("div");
    wrapper.className = "ms-widget";
    wrapper.dataset.col = col;

    wrapper.innerHTML = `
      <div class="ms-label">${escHtml(col)}</div>
      <div class="ms-box" tabindex="0">
        <div class="ms-tags"></div>
        <input class="ms-input" placeholder="Search…" autocomplete="off">
      </div>
      <div class="ms-dropdown" style="display:none">
        <div class="ms-drop-list"></div>
      </div>`;

    grid.appendChild(wrapper);

    const box      = wrapper.querySelector(".ms-box");
    const input    = wrapper.querySelector(".ms-input");
    const dropdown = wrapper.querySelector(".ms-dropdown");
    const dropList = wrapper.querySelector(".ms-drop-list");
    const tagsEl   = wrapper.querySelector(".ms-tags");

    function renderTags() {
      const sel = _evFilterSel[col];
      tagsEl.innerHTML = [...sel].map(v =>
        `<span class="ms-tag">${escHtml(v)}<button class="ms-tag-x" data-v="${escHtml(v)}">×</button></span>`
      ).join("");
      // Wire remove buttons
      tagsEl.querySelectorAll(".ms-tag-x").forEach(btn => {
        btn.addEventListener("mousedown", e => {
          e.preventDefault();
          _evFilterSel[col].delete(btn.dataset.v);
          renderTags();
          renderDropdown(input.value);
          _applyEventFilters();
        });
      });
    }

    function renderDropdown(q) {
      const sel    = _evFilterSel[col];
      const tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
      const filtered = opts.filter(o => {
        const lo = o.toLowerCase();
        return tokens.length === 0 || tokens.every(t => lo.includes(t));
      });
      if (!filtered.length) {
        dropList.innerHTML = `<div class="ms-no-match">No matches</div>`;
        return;
      }
      dropList.innerHTML = filtered.map(o =>
        `<div class="ms-opt${sel.has(o) ? " ms-opt-on" : ""}" data-v="${escHtml(o)}">${escHtml(o)}</div>`
      ).join("");
      dropList.querySelectorAll(".ms-opt").forEach(item => {
        item.addEventListener("mousedown", e => {
          e.preventDefault();
          const v = item.dataset.v;
          if (sel.has(v)) sel.delete(v);
          else            sel.add(v);
          renderTags();
          renderDropdown(input.value);
          _applyEventFilters();
        });
      });
    }

    // Auto-select all tokens that exactly match available options
    function _bulkSelect(raw) {
      const tokens = raw.trim().split(/[\s,]+/).map(t => t.trim()).filter(Boolean);
      if (tokens.length < 2) return false;   // single token → normal search
      const optsLower = opts.map(o => o.toLowerCase());
      const matched = tokens.filter(t => optsLower.includes(t.toLowerCase()));
      if (matched.length === 0) return false;
      matched.forEach(t => {
        // find exact case-insensitive match in opts
        const real = opts.find(o => o.toLowerCase() === t.toLowerCase());
        if (real) _evFilterSel[col].add(real);
      });
      renderTags();
      renderDropdown("");
      input.value = "";
      dropdown.style.display = "none";
      _applyEventFilters();
      return true;
    }

    function openDropdown() {
      if (dropdown.style.display === "none") {
        renderDropdown(input.value);
        dropdown.style.display = "";
      }
    }
    function closeDropdown() { dropdown.style.display = "none"; input.value = ""; }

    input.addEventListener("focus", openDropdown);
    input.addEventListener("input", () => {
      // Try bulk-select first; if not a multi-token paste, show dropdown normally
      if (_bulkSelect(input.value)) return;
      dropdown.style.display = "";
      renderDropdown(input.value);
    });
    input.addEventListener("paste", e => {
      // On paste, wait one tick for value to update then attempt bulk-select
      setTimeout(() => {
        if (!_bulkSelect(input.value)) {
          dropdown.style.display = "";
          renderDropdown(input.value);
        }
      }, 0);
    });
    box.addEventListener("mousedown", e => {
      // clicking the box (but not a tag-x) opens/focuses
      if (!e.target.classList.contains("ms-tag-x")) {
        e.preventDefault();
        input.focus();
        openDropdown();
      }
    });

    // Close ONLY on outside click — never on blur so multi-select stays open
    document.addEventListener("mousedown", e => {
      if (!wrapper.contains(e.target)) closeDropdown();
    });

    renderTags();
  });
}

function _applyEventFilters() {
  let rows = [..._sortedEvRows()];
  Object.entries(_evFilterSel).forEach(([col, sel]) => {
    if (sel.size > 0) rows = rows.filter(r => sel.has(String(r[col] ?? "").trim()));
  });

  buildTable("events-table-wrap", _visibleEvCols(), rows, "tbl-events");

  if (_eventsAllCols.includes("Tactic ID")) {
    _eventTactics = [...new Set(rows.map(r => String(r["Tactic ID"] ?? "").trim()).filter(Boolean))];
  }

  const spend = {
    planned:   rows.reduce((s, r) => s + (parseFloat(r["Planned Spend $"])  || 0), 0),
    settled:   rows.reduce((s, r) => s + (parseFloat(r["Settled Spend $"])  || 0), 0),
    remaining: rows.reduce((s, r) => s + (parseFloat(r["Remaining Spend $"]) || 0), 0),
  };
  renderSpend(spend);
  // Update LP breakdown with the current filtered rows
  _renderLpBreakdown(rows);
  // Shipment sync is handled automatically via _renderTable → _syncShipmentsFromEventTable
}

// Keep these so the HTML buttons still work
function applyEventFilters() { _applyEventFilters(); }

function clearEventFilters() {
  Object.keys(_evFilterSel).forEach(col => _evFilterSel[col] = new Set());
  // Re-render tags on each widget
  document.querySelectorAll(".ms-widget").forEach(w => {
    w.querySelector(".ms-tags").innerHTML = "";
  });
  _applyEventFilters();
}

function renderSpend(spend) {
  if (!spend) return;
  document.getElementById("m-planned").textContent   = fmt$(spend.planned);
  document.getElementById("m-settled").textContent   = fmt$(spend.settled);
  document.getElementById("m-remaining").textContent = fmt$(spend.remaining);
}

// ── Shipments ──────────────────────────────────────

async function runShipmentSearch() {
  spin("ship-spin", true);
  const tacticVal = document.getElementById("ship-tactic").value.trim();
  const lpVal     = document.getElementById("ship-lp").value.trim();
  const itemVal   = document.getElementById("ship-item").value.trim();
  // If the user has typed directly in the shipment fields, don't mix in event tactics —
  // treat it as a fully independent search
  const hasDirectInput = tacticVal || lpVal || itemVal;
  const body = {
    tactic:        tacticVal,
    lp:            lpVal,
    item:          itemVal,
    event_tactics: hasDirectInput ? [] : _eventTactics,
    ship_files:    checkedValues("ship"),
  };

  // Save parsed search terms so downloads can replay the exact same filters
  _lastShipSearch = {
    tactic_list:   parseInput(body.tactic),
    lp_list:       parseInput(body.lp),
    item_list:     parseInput(body.item),
    event_tactics: body.event_tactics,
    ship_files:    body.ship_files,
  };

  try {
    const res  = await fetch("/api/shipments", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    _shipResult = data;
    renderShipments(data);
  } finally {
    spin("ship-spin", false);
  }
}

function renderShipments(data) {
  const rows    = data.rows    || [];
  const cols    = data.cols    || [];
  const tactics = data.tactics || [];

  // Link info
  const info = document.getElementById("ship-link-info");
  if (_eventTactics.length && !document.getElementById("ship-tactic").value.trim()) {
    info.innerHTML = `<div class="info-box">🔗 Showing shipments linked to <strong>${_eventTactics.length}</strong> Tactic ID(s) from Events filter.</div>`;
  } else {
    info.innerHTML = "";
  }

  buildTable("ship-table-wrap", cols, rows, "tbl-ship");
  _buildShipSourceFilter(rows, cols, tactics);   // also clears stale __source__ filter
  _renderShipDownloadStrip(rows);                // initial strip uses all rows (no source filter yet)
  _renderShipTotal(rows);
  _renderShipLpBreakdown(rows, cols, tactics);
}

// ── Source-file filter for shipments ─────────────────────────────────
let _shipSourceTactics = [];  // tactics list from last render, needed for LP breakdown refresh

function _buildShipSourceFilter(rows, cols, tactics) {
  _shipSourceTactics = tactics;
  const panel = document.getElementById("ship-source-filter");
  const chipsEl = document.getElementById("ship-source-chips");
  if (!panel || !chipsEl) return;

  // Clear any stale __source__ filter from a previous search
  if (_filterState["tbl-ship"]) delete _filterState["tbl-ship"]["__source__"];

  // Collect unique source files present in results
  const sources = [...new Set(rows.map(r => r["__source__"]).filter(Boolean))].sort();

  if (sources.length < 2) {
    panel.style.display = "none";
    return;
  }

  panel.style.display = "";
  chipsEl.innerHTML = sources.map(src => `
    <label class="file-chip" style="cursor:pointer">
      <input type="checkbox" name="ship-src" value="${escHtml(src)}" checked
             onchange="_onShipSourceChange()">
      ${escHtml(src)}
    </label>`).join("");
}

function _onShipSourceChange() {
  const checked    = [...document.querySelectorAll('input[name="ship-src"]:checked')].map(x => x.value);
  const allSources = [...document.querySelectorAll('input[name="ship-src"]')].map(x => x.value);
  const fs = _filterState["tbl-ship"] = _filterState["tbl-ship"] || {};
  if (checked.length === allSources.length) {
    delete fs["__source__"];
  } else {
    fs["__source__"] = new Set(checked);
  }
  _renderTable("ship-table-wrap", "tbl-ship");
  const visibleRows = _filteredRows("tbl-ship");
  _renderShipDownloadStrip(visibleRows);
  _renderShipLpBreakdown(visibleRows, (_tableState["tbl-ship"] || {}).cols || [], _shipSourceTactics);
  _renderShipTotal(visibleRows);
}

// Re-render the tactic pills + download buttons based on currently visible rows
function _renderShipDownloadStrip(visibleRows) {
  const strip = document.getElementById("ship-downloads");
  if (!strip || !_shipResult) return;

  const allTactics = _shipResult.tactics || [];
  if (!visibleRows.length) {
    strip.innerHTML = `<span style="color:#57606a;font-size:13px">No rows to download.</span>`;
    return;
  }

  if (allTactics.length <= 1) {
    const fname = allTactics.length === 1
      ? allTactics[0].replace(/[^\w\-]/g, "") + "_POP.csv"
      : "shipments_POP.csv";
    strip.innerHTML = `<button class="btn-success btn-sm" onclick="downloadShipment('','${escHtml(fname)}')">⬇️ Download ${escHtml(fname)}</button>`;
    return;
  }

  // Multi-tactic: check which tactics have rows in the VISIBLE set
  const withRows    = allTactics.filter(t => visibleRows.some(r => String(r["TACTIC ID"] ?? "").trim() === t.trim()));
  const withoutRows = allTactics.filter(t => !visibleRows.some(r => String(r["TACTIC ID"] ?? "").trim() === t.trim()));

  const tacticPills = [
    ...withRows.map(t =>
      `<span style="display:inline-flex;align-items:center;gap:4px;background:#dcfce7;border:1px solid #86efac;border-radius:4px;padding:2px 8px;font-size:11px;margin:2px">✅ ${escHtml(t)}</span>`),
    ...withoutRows.map(t =>
      `<span style="display:inline-flex;align-items:center;gap:4px;background:#fee2e2;border:1px solid #fca5a5;border-radius:4px;padding:2px 8px;font-size:11px;margin:2px">⚠️ ${escHtml(t)} (filtered out)</span>`),
  ].join("");

  if (withRows.length === 1) {
    const singleTactic = withRows[0];
    const fname = singleTactic.replace(/[^\w\-]/g, "") + "_POP.csv";
    strip.innerHTML = `
      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:8px">
        <button class="btn-success btn-sm" onclick="downloadShipment('${escHtml(singleTactic)}','${escHtml(fname)}')">⬇️ Download ${escHtml(fname)}</button>
        <span style="font-size:11px;font-weight:600;color:#57606a;margin-left:4px">Tactics:</span>
        ${tacticPills}
      </div>`;
    return;
  }

  strip.innerHTML = `
    <div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:8px">
      <button class="btn-success btn-sm" onclick="downloadShipment('','ALL_TACTICS_POP.csv')">⬇️ Download ALL (combined)</button>
      <button class="btn-primary btn-sm" onclick="downloadAllSeparate()">⬇️ Download ALL (separate files)</button>
      <span style="font-size:11px;font-weight:600;color:#57606a;margin-left:4px">Tactics:</span>
      ${tacticPills}
    </div>`;
}

function _renderShipTotal(rows) {
  const el = document.getElementById("ship-total-bar");
  if (!el) return;
  if (!rows || !rows.length) { el.style.display = "none"; return; }

  const QTY_COL    = "SALES INVOICE QTY";
  const TACTIC_COL = "TACTIC ID";

  const hasQty = rows.some(r => r[QTY_COL] != null && r[QTY_COL] !== "");

  const tactics = [...new Set(rows.map(r => String(r[TACTIC_COL] ?? "").trim()).filter(Boolean))].sort();

  const fmtQty = n => n.toLocaleString();
  const sumQty = arr => arr.reduce((s, r) => s + (parseFloat(r[QTY_COL]) || 0), 0);

  // ── single tactic — compact one-liner ──
  if (tactics.length <= 1) {
    const label   = tactics.length === 1 ? tactics[0] : "Total";
    const sources = [...new Set(rows.map(r => r["__source__"]).filter(Boolean))].sort();
    const srcPills = sources.map(s => `<span class="total-src-pill">${escHtml(s)}</span>`).join("");
    const qtyPart = hasQty ? `<span class="stot-cell"><span class="stot-lbl">Qty</span><span class="stot-val">${fmtQty(sumQty(rows))}</span></span>` : "";
    el.style.display = "";
    el.innerHTML = `<div class="stot-oneliner">
      <span class="stot-tactic">${escHtml(label)}</span>
      <span class="total-src-wrap">${srcPills}</span>
      <span class="stot-cell"><span class="stot-lbl">Rows</span><span class="stot-val">${rows.length.toLocaleString()}</span></span>
      ${qtyPart}
    </div>`;
    return;
  }

  // ── multiple tactics — compact table ──
  const qtyTh = hasQty ? `<th class="stot-num">Qty</th>` : "";

  const dataRows = tactics.map(t => {
    const sub     = rows.filter(r => String(r[TACTIC_COL] ?? "").trim() === t);
    const sources = [...new Set(sub.map(r => r["__source__"]).filter(Boolean))].sort();
    const srcPills = sources.map(s => `<span class="total-src-pill">${escHtml(s)}</span>`).join("");
    const qtyTd = hasQty ? `<td class="stot-num">${fmtQty(sumQty(sub))}</td>` : "";
    return `<tr>
      <td class="stot-tactic-cell">${escHtml(t)}</td>
      <td><span class="total-src-wrap">${srcPills}</span></td>
      <td class="stot-num">${sub.length.toLocaleString()}</td>
      ${qtyTd}
    </tr>`;
  }).join("");

  const qtyFoot = hasQty ? `<td class="stot-num stot-grand">${fmtQty(sumQty(rows))}</td>` : "";
  const footRow = `<tr class="stot-foot">
    <td class="stot-grand" colspan="2">GRAND TOTAL</td>
    <td class="stot-num stot-grand">${rows.length.toLocaleString()}</td>
    ${qtyFoot}
  </tr>`;

  el.style.display = "";
  el.innerHTML = `
    <table class="stot-table">
      <thead><tr><th>Tactic</th><th>Source File(s)</th><th class="stot-num">Rows</th>${qtyTh}</tr></thead>
      <tbody>${dataRows}</tbody>
      <tfoot>${footRow}</tfoot>
    </table>`;
}

function _renderShipLpBreakdown(rows, cols, tactics) {
  const breakdown = document.getElementById("ship-lp-breakdown");
  if (!breakdown) return;

  // Resolve LP column
  let lpCol = (cols || []).find(c =>
    (c.toUpperCase().includes("L5") && c.toUpperCase().includes("PROMOTED")) ||
    c.toUpperCase().includes("L5_PROMOTED") ||
    c.toUpperCase().includes("GROUP CODE")
  );

  const colFilterState = _filterState["tbl-ship"] || {};

  // Gather LP values to check
  const inputLPs     = parseInput(document.getElementById("ship-lp")?.value || "");
  const mainLPs      = parseInput(document.getElementById("lp-input")?.value || "");
  const refLPs       = _searchResult?.effective_lps || [];
  const colFilterLPs = lpCol && colFilterState[lpCol] ? [...colFilterState[lpCol]] : [];

  // Pattern fallback
  let resolvedLpCol = lpCol;
  let extraFilterLPs = [];
  if (!resolvedLpCol) {
    for (const [col, sel] of Object.entries(colFilterState)) {
      if (sel && sel.size > 0) {
        const vals = [...sel];
        if (vals.some(v => /^[A-Za-z]{1,4}\d{4,}/.test(v))) {
          resolvedLpCol = col; extraFilterLPs = vals; break;
        }
      }
    }
  }

  let searchedLPs = [...new Set([...inputLPs, ...mainLPs, ...refLPs, ...colFilterLPs, ...extraFilterLPs])];
  if (searchedLPs.length === 0) { breakdown.style.display = "none"; return; }

  // Fallback scan if column not yet identified
  if (!resolvedLpCol && !lpCol) {
    lpCol = (cols || []).find(c => {
      const sample = (rows || []).slice(0, 100).map(r => String(r[c] ?? "").trim());
      return searchedLPs.some(lp => sample.includes(lp));
    });
  }

  const col = resolvedLpCol || lpCol;
  if (!col) { breakdown.style.display = "none"; return; }

  const tacticList = (tactics && tactics.length > 0) ? tactics : (_shipResult?.tactics || null);

  const QTY_COL = "SALES INVOICE QTY";
  const sumQty = arr => arr.reduce((s, r) => {
    const val = parseFloat(String(r[QTY_COL] ?? "").replace(/,/g, ""));
    return s + (isNaN(val) ? 0 : val);
  }, 0);

  const getLpRows = (rowList, targetLp) => {
    const targetLower = targetLp.toLowerCase();
    return rowList.filter(r => {
      const val = String(r[col] ?? "").trim().toLowerCase();
      if (val === targetLower) return true;
      for (const alias of ["L5 PROMOTED PRODUCT GROUP CODE", "L5_PROMOTED_PRODUCT_GROUP_CODE (2)"]) {
        if (r[alias] != null && String(r[alias]).trim().toLowerCase() === targetLower) return true;
      }
      return false;
    });
  };

  // Single tactic or no tactic distinction — flat list
  if (!tacticList || tacticList.length <= 1) {
    const pills = searchedLPs.map(lp => {
      const lpRows = getLpRows(rows, lp);
      const isPresent = lpRows.length > 0;
      const qty = isPresent ? sumQty(lpRows) : 0;
      return _lpPill(lp, isPresent, qty, lpRows.length);
    }).join("");

    breakdown.style.display = "";
    breakdown.innerHTML = `
      <div style="font-size:12px;font-weight:600;color:#57606a;margin-bottom:6px">🔍 LP check & Qty</div>
      <div style="display:flex;flex-wrap:wrap;gap:4px">${pills}</div>`;
    return;
  }

  // Multiple tactics — show LP breakdown per tactic + overall total
  const tacticRows = tactic => rows.filter(r => String(r["TACTIC ID"] ?? "").trim() === tactic.trim());

  const totalLpPills = searchedLPs.map(lp => {
    const lpRows = getLpRows(rows, lp);
    const isPresent = lpRows.length > 0;
    const qty = isPresent ? sumQty(lpRows) : 0;
    return _lpPill(lp, isPresent, qty, lpRows.length);
  }).join("");

  const sections = tacticList.map(t => {
    const tRows = tacticRows(t);
    const pills = searchedLPs.map(lp => {
      const lpRows = getLpRows(tRows, lp);
      const isPresent = lpRows.length > 0;
      const qty = isPresent ? sumQty(lpRows) : 0;
      return _lpPill(lp, isPresent, qty, lpRows.length);
    }).join("");

    const hasRows = tRows.length > 0;
    const tacticBadge = hasRows
      ? `<span style="background:#dcfce7;border:1px solid #86efac;border-radius:4px;padding:1px 8px;font-size:11px;font-weight:700;color:#166534">✅ ${escHtml(t)}</span>`
      : `<span style="background:#fee2e2;border:1px solid #fca5a5;border-radius:4px;padding:1px 8px;font-size:11px;font-weight:700;color:#991b1b">⚠️ ${escHtml(t)} (no rows)</span>`;

    return `
      <div style="margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">${tacticBadge}</div>
        <div style="display:flex;flex-wrap:wrap;gap:3px;padding-left:4px">${pills || '<span style="font-size:11px;color:#9ca3af">No LP match</span>'}</div>
      </div>`;
  }).join("");

  breakdown.style.display = "";
  breakdown.innerHTML = `
    <div style="font-size:12px;font-weight:600;color:#57606a;margin-bottom:6px">🔍 LP check & Qty (Total)</div>
    <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px">${totalLpPills}</div>
    <div style="font-size:12px;font-weight:600;color:#57606a;margin-bottom:8px">🔍 LP check & Qty — by tactic</div>
    ${sections}`;
}

function _lpPill(lp, present, qty, rowCount) {
  const bg     = present ? "#dcfce7" : "#fee2e2";
  const border = present ? "#86efac" : "#fca5a5";
  const icon   = present ? "✅" : "⚠️";
  const qtyFormatted = (qty != null ? Number(qty).toLocaleString() : "0");
  const qtyPart = present
    ? ` · <span style="font-weight:700;color:#166534">Qty: ${qtyFormatted}</span>`
    : ` · <span style="font-weight:500;color:#991b1b">Qty: 0</span>`;
  const countPart = (present && rowCount != null)
    ? ` <span style="color:#57606a;font-size:10px">(${rowCount.toLocaleString()} row${rowCount !== 1 ? "s" : ""})</span>`
    : "";
  return `<span style="display:inline-flex;align-items:center;gap:3px;background:${bg};border:1px solid ${border};border-radius:4px;padding:2px 8px;font-size:11px;margin:2px">${icon} <span>${escHtml(lp)}</span>${qtyPart}${countPart}</span>`;
}

function rowsToCsv(cols, rows) {
  // Build a CSV string from column list + row objects — pure client side.
  const escape = v => {
    const s = String(v ?? "");
    return s.includes(",") || s.includes('"') || s.includes("\n")
      ? '"' + s.replace(/"/g, '""') + '"'
      : s;
  };
  const header = cols.map(escape).join(",");
  const body   = rows.map(r => cols.map(c => escape(r[c] ?? "")).join(",")).join("\n");
  return header + "\n" + body;
}

function downloadCsv(csvStr, filename) {
  const blob = new Blob([csvStr], { type: "text/csv;charset=utf-8;" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function downloadShipment(tactic, filename) {
  if (!_shipResult) return;
  const cols = _shipResult.cols || [];
  // Always use the currently filtered (visible) rows so source-file selection is respected
  let rows = _filteredRows("tbl-ship");
  if (tactic) rows = rows.filter(r => String(r["TACTIC ID"] ?? "").trim() === tactic.trim());
  downloadCsv(rowsToCsv(cols, rows), filename);
}

async function downloadAllSeparate() {
  if (!_shipResult || !_lastShipSearch) return;

  const allRows = _filteredRows("tbl-ship");
  const tacticsWithRows = (_shipResult.tactics || []).filter(t =>
    allRows.some(r => String(r["TACTIC ID"] ?? "").trim() === t.trim())
  );
  if (!tacticsWithRows.length) return;

  const shipSrcCheckboxes = [...document.querySelectorAll('input[name="ship-src"]')];
  let shipFiles = _lastShipSearch.ship_files;
  if (shipSrcCheckboxes.length > 0) {
    shipFiles = [...document.querySelectorAll('input[name="ship-src"]:checked')].map(x => x.value);
  }

  const payload = { ..._lastShipSearch, tactics: tacticsWithRows, ship_files: shipFiles };
  const res = await fetch("/api/download_shipments_zip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) { alert("ZIP download failed: " + (await res.text())); return; }

  const blob = await res.blob();
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href = url; a.download = "shipments_separate.zip";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ── File management: upload, delete, drag-drop ─────────────

const _CHIP_CONTAINERS = { ref: "ref-chips", events: "events-chips", shipments: "ship-chips" };
const _CHIP_NAMES      = { ref: "ref",       events: "events",       shipments: "ship" };
const _UL_MSG          = { ref: "ul-ref",    events: "ul-events",    shipments: "ul-ship" };

// ── Checkbox state persisted in localStorage ───────
const _CHECKED_KEY = "upc_lp_checked";   // { ref: Set, events: Set, shipments: Set }

function _loadChecked() {
  try { return JSON.parse(localStorage.getItem(_CHECKED_KEY)) || {}; } catch { return {}; }
}
function _saveChecked(state) {
  // Convert Sets → arrays for JSON
  const out = {};
  for (const k of Object.keys(state)) out[k] = [...(state[k] || [])];
  localStorage.setItem(_CHECKED_KEY, JSON.stringify(out));
}

function _rebuildChips(folderKey, files) {
  const name      = _CHIP_NAMES[folderKey];
  const container = document.getElementById(_CHIP_CONTAINERS[folderKey]);
  if (!container) return;

  // Load persisted unchecked set; default new files to checked
  const raw       = _loadChecked();
  // raw[folderKey] = array of files that were UNchecked; if key absent → all checked
  const unchecked = new Set(raw[folderKey] || []);

  container.innerHTML = files.map(f => {
    const isChecked = !unchecked.has(f);
    return (
      `<span class="file-chip-del">` +
      `<input type="checkbox" name="${name}" value="${escHtml(f)}" ${isChecked ? "checked" : ""} ` +
      `style="width:14px;height:14px;margin:0" onchange="_onChipCheck('${folderKey}','${escHtml(f)}',this.checked)"> ` +
      `${escHtml(f)} ` +
      `<button class="del-btn" onclick="deleteFile('${folderKey}','${escHtml(f)}')" title="Delete">✕</button>` +
      `</span>`
    );
  }).join("");
}

function _onChipCheck(folderKey, filename, isChecked) {
  const raw       = _loadChecked();
  const unchecked = new Set(raw[folderKey] || []);
  if (isChecked) unchecked.delete(filename);
  else           unchecked.add(filename);
  raw[folderKey] = [...unchecked];
  _saveChecked(raw);
  // Re-run search so table reflects the toggled file
  runSearch(true);
}

function _updateAllChips(data) {
  _rebuildChips("ref",       data.ref       || []);
  _rebuildChips("events",    data.events    || []);
  _rebuildChips("shipments", data.shipments || []);
}

async function uploadFile(input, folderKey) {
  const files = [...input.files];
  if (!files.length) return;
  const msg = document.getElementById(_UL_MSG[folderKey]);
  if (msg) msg.style.display = "block";

  try {
    let lastData = null;
    for (const file of files) {
      const fd = new FormData();
      fd.append("folder", folderKey);
      fd.append("file", file);
      const res  = await fetch("/api/upload", { method: "POST", body: fd });
      const data = await res.json();
      if (data.error) { alert(`Upload failed for "${file.name}": ${data.error}`); continue; }
      lastData = data;
    }
    if (lastData) { _updateAllChips(lastData); runSearch(true); }
  } finally {
    if (msg) msg.style.display = "none";
    input.value = "";
  }
}

async function deleteFile(folderKey, filename) {
  if (!confirm(`Delete "${filename}"? This cannot be undone.`)) return;
  const msg = document.getElementById(_UL_MSG[folderKey]);
  if (msg) { msg.textContent = "⏳ Deleting & reloading…"; msg.style.display = "block"; }

  try {
    const res  = await fetch("/api/delete_file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder: folderKey, filename }),
    });
    const data = await res.json();
    if (data.error) { alert("Delete failed: " + data.error); return; }
    _updateAllChips(data);
    runSearch(true);
  } finally {
    if (msg) { msg.textContent = "⏳ Uploading & reloading…"; msg.style.display = "none"; }
  }
}

// Drag-and-drop helpers
function dzOver(e, id)  { e.preventDefault(); document.getElementById(id)?.classList.add("drag-over"); }
function dzLeave(id)    { document.getElementById(id)?.classList.remove("drag-over"); }
function dzDrop(e, folderKey) {
  e.preventDefault();
  const dzId = { ref: "dz-ref", events: "dz-events", shipments: "dz-ship" }[folderKey];
  dzLeave(dzId);
  const droppedFiles = [...e.dataTransfer.files];
  if (!droppedFiles.length) return;
  const inputId = { ref: "fu-ref", events: "fu-events", shipments: "fu-ship" }[folderKey];
  const dt = new DataTransfer();
  droppedFiles.forEach(f => dt.items.add(f));
  const input = document.getElementById(inputId);
  input.files = dt.files;
  uploadFile(input, folderKey);
}

// ── Enter key, input debounce, paste auto-search, and page open ────
let _searchDebounce = null;

document.addEventListener("DOMContentLoaded", () => {
  ["upc-input", "lp-input"].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    // Enter key — instant
    el.addEventListener("keydown", e => { if (e.key === "Enter") { clearTimeout(_searchDebounce); runSearch(); } });
    // Any input (including clearing the box) → debounced auto-search
    el.addEventListener("input", () => {
      clearTimeout(_searchDebounce);
      _searchDebounce = setTimeout(() => runSearch(), 400);
    });
    // Paste → slightly shorter wait so value is settled
    el.addEventListener("paste", () => {
      clearTimeout(_searchDebounce);
      _searchDebounce = setTimeout(() => runSearch(), 300);
    });
  });
  ["ship-tactic", "ship-lp", "ship-item"].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("keydown", e => { if (e.key === "Enter") runShipmentSearch(); });
    el.addEventListener("paste", () => {
      clearTimeout(_searchDebounce);
      _searchDebounce = setTimeout(() => runShipmentSearch(), 300);
    });
  });
  // Auto-load all events on page open — pass true so shipment search doesn't also auto-fire
  runSearch(true);
});
