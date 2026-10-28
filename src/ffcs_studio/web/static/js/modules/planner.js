import { api, downloadObject, option, textElement } from "../api.js";
import { workspace } from "../state.js";
import { clock, renderTimetable } from "./timetable-grid.js";

let editorOfferingId = null;
let pendingSavedResult = null;

export function initPlanner() {
  byId("solver-load-courses").addEventListener("click", loadCatalog);
  byId("solver-semester").addEventListener("change", changeSemester);
  byId("solver-calendar").addEventListener("change", () => editValue("calendar_id", byId("solver-calendar").value || null, "Change calendar"));
  byId("solver-campus").addEventListener("change", () => editValue("campus", byId("solver-campus").value.trim(), "Change campus"));
  byId("solver-mode").addEventListener("change", () => editValue("mode", byId("solver-mode").value, "Change evaluation mode"));
  byId("planner-course-search").addEventListener("input", renderCourseList);
  byId("reset-course-roles").addEventListener("click", () => workspace.edit((documentValue) => { documentValue.courses = []; }, "Reset course roles"));
  byId("select-visible-optional").addEventListener("click", selectVisibleOptional);
  byId("close-course-editor").addEventListener("click", closeEditor);
  byId("undo-button").addEventListener("click", () => workspace.undo());
  byId("redo-button").addEventListener("click", () => workspace.redo());
  byId("solver-validate").addEventListener("click", validateScenario);
  byId("solver-start").addEventListener("click", startSearch);
  byId("solver-cancel").addEventListener("click", cancelSearch);
  byId("solver-count").addEventListener("click", startCount);
  byId("solver-cancel-count").addEventListener("click", cancelCount);
  byId("result-previous").addEventListener("click", () => loadResultPage(workspace.resultPage - 1));
  byId("result-next").addEventListener("click", () => loadResultPage(workspace.resultPage + 1));
  byId("result-local-sort").addEventListener("change", renderResults);
  byId("clear-comparison").addEventListener("click", () => { workspace.comparison = []; renderComparison(); renderResults(); });
  byId("print-timetable").addEventListener("click", () => window.print());
  byId("lock-result").addEventListener("click", openLockDialog);
  byId("apply-locks").addEventListener("click", applyLocks);
  byId("result-form").addEventListener("submit", submitSavedResult);
  bindSettings();
  workspace.addEventListener("sources-changed", (event) => populateSources(event.detail));
  workspace.addEventListener("document-changed", syncFromDocument);
  workspace.addEventListener("scenario-saved", () => { updateToolbar(); renderResults(); });
  workspace.addEventListener("select-offering", (event) => selectOfferingFromExplorer(event.detail));
  workspace.addEventListener("display-result", (event) => displayExternalResult(event.detail));
  workspace.addEventListener("compare-saved-results", (event) => displaySavedComparison(event.detail));
  workspace.addEventListener("load-active-catalog", loadCatalog);
  syncFromDocument();
}

function populateSources({ semesters, calendars }) {
  const semester = byId("solver-semester"); const selected = `${workspace.document.campus}\u001f${workspace.document.semester_label}`;
  semester.replaceChildren(option("", semesters.length ? "Select a semester" : "No imported semesters"));
  for (const item of semesters) semester.append(option(`${item.campus}\u001f${item.semester_label}`, `${item.semester_label} — ${item.campus} (${item.offering_count})`));
  if ([...semester.options].some((item) => item.value === selected)) semester.value = selected;
  filterCalendars(calendars);
}

function filterCalendars(calendars = workspace.calendars) {
  const select = byId("solver-calendar"); const matches = calendars.filter((item) => item.campus === workspace.document.campus && item.semester_label === workspace.document.semester_label);
  select.replaceChildren(option("", matches.length ? "Select matching calendar" : "No exact matching calendar"));
  for (const item of matches) select.append(option(item.calendar_id, `${item.profile_name} v${item.version} [${item.verification_status}]${item.active ? " · active" : ""}`));
  if (matches.some((item) => item.calendar_id === workspace.document.calendar_id)) select.value = workspace.document.calendar_id;
  else select.value = "";
}

function changeSemester(event) {
  const [campus = "", semester = ""] = event.target.value.split("\u001f");
  if (workspace.dirty && workspace.document.semester_label && semester !== workspace.document.semester_label && !window.confirm("Switch semester and clear the current unsaved course selection?")) { event.target.value = `${workspace.document.campus}\u001f${workspace.document.semester_label}`; return; }
  workspace.edit((documentValue) => { documentValue.campus = campus; documentValue.semester_label = semester; documentValue.calendar_id = null; documentValue.courses = []; }, "Switch semester");
  workspace.catalog = []; workspace.details.clear(); filterCalendars(); renderCourseList();
}

async function loadCatalog() {
  const { campus, semester_label: semester } = workspace.document;
  if (!campus || !semester) return feedback("Select an imported semester first.", "error");
  const items = []; let page = 1; let total = 0;
  try {
    do { const result = await api(`/api/v1/offerings?${new URLSearchParams({ campus, semester_label: semester, page, page_size: 100 })}`); items.push(...result.items); total = result.total; page += 1; } while (items.length < total);
    workspace.catalog = items; renderCourseList(); feedback(`Loaded ${items.length} active offering(s) from SQLite.`, items.length ? "success" : "warning");
  } catch (error) { feedback(error.message, "error"); }
}

function renderCourseList() {
  const term = byId("planner-course-search").value.trim().toLocaleLowerCase();
  const visible = workspace.catalog.filter((item) => !term || `${item.course_code} ${item.course_title} ${item.category}`.toLocaleLowerCase().includes(term));
  const target = byId("planner-course-list");
  if (!visible.length) { target.replaceChildren(emptyState(workspace.catalog.length ? "No courses match the search." : "Load a semester to see courses.")); return; }
  target.replaceChildren(...visible.map((item) => {
    const state = courseState(item.offering_id); const card = document.createElement("article"); card.className = `course-card${editorOfferingId === item.offering_id ? " selected" : ""}`;
    const title = textElement("h3", item.course_code); const detail = textElement("p", item.course_title); const meta = textElement("p", `${item.category} · ${item.allocation_count} source row(s) · ${item.component_types.join("/") || "type unknown"}`);
    const roles = document.createElement("div"); roles.className = "role-switch";
    for (const [role, label] of [["required", "Must take"], ["optional", "Preferred"], ["excluded", "Excluded"]]) { const button = textElement("button", label, state.role === role ? "active" : ""); button.type = "button"; button.setAttribute("aria-pressed", String(state.role === role)); button.addEventListener("click", (event) => { event.stopPropagation(); setCourseRole(item, role); }); roles.append(button); }
    card.append(title, detail, meta, roles); card.tabIndex = 0; card.addEventListener("click", () => openCourseEditor(item)); card.addEventListener("keydown", (event) => { if (event.key === "Enter") openCourseEditor(item); }); return card;
  }));
}

function courseState(offeringId) {
  return workspace.document.courses.find((item) => item.offering_id === Number(offeringId)) || { offering_id: Number(offeringId), source_revision_id: null, role: "excluded", curriculum_type: "unknown", curriculum_source: "unknown", credits: null, credit_source: "unknown", priority_tier: 1, locked_allocation_ids: [], locked_faculties: [], forbidden_allocation_ids: [], forbidden_faculties: [] };
}

function setCourseRole(item, role) {
  workspace.edit((documentValue) => {
    let course = documentValue.courses.find((entry) => entry.offering_id === item.offering_id);
    if (!course) { course = courseState(item.offering_id); documentValue.courses.push(course); }
    course.role = role;
  }, `Set ${item.course_code} role`);
  ensureDetail(item.offering_id); renderCourseList();
}

function selectVisibleOptional() {
  const term = byId("planner-course-search").value.trim().toLocaleLowerCase();
  const ids = new Set(workspace.catalog.filter((item) => !term || `${item.course_code} ${item.course_title}`.toLocaleLowerCase().includes(term)).map((item) => item.offering_id));
  workspace.edit((documentValue) => { for (const item of workspace.catalog.filter((entry) => ids.has(entry.offering_id))) { let course = documentValue.courses.find((entry) => entry.offering_id === item.offering_id); if (!course) { course = courseState(item.offering_id); documentValue.courses.push(course); } course.role = "optional"; } }, "Mark visible courses optional");
}

async function openCourseEditor(item) {
  editorOfferingId = item.offering_id; renderCourseList(); byId("course-editor").hidden = false; byId("course-editor-title").textContent = `${item.course_code} — ${item.course_title}`;
  byId("course-editor-content").replaceChildren(textElement("p", "Loading exact source allocations…", "muted"));
  try { const detail = await ensureDetail(item.offering_id); renderCourseEditor(item, detail); } catch (error) { byId("course-editor-content").replaceChildren(textElement("p", error.message, "error-text")); }
}

async function ensureDetail(offeringId) {
  if (!workspace.details.has(offeringId)) {
    const [detail, allocations, candidates] = await Promise.all([api(`/api/v1/offerings/${offeringId}`), api(`/api/v1/offerings/${offeringId}/allocations`), api(`/api/v1/offerings/${offeringId}/registration-options`)]);
    workspace.details.set(offeringId, { detail, allocations: allocations.items, candidates: candidates.items });
  }
  const stored = workspace.details.get(offeringId); const state = workspace.document.courses.find((entry) => entry.offering_id === offeringId);
  if (state && !state.source_revision_id) state.source_revision_id = stored.detail.revision_id;
  return stored;
}

function renderCourseEditor(item, source) {
  const state = courseState(item.offering_id); const content = byId("course-editor-content"); content.replaceChildren();
  const metadata = document.createElement("div"); metadata.className = "form-grid";
  metadata.append(labeledSelect("Curriculum type", state.curriculum_type, ["unknown", "TH", "ETL", "ETP", "LO", "ELJ", "PJ", "SS"], (value) => updateCourse(item, (course) => { course.curriculum_type = value; }, "Change curriculum type")), labeledSelect("Type source", state.curriculum_source, ["unknown", "user_supplied", "verified"], (value) => updateCourse(item, (course) => { course.curriculum_source = value; }, "Change type provenance")), labeledInput("Credits", state.credits ?? "", "number", (value) => updateCourse(item, (course) => { course.credits = value || null; }, "Change credits")), labeledSelect("Credit source", state.credit_source, ["unknown", "user_supplied", "verified"], (value) => updateCourse(item, (course) => { course.credit_source = value; }, "Change credit provenance")), labeledInput("Priority tier", state.priority_tier, "number", (value) => updateCourse(item, (course) => { course.priority_tier = Math.max(1, Number(value) || 1); }, "Change priority")));
  content.append(metadata, textElement("h4", "Faculty rules"));
  const faculties = [...new Set(source.allocations.map((row) => row.faculty).filter(Boolean))];
  for (const faculty of faculties) {
    let value = "none"; if (state.locked_faculties.includes(faculty)) value = "require"; else if (state.forbidden_faculties.includes(faculty)) value = "exclude"; else if (workspace.document.ranking.preferred_faculties.includes(faculty)) value = "prefer";
    content.append(labeledSelect(faculty, value, [["none", "No rule"], ["prefer", "Prefer (soft)"], ["require", "Require (hard)"], ["exclude", "Exclude (hard)"]], (selected) => updateFaculty(item, faculty, selected)));
  }
  content.append(textElement("h4", "Source allocations"));
  for (const allocation of source.allocations) {
    const wrapper = document.createElement("div"); wrapper.className = "allocation-option";
    wrapper.append(textElement("strong", `${allocation.course_type} · ${allocation.faculty}`), textElement("p", `${allocation.slot} · ${allocation.venue} · allocation #${allocation.allocation_id}`));
    let value = "allow"; if (state.locked_allocation_ids.includes(allocation.allocation_id)) value = "lock"; if (state.forbidden_allocation_ids.includes(allocation.allocation_id)) value = "exclude";
    wrapper.append(labeledSelect("Rule", value, [["allow", "Allowed"], ["lock", "Lock this allocation"], ["exclude", "Exclude this allocation"]], (selected) => updateAllocation(item, allocation.allocation_id, selected))); content.append(wrapper);
  }
  content.append(textElement("h4", "Eligible complete component combinations"));
  const list = document.createElement("ul"); list.className = "issue-list";
  for (const candidate of source.candidates) list.append(textElement("li", `${candidate.status}: ${candidate.allocations.map((row) => `${row.course_type} ${row.faculty} · ${row.slot} (#${row.allocation_id})`).join(" + ") || "No combination"}. ${candidate.reasons.join("; ")}`));
  content.append(list, textElement("p", `Source revision ${source.detail.revision_id}. Same-name faculty rows remain distinct allocations.`, "source-note"));
}

function updateCourse(item, mutator, label) { workspace.edit((documentValue) => { let course = documentValue.courses.find((entry) => entry.offering_id === item.offering_id); if (!course) { course = courseState(item.offering_id); documentValue.courses.push(course); } mutator(course); }, `${label}: ${item.course_code}`); }
function updateFaculty(item, faculty, rule) { workspace.edit((documentValue) => { let course = documentValue.courses.find((entry) => entry.offering_id === item.offering_id); if (!course) { course = courseState(item.offering_id); documentValue.courses.push(course); } course.locked_faculties = course.locked_faculties.filter((value) => value !== faculty); course.forbidden_faculties = course.forbidden_faculties.filter((value) => value !== faculty); documentValue.ranking.preferred_faculties = documentValue.ranking.preferred_faculties.filter((value) => value !== faculty); if (rule === "require") course.locked_faculties.push(faculty); if (rule === "exclude") course.forbidden_faculties.push(faculty); if (rule === "prefer") documentValue.ranking.preferred_faculties.push(faculty); }, `Set faculty rule for ${item.course_code}`); }
function updateAllocation(item, allocationId, rule) { workspace.edit((documentValue) => { let course = documentValue.courses.find((entry) => entry.offering_id === item.offering_id); if (!course) { course = courseState(item.offering_id); documentValue.courses.push(course); } course.locked_allocation_ids = course.locked_allocation_ids.filter((value) => value !== allocationId); course.forbidden_allocation_ids = course.forbidden_allocation_ids.filter((value) => value !== allocationId); if (rule === "lock") course.locked_allocation_ids.push(allocationId); if (rule === "exclude") course.forbidden_allocation_ids.push(allocationId); }, `Set allocation rule for ${item.course_code}`); }

function bindSettings() {
  const simple = [
    ["solver-min-credits", (doc, value) => { doc.credit_constraints.minimum = value || null; }, "minimum credits"], ["solver-target-credits", (doc, value) => { doc.credit_constraints.target = value || null; }, "target credits"], ["solver-max-credits", (doc, value) => { doc.credit_constraints.maximum = value || null; }, "maximum credits"], ["solver-top-k", (doc, value) => { doc.top_k = Number(value); }, "top K"], ["solver-node-budget", (doc, value) => { doc.max_search_nodes = Number(value); }, "node budget"],
    ["solver-morning", (doc, value) => { doc.ranking.prefer_morning_theory = value; }, "morning preference", true], ["solver-evening", (doc, value) => { doc.ranking.prefer_evening_theory = value; }, "evening preference", true], ["solver-min-labs", (doc, value) => { doc.ranking.minimize_labs = value; }, "lab preference", true], ["solver-min-days", (doc, value) => { doc.ranking.minimize_campus_days = value; }, "campus-day preference", true],
    ["solver-allow-calendar", (doc, value) => { doc.provisional_policy.allow_unverified_calendar = value; }, "calendar assumption", true], ["solver-allow-metadata", (doc, value) => { doc.provisional_policy.allow_user_supplied_metadata = value; }, "metadata assumption", true], ["solver-allow-provisional", (doc, value) => { doc.provisional_policy.allow_provisional_pairing = value; }, "pairing assumption", true], ["solver-same-faculty", (doc, value) => { doc.provisional_policy.allow_same_faculty_pairing = value; }, "same-faculty assumption", true], ["solver-unknown-pairing", (doc, value) => { doc.provisional_policy.allow_unknown_pairing = value; }, "unknown-pairing assumption", true],
  ];
  for (const [id, setter, label, checked] of simple) byId(id).addEventListener("change", (event) => workspace.edit((doc) => setter(doc, checked ? event.target.checked : event.target.value), `Change ${label}`));
  byId("solver-preferred-faculty").addEventListener("change", (event) => workspace.edit((doc) => { doc.ranking.preferred_faculties = textList(event.target.value); }, "Edit preferred faculty"));
  byId("solver-avoid-late").addEventListener("change", (event) => workspace.edit((doc) => { doc.ranking.avoid_late_after_minute = timeMinute(event.target.value); }, "Edit late cutoff"));
  byId("solver-occupied").addEventListener("change", (event) => { try { const periods = parseOccupied(event.target.value); workspace.edit((doc) => { doc.occupied_intervals = periods; }, "Edit occupied periods"); } catch (error) { feedback(error.message, "error"); } });
}

function syncFromDocument() {
  const doc = workspace.document; byId("solver-campus").value = doc.campus || ""; byId("solver-mode").value = doc.mode;
  const semesterValue = `${doc.campus}\u001f${doc.semester_label}`; byId("solver-semester").value = [...byId("solver-semester").options].some((item) => item.value === semesterValue) ? semesterValue : "";
  filterCalendars(); if (doc.calendar_id) byId("solver-calendar").value = doc.calendar_id;
  byId("solver-min-credits").value = doc.credit_constraints.minimum ?? ""; byId("solver-target-credits").value = doc.credit_constraints.target ?? ""; byId("solver-max-credits").value = doc.credit_constraints.maximum ?? ""; byId("solver-top-k").value = doc.top_k; byId("solver-node-budget").value = doc.max_search_nodes ?? 2000000;
  byId("solver-preferred-faculty").value = doc.ranking.preferred_faculties.join(", "); byId("solver-avoid-late").value = minuteTime(doc.ranking.avoid_late_after_minute); byId("solver-morning").checked = doc.ranking.prefer_morning_theory; byId("solver-evening").checked = doc.ranking.prefer_evening_theory; byId("solver-min-labs").checked = doc.ranking.minimize_labs; byId("solver-min-days").checked = doc.ranking.minimize_campus_days;
  byId("solver-allow-calendar").checked = doc.provisional_policy.allow_unverified_calendar; byId("solver-allow-metadata").checked = doc.provisional_policy.allow_user_supplied_metadata; byId("solver-allow-provisional").checked = doc.provisional_policy.allow_provisional_pairing; byId("solver-same-faculty").checked = doc.provisional_policy.allow_same_faculty_pairing; byId("solver-unknown-pairing").checked = doc.provisional_policy.allow_unknown_pairing;
  byId("solver-occupied").value = doc.occupied_intervals.map((item) => `${item.day},${item.start_minute},${item.end_minute},${item.label}`).join("\n");
  updateToolbar(); renderCourseList(); updateOverview();
  if (editorOfferingId) { const item = workspace.catalog.find((entry) => entry.offering_id === editorOfferingId); const detail = workspace.details.get(editorOfferingId); if (item && detail) renderCourseEditor(item, detail); }
}

function updateToolbar() { byId("dirty-indicator").textContent = workspace.dirty ? "Unsaved changes" : workspace.activeScenario ? `Saved · revision ${workspace.activeScenario.current_revision}` : "Unsaved draft"; byId("dirty-indicator").className = `state-pill ${workspace.dirty ? "warning" : "success"}`; byId("undo-button").disabled = !workspace.undoStack.length; byId("redo-button").disabled = !workspace.redoStack.length; }

async function selectOfferingFromExplorer(offeringId) { if (!offeringId) return; const detail = await api(`/api/v1/offerings/${offeringId}`); const semesterValue = `${detail.campus}\u001f${detail.semester_label}`; if (workspace.document.semester_label !== detail.semester_label) { workspace.edit((doc) => { doc.campus = detail.campus; doc.semester_label = detail.semester_label; doc.calendar_id = null; doc.courses = []; }, "Select course semester"); if ([...byId("solver-semester").options].some((item) => item.value === semesterValue)) byId("solver-semester").value = semesterValue; await loadCatalog(); } const item = workspace.catalog.find((entry) => entry.offering_id === offeringId); if (item) { setCourseRole(item, "optional"); openCourseEditor(item); } }

async function validateScenario() { try { await ensureSelectedDetails(); const result = await api("/api/v1/solver/scenarios/validate", { method: "POST", json: solverPayload() }); if (result.valid) { byId("solver-state").textContent = result.assumptions.length ? "Exploratory ready" : "Verified ready"; feedback(`Ready: ${result.course_count} course(s), ${result.candidate_count} complete option(s).${result.assumptions.length ? ` Assumptions: ${result.assumptions.join("; ")}` : ""}`, result.assumptions.length ? "warning" : "success"); } else feedback(`Blocked: ${result.issues.map((item) => item.message).join("; ")}`, "error"); } catch (error) { feedback(error.message, "error"); } }

async function startSearch() {
  if (workspace.activeJob && ["queued", "running", "cancellation_requested"].includes(workspace.activeJob.status)) { if (!window.confirm("A search is still active. Cancel it before starting a new search?")) return; await cancelSearch(); }
  try {
    await ensureSelectedDetails(); const generation = ++workspace.pollGeneration; workspace.results.clear(); workspace.resultOrder = []; workspace.selectedResultId = null; renderTimetable(null, inspectMeeting); renderResults();
    const created = await api("/api/v1/solver/jobs", { method: "POST", json: solverPayload() }); workspace.activeJob = { id: created.job_id, status: created.status, generation };
    byId("solver-cancel").disabled = false; byId("solver-count").disabled = true; feedback(`Search ${created.job_id.slice(0, 8)} started from snapshot ${created.scenario_fingerprint.slice(0, 12)}.`, "success"); pollSearch(generation);
  } catch (error) { const issues = error.payload?.issues?.map((item) => item.message).join("; "); feedback(issues || error.message, "error"); }
}

async function pollSearch(generation) {
  if (!workspace.activeJob || generation !== workspace.pollGeneration) return;
  try {
    const status = await api(`/api/v1/solver/jobs/${workspace.activeJob.id}`); if (generation !== workspace.pollGeneration) return;
    workspace.activeJob.status = status.status; byId("solver-state").textContent = status.status.replaceAll("_", " "); byId("solver-progress").hidden = false; byId("solver-progress").textContent = `Nodes ${status.progress.nodes_visited || 0}; pruned ${status.progress.branches_pruned || 0}; feasible ${status.progress.feasible_solutions_seen || 0}.`;
    if (["queued", "running", "cancellation_requested"].includes(status.status)) { window.setTimeout(() => pollSearch(generation), 500); return; }
    byId("solver-cancel").disabled = true; byId("solver-count").disabled = status.status === "failed"; await loadResultPage(1);
    const messages = { exhausted: "Exhaustive search complete. Solver ranks are globally valid.", infeasible: "No complete timetable satisfies every hard constraint.", cancelled: "Search cancelled. Results are best found so far only.", resource_limit: "Node budget reached. Results are best found so far, not globally optimal.", failed: "The solver worker failed safely." };
    feedback(messages[status.status] || `Search ended: ${status.status}.`, ["exhausted"].includes(status.status) ? "success" : status.status === "failed" ? "error" : "warning");
  } catch (error) { if (error.status === 404) { workspace.activeJob = null; feedback("The in-memory solver job is no longer available. Saved scenarios and timetables are unaffected.", "warning"); } else feedback(error.message, "error"); }
}

async function loadResultPage(page) {
  if (!workspace.activeJob) return; const result = await api(`/api/v1/solver/jobs/${workspace.activeJob.id}/results?page=${page}&page_size=${workspace.resultPageSize}`);
  workspace.resultPage = result.page; workspace.resultTotal = result.total;
  for (const item of result.items) workspace.results.set(item.result_id, item);
  workspace.resultOrder = result.items.map((item) => item.result_id); renderResults();
  byId("result-pagination").hidden = result.total <= workspace.resultPageSize; byId("result-page-label").textContent = `Page ${result.page} · ${result.total} retained result(s)`; byId("result-previous").disabled = result.page <= 1; byId("result-next").disabled = result.page * result.page_size >= result.total;
}

function renderResults() {
  const target = byId("solver-results"); let results = workspace.resultOrder.map((id) => workspace.results.get(id)).filter(Boolean); const sort = byId("result-local-sort").value;
  if (sort !== "rank") { const key = { gaps: "interclass_gap_minutes", days: "campus_days", labs: "physical_lab_sessions" }[sort]; results = [...results].sort((a, b) => a.metrics[key] - b.metrics[key] || a.result_id.localeCompare(b.result_id)); }
  if (!results.length) { target.replaceChildren(emptyState("No results loaded.")); return; }
  target.replaceChildren(...results.map((result) => {
    const rank = (workspace.resultPage - 1) * workspace.resultPageSize + workspace.resultOrder.indexOf(result.result_id) + 1; const card = document.createElement("article"); card.className = `result-card${workspace.selectedResultId === result.result_id ? " selected" : ""}`;
    card.append(textElement("h3", `#${rank} · ${result.selected_courses.length} course(s)`), textElement("p", `${result.metrics.total_credits ?? "Unknown"} credits · ${result.verification_status}`));
    const metrics = document.createElement("div"); metrics.className = "result-metrics"; for (const value of [`${result.metrics.physical_lab_sessions} labs`, `${result.metrics.lab_minutes} lab min`, `${result.metrics.campus_days} days`, `${result.metrics.total_contact_minutes} contact min`, `${result.metrics.interclass_gap_minutes} gap min`]) metrics.append(textElement("span", value)); card.append(metrics, textElement("p", result.explanation[1] || result.explanation[0]));
    if (result.assumptions.length) { const list = document.createElement("ul"); list.className = "assumption-list"; for (const item of result.assumptions) list.append(textElement("li", item)); card.append(list); }
    const actions = document.createElement("div"); actions.className = "scenario-card-actions"; const view = textElement("button", "View", "secondary"); view.addEventListener("click", () => selectResult(result));
    const compareLabel = document.createElement("label"); compareLabel.className = "inline-check"; const compare = document.createElement("input"); compare.type = "checkbox"; compare.checked = workspace.comparison.includes(result.result_id); compare.disabled = !compare.checked && workspace.comparison.length >= 3; compare.addEventListener("change", () => toggleCompare(result.result_id)); compareLabel.append(compare, " Compare");
    const save = textElement("button", "Save", "ghost"); save.disabled = !workspace.activeScenario || !workspace.activeJob; save.title = workspace.activeJob ? "Save immutable timetable snapshot" : "Generate this scenario before saving a new snapshot"; save.addEventListener("click", () => saveResult(result));
    const jsonButton = textElement("button", "JSON", "ghost"); jsonButton.addEventListener("click", () => downloadObject({ export_schema_version: "1.0", kind: "ffcs-studio-generated-timetable", scenario_fingerprint: workspace.activeJob?.id, result }, `ffcs-timetable-${result.result_id}.json`));
    const csvButton = textElement("button", "CSV", "ghost"); csvButton.addEventListener("click", () => downloadResultCsv(result)); actions.append(view, compareLabel, save, jsonButton, csvButton); card.append(actions); return card;
  }));
}

function selectResult(result) { workspace.selectedResultId = result.result_id; renderTimetable(result, inspectMeeting); byId("selected-result-label").textContent = `${result.selected_courses.join(", ")} · ${result.verification_status}`; byId("print-timetable").disabled = false; byId("lock-result").disabled = false; renderResults(); }
function displayExternalResult(detail) { workspace.results.set(detail.result.result_id, detail.result); workspace.resultOrder = [detail.result.result_id]; workspace.resultPage = 1; workspace.resultTotal = 1; selectResult(detail.result); location.hash = "planner"; feedback(`Opened saved historical result “${detail.name}”. Compatibility is shown with the saved record.`, detail.compatibility?.length ? "warning" : "success"); }
function displaySavedComparison(savedItems) {
  workspace.results.clear(); workspace.resultOrder = []; workspace.comparison = [];
  for (const saved of savedItems) { const result = structuredClone(saved.result); result.result_id = saved.saved_result_id; workspace.results.set(result.result_id, result); workspace.resultOrder.push(result.result_id); workspace.comparison.push(result.result_id); }
  workspace.resultPage = 1; workspace.resultTotal = savedItems.length; location.hash = "planner"; selectResult(workspace.results.get(workspace.resultOrder[0])); renderComparison(); feedback(`Comparing ${savedItems.length} immutable historical timetable snapshots.`, savedItems.some((item) => item.compatibility?.length) ? "warning" : "success");
}
function inspectMeeting(meeting) { const panel = byId("meeting-inspector"); panel.hidden = false; panel.textContent = `${meeting.course_code} · ${meeting.component_type} · ${meeting.day_name} ${meeting.start_time}–${meeting.end_time} · ${meeting.faculty || "Faculty not supplied"} · ${meeting.venue || "Venue not supplied"} · slot ${meeting.slot} · allocation #${meeting.allocation_id}${meeting.session_id ? ` · session ${meeting.session_id}` : ""}`; }

function toggleCompare(resultId) { const index = workspace.comparison.indexOf(resultId); if (index >= 0) workspace.comparison.splice(index, 1); else if (workspace.comparison.length < 3) workspace.comparison.push(resultId); renderComparison(); renderResults(); }
function renderComparison() {
  const panel = byId("comparison-panel"); const results = workspace.comparison.map((id) => workspace.results.get(id)).filter(Boolean); panel.hidden = results.length < 2; if (results.length < 2) return;
  const table = document.createElement("table"); table.className = "comparison-table"; const head = document.createElement("tr"); head.append(textElement("th", "Measure"), ...results.map((item) => textElement("th", item.result_id.slice(0, 8)))); table.append(head);
  const rows = [["Courses", (r) => r.selected_courses.join(", ")], ["Credits", (r) => r.metrics.total_credits ?? "Unknown"], ["Faculty / sections", (r) => r.assignments.map((a) => `${a.course_code}: ${a.meetings.map((m) => `${m.faculty} ${m.slot}`).join(" + ")}`).join("; ")], ["Labs", (r) => `${r.metrics.physical_lab_sessions} / ${r.metrics.lab_minutes} min`], ["Campus days", (r) => r.metrics.campus_days], ["Contact time", (r) => `${r.metrics.total_contact_minutes} min`], ["Gaps", (r) => `${r.metrics.interclass_gap_minutes} min`], ["Start / finish", (r) => r.metrics.daily_spans.map((s) => `${s.day_name} ${s.start_time}–${s.end_time}`).join("; ")], ["Assumptions", (r) => r.assumptions.join("; ") || "None"]];
  for (const [label, getter] of rows) { const row = document.createElement("tr"); const values = results.map(getter); row.append(textElement("td", label), ...values.map((value) => textElement("td", String(value), new Set(values.map(String)).size > 1 ? "difference" : ""))); table.append(row); }
  byId("comparison-content").replaceChildren(table); panel.scrollIntoView({ block: "nearest" });
}

function openLockDialog() { const result = workspace.results.get(workspace.selectedResultId); if (!result) return; const target = byId("lock-options"); target.replaceChildren(...result.assignments.map((assignment) => { const label = document.createElement("label"); label.className = "allocation-option inline-check"; const check = document.createElement("input"); check.type = "checkbox"; check.checked = true; check.dataset.offeringId = assignment.offering_id; check.dataset.allocationIds = assignment.allocation_ids.join(","); label.append(check, `${assignment.course_code}: ${assignment.meetings.map((m) => `${m.component_type} ${m.faculty} ${m.slot}`).join(" + ")}`); return label; })); byId("lock-dialog").showModal(); }
function applyLocks() { const selected = [...byId("lock-options").querySelectorAll("input:checked")]; workspace.edit((doc) => { for (const input of selected) { const course = doc.courses.find((item) => item.offering_id === Number(input.dataset.offeringId)); if (course) course.locked_allocation_ids = input.dataset.allocationIds.split(",").filter(Boolean).map(Number); } }, "Lock selected timetable assignments"); feedback(`Applied hard allocation locks for ${selected.length} selected course(s). Review and generate again.`, "success"); }

function saveResult(result) {
  if (!workspace.activeScenario || !workspace.activeJob) return;
  pendingSavedResult = result;
  byId("result-name").value = `Timetable ${result.result_id.slice(0, 8)}`;
  byId("result-dialog-status").textContent = "Stored only in the local FFCS Studio database.";
  byId("result-dialog-status").className = "feedback";
  byId("result-dialog").showModal();
  byId("result-name").focus();
}

async function submitSavedResult(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") { pendingSavedResult = null; byId("result-dialog").close(); return; }
  const name = byId("result-name").value.trim();
  if (!name || !pendingSavedResult || !workspace.activeScenario || !workspace.activeJob) return;
  byId("confirm-result-save").disabled = true;
  try {
    const saved = await api(`/api/v1/scenarios/${workspace.activeScenario.scenario_id}/results`, { method: "POST", json: { scenario_revision: workspace.activeScenario.current_revision, job_id: workspace.activeJob.id, solver_result_id: pendingSavedResult.result_id, name } });
    pendingSavedResult = null; byId("result-dialog").close(); feedback(`Saved immutable timetable “${saved.name}”.`, "success"); workspace.dispatchEvent(new CustomEvent("refresh-scenarios"));
  } catch (error) { byId("result-dialog-status").textContent = error.message; byId("result-dialog-status").className = "feedback error"; }
  finally { byId("confirm-result-save").disabled = false; }
}

async function cancelSearch() { if (!workspace.activeJob) return; ++workspace.pollGeneration; try { await api(`/api/v1/solver/jobs/${workspace.activeJob.id}/cancel`, { method: "POST", json: {} }); workspace.activeJob.status = "cancellation_requested"; feedback("Cancellation requested; the backend worker is stopping.", "warning"); const generation = workspace.pollGeneration; pollSearch(generation); } catch (error) { feedback(error.message, "error"); } }
async function startCount() { if (!workspace.activeJob) return; try { await api(`/api/v1/solver/jobs/${workspace.activeJob.id}/count`, { method: "POST", json: {} }); byId("solver-count").disabled = true; byId("solver-cancel-count").disabled = false; pollCount(workspace.pollGeneration); } catch (error) { feedback(error.message, "error"); } }
async function pollCount(generation) { if (!workspace.activeJob || generation !== workspace.pollGeneration) return; try { const status = await api(`/api/v1/solver/jobs/${workspace.activeJob.id}/count`); byId("solver-progress").textContent = `Exact count: ${status.status}; nodes ${status.progress.nodes_visited || 0}; pruned ${status.progress.branches_pruned || 0}.`; if (["pending", "running"].includes(status.status)) { window.setTimeout(() => pollCount(generation), 500); return; } byId("solver-cancel-count").disabled = true; feedback(status.status === "exact" ? `Exact feasible timetable count: ${status.result.exact_count}.` : `Exact count ${status.status}; no exact number is displayed.`, status.status === "exact" ? "success" : "warning"); } catch (error) { feedback(error.message, "error"); } }
async function cancelCount() { if (!workspace.activeJob) return; try { await api(`/api/v1/solver/jobs/${workspace.activeJob.id}/count/cancel`, { method: "POST", json: {} }); feedback("Exact-count cancellation requested.", "warning"); } catch (error) { feedback(error.message, "error"); } }

async function ensureSelectedDetails() { for (const course of workspace.document.courses.filter((item) => item.role !== "excluded")) await ensureDetail(course.offering_id); }
function solverPayload() { const payload = structuredClone(workspace.document); delete payload.schema_version; return payload; }
function editValue(key, value, label) { workspace.edit((doc) => { doc[key] = value; }, label); }
function closeEditor() { editorOfferingId = null; byId("course-editor").hidden = true; renderCourseList(); }
function updateOverview() { const doc = workspace.document; byId("header-semester").textContent = doc.semester_label || "No semester selected"; byId("overview-semester").textContent = doc.semester_label || "No semester selected"; byId("overview-scenario").textContent = workspace.activeScenario ? `${workspace.activeScenario.name} · revision ${workspace.activeScenario.current_revision}` : "No saved scenario is open."; byId("overview-course-count").textContent = workspace.catalog.length; const calendar = workspace.calendars.find((item) => item.calendar_id === doc.calendar_id); byId("overview-calendar").textContent = calendar ? `${calendar.profile_name} [${calendar.verification_status}]` : "Not selected"; byId("overview-readiness").textContent = workspace.activeScenario?.status || "Draft"; byId("overview-roles").textContent = `${doc.courses.filter((c) => c.role === "required").length} required · ${doc.courses.filter((c) => c.role === "optional").length} optional`; }
function feedback(message, style = "") { byId("solver-feedback").textContent = message; byId("solver-feedback").className = `feedback ${style}`; }

function labeledSelect(labelText, value, entries, onChange) { const label = document.createElement("label"); label.append(labelText); const select = document.createElement("select"); for (const entry of entries) { const [entryValue, text] = Array.isArray(entry) ? entry : [entry, entry.replaceAll("_", " ")]; select.append(option(entryValue, text)); } select.value = value; select.addEventListener("change", () => onChange(select.value)); label.append(select); return label; }
function labeledInput(labelText, value, type, onChange) { const label = document.createElement("label"); label.append(labelText); const input = document.createElement("input"); input.type = type; input.value = value; if (type === "number") { input.min = "0"; input.step = labelText === "Priority tier" ? "1" : "0.001"; } input.addEventListener("change", () => onChange(input.value)); label.append(input); return label; }
function parseOccupied(value) { return value.split(/\r?\n/).filter((line) => line.trim()).map((line) => { const [day, start, end, ...label] = line.split(",").map((item) => item.trim()); const parsed = { day: Number(day), start_minute: Number(start), end_minute: Number(end), label: label.join(",") || "manual commitment" }; if (![parsed.day, parsed.start_minute, parsed.end_minute].every(Number.isInteger) || parsed.day < 0 || parsed.day > 6 || parsed.start_minute >= parsed.end_minute) throw new Error(`Invalid occupied-period line: ${line}`); return parsed; }); }
function downloadResultCsv(result) { const safe = (value) => { const text = String(value ?? ""); const protectedText = /^[=+\-@]/.test(text.trimStart()) ? `'${text}` : text; return `"${protectedText.replaceAll('"', '""')}"`; }; const rows = [["Day", "Start", "End", "Course", "Component", "Faculty", "Venue", "Slot"], ...result.assignments.flatMap((assignment) => assignment.meetings.map((meeting) => [meeting.day_name, meeting.start_time, meeting.end_time, assignment.course_code, meeting.component_type, meeting.faculty, meeting.venue, meeting.slot]))]; downloadObject(`\ufeff${rows.map((row) => row.map(safe).join(",")).join("\r\n")}`, `ffcs-timetable-${result.result_id}.csv`, "text/csv"); }
function textList(value) { return value.split(",").map((item) => item.trim()).filter(Boolean); }
function timeMinute(value) { if (!value) return null; const [hour, minute] = value.split(":").map(Number); return hour * 60 + minute; }
function minuteTime(value) { return value == null ? "" : clock(value); }
function emptyState(message) { const element = textElement("div", message, "empty-state compact"); return element; }
function byId(id) { return document.getElementById(id); }
