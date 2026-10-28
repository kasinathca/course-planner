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

const importFlow = { validationId: null, previewId: null };
const explorer = { page: 1, pageSize: 25, total: 0 };
const calendarFlow = { validationId: null, previewId: null };

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

async function loadCalendars() {
  try {
    const result = await api("/api/v1/calendars");
    calendarSelect.replaceChildren(option("", result.items.length ? "Select a calendar" : "No committed calendars"));
    for (const item of result.items) {
      const label = `${item.semester_label} — ${item.profile_name} v${item.version} [${item.verification_status}]`;
      calendarSelect.append(option(item.calendar_id, label));
      if (item.active) calendarSelect.value = item.calendar_id;
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
    await loadCalendars();
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
