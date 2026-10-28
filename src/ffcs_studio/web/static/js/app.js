import { initDataWorkspace } from "./modules/data.js?v=0.7.0";
import { initNavigation } from "./navigation.js?v=0.7.0";
import { initPlanner } from "./modules/planner.js?v=0.7.0";
import { initScenarios } from "./modules/scenarios.js?v=0.7.0";
import { initInteroperability } from "./modules/interoperability.js?v=0.7.0";
import { initDegreePlanner } from "./modules/degree.js?v=0.7.0";
import { api } from "./api.js";
import { workspace } from "./state.js";

async function start() {
  initNavigation();
  initDataWorkspace();
  initPlanner();
  initScenarios();
  initInteroperability();
  initDegreePlanner();
  try {
    const health = await api("/health");
    const status = document.querySelector("#health-text");
    status.textContent = health.status === "ready" ? "Local service ready" : "Local service unavailable";
    status.className = `health-state ${health.status === "ready" ? "ready" : "error"}`;
  } catch (_error) {
    const status = document.querySelector("#health-text");
    status.textContent = "Local service check failed";
    status.className = "health-state error";
  }
  workspace.dispatchEvent(new CustomEvent("refresh-overview"));
}

start();
