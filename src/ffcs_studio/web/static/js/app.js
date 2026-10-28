const statusText = document.querySelector("#health-text");
const statusDot = document.querySelector("#health-dot");
const csrfToken = document.querySelector('meta[name="ffcs-csrf"]').content;
const fileInput = document.querySelector("#import-file");
const selectedFile = document.querySelector("#selected-file");
const csvMetadata = document.querySelector("#csv-metadata");
const validateButton = document.querySelector("#validate-button");
const previewButton = document.querySelector("#preview-button");
const commitButton = document.querySelector("#commit-button");
const cancelButton = document.querySelector("#cancel-button");
const importState = document.querySelector("#import-state");
const importStatus = document.querySelector("#import-status");
const importSummary = document.querySelector("#import-summary");
const issuesPanel = document.querySelector("#issues-panel");
const issuesList = document.querySelector("#issues-list");
const previewPanel = document.querySelector("#preview-panel");
const changeList = document.querySelector("#change-list");
const semesterFilter = document.querySelector("#semester-filter");
const offeringsBody = document.querySelector("#offerings-body");
const resultCount = document.querySelector("#result-count");
const previousPage = document.querySelector("#previous-page");
const nextPage = document.querySelector("#next-page");
const pageLabel = document.querySelector("#page-label");
const detailPanel = document.querySelector("#offering-detail");
const calendarFile = document.querySelector("#calendar-file");
const calendarValidate = document.querySelector("#calendar-validate");
const calendarPreview = document.querySelector("#calendar-preview");
const calendarCommit = document.querySelector("#calendar-commit");
const calendarSelect = document.querySelector("#calendar-select");
const calendarFeedback = document.querySelector("#calendar-feedback");
const calendarState = document.querySelector("#calendar-state");
const slotOutput = document.querySelector("#slot-output");
const solverSemester = document.querySelector("#solver-semester");
const solverCalendar = document.querySelector("#solver-calendar");
const solverCoursesBody = document.querySelector("#solver-courses-body");
const solverFeedback = document.querySelector("#solver-feedback");
const solverState = document.querySelector("#solver-state");
const solverProgress = document.querySelector("#solver-progress");
const solverResults = document.querySelector("#solver-results");

const importFlow = { validationId: null, previewId: null };
const explorer = { page: 1, pageSize: 25, total: 0 };
const calendarFlow = { validationId: null, previewId: null };
const solverFlow = { calendars: [], jobId: null, pollTimer: null, countTimer: null };

class ApiError extends Error {
  constructor(response, payload) {
    super(payload?.error?.message || `Request failed with HTTP ${response.status}`);
    this.status = response.status;
    this.payload = payload;
  }
}

async function checkHealth() {
  try {
    const response = await fetch("/health", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const health = await response.json();
    if (health.status !== "ready") throw new Error("Service is not ready");
    statusText.textContent = "Local service ready";
    statusDot.classList.add("ready");
  } catch (_error) {
    statusText.textContent = "Local service check failed. Review the server terminal.";
    statusDot.classList.add("error");
  }
}

checkHealth();

fileInput.addEventListener("change", () => {
  resetImport(false);
  const file = fileInput.files[0];
  if (!file) return;
  selectedFile.textContent = `${file.name} — ${formatBytes(file.size)}`;
  csvMetadata.hidden = !isCsv(file);
  if (isCsv(file) && !document.querySelector("#csv-captured-at").value) {
    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    document.querySelector("#csv-captured-at").value = now.toISOString().slice(0, 16);
  }
  validateButton.disabled = false;
  cancelButton.disabled = false;
  setImportState("File selected", "");
  setFeedback("Ready to validate. No database changes have been made.", "");
});

validateButton.addEventListener("click", validateSelectedFile);
previewButton.addEventListener("click", previewSelectedFile);
commitButton.addEventListener("click", commitPreview);
cancelButton.addEventListener("click", () => resetImport(true));
document.querySelector("#filter-button").addEventListener("click", () => loadOfferings(1));
document.querySelector("#search-filter").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadOfferings(1);
});
previousPage.addEventListener("click", () => loadOfferings(explorer.page - 1));
nextPage.addEventListener("click", () => loadOfferings(explorer.page + 1));
document.querySelector("#close-detail").addEventListener("click", () => {
  detailPanel.hidden = true;
});

loadSemesters();
loadOfferings(1);
loadCalendars();

calendarFile.addEventListener("change", () => {
  calendarFlow.validationId = null;
  calendarFlow.previewId = null;
  const file = calendarFile.files[0];
  document.querySelector("#calendar-file-detail").textContent = file ? `${file.name} — ${formatBytes(file.size)}` : "No file selected.";
  calendarValidate.disabled = !file;
  calendarPreview.disabled = true;
  calendarCommit.disabled = true;
});
calendarValidate.addEventListener("click", validateCalendar);
calendarPreview.addEventListener("click", previewCalendar);
calendarCommit.addEventListener("click", commitCalendar);
calendarSelect.addEventListener("change", updateCalendarControls);
document.querySelector("#resolve-slot").addEventListener("click", resolveLeftSlot);
document.querySelector("#check-conflict").addEventListener("click", checkSlotConflict);
document.querySelector("#solver-load-courses").addEventListener("click", loadSolverCourses);
document.querySelector("#solver-validate").addEventListener("click", validateSolverScenario);
document.querySelector("#solver-start").addEventListener("click", startSolverJob);
document.querySelector("#solver-cancel").addEventListener("click", cancelSolverJob);
document.querySelector("#solver-count").addEventListener("click", startExactCount);
document.querySelector("#solver-cancel-count").addEventListener("click", cancelExactCount);
solverSemester.addEventListener("change", filterSolverCalendars);
loadSolverSources();

async function loadCalendars(preferredCalendarId = "") {
  try {
    const result = await api("/api/v1/calendars");
    calendarSelect.replaceChildren(option("", result.items.length ? "Select a calendar" : "No committed calendars"));
    let selectedActive = false;
    for (const item of result.items) {
      const activeLabel = item.active ? " · active for semester" : "";
      const label = `${item.semester_label} — ${item.profile_name} v${item.version} [${item.verification_status}]${activeLabel}`;
      calendarSelect.append(option(item.calendar_id, label));
      if (item.calendar_id === preferredCalendarId || (!preferredCalendarId && item.active && !selectedActive)) {
        calendarSelect.value = item.calendar_id;
        selectedActive = true;
      }
    }
    updateCalendarControls();
  } catch (error) {
    calendarFeedback.textContent = error.message;
  }
}

function updateCalendarControls() {
  const selected = Boolean(calendarSelect.value);
  document.querySelector("#resolve-slot").disabled = !selected;
  document.querySelector("#check-conflict").disabled = !selected;
  calendarState.textContent = selected ? "Calendar selected" : "No calendar selected";
}

async function validateCalendar() {
  const file = calendarFile.files[0];
  if (!file) return;
  try {
    const result = await api("/api/v1/calendars/validate", { method: "POST", json: JSON.parse(await file.text()) });
    calendarFlow.validationId = result.validation_id;
    calendarPreview.disabled = false;
    calendarFeedback.textContent = `Valid ${result.calendar.verification_status} calendar. ${result.issues.length} review note(s).`;
  } catch (error) {
    calendarFeedback.textContent = error.message;
  }
}

async function previewCalendar() {
  try {
    const result = await api("/api/v1/calendars/preview", { method: "POST", json: { validation_id: calendarFlow.validationId } });
    calendarFlow.previewId = result.preview_id;
    calendarCommit.disabled = false;
    calendarFeedback.textContent = `${result.slot_count} atomic slots and ${result.interval_count} intervals; ${result.duplicate_calendar_id ? "already committed" : "new immutable version"}.`;
  } catch (error) {
    calendarFeedback.textContent = error.message;
  }
}

async function commitCalendar() {
  try {
    const result = await api("/api/v1/calendars/commit", { method: "POST", json: { preview_id: calendarFlow.previewId, make_active: true } });
    calendarFeedback.textContent = `Calendar ${result.status}: ${result.calendar_id}`;
    calendarCommit.disabled = true;
    await loadCalendars(result.calendar_id);
  } catch (error) {
    calendarFeedback.textContent = error.message;
  }
}

async function resolveLeftSlot() {
  try {
    const result = await api("/api/v1/slots/resolve", { method: "POST", json: { calendar_id: calendarSelect.value, expression: document.querySelector("#left-slot").value } });
    slotOutput.textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    slotOutput.textContent = error.message;
  }
}

async function checkSlotConflict() {
  try {
    const result = await api("/api/v1/conflicts/check", { method: "POST", json: { calendar_id: calendarSelect.value, left: document.querySelector("#left-slot").value, right: document.querySelector("#right-slot").value } });
    slotOutput.textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    slotOutput.textContent = error.message;
  }
}

async function validateSelectedFile() {
  const file = fileInput.files[0];
  if (!file) return;
  setBusy(true);
  setImportState("Validating", "");
  setFeedback("Validating the complete file and source contract…", "");
  clearReview();
  const headers = {
    "Content-Type": isCsv(file) ? "text/csv" : "application/json",
    "X-FFCS-Filename": file.name,
  };
  if (isCsv(file)) {
    const campus = document.querySelector("#csv-campus").value;
    const semester = document.querySelector("#csv-semester").value;
    const capturedValue = document.querySelector("#csv-captured-at").value;
    headers["X-FFCS-Campus"] = campus;
    headers["X-FFCS-Semester"] = semester;
    if (capturedValue) headers["X-FFCS-Captured-At"] = new Date(capturedValue).toISOString();
  }
  try {
    const result = await api("/api/v1/imports/validate", {
      method: "POST",
      headers,
      body: file,
    });
    importFlow.validationId = result.validation_id;
    setSummary(result.course_count, result.allocation_count, result.issues.length);
    renderIssues(result.issues);
    previewButton.disabled = false;
    cancelButton.disabled = false;
    setImportState(result.issues.length ? "Valid with warnings" : "Valid", result.issues.length ? "warning" : "success");
    setFeedback(
      `Validated ${result.course_count} course(s) and ${result.allocation_count} allocation row(s). Preview the database changes before committing.`,
      result.issues.length ? "warning" : "success",
    );
  } catch (error) {
    handleImportError(error, "Invalid file");
  } finally {
    setBusy(false);
  }
}

async function previewSelectedFile() {
  if (!importFlow.validationId) return;
  setBusy(true);
  setImportState("Preparing preview", "");
  setFeedback("Comparing this partial capture with active semester records…", "");
  try {
    const result = await api("/api/v1/imports/preview", {
      method: "POST",
      json: { validation_id: importFlow.validationId },
    });
    importFlow.previewId = result.preview_id;
    renderPreview(result.reconciliation);
    commitButton.disabled = false;
    setImportState(result.reconciliation.duplicate_import_id ? "Duplicate import" : "Preview ready", result.reconciliation.duplicate_import_id ? "warning" : "success");
    setFeedback(
      result.reconciliation.duplicate_import_id
        ? "This canonical content was already imported. Commit will confirm the existing snapshot without duplicating data."
        : "Review the proposed per-course changes, then commit explicitly.",
      result.reconciliation.duplicate_import_id ? "warning" : "success",
    );
  } catch (error) {
    handleImportError(error, "Preview failed");
  } finally {
    setBusy(false);
  }
}

async function commitPreview() {
  if (!importFlow.previewId) return;
  setBusy(true);
  commitButton.disabled = true;
  setImportState("Committing", "");
  setFeedback("Saving the exact reviewed snapshot in one SQLite transaction…", "");
  try {
    const result = await api("/api/v1/imports/commit", {
      method: "POST",
      json: { preview_id: importFlow.previewId },
    });
    const duplicate = result.status === "already_imported";
    setImportState(duplicate ? "Already imported" : "Successfully imported", duplicate ? "warning" : "success");
    setFeedback(
      duplicate
        ? `No duplicate records were created. Existing import ${result.import_id} remains active.`
        : `Saved import ${result.import_id}: ${result.course_count} course(s), ${result.allocation_count} row(s).`,
      duplicate ? "warning" : "success",
    );
    previewButton.disabled = true;
    await loadSemesters();
    await loadOfferings(1);
  } catch (error) {
    handleImportError(error, error.status === 409 ? "Stale preview" : "Commit failed");
  } finally {
    setBusy(false);
  }
}

async function loadSemesters() {
  try {
    const result = await api("/api/v1/semesters");
    const previous = semesterFilter.value;
    semesterFilter.replaceChildren(option("", "All semesters"));
    for (const semester of result.items) {
      semesterFilter.append(option(
        `${semester.campus}\u001f${semester.semester_label}`,
        `${semester.semester_label} — ${semester.campus} (${semester.offering_count})`,
      ));
    }
    if ([...semesterFilter.options].some((item) => item.value === previous)) {
      semesterFilter.value = previous;
    } else if (result.items.length) {
      semesterFilter.selectedIndex = 1;
    }
  } catch (error) {
    console.error(error);
  }
}

async function loadOfferings(page) {
  explorer.page = Math.max(1, page);
  const params = new URLSearchParams({ page: explorer.page, page_size: explorer.pageSize });
  const semester = semesterFilter.value.split("\u001f");
  if (semesterFilter.value) {
    params.set("campus", semester[0]);
    params.set("semester_label", semester[1]);
  }
  const search = document.querySelector("#search-filter").value.trim();
  const category = document.querySelector("#category-filter").value.trim();
  const component = document.querySelector("#component-filter").value;
  if (search) params.set("search", search);
  if (category) params.set("category", category);
  if (component) params.set("component", component);
  try {
    const result = await api(`/api/v1/offerings?${params}`);
    explorer.total = result.total;
    renderOfferings(result.items);
    resultCount.textContent = `${result.total} course${result.total === 1 ? "" : "s"}`;
    pageLabel.textContent = `Page ${result.page}`;
    previousPage.disabled = result.page <= 1;
    nextPage.disabled = result.page * result.page_size >= result.total;
  } catch (error) {
    offeringsBody.replaceChildren(emptyRow("Courses could not be loaded."));
  }
}

function renderOfferings(items) {
  if (!items.length) {
    offeringsBody.replaceChildren(emptyRow("No courses match the current filters."));
    return;
  }
  const rows = items.map((item) => {
    const row = document.createElement("tr");
    const courseCell = document.createElement("td");
    courseCell.append(textElement("span", item.course_code, "course-code"));
    courseCell.append(textElement("span", item.course_title, "course-title"));
    row.append(courseCell, textElement("td", item.category));
    const types = document.createElement("td");
    for (const component of item.component_types) types.append(textElement("span", component, "component-tag"));
    if (!item.component_types.length) types.textContent = "Not supplied";
    row.append(types, textElement("td", String(item.allocation_count)));
    const action = document.createElement("td");
    const button = textElement("button", "View", "secondary");
    button.type = "button";
    button.addEventListener("click", () => showOffering(item.offering_id));
    action.append(button);
    row.append(action);
    return row;
  });
  offeringsBody.replaceChildren(...rows);
}

async function showOffering(offeringId) {
  try {
    const [detail, allocations, components, candidates] = await Promise.all([
      api(`/api/v1/offerings/${offeringId}`),
      api(`/api/v1/offerings/${offeringId}/allocations`),
      api(`/api/v1/offerings/${offeringId}/components`),
      api(`/api/v1/offerings/${offeringId}/registration-options`),
    ]);
    document.querySelector("#detail-title").textContent = `${detail.course_code} — ${detail.course_title}`;
    document.querySelector("#detail-meta").textContent = `${detail.category} · ${detail.semester_label} · ${detail.campus} · ${detail.allocation_count} source row(s)`;
    const body = document.querySelector("#allocations-body");
    if (!allocations.items.length) {
      body.replaceChildren(emptyRow("No allocation rows were captured.", 4));
    } else {
      body.replaceChildren(...allocations.items.map((item) => {
        const row = document.createElement("tr");
        row.append(
          textElement("td", item.slot),
          textElement("td", item.venue),
          textElement("td", item.faculty),
          textElement("td", item.course_type),
        );
        return row;
      }));
    }
    document.querySelector("#detail-provenance").textContent = `Source: ${detail.source_kind} (${detail.source_format}); file: ${detail.original_filename}; captured: ${detail.captured_at}; committed: ${detail.committed_at}; import: ${detail.import_id}`;
    document.querySelector("#detail-missing").textContent = `Not supplied by this source: ${detail.missing_metadata.join(", ").replaceAll("_", " ")}. No values were inferred.`;
    const reviewCount = components.items.filter((item) => item.classification_status === "needs_review").length;
    document.querySelector("#detail-component-status").textContent = `Curriculum type: ${components.curriculum_type} (${components.curriculum_type_status}); ${reviewCount} allocation type(s) need review.`;
    document.querySelector("#detail-candidates").replaceChildren(...candidates.items.map((candidate) => {
      const allocationIds = candidate.allocations.map((item) => `#${item.allocation_id} ${item.course_type} ${item.slot}`).join(" + ") || "No permitted combination";
      return textElement("li", `${candidate.status}: ${allocationIds} — ${candidate.reasons.join("; ")}`);
    }));
    const detailWarnings = document.querySelector("#detail-warnings");
    detailWarnings.replaceChildren(...detail.warnings.map((warning) =>
      textElement("li", `${warning.code}: ${warning.message}`, "warning")
    ));
    detailWarnings.hidden = detail.warnings.length === 0;
    detailPanel.hidden = false;
    detailPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    console.error(error);
  }
}

function renderIssues(issues) {
  issuesList.replaceChildren(...issues.map((issue) => {
    const item = textElement("li", `${issue.path}: ${issue.message}`, issue.level);
    item.prepend(textElement("strong", `${issue.level.toUpperCase()} · ${issue.code} — `));
    return item;
  }));
  issuesPanel.hidden = issues.length === 0;
}

function renderPreview(diff) {
  previewPanel.hidden = false;
  for (const [id, key] of Object.entries({
    "diff-new": "new_courses",
    "diff-updated": "updated_courses",
    "diff-unchanged": "unchanged_courses",
    "diff-added": "added_rows",
    "diff-removed": "removed_rows",
    "diff-modified": "modified_rows",
  })) document.querySelector(`#${id}`).textContent = diff[key];
  changeList.replaceChildren(...diff.changes.map((change) => {
    const detail = `${change.course_code} — ${change.course_title}: ${change.change_type}; +${change.added_rows.length} / −${change.removed_rows.length} / ${change.modified_rows.length} modified${change.order_changed ? "; order changed" : ""}`;
    return textElement("div", detail, "change-item");
  }));
}

function handleImportError(error, state) {
  const issues = error.payload?.error?.issues || [];
  setImportState(state, "error");
  setFeedback(error.message, "error");
  renderIssues(issues);
  importFlow.validationId = null;
  importFlow.previewId = null;
  previewButton.disabled = true;
  commitButton.disabled = true;
}

function resetImport(clearFile) {
  importFlow.validationId = null;
  importFlow.previewId = null;
  if (clearFile) {
    fileInput.value = "";
    selectedFile.textContent = "No file selected.";
    csvMetadata.hidden = true;
  }
  clearReview();
  validateButton.disabled = !fileInput.files[0];
  previewButton.disabled = true;
  commitButton.disabled = true;
  cancelButton.disabled = !fileInput.files[0];
  setImportState(fileInput.files[0] ? "File selected" : "Empty", "");
  setFeedback("Select a file to begin. Nothing is saved until Commit import is pressed.", "");
}

function clearReview() {
  importSummary.hidden = true;
  issuesPanel.hidden = true;
  previewPanel.hidden = true;
  issuesList.replaceChildren();
  changeList.replaceChildren();
}

function setSummary(courses, rows, warnings) {
  document.querySelector("#summary-courses").textContent = courses;
  document.querySelector("#summary-rows").textContent = rows;
  document.querySelector("#summary-warnings").textContent = warnings;
  importSummary.hidden = false;
}

function setBusy(busy) {
  validateButton.disabled = busy || !fileInput.files[0];
  if (busy) {
    previewButton.disabled = true;
    commitButton.disabled = true;
  }
}

function setImportState(text, style) {
  importState.textContent = text;
  importState.className = `state-pill${style ? ` ${style}` : ""}`;
}

function setFeedback(text, style) {
  importStatus.textContent = text;
  importStatus.className = `feedback${style ? ` ${style}` : ""}`;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  const request = { method: options.method || "GET", headers, cache: "no-store" };
  if (request.method !== "GET" && request.method !== "HEAD") headers.set("X-FFCS-CSRF", csrfToken);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    request.body = JSON.stringify(options.json);
  } else if (options.body !== undefined) {
    request.body = options.body;
  }
  const response = await fetch(path, request);
  let payload = null;
  try { payload = await response.json(); } catch (_error) { /* handled below */ }
  if (!response.ok) throw new ApiError(response, payload);
  return payload;
}

async function loadSolverSources() {
  try {
    const [semesters, calendars] = await Promise.all([
      api("/api/v1/semesters"),
      api("/api/v1/calendars"),
    ]);
    solverFlow.calendars = calendars.items;
    solverSemester.replaceChildren(option("", semesters.items.length ? "Select a semester" : "No imported semesters"));
    for (const semester of semesters.items) {
      solverSemester.append(option(
        `${semester.campus}\u001f${semester.semester_label}`,
        `${semester.semester_label} — ${semester.campus} (${semester.offering_count})`,
      ));
    }
    if (semesters.items.length) solverSemester.selectedIndex = 1;
    filterSolverCalendars();
  } catch (error) {
    setSolverFeedback(error.message, "error");
  }
}

function filterSolverCalendars() {
  const [campus = "", semester = ""] = solverSemester.value.split("\u001f");
  if (campus) document.querySelector("#solver-campus").value = campus;
  const matches = solverFlow.calendars.filter((item) =>
    item.campus === campus && item.semester_label === semester
  );
  solverCalendar.replaceChildren(option("", matches.length ? "Select a matching calendar" : "No exact matching calendar"));
  for (const item of matches) {
    const active = item.active ? " · active" : "";
    solverCalendar.append(option(
      item.calendar_id,
      `${item.profile_name} v${item.version} [${item.verification_status}]${active}`,
    ));
  }
  const active = matches.find((item) => item.active);
  if (active) solverCalendar.value = active.calendar_id;
}

async function loadSolverCourses() {
  const [campus, semester] = solverSemester.value.split("\u001f");
  if (!campus || !semester) {
    setSolverFeedback("Select an imported campus and semester first.", "error");
    return;
  }
  try {
    const items = [];
    let page = 1;
    let total = 0;
    do {
      const params = new URLSearchParams({ campus, semester_label: semester, page, page_size: 100 });
      const result = await api(`/api/v1/offerings?${params}`);
      items.push(...result.items);
      total = result.total;
      page += 1;
    } while (items.length < total);
    renderSolverCourses(items);
    setSolverFeedback(
      items.length ? `Loaded ${items.length} active offering(s). Choose required or optional roles.` : "No active offerings exist for this semester.",
      items.length ? "success" : "warning",
    );
    solverState.textContent = items.length ? "Courses loaded" : "No courses";
  } catch (error) {
    setSolverFeedback(error.message, "error");
  }
}

function renderSolverCourses(items) {
  if (!items.length) {
    solverCoursesBody.replaceChildren(emptyRow("No active offerings exist for this semester.", 7));
    return;
  }
  solverCoursesBody.replaceChildren(...items.map((item) => {
    const row = document.createElement("tr");
    row.dataset.offeringId = String(item.offering_id);
    const courseCell = document.createElement("td");
    courseCell.append(textElement("span", item.course_code, "course-code"));
    courseCell.append(textElement("span", item.course_title, "course-title"));
    courseCell.append(textElement("span", `${item.category} · ${item.allocation_count} rows`, "source-note"));

    const role = selectControl("solver-role", [
      ["excluded", "Excluded"], ["required", "Required"], ["optional", "Optional"],
    ]);
    const curriculum = selectControl("solver-curriculum", [
      ["unknown", "Unknown"], ["TH", "TH"], ["ETL", "ETL"], ["ETP", "ETP"],
      ["LO", "LO"], ["ELJ", "ELJ"], ["PJ", "PJ"], ["SS", "SS"],
    ]);
    const credits = document.createElement("input");
    credits.className = "solver-credits";
    credits.type = "number";
    credits.min = "0";
    credits.step = "0.001";
    credits.setAttribute("aria-label", `${item.course_code} credits`);
    const source = selectControl("solver-source", [
      ["unknown", "Unknown"], ["user_supplied", "User supplied"], ["verified", "Verified source"],
    ]);
    const tier = document.createElement("input");
    tier.className = "solver-tier";
    tier.type = "number";
    tier.min = "1";
    tier.max = "20";
    tier.value = "1";
    tier.setAttribute("aria-label", `${item.course_code} priority tier`);
    const restrictions = document.createElement("div");
    restrictions.className = "solver-locks";
    restrictions.append(
      compactInput("solver-locked", "Locked allocation IDs, comma separated", item.course_code),
      compactInput("solver-locked-faculty", "Required faculty, comma separated", item.course_code),
      compactInput("solver-forbidden", "Forbidden allocation IDs, comma separated", item.course_code),
      compactInput("solver-forbidden-faculty", "Forbidden faculty, comma separated", item.course_code),
    );
    row.append(
      courseCell,
      wrapControl(role),
      wrapControl(curriculum),
      wrapControl(credits),
      wrapControl(source),
      wrapControl(tier),
      wrapControl(restrictions),
    );
    return row;
  }));
}

function selectControl(className, entries) {
  const select = document.createElement("select");
  select.className = className;
  for (const [value, label] of entries) select.append(option(value, label));
  return select;
}

function compactInput(className, placeholder, courseCode) {
  const input = document.createElement("input");
  input.className = className;
  input.placeholder = placeholder;
  input.setAttribute("aria-label", `${courseCode}: ${placeholder}`);
  return input;
}

function wrapControl(control) {
  const cell = document.createElement("td");
  cell.append(control);
  return cell;
}

function buildSolverPayload() {
  const [selectedCampus = "", semester = ""] = solverSemester.value.split("\u001f");
  const campus = document.querySelector("#solver-campus").value.trim() || selectedCampus;
  if (!campus || !semester || !solverCalendar.value) {
    throw new Error("Select an exact campus, semester, and calendar before planning.");
  }
  const courses = [...solverCoursesBody.querySelectorAll("tr[data-offering-id]")].flatMap((row) => {
    const role = row.querySelector(".solver-role").value;
    if (role === "excluded") return [];
    const credits = row.querySelector(".solver-credits").value.trim();
    const source = row.querySelector(".solver-source").value;
    return [{
      offering_id: Number(row.dataset.offeringId),
      role,
      curriculum_type: row.querySelector(".solver-curriculum").value,
      curriculum_source: source,
      credits: credits || null,
      credit_source: credits ? source : "unknown",
      priority_tier: Number(row.querySelector(".solver-tier").value || 1),
      locked_allocation_ids: integerList(row.querySelector(".solver-locked").value),
      locked_faculties: textList(row.querySelector(".solver-locked-faculty").value),
      forbidden_allocation_ids: integerList(row.querySelector(".solver-forbidden").value),
      forbidden_faculties: textList(row.querySelector(".solver-forbidden-faculty").value),
    }];
  });
  if (!courses.length) throw new Error("Mark at least one course as required or optional.");
  const occupied = document.querySelector("#solver-occupied").value.split(/\r?\n/).filter((line) => line.trim()).map((line) => {
    const [day, start, end, ...label] = line.split(",").map((item) => item.trim());
    const parsed = { day: Number(day), start_minute: Number(start), end_minute: Number(end), label: label.join(",") || "manual commitment" };
    if (!Number.isInteger(parsed.day) || !Number.isInteger(parsed.start_minute) || !Number.isInteger(parsed.end_minute)) {
      throw new Error(`Invalid occupied-period line: ${line}`);
    }
    return parsed;
  });
  return {
    campus,
    semester_label: semester,
    calendar_id: solverCalendar.value,
    mode: document.querySelector("#solver-mode").value,
    courses,
    occupied_intervals: occupied,
    credit_constraints: {
      minimum: optionalValue("#solver-min-credits"),
      target: optionalValue("#solver-target-credits"),
      maximum: optionalValue("#solver-max-credits"),
    },
    ranking: {
      preferred_faculties: textList(document.querySelector("#solver-preferred-faculty").value),
      prefer_morning_theory: document.querySelector("#solver-morning").checked,
      prefer_evening_theory: document.querySelector("#solver-evening").checked,
      minimize_labs: document.querySelector("#solver-min-labs").checked,
      minimize_campus_days: document.querySelector("#solver-min-days").checked,
    },
    provisional_policy: {
      allow_unverified_calendar: document.querySelector("#solver-allow-calendar").checked,
      allow_user_supplied_metadata: document.querySelector("#solver-allow-metadata").checked,
      allow_provisional_pairing: document.querySelector("#solver-allow-provisional").checked,
      allow_same_faculty_pairing: document.querySelector("#solver-same-faculty").checked,
      allow_unknown_pairing: document.querySelector("#solver-unknown-pairing").checked,
    },
    top_k: Number(document.querySelector("#solver-top-k").value || 20),
    max_search_nodes: Number(document.querySelector("#solver-node-budget").value || 2000000),
  };
}

async function validateSolverScenario() {
  try {
    const result = await api("/api/v1/solver/scenarios/validate", { method: "POST", json: buildSolverPayload() });
    renderSolverValidation(result);
  } catch (error) {
    setSolverFeedback(error.message, "error");
  }
}

function renderSolverValidation(result) {
  if (result.valid) {
    const assumptions = result.assumptions.length ? ` Exploratory assumptions: ${result.assumptions.join("; ")}` : "";
    setSolverFeedback(`Scenario ready with ${result.course_count} course(s) and ${result.candidate_count} complete option(s).${assumptions}`, result.assumptions.length ? "warning" : "success");
    solverState.textContent = result.assumptions.length ? "Exploratory ready" : "Verified ready";
  } else {
    setSolverFeedback(`Scenario blocked: ${result.issues.map((item) => item.message).join("; ")}`, "error");
    solverState.textContent = "Unresolved";
  }
}

async function startSolverJob() {
  try {
    clearSolverTimers();
    solverResults.replaceChildren();
    const result = await api("/api/v1/solver/jobs", { method: "POST", json: buildSolverPayload() });
    solverFlow.jobId = result.job_id;
    document.querySelector("#solver-cancel").disabled = false;
    document.querySelector("#solver-count").disabled = true;
    solverState.textContent = result.status;
    setSolverFeedback(`Solver job ${result.job_id.slice(0, 8)} started from immutable snapshot ${result.scenario_fingerprint.slice(0, 12)}.`, "success");
    pollSolverJob();
  } catch (error) {
    const issues = error.payload?.issues?.map((item) => item.message).join("; ");
    setSolverFeedback(issues ? `Scenario blocked: ${issues}` : error.message, "error");
  }
}

async function pollSolverJob() {
  if (!solverFlow.jobId) return;
  try {
    const status = await api(`/api/v1/solver/jobs/${solverFlow.jobId}`);
    solverState.textContent = status.status.replaceAll("_", " ");
    solverProgress.hidden = false;
    solverProgress.textContent = `Nodes ${status.progress.nodes_visited || 0}; pruned ${status.progress.branches_pruned || 0}; feasible found ${status.progress.feasible_solutions_seen || 0}.`;
    if (["queued", "running", "cancellation_requested"].includes(status.status)) {
      solverFlow.pollTimer = window.setTimeout(pollSolverJob, 250);
      return;
    }
    document.querySelector("#solver-cancel").disabled = true;
    document.querySelector("#solver-count").disabled = status.status === "failed";
    await loadSolverResults();
  } catch (error) {
    setSolverFeedback(error.message, "error");
  }
}

async function loadSolverResults() {
  const result = await api(`/api/v1/solver/jobs/${solverFlow.jobId}/results?page=1&page_size=50`);
  renderSolverResults(result);
  if (result.status === "infeasible") {
    setSolverFeedback("No complete timetable satisfies every hard constraint. Review required-course conflicts, locks, metadata, and credit bounds.", "warning");
  } else if (result.status === "resource_limit" || result.status === "cancelled") {
    setSolverFeedback(`Search ${result.status.replaceAll("_", " ")}; displayed schedules are best found so far, not guaranteed globally optimal.`, "warning");
  } else if (result.status === "failed") {
    setSolverFeedback("The local solver worker failed safely. Review the server log; no result was certified.", "error");
  } else {
    setSolverFeedback(`Exhaustive search completed; showing ${result.total} bounded ranked result(s). Request exact count separately.`, "success");
  }
}

function renderSolverResults(payload) {
  if (!payload.items.length) {
    solverResults.replaceChildren(textElement("p", "No timetable results are available.", "source-note"));
    return;
  }
  solverResults.replaceChildren(...payload.items.map((result, index) => {
    const card = document.createElement("article");
    card.className = "solver-result";
    card.append(textElement("h3", `#${index + 1} · ${result.selected_courses.join(", ")}`));
    card.append(textElement("p", `${result.verification_status} · result ${result.result_id}`, "source-note"));
    const summary = document.createElement("div");
    summary.className = "solver-result-summary";
    const metrics = result.metrics;
    for (const value of [
      `${metrics.total_credits ?? "unknown"} credits`,
      `${metrics.physical_lab_sessions} lab sessions`,
      `${metrics.lab_minutes} lab minutes`,
      `${metrics.campus_days} campus days`,
      `${metrics.interclass_gap_minutes} gap minutes`,
    ]) summary.append(textElement("span", value));
    card.append(summary);
    card.append(textElement(
      "p",
      result.course_metadata.map((course) =>
        `${course.course_code}: ${course.credits ?? "unknown"} credits (${course.credit_source}), ${course.curriculum_type} (${course.curriculum_source})`
      ).join(" · "),
      "source-note",
    ));
    if (metrics.daily_spans.length) {
      card.append(textElement(
        "p",
        `Daily spans: ${metrics.daily_spans.map((span) => `${span.day_name} ${span.start_time}–${span.end_time}`).join("; ")}`,
        "source-note",
      ));
    }
    const explanation = document.createElement("ul");
    for (const line of result.explanation) explanation.append(textElement("li", line));
    card.append(explanation);
    if (result.assumptions.length) {
      card.append(textElement("p", `Assumptions: ${result.assumptions.join("; ")}`, "solver-assumptions"));
    }
    const tableWrap = document.createElement("div");
    tableWrap.className = "table-wrap solver-meetings";
    const table = document.createElement("table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const name of ["Course", "Component", "Day", "Time", "Faculty", "Venue"]) headRow.append(textElement("th", name));
    head.append(headRow);
    const body = document.createElement("tbody");
    const rows = result.assignments.flatMap((assignment) => assignment.meetings.map((meeting) => ({ assignment, meeting })));
    rows.sort((left, right) => left.meeting.day - right.meeting.day || left.meeting.start_minute - right.meeting.start_minute || left.assignment.course_code.localeCompare(right.assignment.course_code));
    for (const { assignment, meeting } of rows) {
      const row = document.createElement("tr");
      row.append(
        textElement("td", assignment.course_code),
        textElement("td", meeting.component_type),
        textElement("td", meeting.day_name),
        textElement("td", `${meeting.start_time}–${meeting.end_time}`),
        textElement("td", meeting.faculty),
        textElement("td", meeting.venue),
      );
      body.append(row);
    }
    table.append(head, body);
    tableWrap.append(table);
    card.append(tableWrap);
    return card;
  }));
}

async function cancelSolverJob() {
  if (!solverFlow.jobId) return;
  try {
    await api(`/api/v1/solver/jobs/${solverFlow.jobId}/cancel`, { method: "POST", json: {} });
    setSolverFeedback("Cancellation requested. The worker will stop cooperatively, with a forced local fallback if needed.", "warning");
  } catch (error) {
    setSolverFeedback(error.message, "error");
  }
}

async function startExactCount() {
  if (!solverFlow.jobId) return;
  try {
    const result = await api(`/api/v1/solver/jobs/${solverFlow.jobId}/count`, { method: "POST", json: {} });
    document.querySelector("#solver-count").disabled = true;
    document.querySelector("#solver-cancel-count").disabled = false;
    solverProgress.hidden = false;
    solverProgress.textContent = `Exact count ${result.status}.`;
    pollExactCount();
  } catch (error) {
    setSolverFeedback(error.message, "error");
  }
}

async function pollExactCount() {
  if (!solverFlow.jobId) return;
  try {
    const result = await api(`/api/v1/solver/jobs/${solverFlow.jobId}/count`);
    solverProgress.textContent = `Exact count ${result.status}; nodes ${result.progress.nodes_visited || 0}; pruned ${result.progress.branches_pruned || 0}.`;
    if (["pending", "running"].includes(result.status)) {
      solverFlow.countTimer = window.setTimeout(pollExactCount, 250);
      return;
    }
    document.querySelector("#solver-cancel-count").disabled = true;
    if (result.status === "exact") {
      setSolverFeedback(`Exact feasible timetable count: ${result.result.exact_count}.`, "success");
    } else {
      setSolverFeedback(`Exact count ended as ${result.status}; no exact number is displayed.`, "warning");
    }
  } catch (error) {
    setSolverFeedback(error.message, "error");
  }
}

async function cancelExactCount() {
  if (!solverFlow.jobId) return;
  try {
    await api(`/api/v1/solver/jobs/${solverFlow.jobId}/count/cancel`, { method: "POST", json: {} });
    setSolverFeedback("Exact-count cancellation requested.", "warning");
  } catch (error) {
    setSolverFeedback(error.message, "error");
  }
}

function setSolverFeedback(text, style) {
  solverFeedback.textContent = text;
  solverFeedback.className = `feedback${style ? ` ${style}` : ""}`;
}

function clearSolverTimers() {
  if (solverFlow.pollTimer) window.clearTimeout(solverFlow.pollTimer);
  if (solverFlow.countTimer) window.clearTimeout(solverFlow.countTimer);
  solverFlow.pollTimer = null;
  solverFlow.countTimer = null;
}

function integerList(value) {
  if (!value.trim()) return [];
  const values = value.split(",").map((item) => Number(item.trim()));
  if (values.some((item) => !Number.isInteger(item) || item <= 0)) throw new Error("Allocation ID lists must contain positive integers.");
  return values;
}

function textList(value) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function optionalValue(selector) {
  const value = document.querySelector(selector).value.trim();
  return value || null;
}

function isCsv(file) {
  return file.name.toLowerCase().endsWith(".csv") || file.type === "text/csv";
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function textElement(tag, text, className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function option(value, label) {
  const element = document.createElement("option");
  element.value = value;
  element.textContent = label;
  return element;
}

function emptyRow(message, columns = 5) {
  const row = document.createElement("tr");
  const cell = textElement("td", message, "empty-cell");
  cell.colSpan = columns;
  row.append(cell);
  return row;
}
