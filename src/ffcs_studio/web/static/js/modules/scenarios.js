import { api, textElement } from "../api.js";
import { blankDocument, workspace } from "../state.js";

let scenarios = [];
const savedComparison = new Map();

export function initScenarios() {
  byId("save-scenario-button").addEventListener("click", openSaveDialog);
  byId("scenario-form").addEventListener("submit", submitScenario);
  byId("new-scenario").addEventListener("click", newDraft);
  byId("show-archived").addEventListener("change", refreshScenarios);
  workspace.addEventListener("refresh-scenarios", refreshScenarios);
  workspace.addEventListener("refresh-overview", refreshOverview);
  workspace.addEventListener("scenario-saved", () => {
    refreshScenarios();
    refreshOverview();
  });
  document.addEventListener("ffcs-scenario-imported", refreshScenarios);
  refreshScenarios();
}

function openSaveDialog() {
  const active = workspace.activeScenario;
  byId("scenario-dialog-title").textContent = active ? "Save scenario revision" : "Save new scenario";
  byId("scenario-name").value = active?.name || "";
  byId("scenario-description").value = active?.description || "";
  setDialogStatus(active ? `This will create revision ${active.current_revision + 1}.` : "The scenario will be stored only in local SQLite.");
  byId("scenario-dialog").showModal();
  byId("scenario-name").focus();
}

async function submitScenario(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    byId("scenario-dialog").close();
    return;
  }
  const name = byId("scenario-name").value.trim();
  if (!name) {
    setDialogStatus("Enter a scenario name.", "error");
    return;
  }
  const active = workspace.activeScenario;
  const payload = {
    name,
    description: byId("scenario-description").value.trim(),
    document: workspace.document,
  };
  let path = "/api/v1/scenarios";
  let method = "POST";
  if (active) {
    path += `/${active.scenario_id}`;
    method = "PUT";
    payload.expected_revision = active.current_revision;
    payload.change_summary = "Saved from the browser workspace";
  }
  setDialogStatus("Saving…");
  byId("confirm-scenario-save").disabled = true;
  try {
    const stored = await api(path, { method, json: payload });
    workspace.markSaved(stored);
    byId("scenario-dialog").close();
    setNotice(`Saved “${stored.name}” at revision ${stored.current_revision}.`, "success");
  } catch (error) {
    setDialogStatus(error.status === 409 ? `${error.message} Your edits remain open; reload deliberately before retrying.` : error.message, "error");
  } finally {
    byId("confirm-scenario-save").disabled = false;
  }
}

async function refreshScenarios() {
  try {
    const result = await api(`/api/v1/scenarios?${new URLSearchParams({ page: 1, page_size: 100, include_archived: byId("show-archived").checked })}`);
    scenarios = result.items;
    renderScenarioList();
    if (workspace.activeScenario) {
      const current = scenarios.find((item) => item.scenario_id === workspace.activeScenario.scenario_id);
      if (current && current.current_revision !== workspace.activeScenario.current_revision) setNotice("The open scenario has a newer stored revision. Reload it before saving.", "warning");
      await Promise.all([renderRevisions(workspace.activeScenario.scenario_id), renderSavedResults(workspace.activeScenario.scenario_id)]);
    } else {
      byId("revision-context").textContent = "Open a scenario to inspect its history.";
      byId("revision-list").replaceChildren(empty("No open scenario."));
      byId("saved-result-list").replaceChildren(empty("No open scenario."));
    }
  } catch (error) {
    byId("scenario-list").replaceChildren(empty(error.message));
  }
}

function renderScenarioList() {
  const target = byId("scenario-list");
  if (!scenarios.length) {
    target.replaceChildren(empty("No saved scenarios yet."));
    return;
  }
  target.replaceChildren(...scenarios.map((scenario) => {
    const card = document.createElement("article");
    card.className = `scenario-card${workspace.activeScenario?.scenario_id === scenario.scenario_id ? " selected" : ""}`;
    card.append(
      textElement("h3", scenario.name),
      textElement("p", scenario.description || "No description", "muted"),
      textElement("p", `${scenario.semester_label || "No semester"} · revision ${scenario.current_revision} · ${scenario.status} · ${scenario.saved_result_count} saved timetable(s)`, "source-note"),
    );
    const actions = document.createElement("div");
    actions.className = "scenario-card-actions";
    actions.append(
      action("Open", () => openScenario(scenario.scenario_id), "secondary"),
      action("Duplicate", () => duplicateScenario(scenario)),
      scenario.archived_at ? action("Restore", () => unarchiveScenario(scenario)) : action("Archive", () => archiveScenario(scenario)),
      action("Delete", () => deleteScenario(scenario), "danger"),
      downloadLink("JSON", `/api/v1/scenarios/${scenario.scenario_id}/export`),
    );
    card.append(actions);
    return card;
  }));
}

async function openScenario(scenarioId) {
  if (workspace.dirty && !window.confirm("Discard the current unsaved browser edits and open this saved scenario?")) return;
  try {
    const stored = await api(`/api/v1/scenarios/${scenarioId}`);
    workspace.markSaved(stored);
    workspace.catalog = [];
    workspace.details.clear();
    workspace.dispatchEvent(new CustomEvent("load-active-catalog"));
    location.hash = "planner";
    setNotice(`Opened “${stored.name}” revision ${stored.current_revision}.`, stored.compatibility.length ? "warning" : "success");
  } catch (error) {
    setNotice(error.message, "error");
  }
}

async function duplicateScenario(scenario) {
  const name = window.prompt("Name the duplicate scenario", `${scenario.name} copy`);
  if (!name?.trim()) return;
  try {
    const stored = await api(`/api/v1/scenarios/${scenario.scenario_id}/duplicate`, { method: "POST", json: { name: name.trim() } });
    setNotice(`Created independent scenario “${stored.name}”.`, "success");
    await refreshScenarios();
  } catch (error) { setNotice(error.message, "error"); }
}

async function archiveScenario(scenario) {
  if (!window.confirm(`Archive “${scenario.name}”? It remains recoverable when “Show archived” is enabled.`)) return;
  await mutateScenario(`/api/v1/scenarios/${scenario.scenario_id}/archive`, { expected_revision: scenario.current_revision }, `Archived “${scenario.name}”.`);
}

async function unarchiveScenario(scenario) {
  await mutateScenario(`/api/v1/scenarios/${scenario.scenario_id}/unarchive`, {}, `Restored “${scenario.name}”.`);
}

async function deleteScenario(scenario) {
  if (!window.confirm(`Permanently delete “${scenario.name}”, every revision, and its saved timetables? This cannot be undone.`)) return;
  try {
    await api(`/api/v1/scenarios/${scenario.scenario_id}?expected_revision=${scenario.current_revision}`, { method: "DELETE" });
    if (workspace.activeScenario?.scenario_id === scenario.scenario_id) workspace.reset();
    setNotice(`Permanently deleted “${scenario.name}”.`, "success");
    await refreshScenarios();
  } catch (error) { setNotice(error.message, "error"); }
}

async function mutateScenario(path, json, success) {
  try {
    const stored = await api(path, { method: "POST", json });
    if (workspace.activeScenario?.scenario_id === stored.scenario_id) workspace.markSaved(stored);
    setNotice(success, "success");
    await refreshScenarios();
  } catch (error) { setNotice(error.message, "error"); }
}

async function renderRevisions(scenarioId) {
  const result = await api(`/api/v1/scenarios/${scenarioId}/revisions`);
  const active = workspace.activeScenario;
  byId("revision-context").textContent = `${active.name} · current revision ${active.current_revision}`;
  byId("revision-list").replaceChildren(...result.items.map((revision) => {
    const row = document.createElement("article");
    row.className = "revision-row";
    row.append(textElement("strong", `Revision ${revision.revision} · ${revision.status}`), textElement("span", `${revision.change_summary} · ${formatDate(revision.created_at)}`, "muted"));
    if (revision.revision !== active.current_revision && !active.archived_at) row.append(action("Restore as new revision", () => restoreRevision(revision.revision), "ghost"));
    return row;
  }));
}

async function restoreRevision(sourceRevision) {
  const active = workspace.activeScenario;
  if (!window.confirm(`Restore revision ${sourceRevision} as a new revision? Current history will remain intact.`)) return;
  try {
    const stored = await api(`/api/v1/scenarios/${active.scenario_id}/restore`, { method: "POST", json: { source_revision: sourceRevision, expected_revision: active.current_revision } });
    workspace.markSaved(stored);
    workspace.catalog = [];
    workspace.details.clear();
    workspace.dispatchEvent(new CustomEvent("load-active-catalog"));
    setNotice(`Restored revision ${sourceRevision} as revision ${stored.current_revision}.`, "success");
  } catch (error) { setNotice(error.message, "error"); }
}

async function renderSavedResults(scenarioId) {
  const result = await api(`/api/v1/scenarios/${scenarioId}/results?page=1&page_size=50`);
  const target = byId("saved-result-list");
  if (!result.items.length) {
    target.replaceChildren(empty("No immutable timetable snapshots saved yet."));
    byId("overview-result").replaceChildren(empty("No timetable has been saved for the current scenario."));
    return;
  }
  target.replaceChildren(...result.items.map((saved) => {
    const card = document.createElement("article"); card.className = "scenario-card";
    card.append(textElement("h3", `${saved.is_preferred ? "★ " : ""}${saved.name}`), textElement("p", `Scenario revision ${saved.scenario_revision} · ${saved.verification_status} · ${formatDate(saved.created_at)}`, "muted"));
    const actions = document.createElement("div"); actions.className = "scenario-card-actions";
    actions.append(action("Open", () => openSavedResult(saved.saved_result_id), "secondary"), action(savedComparison.has(saved.saved_result_id) ? "Remove comparison" : "Compare", () => toggleSavedComparison(saved.saved_result_id)), action("Make preferred", () => preferResult(saved.saved_result_id)), downloadLink("JSON", `/api/v1/saved-results/${saved.saved_result_id}/export.json`), downloadLink("CSV", `/api/v1/saved-results/${saved.saved_result_id}/export.csv`));
    card.append(actions); return card;
  }));
  const preferred = result.items.find((item) => item.is_preferred) || result.items[0];
  byId("overview-result").replaceChildren(textElement("strong", preferred.name), textElement("p", `${preferred.verification_status} · scenario revision ${preferred.scenario_revision} · ${formatDate(preferred.created_at)}`, "muted"));
}

async function openSavedResult(savedResultId) {
  try {
    const saved = await api(`/api/v1/saved-results/${savedResultId}`);
    workspace.dispatchEvent(new CustomEvent("display-result", { detail: saved }));
  } catch (error) { setNotice(error.message, "error"); }
}

async function preferResult(savedResultId) {
  try {
    await api(`/api/v1/saved-results/${savedResultId}/preferred`, { method: "POST", json: {} });
    setNotice("Preferred timetable updated.", "success");
    await renderSavedResults(workspace.activeScenario.scenario_id);
  } catch (error) { setNotice(error.message, "error"); }
}

async function toggleSavedComparison(savedResultId) {
  if (savedComparison.has(savedResultId)) savedComparison.delete(savedResultId);
  else {
    if (savedComparison.size >= 3) { setNotice("Compare at most three saved timetables.", "warning"); return; }
    try { savedComparison.set(savedResultId, await api(`/api/v1/saved-results/${savedResultId}`)); }
    catch (error) { setNotice(error.message, "error"); return; }
  }
  await renderSavedResults(workspace.activeScenario.scenario_id);
  if (savedComparison.size >= 2) workspace.dispatchEvent(new CustomEvent("compare-saved-results", { detail: [...savedComparison.values()] }));
  else setNotice("Choose one more saved timetable to compare historical snapshots.", "success");
}

function newDraft() {
  if (workspace.dirty && !window.confirm("Discard the current unsaved browser edits and start a new draft?")) return;
  workspace.activeJob = null;
  workspace.pollGeneration += 1;
  workspace.activeScenario = null;
  workspace.replaceDocument(blankDocument());
  workspace.catalog = [];
  workspace.details.clear();
  location.hash = "planner";
  setNotice("Started a new unsaved scenario.", "success");
}

async function refreshOverview() {
  const documentValue = workspace.document;
  const hasSemester = Boolean(documentValue.semester_label);
  const hasCourses = documentValue.courses.some((course) => course.role !== "excluded");
  const hasCalendar = Boolean(documentValue.calendar_id);
  const title = byId("overview-next-title"); const detail = byId("overview-next-detail"); const link = byId("overview-next-link");
  if (!hasSemester) { title.textContent = "Choose imported course data"; detail.textContent = "Import or select a semester before building a timetable."; link.href = "#courses"; link.textContent = "Go to Courses & Data"; }
  else if (!hasCalendar) { title.textContent = "Choose the matching calendar"; detail.textContent = "Exact planning requires an explicit calendar for this campus and semester."; link.href = "#planner"; link.textContent = "Open planner settings"; }
  else if (!hasCourses) { title.textContent = "Choose course roles"; detail.textContent = "Mark must-take and preferred courses from the active SQLite catalog."; link.href = "#planner"; link.textContent = "Choose courses"; }
  else { title.textContent = workspace.activeScenario ? "Generate or review timetables" : "Save this scenario"; detail.textContent = workspace.activeScenario ? "Your saved scenario can be validated and regenerated." : "Saving creates revision history and enables immutable timetable snapshots."; link.href = "#planner"; link.textContent = "Open planner"; }
  if (workspace.activeScenario) {
    try { await renderSavedResults(workspace.activeScenario.scenario_id); } catch (_error) { /* overview remains usable */ }
  } else byId("overview-result").replaceChildren(empty("No timetable has been saved for the current scenario."));
}

function action(label, handler, className = "ghost") { const button = textElement("button", label, className); button.type = "button"; button.addEventListener("click", handler); return button; }
function downloadLink(label, href) { const link = textElement("a", label, "button ghost"); link.href = href; link.download = ""; return link; }
function empty(message) { return textElement("div", message, "empty-state compact"); }
function formatDate(value) { return new Date(value).toLocaleString(); }
function setDialogStatus(message, style = "") { byId("scenario-dialog-status").textContent = message; byId("scenario-dialog-status").className = `feedback ${style}`; }
function setNotice(message, style = "") { byId("overview-notice").textContent = message; byId("overview-notice").className = `feedback ${style}`; }
function byId(id) { return document.getElementById(id); }
