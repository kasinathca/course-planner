import { initDataWorkspace } from "./modules/data.js?v=0.5.0";
import { initNavigation } from "./navigation.js?v=0.5.0b";
import { initPlanner } from "./modules/planner.js?v=0.5.0b";
import { initScenarios } from "./modules/scenarios.js?v=0.5.0b";
import { api } from "./api.js";
import { workspace } from "./state.js";

async function start() {
  initNavigation();
  initDataWorkspace();
  initPlanner();
  initScenarios();
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
