import { api, downloadObject, option } from "../api.js";

const scenarioFlow = { validationId: null, previewId: null };
const legacyFlow = { validationId: null, previewId: null };
let backups = [];

export function initInteroperability() {
  for (const [id, format] of [["export-json", "json"], ["export-csv", "csv"], ["export-metadata", "csv-metadata"], ["export-xlsx", "xlsx"], ["export-ffcsinator", "ffcsinator"]]) {
    byId(id).addEventListener("click", () => downloadSemester(format));
  }
  byId("legacy-ts-file").addEventListener("change", () => { byId("legacy-ts-convert").disabled = !byId("legacy-ts-file").files[0]; });
  byId("legacy-ts-convert").addEventListener("click", convertLegacy);
  byId("legacy-ts-preview").addEventListener("click", previewLegacy);
  byId("legacy-ts-commit").addEventListener("click", commitLegacy);
  byId("scenario-import-file").addEventListener("change", selectScenarioFile);
  byId("scenario-import-validate").addEventListener("click", validateScenario);
  byId("scenario-import-preview").addEventListener("click", previewScenario);
  byId("scenario-import-commit").addEventListener("click", commitScenario);
  byId("backup-create").addEventListener("click", createBackup);
  byId("backup-refresh").addEventListener("click", refreshBackups);
  byId("backup-select").addEventListener("change", selectBackup);
  byId("backup-confirm").addEventListener("input", selectBackup);
  byId("backup-restore").addEventListener("click", restoreBackup);
  refreshBackups();
}

function semesterParams() {
  const campus = byId("export-campus").value.trim();
  const semester = byId("export-semester").value.trim();
  if (!campus || !semester) throw new Error("Enter an exact campus and semester label.");
  return new URLSearchParams({ campus, semester_label: semester });
}

function downloadSemester(format) {
  try {
    const link = document.createElement("a");
    link.href = `/api/v1/data/export/${format}?${semesterParams()}`;
    link.download = "";
    link.click();
    setOutput("interchange-output", `Requested ${format} export for the selected exact semester.`, "success");
  } catch (error) { setOutput("interchange-output", error.message, "error"); }
}

async function convertLegacy() {
  const file = byId("legacy-ts-file").files[0];
  if (!file) return;
  try {
    const params = semesterParams();
    const result = await api("/api/v1/data/ffcsinator/convert", { method: "POST", json: { filename: file.name, campus: params.get("campus"), semester_label: params.get("semester_label"), content: await file.text() } });
    legacyFlow.validationId = result.validation_id; legacyFlow.previewId = null;
    byId("legacy-ts-preview").disabled = false; byId("legacy-ts-commit").disabled = true;
    downloadObject(result.canonical, `${file.name.replace(/\.ts$/i, "")}-canonical.json`);
    setOutput("interchange-output", JSON.stringify({ source: result.source, course_count: result.course_count, allocation_count: result.allocation_count, diagnostics: result.diagnostics, next: "Preview before committing this independent legacy import." }, null, 2), "success");
  } catch (error) { setOutput("interchange-output", error.message, "error"); }
}

async function previewLegacy() {
  try {
    const result = await api("/api/v1/imports/preview", { method: "POST", json: { validation_id: legacyFlow.validationId } });
    legacyFlow.previewId = result.preview_id; byId("legacy-ts-commit").disabled = false;
    setOutput("interchange-output", JSON.stringify({ source: "legacy-ffcsinator", course_count: result.course_count, allocation_count: result.allocation_count, reconciliation: result.reconciliation, issues: result.issues }, null, 2), "warning");
  } catch (error) { setOutput("interchange-output", error.message, "error"); }
}

async function commitLegacy() {
  try {
    const result = await api("/api/v1/imports/commit", { method: "POST", json: { preview_id: legacyFlow.previewId } });
    byId("legacy-ts-commit").disabled = true;
    setOutput("interchange-output", JSON.stringify({ ...result, source: "legacy-ffcsinator" }, null, 2), "success");
  } catch (error) { setOutput("interchange-output", error.message, "error"); }
}

function selectScenarioFile() {
  scenarioFlow.validationId = null; scenarioFlow.previewId = null;
  const file = byId("scenario-import-file").files[0];
  byId("scenario-import-validate").disabled = !file;
  byId("scenario-import-preview").disabled = true;
  byId("scenario-import-commit").disabled = true;
  if (file) byId("scenario-import-name").value = file.name.replace(/\.json$/i, "").slice(0, 120);
}

async function validateScenario() {
  try {
    const file = byId("scenario-import-file").files[0];
    const result = await api("/api/v1/scenarios/import/validate", { method: "POST", json: { document: JSON.parse(await file.text()) } });
    scenarioFlow.validationId = result.validation_id;
    byId("scenario-import-preview").disabled = false;
    if (!byId("scenario-import-name").value.trim()) byId("scenario-import-name").value = result.name;
    setOutput("scenario-import-output", JSON.stringify(result, null, 2), "success");
  } catch (error) { setOutput("scenario-import-output", error.message, "error"); }
}

async function previewScenario() {
  try {
    const result = await api("/api/v1/scenarios/import/preview", { method: "POST", json: { validation_id: scenarioFlow.validationId } });
    scenarioFlow.previewId = result.preview_id;
    byId("scenario-import-commit").disabled = false;
    setOutput("scenario-import-output", JSON.stringify({ status: result.status, solver_ready: result.solver_ready, identity_conflict: result.identity_conflict, compatibility: result.compatibility, courses: result.document.courses.length }, null, 2), result.compatibility.some((item) => item.level === "error") ? "warning" : "success");
  } catch (error) { setOutput("scenario-import-output", error.message, "error"); }
}

async function commitScenario() {
  const name = byId("scenario-import-name").value.trim();
  if (!name) return setOutput("scenario-import-output", "Enter a name for the imported independent copy.", "error");
  try {
    const result = await api("/api/v1/scenarios/import/commit", { method: "POST", json: { preview_id: scenarioFlow.previewId, choice: byId("scenario-import-choice").value, name } });
    byId("scenario-import-commit").disabled = true;
    setOutput("scenario-import-output", `Imported “${result.name}” as ${result.status} revision ${result.current_revision}.`, "success");
    document.dispatchEvent(new CustomEvent("ffcs-scenario-imported"));
  } catch (error) { setOutput("scenario-import-output", error.message, "error"); }
}

async function refreshBackups() {
  try {
    const result = await api("/api/v1/backups");
    backups = result.items;
    const select = byId("backup-select");
    const previous = select.value;
    select.replaceChildren(option("", backups.length ? "Select a reviewed backup" : "No backups available"));
    for (const backup of backups) select.append(option(backup.backup_id, backup.valid ? `${new Date(backup.created_at).toLocaleString()} · schema ${backup.schema_version} · ${formatBytes(backup.size_bytes)}` : `${backup.backup_id} · INVALID`));
    if (backups.some((backup) => backup.backup_id === previous)) select.value = previous;
    selectBackup();
  } catch (error) { setOutput("backup-output", error.message, "error"); }
}

async function createBackup() {
  try {
    const result = await api("/api/v1/backups", { method: "POST", json: { label: "manual-browser" } });
    setOutput("backup-output", `Created ${result.backup_id}\nSHA-256 ${result.sha256}\nSQLite integrity: ${result.integrity}`, "success");
    await refreshBackups(); byId("backup-select").value = result.backup_id; selectBackup();
  } catch (error) { setOutput("backup-output", error.message, "error"); }
}

function selectBackup() {
  const selected = backups.find((backup) => backup.backup_id === byId("backup-select").value);
  byId("backup-download").href = selected?.valid ? `/api/v1/backups/${encodeURIComponent(selected.backup_id)}/download` : "#";
  byId("backup-restore").disabled = !selected?.valid || byId("backup-confirm").value !== "RESTORE";
  if (selected) setOutput("backup-output", JSON.stringify(selected, null, 2), selected.valid ? "" : "error");
}

async function restoreBackup() {
  const selected = backups.find((backup) => backup.backup_id === byId("backup-select").value);
  if (!selected?.valid) return;
  try {
    byId("backup-restore").disabled = true;
    setOutput("backup-output", "Stopping active workers, creating a safety backup, and validating restore…");
    const result = await api("/api/v1/backups/restore", { method: "POST", json: { backup_id: selected.backup_id, expected_sha256: selected.sha256, confirmation: byId("backup-confirm").value } });
    byId("backup-confirm").value = "";
    setOutput("backup-output", JSON.stringify(result, null, 2), "success");
    await refreshBackups();
  } catch (error) { setOutput("backup-output", error.message, "error"); await refreshBackups(); }
}

function setOutput(id, message, style = "") { const target = byId(id); target.textContent = message; target.className = `inspection-output ${style}`; }
function formatBytes(bytes) { return bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`; }
function byId(id) { return document.getElementById(id); }
