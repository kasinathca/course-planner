// ==UserScript==
// @name         FFCS Studio VTOP Allocation Collector
// @namespace    https://ffcs-studio.local/
// @version      1.0.0
// @description  Manually capture the allocation table already displayed on VTOP for offline FFCS Studio import.
// @match        https://vtop.vit.ac.in/vtop/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_download
// @connect      none
// @run-at       document-idle
// ==/UserScript==

(() => {
  "use strict";

  const FIXTURE = document.documentElement.dataset.ffcsCollectorFixture === "true";
  const STORAGE_KEY = "ffcs-studio-vtop-capture-v1";
  const EXPECTED_HEADERS = ["Slot Detail", "Venue", "Faculty", "Course Type"];
  const KNOWN_TYPES = new Set(["TH", "ETH", "ELA", "EPJ", "SS"]);
  const MAX_COURSES = 500;
  const MAX_ROWS = 10000;
  const STABLE_MS = 450;
  let fixtureMemoryStore = null;
  const state = {
    phase: "no_course_selected",
    selectionVersion: 0,
    stableTimer: null,
    baselineSignature: "",
    tableSignature: "",
    parsed: null,
    warning: "",
    observer: null,
    observedRoot: null,
    lastCapture: null,
    store: loadStore(),
  };

  if (!FIXTURE && location.hostname !== "vtop.vit.ac.in") return;

  function normalize(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
  }

  function visible(element) {
    if (!(element instanceof HTMLElement)) return false;
    const style = getComputedStyle(element);
    return !element.hidden && style.display !== "none" && style.visibility !== "hidden";
  }

  function elementsById(id) {
    return [...document.querySelectorAll(`[id="${CSS.escape(id)}"]`)];
  }

  function selected(select) {
    if (!(select instanceof HTMLSelectElement) || !select.value) return null;
    const option = select.options[select.selectedIndex];
    const text = normalize(option?.textContent);
    if (!text || /^--?\s*choose/i.test(text) || /^select\b/i.test(text)) return null;
    return { value: normalize(select.value), text };
  }

  function identity() {
    const categorySelect = [...document.querySelectorAll("select#curriculumCategory")].find(visible);
    const courseSelect = [...document.querySelectorAll("select#courseId")].find(visible);
    const category = selected(categorySelect);
    const course = selected(courseSelect);
    if (!category || !course) return null;
    const match = course.text.match(/^([^\s–—-]+)\s*(?:[-–—]\s*)?(.+)?$/);
    return {
      category: category.value || category.text,
      courseCode: normalize(match?.[1] || course.value),
      courseTitle: normalize(match?.[2] || course.text),
      rawCourseText: course.text,
    };
  }

  function findTable() {
    const fragments = elementsById("courseDetailFragement").filter(visible);
    const tables = fragments.flatMap((fragment) => [...fragment.querySelectorAll("table")]);
    for (const table of tables) {
      if (!visible(table)) continue;
      const headerRow = table.tHead?.rows[0] || table.rows[0];
      const headers = [...(headerRow?.cells || [])].map((cell) => normalize(cell.textContent));
      if (EXPECTED_HEADERS.every((header) => headers.includes(header))) return { table, headers };
    }
    return null;
  }

  function signature(table) {
    if (!table) return "";
    const values = [...table.querySelectorAll("tr")].map((row) => [...row.cells].map((cell) => normalize(cell.textContent)));
    return JSON.stringify(values);
  }

  function parseVisibleTable() {
    const before = identity();
    const found = findTable();
    if (!before) return { ok: false, phase: "no_course_selected", warning: "Choose a category and course first." };
    if (!found) return { ok: false, phase: "waiting_for_details", warning: "A visible allocation table with the expected headers is not available." };
    const unexpected = found.headers.filter((header) => !EXPECTED_HEADERS.includes(header));
    if (unexpected.length) return { ok: false, phase: "review_required", warning: `Unexpected table columns: ${unexpected.join(", ")}. Capture is blocked so the extra data is not silently lost.` };
    const indexes = Object.fromEntries(EXPECTED_HEADERS.map((header) => [header, found.headers.indexOf(header)]));
    const tableRows = [...found.table.querySelectorAll("tbody tr")];
    const rows = [];
    for (const [index, row] of tableRows.entries()) {
      const cells = [...row.cells].map((cell) => normalize(cell.textContent));
      if (!cells.some(Boolean)) continue;
      const allocation = {
        source_row: index + 1,
        slot: cells[indexes["Slot Detail"]] || "",
        venue: cells[indexes.Venue] || "",
        faculty: cells[indexes.Faculty] || "",
        course_type: cells[indexes["Course Type"]] || "",
      };
      if (Object.values(allocation).some((value, fieldIndex) => fieldIndex > 0 && !value)) {
        return { ok: false, phase: "review_required", warning: `Allocation row ${index + 1} is incomplete.` };
      }
      rows.push(allocation);
    }
    const after = identity();
    if (!after || JSON.stringify(before) !== JSON.stringify(after)) {
      return { ok: false, phase: "selection_changed", warning: "The selected course changed while the table was being parsed." };
    }
    const unknown = [...new Set(rows.map((row) => row.course_type).filter((value) => !KNOWN_TYPES.has(value)))];
    return {
      ok: true,
      phase: "details_stable",
      identity: before,
      rows,
      signature: signature(found.table),
      warning: unknown.length ? `Unknown component type retained for review: ${unknown.join(", ")}.` : "",
    };
  }

  function onSelectionChange() {
    state.selectionVersion += 1;
    state.phase = identity() ? "selection_changed" : "no_course_selected";
    state.baselineSignature = signature(findTable()?.table);
    state.tableSignature = "";
    state.parsed = null;
    state.warning = "Waiting for the displayed allocation details to update and stabilize.";
    render();
    attachObserver();
    scheduleStabilityCheck(state.selectionVersion);
  }

  function scheduleStabilityCheck(version) {
    clearTimeout(state.stableTimer);
    state.phase = identity() ? "details_updating" : "no_course_selected";
    state.stableTimer = setTimeout(() => {
      if (version !== state.selectionVersion) return;
      const first = parseVisibleTable();
      if (!first.ok) {
        state.phase = first.phase;
        state.warning = first.warning;
        state.parsed = null;
        render();
        return;
      }
      setTimeout(() => {
        if (version !== state.selectionVersion) return;
        const second = parseVisibleTable();
        if (!second.ok || first.signature !== second.signature || JSON.stringify(first.identity) !== JSON.stringify(second.identity)) {
          state.phase = "details_updating";
          state.warning = second.warning || "The allocation table is still changing.";
          state.parsed = null;
        } else {
          state.phase = "ready_to_capture";
          state.tableSignature = second.signature;
          state.parsed = second;
          state.warning = second.warning || (state.baselineSignature === second.signature ? "The table did not visibly change after selection. Confirm below that it belongs to the selected course." : "Details are stable. Confirm the visible identity before capture.");
        }
        render();
      }, STABLE_MS);
    }, STABLE_MS);
  }

  function attachObserver() {
    const candidates = elementsById("courseDetailFragement");
    const fragment = candidates.find(visible) || candidates[0];
    const root = fragment?.parentElement || document.querySelector("#courseListFragement")?.parentElement;
    if (!root || root === state.observedRoot) return;
    state.observer?.disconnect();
    state.observedRoot = root;
    state.observer = new MutationObserver(() => {
      state.phase = "details_updating";
      state.parsed = null;
      scheduleStabilityCheck(state.selectionVersion);
      render();
    });
    state.observer.observe(root, { childList: true, subtree: true, characterData: true });
  }

  function captureCurrent() {
    const campus = normalize(ui.campus.value);
    const semester = normalize(ui.semester.value);
    const allowZero = ui.zero.checked;
    if (!campus || !semester) return setWarning("Enter the campus and semester label before capture.");
    if (!state.parsed || state.phase !== "ready_to_capture") return setWarning("Wait until the selected table is stable.");
    if (!ui.confirm.checked) return setWarning("Confirm that the visible table belongs to the selected course.");
    if (!state.parsed.rows.length && !allowZero) return setWarning("An empty table requires the explicit reviewed zero-allocation acknowledgement.");
    const { category, courseCode, courseTitle } = state.parsed.identity;
    const key = [campus, semester, category, courseCode].join("\u001f");
    const course = { category, course_code: courseCode, course_title: courseTitle, allocations: state.parsed.rows };
    const previous = state.store.courses[key];
    if (previous && JSON.stringify(previous.active) !== JSON.stringify(course)) {
      if (!window.confirm("This course was captured before and has changed. Replace the active capture while retaining bounded review history?")) return;
      previous.history = [...(previous.history || []), previous.active].slice(-3);
      previous.active = course;
      previous.captured_at = new Date().toISOString();
    } else if (!previous) {
      state.store.courses[key] = { active: course, history: [], captured_at: new Date().toISOString() };
    }
    state.store.campus = campus;
    state.store.semester_label = semester;
    state.store.updated_at = new Date().toISOString();
    enforceBounds();
    saveStore();
    state.phase = "captured";
    state.lastCapture = `${courseCode} — ${courseTitle}`;
    ui.confirm.checked = false;
    ui.zero.checked = false;
    render();
  }

  function removeSelected() {
    const parsed = state.parsed;
    if (!parsed) return;
    const key = [normalize(ui.campus.value), normalize(ui.semester.value), parsed.identity.category, parsed.identity.courseCode].join("\u001f");
    if (state.store.courses[key] && window.confirm(`Remove the active capture for ${parsed.identity.courseCode}?`)) {
      delete state.store.courses[key];
      saveStore();
      render();
    }
  }

  function resetSemester() {
    const prefix = `${normalize(ui.campus.value)}\u001f${normalize(ui.semester.value)}\u001f`;
    if (!window.confirm("Reset every captured course for this campus and semester? This cannot be undone.")) return;
    for (const key of Object.keys(state.store.courses)) if (key.startsWith(prefix)) delete state.store.courses[key];
    saveStore();
    render();
  }

  function activeCourses() {
    const campus = normalize(ui.campus.value);
    const semester = normalize(ui.semester.value);
    const prefix = `${campus}\u001f${semester}\u001f`;
    return Object.entries(state.store.courses)
      .filter(([key]) => key.startsWith(prefix))
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([, value]) => value.active);
  }

  function canonical() {
    return {
      schema_version: "1.0.0",
      source: "vtop-tampermonkey",
      campus: normalize(ui.campus.value),
      semester_label: normalize(ui.semester.value),
      captured_at: new Date().toISOString(),
      courses: activeCourses(),
    };
  }

  function exportJson() {
    const payload = canonical();
    if (!payload.campus || !payload.semester_label || !payload.courses.length) return setWarning("Enter metadata and capture at least one course before export.");
    download(JSON.stringify(payload, null, 2), "application/json", filename("json"));
  }

  function exportCsv() {
    const payload = canonical();
    if (!payload.campus || !payload.semester_label || !payload.courses.length) return setWarning("Enter metadata and capture at least one course before export.");
    const columns = ["semester_label", "category", "course_code", "course_title", "source_row", "slot", "venue", "faculty", "course_type"];
    const lines = [columns.join(",")];
    const zero = [];
    for (const course of payload.courses) {
      if (!course.allocations.length) zero.push({ category: course.category, course_code: course.course_code, course_title: course.course_title });
      for (const row of course.allocations) {
        const values = [payload.semester_label, course.category, course.course_code, course.course_title, row.source_row, row.slot, row.venue, row.faculty, row.course_type];
        lines.push(values.map(csvCell).join(","));
      }
    }
    const base = filename("").replace(/\.$/, "");
    download(`\uFEFF${lines.join("\r\n")}\r\n`, "text/csv", `${base}.csv`);
    download(JSON.stringify({ schema_version: "1.0.0", source: "vtop-tampermonkey-csv-sidecar", campus: payload.campus, semester_label: payload.semester_label, captured_at: payload.captured_at, zero_allocation_courses: zero, provenance: "Manual visible VTOP allocation capture", spreadsheet_formula_neutralization: "CSV cells beginning with =, +, -, or @ are prefixed with an apostrophe; canonical JSON is unchanged." }, null, 2), "application/json", `${base}.metadata.json`);
  }

  function csvCell(value) {
    let text = String(value ?? "");
    if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  }

  function filename(extension) {
    const part = `${normalize(ui.campus.value)}-${normalize(ui.semester.value)}`.replace(/[^A-Za-z0-9_-]+/g, "-").slice(0, 100);
    return `FFCS-Studio-${part || "capture"}.${extension}`;
  }

  function download(content, type, name) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    if (typeof GM_download === "function") GM_download({ url, name, saveAs: true, onload: () => URL.revokeObjectURL(url), onerror: () => URL.revokeObjectURL(url) });
    else {
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }

  function loadStore() {
    try {
      const value =
        typeof GM_getValue === "function" ? GM_getValue(STORAGE_KEY, null) : fixtureMemoryStore;
      const parsed = typeof value === "string" ? JSON.parse(value) : value;
      return parsed?.version === 1 && parsed.courses ? parsed : { version: 1, campus: "Vellore", semester_label: "", courses: {}, updated_at: null };
    } catch (_error) {
      return { version: 1, campus: "Vellore", semester_label: "", courses: {}, updated_at: null };
    }
  }

  function saveStore() {
    const serialized = JSON.stringify(state.store);
    if (serialized.length > 2_000_000) throw new Error("Collector storage exceeds the 2 MB safety limit; export and reset older captures.");
    if (typeof GM_setValue === "function") GM_setValue(STORAGE_KEY, serialized);
    else fixtureMemoryStore = serialized;
  }

  function enforceBounds() {
    const entries = Object.entries(state.store.courses);
    const rows = entries.reduce((total, [, value]) => total + value.active.allocations.length, 0);
    if (entries.length > MAX_COURSES || rows > MAX_ROWS) throw new Error("Capture exceeds the bounded 500-course/10,000-row session limit.");
  }

  const host = document.createElement("div");
  host.id = "ffcs-studio-collector-host";
  const shadow = host.attachShadow({ mode: "open" });
  shadow.innerHTML = `<style>
    :host{all:initial} .panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:min(360px,calc(100vw - 32px));font:14px/1.4 system-ui,sans-serif;color:#202124;background:#fff;border:1px solid #9aa0a6;border-radius:10px;box-shadow:0 4px 20px #0003} summary{cursor:pointer;padding:12px 14px;font-weight:700;background:#eef3fe;border-radius:10px} .body{padding:12px;max-height:70vh;overflow:auto} label{display:block;margin:8px 0 3px;font-weight:600} input{box-sizing:border-box;width:100%;min-height:36px;padding:6px} .check{display:flex;gap:8px;align-items:flex-start;font-weight:400}.check input{width:auto;min-height:auto;margin-top:4px}.actions{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}button{min-height:36px;border:1px solid #5f6368;border-radius:6px;background:#fff;padding:6px 9px;cursor:pointer}button.primary{background:#2563eb;color:#fff;border-color:#2563eb}button:disabled{opacity:.5;cursor:not-allowed}.status{padding:8px;background:#f7f8fa;border-radius:6px;white-space:pre-wrap}.warning{color:#8a3b00}.meta{color:#5f6368;font-size:12px}ul{padding-left:20px}</style>
    <details class="panel" open><summary>FFCS Studio collector</summary><div class="body">
      <label for="campus">Campus</label><input id="campus" autocomplete="off">
      <label for="semester">Semester label</label><input id="semester" autocomplete="off">
      <p id="selection" class="meta"></p><div id="status" class="status" role="status" aria-live="polite"></div>
      <label class="check"><input id="confirm" type="checkbox">I confirm the visible allocation table belongs to the selected course.</label>
      <label class="check"><input id="zero" type="checkbox">I reviewed and accept a confirmed zero-allocation course.</label>
      <div class="actions"><button id="capture" class="primary">Capture current course</button><button id="remove">Remove selected capture</button><button id="json">Export canonical JSON</button><button id="csv">Export CSV + metadata</button><button id="reset">Reset semester</button></div>
      <p id="counts" class="meta"></p><p id="warning" class="warning" role="alert"></p><details><summary>Review captured courses</summary><ul id="review"></ul></details>
    </div></details>`;
  document.documentElement.append(host);
  const ui = Object.fromEntries(["campus", "semester", "selection", "status", "confirm", "zero", "capture", "remove", "json", "csv", "reset", "counts", "warning", "review"].map((id) => [id, shadow.getElementById(id)]));
  ui.campus.value = state.store.campus || "Vellore";
  ui.semester.value = state.store.semester_label || "";
  ui.capture.addEventListener("click", captureCurrent);
  ui.remove.addEventListener("click", removeSelected);
  ui.json.addEventListener("click", exportJson);
  ui.csv.addEventListener("click", exportCsv);
  ui.reset.addEventListener("click", resetSemester);
  ui.campus.addEventListener("change", render);
  ui.semester.addEventListener("change", render);
  document.addEventListener("change", (event) => {
    if (event.target?.matches?.("select#curriculumCategory, select#courseId")) onSelectionChange();
  }, true);

  function setWarning(message) { state.warning = message; render(); }
  function render() {
    const current = identity();
    const courses = activeCourses();
    const rowCount = courses.reduce((total, course) => total + course.allocations.length, 0);
    ui.selection.textContent = current ? `Selected: ${current.category} · ${current.courseCode} — ${current.courseTitle}` : "No complete category/course selection detected.";
    ui.status.textContent = `State: ${state.phase.replaceAll("_", " ")}`;
    ui.warning.textContent = state.warning;
    ui.capture.disabled = state.phase !== "ready_to_capture";
    ui.remove.disabled = !state.parsed;
    ui.counts.textContent = `${courses.length} captured course(s) · ${rowCount} allocation row(s)${state.lastCapture ? ` · latest ${state.lastCapture}` : ""}${state.store.updated_at ? ` · saved ${new Date(state.store.updated_at).toLocaleString()}` : ""}`;
    ui.review.replaceChildren(...courses.map((course) => { const item = document.createElement("li"); item.textContent = `${course.category} · ${course.course_code} — ${course.course_title}: ${course.allocations.length} row(s)`; return item; }));
  }

  attachObserver();
  onSelectionChange();
  if (FIXTURE) window.__FFCSCollector = { state, identity, findTable, parseVisibleTable, onSelectionChange, activeCourses, canonical };
})();
