function blankDocument() {
  return {
    schema_version: "1.0", campus: "Vellore", semester_label: "", calendar_id: null,
    mode: "exploratory", courses: [], occupied_intervals: [],
    credit_constraints: { minimum: null, target: null, maximum: null, category_minimums: {}, category_maximums: {} },
    ranking: { preferred_faculties: [], prefer_morning_theory: false, prefer_evening_theory: false, avoid_late_after_minute: null, minimize_labs: true, minimize_campus_days: true },
    provisional_policy: { allow_unverified_calendar: false, allow_user_supplied_metadata: false, allow_provisional_pairing: false, allow_unknown_pairing: false, allow_same_faculty_pairing: false },
    top_k: 20, max_search_nodes: 2000000,
  };
}

class WorkspaceState extends EventTarget {
  constructor() {
    super(); this.document = blankDocument(); this.catalog = []; this.details = new Map();
    this.calendars = []; this.activeScenario = null; this.dirty = false; this.undoStack = [];
    this.redoStack = []; this.results = new Map(); this.resultOrder = [];
    this.selectedResultId = null; this.comparison = []; this.activeJob = null;
    this.pollGeneration = 0; this.resultPage = 1; this.resultPageSize = 20; this.resultTotal = 0;
  }
  replaceDocument(value, { clean = false } = {}) {
    this.document = structuredClone(value || blankDocument()); this.undoStack = []; this.redoStack = [];
    this.dirty = !clean; this.dispatchEvent(new CustomEvent("document-changed", { detail: { replace: true } }));
  }
  edit(mutator, label = "Edit scenario") {
    this.undoStack.push({ document: structuredClone(this.document), label });
    if (this.undoStack.length > 60) this.undoStack.shift();
    this.redoStack = []; mutator(this.document); this.dirty = true;
    this.dispatchEvent(new CustomEvent("document-changed", { detail: { label } }));
  }
  undo() {
    const previous = this.undoStack.pop(); if (!previous) return;
    this.redoStack.push({ document: structuredClone(this.document), label: previous.label });
    this.document = previous.document; this.dirty = true;
    this.dispatchEvent(new CustomEvent("document-changed", { detail: { label: `Undo ${previous.label}` } }));
  }
  redo() {
    const next = this.redoStack.pop(); if (!next) return;
    this.undoStack.push({ document: structuredClone(this.document), label: next.label });
    this.document = next.document; this.dirty = true;
    this.dispatchEvent(new CustomEvent("document-changed", { detail: { label: `Redo ${next.label}` } }));
  }
  markSaved(scenario) {
    this.activeScenario = scenario; this.document = structuredClone(scenario.document);
    this.dirty = false; this.undoStack = []; this.redoStack = [];
    this.dispatchEvent(new CustomEvent("scenario-saved"));
    this.dispatchEvent(new CustomEvent("document-changed", { detail: { replace: true } }));
  }
  reset() { this.activeScenario = null; this.replaceDocument(blankDocument()); }
}

export const workspace = new WorkspaceState();
export { blankDocument };
