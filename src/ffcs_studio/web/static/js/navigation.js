import { workspace } from "./state.js";

const titles = { overview: "Overview", courses: "Courses & Data", planner: "Timetable Planner", degree: "Degree Planner", scenarios: "Scenarios" };

export function initNavigation() {
  window.addEventListener("hashchange", showRoute);
  window.addEventListener("beforeunload", (event) => {
    if (!workspace.dirty && !workspace.activeJob) return;
    event.preventDefault(); event.returnValue = "";
  });
  showRoute();
}

function showRoute() {
  const route = location.hash.slice(1) || "overview";
  const current = document.querySelector("[data-route][aria-current='page']")?.dataset.route;
  const selected = titles[route] ? route : (current || "overview");
  for (const view of document.querySelectorAll("[data-view]")) view.hidden = view.dataset.view !== selected;
  for (const link of document.querySelectorAll("[data-route]")) {
    if (link.dataset.route === selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.title = `${titles[selected]} · FFCS Studio`;
  if (selected === "scenarios") workspace.dispatchEvent(new CustomEvent("refresh-scenarios"));
  if (selected === "overview") workspace.dispatchEvent(new CustomEvent("refresh-overview"));
}
