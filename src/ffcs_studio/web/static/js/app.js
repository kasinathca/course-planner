const statusText = document.querySelector("#health-text");
const statusDot = document.querySelector("#health-dot");

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
