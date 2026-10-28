import { api, option, textElement } from "../api.js";
import { workspace } from "../state.js";

const importFlow = { validationId: null, previewId: null };
const calendarFlow = { validationId: null, previewId: null };
const explorer = { page: 1, pageSize: 25, total: 0, controller: null, detailOfferingId: null };

export function initDataWorkspace() {
  const file = byId("import-file");
  file.addEventListener("change", selectImportFile);
  byId("validate-button").addEventListener("click", validateImport);
  byId("preview-button").addEventListener("click", previewImport);
  byId("commit-button").addEventListener("click", commitImport);
  byId("cancel-button").addEventListener("click", () => resetImport(true));
  byId("filter-button").addEventListener("click", () => loadOfferings(1));
  byId("search-filter").addEventListener("keydown", (event) => { if (event.key === "Enter") loadOfferings(1); });
  byId("previous-page").addEventListener("click", () => loadOfferings(explorer.page - 1));
  byId("next-page").addEventListener("click", () => loadOfferings(explorer.page + 1));
  byId("close-detail").addEventListener("click", () => { byId("offering-detail").hidden = true; });
  byId("add-course-to-planner").addEventListener("click", () => {
    workspace.dispatchEvent(new CustomEvent("select-offering", { detail: explorer.detailOfferingId }));
    location.hash = "planner";
  });
  byId("calendar-file").addEventListener("change", selectCalendarFile);
  byId("calendar-validate").addEventListener("click", validateCalendar);
  byId("calendar-preview").addEventListener("click", previewCalendar);
  byId("calendar-commit").addEventListener("click", commitCalendar);
  byId("calendar-select").addEventListener("change", updateCalendarControls);
  byId("resolve-slot").addEventListener("click", resolveSlot);
  byId("check-conflict").addEventListener("click", checkConflict);
  refreshSources(); loadOfferings(1);
}

export async function refreshSources(preferredCalendar = "") {
  const [semesters, calendars] = await Promise.all([api("/api/v1/semesters"), api("/api/v1/calendars")]);
  workspace.calendars = calendars.items;
  const semesterFilter = byId("semester-filter");
  const previous = semesterFilter.value;
  semesterFilter.replaceChildren(option("", "All semesters"));
  for (const item of semesters.items) semesterFilter.append(option(`${item.campus}\u001f${item.semester_label}`, `${item.semester_label} — ${item.campus} (${item.offering_count})`));
  if ([...semesterFilter.options].some((item) => item.value === previous)) semesterFilter.value = previous;
  const calendarSelect = byId("calendar-select");
  calendarSelect.replaceChildren(option("", calendars.items.length ? "Select a calendar" : "No committed calendars"));
  for (const item of calendars.items) {
    calendarSelect.append(option(item.calendar_id, `${item.semester_label} — ${item.profile_name} v${item.version} [${item.verification_status}]${item.active ? " · active" : ""}`));
    if (item.calendar_id === preferredCalendar || (!preferredCalendar && item.active && !calendarSelect.value)) calendarSelect.value = item.calendar_id;
  }
  updateCalendarControls();
  workspace.dispatchEvent(new CustomEvent("sources-changed", { detail: { semesters: semesters.items, calendars: calendars.items } }));
}

async function loadOfferings(page) {
  explorer.controller?.abort(); explorer.controller = new AbortController(); explorer.page = Math.max(1, page);
  const params = new URLSearchParams({ page: explorer.page, page_size: explorer.pageSize });
  const [campus, semester] = byId("semester-filter").value.split("\u001f");
  if (campus) { params.set("campus", campus); params.set("semester_label", semester); }
  for (const [key, id] of [["search", "search-filter"], ["category", "category-filter"], ["component", "component-filter"]]) {
    const value = byId(id).value.trim(); if (value) params.set(key, value);
  }
  try {
    const result = await api(`/api/v1/offerings?${params}`, { signal: explorer.controller.signal });
    explorer.total = result.total; renderOfferings(result.items);
    byId("result-count").textContent = `${result.total} course${result.total === 1 ? "" : "s"}`;
    byId("page-label").textContent = `Page ${result.page}`;
    byId("previous-page").disabled = result.page <= 1;
    byId("next-page").disabled = result.page * result.page_size >= result.total;
  } catch (error) { if (error.name !== "AbortError") byId("offerings-body").replaceChildren(emptyRow("Courses could not be loaded.", 5)); }
}

function renderOfferings(items) {
  if (!items.length) { byId("offerings-body").replaceChildren(emptyRow("No courses match the current filters.", 5)); return; }
  byId("offerings-body").replaceChildren(...items.map((item) => {
    const row = document.createElement("tr"); const course = document.createElement("td");
    course.append(textElement("span", item.course_code, "course-code"), textElement("span", item.course_title, "course-title"));
    const components = textElement("td", item.component_types.join(", ") || "Not supplied");
    const action = document.createElement("td"); const button = textElement("button", "View source", "secondary");
    button.addEventListener("click", () => showOffering(item.offering_id)); action.append(button);
    row.append(course, textElement("td", item.category), components, textElement("td", item.allocation_count), action); return row;
  }));
}

async function showOffering(offeringId) {
  const [detail, allocations, components, candidates] = await Promise.all([
    api(`/api/v1/offerings/${offeringId}`), api(`/api/v1/offerings/${offeringId}/allocations`),
    api(`/api/v1/offerings/${offeringId}/components`), api(`/api/v1/offerings/${offeringId}/registration-options`),
  ]);
  explorer.detailOfferingId = offeringId; byId("detail-title").textContent = `${detail.course_code} — ${detail.course_title}`;
  byId("detail-meta").textContent = `${detail.category} · ${detail.semester_label} · ${detail.campus} · revision ${detail.revision_id}`;
  byId("allocations-body").replaceChildren(...allocations.items.map((item) => {
    const row = document.createElement("tr"); row.append(textElement("td", item.allocation_id), textElement("td", item.slot), textElement("td", item.venue), textElement("td", item.faculty), textElement("td", item.course_type)); return row;
  }));
  byId("detail-provenance").textContent = `Source: ${detail.source_kind} (${detail.source_format}); ${detail.original_filename}; captured ${detail.captured_at}; import ${detail.import_id}.`;
  byId("detail-missing").textContent = `Not supplied: ${detail.missing_metadata.join(", ").replaceAll("_", " ")}. Nothing was inferred.`;
  byId("detail-component-status").textContent = `Curriculum interpretation: ${components.curriculum_type} (${components.curriculum_type_status}).`;
  byId("detail-candidates").replaceChildren(...candidates.items.map((candidate) => textElement("li", `${candidate.status}: ${candidate.allocations.map((row) => `#${row.allocation_id} ${row.course_type} ${row.slot}`).join(" + ") || "No combination"} — ${candidate.reasons.join("; ")}`)));
  const warnings = byId("detail-warnings"); warnings.replaceChildren(...detail.warnings.map((item) => textElement("li", `${item.code}: ${item.message}`, "warning-text"))); warnings.hidden = !detail.warnings.length;
  byId("offering-detail").hidden = false; byId("offering-detail").scrollIntoView({ block: "nearest" });
}

function selectImportFile() {
  resetImport(false); const file = byId("import-file").files[0]; if (!file) return;
  byId("selected-file").textContent = `${file.name} — ${formatBytes(file.size)}`;
  byId("csv-metadata").hidden = !isCsv(file); byId("validate-button").disabled = false; byId("cancel-button").disabled = false;
  setImport("File selected", "Ready to validate. No database change has been made.");
}

async function validateImport() {
  const file = byId("import-file").files[0]; if (!file) return;
  const headers = { "Content-Type": isCsv(file) ? "text/csv" : "application/json", "X-FFCS-Filename": file.name };
  if (isCsv(file)) {
    headers["X-FFCS-Campus"] = byId("csv-campus").value; headers["X-FFCS-Semester"] = byId("csv-semester").value;
    if (byId("csv-captured-at").value) headers["X-FFCS-Captured-At"] = new Date(byId("csv-captured-at").value).toISOString();
  }
  try {
    const result = await api("/api/v1/imports/validate", { method: "POST", headers, body: file }); importFlow.validationId = result.validation_id;
    byId("summary-courses").textContent = result.course_count; byId("summary-rows").textContent = result.allocation_count; byId("summary-warnings").textContent = result.issues.length; byId("import-summary").hidden = false;
    renderIssues(result.issues); byId("preview-button").disabled = false; setImport(result.issues.length ? "Valid with warnings" : "Valid", `Validated ${result.course_count} course(s) and ${result.allocation_count} source row(s).`, result.issues.length ? "warning" : "success");
  } catch (error) { setImport("Invalid file", error.message, "error"); }
}

async function previewImport() {
  try {
    const result = await api("/api/v1/imports/preview", { method: "POST", json: { validation_id: importFlow.validationId } }); importFlow.previewId = result.preview_id; renderPreview(result.reconciliation); byId("commit-button").disabled = false; setImport("Preview ready", "Review the proposed changes, then commit explicitly.", "success");
  } catch (error) { setImport("Preview failed", error.message, "error"); }
}

async function commitImport() {
  try {
    const result = await api("/api/v1/imports/commit", { method: "POST", json: { preview_id: importFlow.previewId } });
    setImport(result.status === "already_imported" ? "Already imported" : "Imported", `Saved ${result.course_count} course(s) and ${result.allocation_count} row(s).`, "success");
    byId("commit-button").disabled = true; await refreshSources(); await loadOfferings(1);
  } catch (error) { setImport("Commit failed", error.message, "error"); }
}

function renderIssues(items) { byId("issues-list").replaceChildren(...items.map((item) => textElement("li", `${item.level.toUpperCase()} · ${item.code}: ${item.path} — ${item.message}`, item.level === "error" ? "error-text" : "warning-text"))); byId("issues-panel").hidden = !items.length; }
function renderPreview(diff) {
  byId("preview-panel").hidden = false;
  const keys = { "diff-new": "new_courses", "diff-updated": "updated_courses", "diff-unchanged": "unchanged_courses", "diff-added": "added_rows", "diff-removed": "removed_rows", "diff-modified": "modified_rows" };
  for (const [id, key] of Object.entries(keys)) byId(id).textContent = diff[key];
  byId("change-list").replaceChildren(...diff.changes.map((item) => textElement("div", `${item.course_code}: ${item.change_type}; +${item.added_rows.length} / −${item.removed_rows.length} / ${item.modified_rows.length} modified`, "change-item")));
}
function resetImport(clear) { importFlow.validationId = null; importFlow.previewId = null; if (clear) { byId("import-file").value = ""; byId("selected-file").textContent = "No file selected."; } byId("preview-button").disabled = true; byId("commit-button").disabled = true; byId("import-summary").hidden = true; byId("issues-panel").hidden = true; byId("preview-panel").hidden = true; }
function setImport(state, message, style = "") { byId("import-state").textContent = state; byId("import-state").className = `state-pill ${style}`; byId("import-status").textContent = message; byId("import-status").className = `feedback ${style}`; }

function selectCalendarFile() { calendarFlow.validationId = null; calendarFlow.previewId = null; const file = byId("calendar-file").files[0]; byId("calendar-file-detail").textContent = file ? `${file.name} — ${formatBytes(file.size)}` : "No file selected."; byId("calendar-validate").disabled = !file; byId("calendar-preview").disabled = true; byId("calendar-commit").disabled = true; }
async function validateCalendar() { try { const result = await api("/api/v1/calendars/validate", { method: "POST", json: JSON.parse(await byId("calendar-file").files[0].text()) }); calendarFlow.validationId = result.validation_id; byId("calendar-preview").disabled = false; byId("calendar-feedback").textContent = `Valid ${result.calendar.verification_status} calendar; ${result.issues.length} review note(s).`; } catch (error) { byId("calendar-feedback").textContent = error.message; } }
async function previewCalendar() { try { const result = await api("/api/v1/calendars/preview", { method: "POST", json: { validation_id: calendarFlow.validationId } }); calendarFlow.previewId = result.preview_id; byId("calendar-commit").disabled = false; byId("calendar-feedback").textContent = `${result.slot_count} slots and ${result.interval_count} exact intervals; ${result.duplicate_calendar_id ? "already committed" : "new immutable version"}.`; } catch (error) { byId("calendar-feedback").textContent = error.message; } }
async function commitCalendar() { try { const result = await api("/api/v1/calendars/commit", { method: "POST", json: { preview_id: calendarFlow.previewId, make_active: true } }); byId("calendar-feedback").textContent = `Calendar ${result.status}.`; await refreshSources(result.calendar_id); } catch (error) { byId("calendar-feedback").textContent = error.message; } }
function updateCalendarControls() { const selected = Boolean(byId("calendar-select").value); byId("resolve-slot").disabled = !selected; byId("check-conflict").disabled = !selected; }
async function resolveSlot() { try { byId("slot-output").textContent = JSON.stringify(await api("/api/v1/slots/resolve", { method: "POST", json: { calendar_id: byId("calendar-select").value, expression: byId("left-slot").value } }), null, 2); } catch (error) { byId("slot-output").textContent = error.message; } }
async function checkConflict() { try { byId("slot-output").textContent = JSON.stringify(await api("/api/v1/conflicts/check", { method: "POST", json: { calendar_id: byId("calendar-select").value, left: byId("left-slot").value, right: byId("right-slot").value } }), null, 2); } catch (error) { byId("slot-output").textContent = error.message; } }

function byId(id) { return document.getElementById(id); }
function isCsv(file) { return file.name.toLowerCase().endsWith(".csv") || file.type === "text/csv"; }
function formatBytes(bytes) { return bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`; }
function emptyRow(message, columns) { const row = document.createElement("tr"); const cell = textElement("td", message, "empty-cell"); cell.colSpan = columns; row.append(cell); return row; }
