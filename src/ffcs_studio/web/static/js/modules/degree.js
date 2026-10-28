import { api, option, textElement } from "../api.js";

const state = { curricula: [], plans: [], active: null, catalog: [], catalogLookup: new Map(), progress: null, dirty: false, file: null, validationId: null, previewId: null };

export function initDegreePlanner() {
  const semester = byId("degree-semester");
  for (let number = 1; number <= 10; number += 1) semester.append(option(number, `Semester ${number}`));
  semester.value = "5";
  byId("degree-plan-select").addEventListener("change", (event) => openPlan(event.target.value));
  byId("degree-new-plan").addEventListener("click", createPlan);
  byId("degree-save").addEventListener("click", savePlan);
  byId("degree-duplicate").addEventListener("click", duplicatePlan);
  byId("degree-compare").addEventListener("click", compareRevision);
  byId("degree-restore").addEventListener("click", restoreRevision);
  byId("degree-archive").addEventListener("click", archivePlan);
  byId("degree-semester").addEventListener("change", () => {
    renderSemesters();
    renderCatalog();
  });
  byId("degree-filter").addEventListener("click", loadCatalog);
  byId("degree-search").addEventListener("keydown", (event) => { if (event.key === "Enter") loadCatalog(); });
  byId("degree-recommend").addEventListener("click", loadRecommendations);
  byId("degree-transfer").addEventListener("click", transferSemester);
  byId("degree-import-file").addEventListener("change", chooseFile);
  byId("degree-import-validate").addEventListener("click", validateImport);
  byId("degree-import-preview").addEventListener("click", previewImport);
  byId("degree-import-commit").addEventListener("click", commitImport);
  byId("degree-run-recovery").addEventListener("click", runRecovery);
  byId("degree-availability-save").addEventListener("click", saveAvailability);
  byId("degree-availability-refresh").addEventListener("click", refreshAvailability);
  refresh();
}

async function refresh() {
  try {
    const [curricula, plans] = await Promise.all([api("/api/v1/curricula"), api("/api/v1/degree/plans")]);
    state.curricula = curricula.items;
    state.plans = plans.items;
    renderPlanSelect();
    if (state.active) await openPlan(state.active.degree_plan_id, false);
  } catch (error) { feedback(error.message, "error"); }
}

function renderPlanSelect() {
  const select = byId("degree-plan-select");
  select.replaceChildren(option("", "Choose a saved timeline"), ...state.plans.map((plan) => option(plan.degree_plan_id, `${plan.name} · revision ${plan.current_revision}`)));
  if (state.active) select.value = state.active.degree_plan_id;
}

async function createPlan() {
  const usable = state.curricula.find((item) => item.course_count > 0) || state.curricula[0];
  if (!usable) { feedback("No programme policy is available.", "error"); return; }
  const name = window.prompt("Name this degree-planning timeline", "Primary degree plan");
  if (!name?.trim()) return;
  try {
    const curriculum = await api(`/api/v1/curricula/${usable.curriculum_id}`);
    const document = { programme_code: curriculum.programme_code, curriculum_revision: curriculum.revision_code, records: [], settings: { warning_threshold_milli: 27000 }, semester_labels: {} };
    const created = await api("/api/v1/degree/plans", { method: "POST", json: { name: name.trim(), curriculum_id: usable.curriculum_id, document } });
    state.plans.unshift(created); state.active = created; state.dirty = false;
    renderPlanSelect(); await loadActive(); feedback(`Created “${created.name}”.`, "success");
  } catch (error) { feedback(error.message, "error"); }
}

async function openPlan(id, guard = true) {
  if (!id) return;
  if (guard && state.dirty && !window.confirm("Discard unsaved degree-plan edits?")) { byId("degree-plan-select").value = state.active?.degree_plan_id || ""; return; }
  try { state.active = await api(`/api/v1/degree/plans/${id}`); state.dirty = false; await loadActive(); feedback(`Opened “${state.active.name}” revision ${state.active.current_revision}.`, "success"); }
  catch (error) { feedback(error.message, "error"); }
}

async function loadActive() {
  byId("degree-revision").textContent = `${state.active.name} · revision ${state.active.current_revision}`;
  for (const id of ["degree-save", "degree-duplicate", "degree-transfer", "degree-recommend", "degree-run-recovery", "degree-archive"]) byId(id).disabled = false;
  await Promise.all([loadCatalog(), loadProgress()]);
  await loadPlanCourses();
  await loadRevisions(); renderSemesters(); renderPlanSelect();
}

async function loadRevisions() {
  const result = await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/revisions`);
  const select = byId("degree-history-revision");
  select.replaceChildren(...result.items.map((item) => option(item.revision, `Revision ${item.revision} · ${item.change_summary}`)));
  select.disabled = !result.items.length; select.value = String(result.items.find((item) => item.revision < state.active.current_revision)?.revision || state.active.current_revision);
  byId("degree-compare").disabled = result.items.length < 2; byId("degree-restore").disabled = Number(select.value) === state.active.current_revision;
  select.onchange = () => { byId("degree-restore").disabled = Number(select.value) === state.active.current_revision; };
}

async function loadCatalog() {
  if (!state.active) return;
  const params = new URLSearchParams({ curriculum_id: state.active.curriculum_id, query: byId("degree-search").value.trim(), category: byId("degree-category-filter").value.trim().toUpperCase(), page: 1, page_size: 100 });
  try { const result = await api(`/api/v1/degree/catalog?${params}`); state.catalog = result.items; for (const course of result.items) state.catalogLookup.set(course.catalogue_course_id, course); byId("degree-catalog-count").textContent = `${result.total} course${result.total === 1 ? "" : "s"}`; renderCatalog(); }
  catch (error) { feedback(error.message, "error"); }
}

async function loadPlanCourses() {
  const missing = [...new Set(state.active.document.records.map((item) => item.course_id))].filter((identity) => !state.catalogLookup.has(identity));
  const loaded = await Promise.all(missing.map((identity) => api(`/api/v1/degree/catalog/${encodeURIComponent(identity)}`)));
  for (const course of loaded) state.catalogLookup.set(course.catalogue_course_id, course);
}

function renderCatalog() {
  const body = byId("degree-catalog-body");
  if (!state.catalog.length) { body.replaceChildren(emptyRow(5, "This curriculum has no imported catalogue yet.")); return; }
  body.replaceChildren(...state.catalog.map((course) => {
    const row = document.createElement("tr");
    const title = document.createElement("td"); title.append(textElement("strong", course.course_code), textElement("span", course.course_title, "muted"));
    const add = textElement("button", `Add to S${byId("degree-semester").value}`, "ghost"); add.type = "button"; add.addEventListener("click", () => addCourse(course));
    row.append(title, textElement("td", course.category_code), textElement("td", credit(course.total_credits_milli)), textElement("td", course.provenance), cell(add)); return row;
  }));
}

function addCourse(course) {
  const active = state.active.document.records.filter((item) => !["withdrawn", "failed"].includes(item.status));
  if (active.some((item) => item.course_id === course.catalogue_course_id)) { feedback(`${course.course_code} is already active in this timeline.`, "warning"); return; }
  state.active.document.records.push({ record_id: crypto.randomUUID(), course_id: course.catalogue_course_id, semester: Number(byId("degree-semester").value), status: "planned", intended_category: course.category_code, notes: "", source: "manual", attempt: 1, offering_id: null });
  dirty(`Added ${course.course_code} to semester ${byId("degree-semester").value}.`); renderSemesters(); renderCatalog(); loadProgress();
}

function renderSemesters() {
  const selected = Number(byId("degree-semester").value);
  const lookup = state.catalogLookup;
  const matrix = byId("degree-semester-matrix");
  const cards = [];
  const historical = state.active?.document.records.filter((item) => Number(item.semester) === 0) || [];
  if (historical.length) {
    const card = document.createElement("article"); card.className = "semester-card";
    card.append(textElement("h3", "Completed · term unknown"), textElement("p", "The source did not identify a semester; credits still count as earned.", "muted"));
    for (const record of historical) card.append(recordEditor(record, lookup.get(record.course_id)));
    cards.push(card);
  }
  for (let number = 1; number <= 10; number += 1) {
    const card = document.createElement("article"); card.className = `semester-card${number === selected ? " selected" : ""}`;
    const records = state.active?.document.records.filter((item) => Number(item.semester) === number) || [];
    const known = records.reduce((total, record) => total + (lookup.get(record.course_id)?.total_credits_milli || 0), 0);
    const heading = textElement("h3", `Semester ${number}`); heading.tabIndex = 0; heading.addEventListener("click", () => { byId("degree-semester").value = String(number); renderSemesters(); renderCatalog(); });
    const progress = state.progress?.semesters?.find((item) => item.semester === number);
    const accounting = progress ? ` · earned ${credit(progress.earned_milli)} · enrolled ${credit(progress.enrolled_milli)} · planned ${credit(progress.planned_milli)} · cumulative ${credit(progress.cumulative_earned_milli + progress.cumulative_enrolled_milli + progress.cumulative_planned_milli)}` : "";
    const categories = progress ? semesterCategories(progress) : "";
    card.append(heading, textElement("p", `${records.length} record${records.length === 1 ? "" : "s"} · ${credit(known)} known credits${accounting}`, "muted"));
    if (categories) card.append(textElement("p", categories, "provenance"));
    for (const record of records) card.append(recordEditor(record, lookup.get(record.course_id)));
    cards.push(card);
  }
  matrix.replaceChildren(...cards);
}

function recordEditor(record, course) {
  const wrapper = document.createElement("div"); wrapper.className = "degree-record";
  wrapper.append(textElement("strong", course?.course_code || record.course_id), textElement("span", course?.course_title || "Catalogue entry not loaded", "muted"));
  const status = document.createElement("select"); for (const value of ["planned", "tentative", "enrolled", "completed", "withdrawn", "failed"]) status.append(option(value, value.replaceAll("_", " "))); status.value = record.status; status.setAttribute("aria-label", "Academic status"); status.addEventListener("change", () => { record.status = status.value; dirty("Changed academic status."); loadProgress(); });
  const semester = document.createElement("select"); if (Number(record.semester) === 0) semester.append(option(0, "Term unknown")); for (let number = 1; number <= 10; number += 1) semester.append(option(number, `Move to S${number}`)); semester.value = String(record.semester); semester.setAttribute("aria-label", "Move course to semester"); semester.addEventListener("change", () => { record.semester = Number(semester.value); dirty("Moved a course between semesters."); renderSemesters(); loadProgress(); });
  const notes = document.createElement("input"); notes.type = "text"; notes.maxLength = 1000; notes.value = record.notes || ""; notes.placeholder = "Course notes"; notes.setAttribute("aria-label", "Course notes"); notes.addEventListener("input", () => { record.notes = notes.value; dirty("Updated course notes."); });
  const remove = textElement("button", "Remove", "ghost"); remove.type = "button"; remove.addEventListener("click", () => { state.active.document.records = state.active.document.records.filter((item) => item.record_id !== record.record_id); dirty("Removed a plan record."); renderSemesters(); loadProgress(); });
  wrapper.append(status, semester, notes, remove); return wrapper;
}

async function savePlan() {
  try { const stored = await api(`/api/v1/degree/plans/${state.active.degree_plan_id}`, { method: "PUT", json: { expected_revision: state.active.current_revision, name: state.active.name, change_summary: "Saved from the Degree Planner", document: state.active.document } }); state.active = stored; state.dirty = false; await refresh(); feedback(`Saved revision ${stored.current_revision}.`, "success"); }
  catch (error) { feedback(error.status === 409 ? `${error.message}. Reload before saving; edits remain visible.` : error.message, "error"); }
}

async function duplicatePlan() {
  const name = window.prompt("Name the alternative timeline", `${state.active.name} alternative`); if (!name?.trim()) return;
  try { const stored = await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/duplicate`, { method: "POST", json: { name: name.trim() } }); await refresh(); await openPlan(stored.degree_plan_id, false); }
  catch (error) { feedback(error.message, "error"); }
}

async function compareRevision() {
  const left = Number(byId("degree-history-revision").value); if (!left) return;
  try { const result = await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/compare?left_revision=${left}&right_revision=${state.active.current_revision}`); byId("degree-history-output").textContent = JSON.stringify(result, null, 2); }
  catch (error) { feedback(error.message, "error"); }
}

async function restoreRevision() {
  const source = Number(byId("degree-history-revision").value); if (!source || source === state.active.current_revision) return;
  if (!window.confirm(`Restore revision ${source} as a new revision? Current history remains intact.`)) return;
  try { state.active = await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/restore`, { method: "POST", json: { source_revision: source, expected_revision: state.active.current_revision } }); state.dirty = false; await refresh(); feedback(`Restored revision ${source} as revision ${state.active.current_revision}.`, "success"); }
  catch (error) { feedback(error.message, "error"); }
}

async function archivePlan() {
  if (!window.confirm(`Archive “${state.active.name}”? Its revision history will remain in SQLite.`)) return;
  try { await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/archive`, { method: "POST", json: { expected_revision: state.active.current_revision } }); state.active = null; state.dirty = false; state.catalog = []; state.catalogLookup.clear(); state.progress = null; await refresh(); byId("degree-revision").textContent = "No plan open"; byId("degree-semester-matrix").replaceChildren(); byId("degree-history-output").textContent = "Timeline archived. Its history remains recoverable through the API."; for (const id of ["degree-save", "degree-duplicate", "degree-transfer", "degree-recommend", "degree-run-recovery", "degree-archive", "degree-compare", "degree-restore"]) byId(id).disabled = true; feedback("Timeline archived without deleting its history.", "success"); }
  catch (error) { feedback(error.message, "error"); }
}

async function loadProgress() {
  if (!state.active) return;
  try { state.progress = state.dirty ? await api("/api/v1/degree/progress/preview", { method: "POST", json: { curriculum_id: state.active.curriculum_id, document: state.active.document } }) : await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/progress?revision=${state.active.current_revision}`); renderProgress(); renderSemesters(); }
  catch (error) { if (state.dirty) renderLocalNotice(); else feedback(error.message, "error"); }
}

function renderLocalNotice() { byId("degree-programme").textContent = "Save the current edits to recalculate source-driven progress."; }

function renderProgress() {
  const value = state.progress; byId("degree-programme").textContent = `${value.programme.name} · admission ${value.programme.admission_batch} · revision ${value.programme.revision_code}`;
  const totals = value.totals; byId("degree-totals").replaceChildren(fact("Earned", credit(totals.earned_milli)), fact("Enrolled", credit(totals.enrolled_milli)), fact("Planned", credit(totals.planned_milli)), fact("Confirmed remaining", credit(totals.remaining_confirmed_milli)), fact("Unknown records", totals.unknown_record_count));
  byId("degree-category-body").replaceChildren(...value.categories.map((row) => { const tr = document.createElement("tr"); tr.append(textElement("td", `${row.code} · ${row.name}`), textElement("td", credit(row.recorded_target_milli)), textElement("td", credit(row.earned_milli)), textElement("td", credit(row.enrolled_milli)), textElement("td", credit(row.planned_milli)), textElement("td", row.projected_remaining_milli == null ? "Pending" : credit(row.projected_remaining_milli)), textElement("td", row.status)); return tr; }));
  byId("degree-warnings").replaceChildren(...value.warnings.map((warning) => textElement("li", warning.message)), textElement("li", "NC accounting remains pending classification; no official graduation-complete claim is made."));
}

async function loadRecommendations() {
  try { const result = await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/recommendations?semester=${byId("degree-semester").value}`); const target = byId("degree-recommendations"); target.replaceChildren(...result.items.slice(0, 20).map((item) => { const card = document.createElement("article"); card.className = "scenario-card"; card.append(textElement("h3", `${item.course.course_code} · ${item.course.course_title}`), textElement("p", item.reason), textElement("p", item.scheduleable ? "Matching imported offering available" : "Tentative only · offering unknown", item.scheduleable ? "provenance" : "muted")); return card; })); if (!result.items.length) target.replaceChildren(textElement("div", "No source-backed recommendations are available.", "empty-state compact")); }
  catch (error) { feedback(error.message, "error"); }
}

async function transferSemester() {
  const calendars = await api("/api/v1/calendars"); const calendar = calendars.items?.[0];
  if (!calendar) { feedback("Import a matching slot calendar before transferring a semester.", "warning"); return; }
  const semesterLabel = window.prompt("Exact imported offering semester label", state.active.document.semester_labels?.[byId("degree-semester").value] || ""); if (!semesterLabel) return;
  try { const preview = await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/semester-transfer/preview`, { method: "POST", json: { semester: Number(byId("degree-semester").value), campus: "Vellore", semester_label: semesterLabel, calendar_id: calendar.calendar_id, roles: {} } }); if (!preview.ready) { feedback(`Transfer blocked: ${preview.issues.map((item) => item.course_code || item.code).join(", ")}.`, "warning"); return; } const name = window.prompt("Name the timetable scenario", `${state.active.name} · semester ${byId("degree-semester").value}`); if (!name) return; const stored = await api(`/api/v1/degree/plans/${state.active.degree_plan_id}/semester-transfer/commit`, { method: "POST", json: { name, preview } }); feedback(`Created timetable scenario “${stored.name}”. Open Scenarios to review and solve it.`, "success"); }
  catch (error) { feedback(error.message, "error"); }
}

async function chooseFile(event) { state.file = event.target.files[0] || null; state.validationId = null; state.previewId = null; byId("degree-import-validate").disabled = !state.file; byId("degree-import-preview").disabled = true; byId("degree-import-commit").disabled = true; byId("degree-import-output").textContent = state.file ? `${state.file.name} · ${state.file.size} bytes` : "No source selected."; }
async function validateImport() { try { const documentValue = JSON.parse(await state.file.text()); const result = await api("/api/v1/degree/imports/validate", { method: "POST", json: { kind: byId("degree-import-kind").value, filename: state.file.name, source_sequence: Number(byId("degree-source-sequence").value), document: documentValue } }); state.validationId = result.validation_id; byId("degree-import-preview").disabled = false; output(result); } catch (error) { feedback(error.message, "error"); } }
async function previewImport() { try { const result = await api("/api/v1/degree/imports/preview", { method: "POST", json: { validation_id: state.validationId } }); state.previewId = result.preview_id; byId("degree-import-commit").disabled = false; output(result); } catch (error) { feedback(error.message, "error"); } }
async function commitImport() { if (!window.confirm("Commit this reviewed source atomically to the local database?")) return; try { const result = await api("/api/v1/degree/imports/commit", { method: "POST", json: { preview_id: state.previewId } }); output(result); await refresh(); feedback(result.duplicate ? "This exact source was already imported; no duplicate was created." : "Degree source committed with original provenance.", "success"); } catch (error) { feedback(error.message, "error"); } }
async function runRecovery() { try { const payload = JSON.parse(byId("degree-recovery-input").value); const result = await api("/api/v1/recovery/scenarios", { method: "POST", json: payload }); byId("degree-recovery-output").textContent = JSON.stringify(result, null, 2); feedback(result.proven_minimum ? "Recovery completed with a proven minimum-disruption score." : "Recovery was resource-limited; results are best found so far.", result.proven_minimum ? "success" : "warning"); } catch (error) { feedback(error.message, "error"); } }
async function saveAvailability() { try { const revision = Number(byId("degree-availability-revision").value); const allocation = Number(byId("degree-availability-allocation").value); if (!revision || !allocation || !byId("degree-availability-semester").value.trim()) throw new Error("Semester label, revision ID, and allocation ID are required."); await api("/api/v1/recovery/availability", { method: "POST", json: { campus: byId("degree-availability-campus").value.trim(), semester_label: byId("degree-availability-semester").value.trim(), offering_revision_id: revision, allocation_id: allocation, state: byId("degree-availability-state").value, provenance: "manual", note: byId("degree-availability-note").value.trim(), captured_at: new Date().toISOString() } }); await refreshAvailability(); feedback("Recorded a local manual state. It is not real-time VTOP evidence.", "success"); } catch (error) { feedback(error.message, "error"); } }
async function refreshAvailability() { try { const params = new URLSearchParams({ campus: byId("degree-availability-campus").value.trim(), semester_label: byId("degree-availability-semester").value.trim() }); const result = await api(`/api/v1/recovery/availability?${params}`); const target = byId("degree-availability-list"); target.replaceChildren(...result.items.slice(0, 30).map((item) => { const row = document.createElement("article"); row.className = "scenario-card"; row.append(textElement("strong", `Allocation ${item.allocation_id} · ${item.state}`), textElement("p", `Revision ${item.offering_revision_id} · ${new Date(item.captured_at).toLocaleString()} · ${item.provenance}`), textElement("p", item.note || "No note", "muted")); const clear = textElement("button", "Clear current state", "ghost"); clear.addEventListener("click", async () => { await api(`/api/v1/recovery/availability/${item.availability_id}/clear`, { method: "POST", json: {} }); await refreshAvailability(); }); row.append(clear); return row; })); if (!result.items.length) target.replaceChildren(textElement("div", "No active manual states for this scope.", "empty-state compact")); } catch (error) { feedback(error.message, "error"); } }

function dirty(message) { state.dirty = true; byId("degree-revision").textContent = `${state.active.name} · unsaved edits`; byId("degree-programme").textContent = "Save to recompute authoritative progress."; feedback(message, "warning"); }
function output(value) { byId("degree-import-output").textContent = JSON.stringify(value, null, 2); }
function fact(label, value) { const item = document.createElement("div"); item.append(textElement("dt", label), textElement("dd", String(value))); return item; }
function cell(child) { const td = document.createElement("td"); td.append(child); return td; }
function emptyRow(colspan, message) { const row = document.createElement("tr"); const td = textElement("td", message, "empty-cell"); td.colSpan = colspan; row.append(td); return row; }
function credit(value) { if (value == null) return "Unknown"; return `${Number(value / 1000).toLocaleString(undefined, { maximumFractionDigits: 3 })}`; }
function semesterCategories(row) { const values = new Map(); for (const [key, value] of Object.entries(row)) { const match = key.match(/^category_(.+)_(earned|enrolled|planned)_milli$/); if (match && value) values.set(match[1], (values.get(match[1]) || 0) + value); } return [...values.entries()].map(([category, value]) => `${category} ${credit(value)}`).join(" · "); }
function feedback(message, style = "") { byId("degree-feedback").textContent = message; byId("degree-feedback").className = `feedback ${style}`; }
function byId(id) { return document.getElementById(id); }
