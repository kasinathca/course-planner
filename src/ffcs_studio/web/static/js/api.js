const csrfToken = document.querySelector('meta[name="ffcs-csrf"]').content;

export class ApiError extends Error {
  constructor(response, payload) {
    super(payload?.error?.message || `Request failed with HTTP ${response.status}`);
    this.status = response.status;
    this.payload = payload;
  }
}

export async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  const request = { method: options.method || "GET", headers, cache: "no-store", signal: options.signal };
  if (!["GET", "HEAD"].includes(request.method)) headers.set("X-FFCS-CSRF", csrfToken);
  if (options.json !== undefined) {
    headers.set("Content-Type", "application/json");
    request.body = JSON.stringify(options.json);
  } else if (options.body !== undefined) request.body = options.body;
  const response = await fetch(path, request);
  let payload = null;
  try { payload = await response.json(); } catch (_error) { /* non-JSON response */ }
  if (!response.ok) throw new ApiError(response, payload);
  return payload;
}

export function downloadObject(value, filename, type = "application/json") {
  const content = type === "application/json" ? JSON.stringify(value, null, 2) : value;
  const url = URL.createObjectURL(new Blob([content], { type: `${type};charset=utf-8` }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function textElement(tag, text, className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

export function option(value, label) {
  const element = document.createElement("option");
  element.value = value;
  element.textContent = label;
  return element;
}
