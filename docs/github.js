"use strict";

const byId = id => document.getElementById(id);
const api = "https://api.github.com/repos/sillysigmabollocks/brick-print-studio";
const github = "https://github.com/sillysigmabollocks/brick-print-studio";
const form = byId("generate");
const input = byId("token");
const download = byId("download");
const artifactLink = byId("artifact-link");
const runLink = byId("run-link");

const remember = byId("remember-token");
const storageKey = "brick-print-studio:github-actions-token";
const validToken = value => /^github_pat_[A-Za-z0-9_]+$/.test(value);
let token = "";
let savedToken = "";
let artifact = null;
let busy = false;

function setNumber(value) {
  const cleaned = value.trim();
  if (/^\d{3,10}(?:-\d{1,4})?$/.test(cleaned)) return cleaned;
  let url;
  try {
    url = new URL(cleaned.includes("://") ? cleaned : "https://" + cleaned);
  } catch {
    throw new Error("Enter a set number such as 75328-1 or a supported set link.");
  }
  if (url.protocol !== "https:" || url.username || url.password) {
    throw new Error("Use a public HTTPS set link.");
  }
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  let match;
  if (host === "lego.com") {
    match = url.pathname.match(/\/(?:product\/[^/]*-|buildinginstructions\/)(\d{3,10})\/?$/i);
  } else if (host === "bricklink.com") {
    match = (url.searchParams.get("S") ?? url.searchParams.get("s") ?? "").match(/^(\d{3,10}(?:-\d{1,4})?)$/);
  } else if (host === "rebrickable.com" || host === "brickset.com") {
    match = url.pathname.match(/^\/sets?\/(\d{3,10}(?:-\d{1,4})?)(?:\/|$)/i);
  }
  if (!match) throw new Error("Enter a set number or a set page from LEGO, BrickLink, Rebrickable, or Brickset.");
  return match[1];
}

function showError(message = "") {
  byId("error").textContent = message;
  byId("error").hidden = !message;
}

function connectionState(connected) {
  const title = savedToken && savedToken === token ? "GitHub token remembered"
    : connected ? "GitHub connected for this tab" : "Connect GitHub for this tab";
  byId("connection-title").textContent = title;
  byId("disconnect").hidden = !connected;
  if (!connected) byId("connection").open = true;
}

function storageNote(message = "") {
  byId("storage-note").textContent = message;
  byId("storage-note").hidden = !message;
}

function forgetSavedToken() {
  try {
    localStorage.removeItem(storageKey);
    savedToken = "";
    storageNote();
  } catch {
    storageNote("This browser blocked removal. Clear this site's data to remove any saved token.");
  }
}

function saveToken() {
  try {
    localStorage.setItem(storageKey, token);
    savedToken = token;
    storageNote();
  } catch {
    storageNote("This browser blocked saving. The token is available for this tab.");
  }
}

try {
  savedToken = localStorage.getItem(storageKey) || "";
  if (validToken(savedToken)) {
    token = savedToken;
    remember.checked = true;
    connectionState(true);
    byId("connection").open = false;
  } else if (savedToken) {
    forgetSavedToken();
  }
} catch {
  storageNote("This browser blocked access to saved site data.");
}

remember.addEventListener("change", () => {
  if (remember.checked) {
    const entered = input.value.trim();
    const candidate = entered || token;
    if (validToken(candidate)) {
      token = candidate;
      saveToken();
      connectionState(true);
    }
  } else {
    forgetSavedToken();
    connectionState(Boolean(token));
  }
});

async function request(path, options = {}, artifactDownload = false) {
  const headers = {
    Accept: "application/vnd.github+json",
    Authorization: "Bearer " + token,
  };
  if (!artifactDownload) headers["X-GitHub-Api-Version"] = "2026-03-10";
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(api + path, {
    ...options, headers, credentials: "omit", cache: "no-store", referrerPolicy: "no-referrer",
  });
  if (response.status === 401) {
    if (savedToken && savedToken === token) forgetSavedToken();
    token = "";
    input.value = "";
    connectionState(false);
    throw new Error("GitHub rejected the token. Enter a new fine-grained token.");
  }
  if (response.status === 403 || response.status === 404) {
    throw new Error("GitHub denied access. Check that the token is for brick-print-studio and grants Actions read and write.");
  }
  if (response.status === 422) {
    const details = await response.json().catch(() => null);
    const message = typeof details?.message === "string"
      ? details.message.replaceAll(token, "[redacted]").slice(0, 300) : "";
    throw new Error("GitHub rejected the request (422)." + (message ? " " + message : ""));
  }
  if (!response.ok) throw new Error("GitHub returned an error (" + response.status + "). Check the run details or try again.");
  return response;
}

async function watchRun(runId) {
  runLink.href = github + "/actions/runs/" + runId;
  runLink.hidden = false;
  const runPath = "/actions/runs/" + runId;
  for (let attempt = 0; attempt < 230; attempt += 1) {
    const run = await request(runPath).then(response => response.json());
    if (run.status === "completed") {
      if (run.conclusion !== "success") throw new Error("GitHub finished with status: " + run.conclusion + ". Open the run details for the error.");
      const result = await request(runPath + "/artifacts").then(response => response.json());
      const zip = result.artifacts.find(item => !item.expired && /^LEGO_Set_[A-Z0-9-]+\.zip$/i.test(item.name));
      if (!zip || !Number.isSafeInteger(zip.id)) throw new Error("The print ZIP could not be found. Check the run details.");
      artifact = zip;
      artifactLink.href = runLink.href + "/artifacts/" + zip.id;
      artifactLink.hidden = false;
      download.hidden = false;
      byId("print-help").hidden = false;
      byId("status").textContent = "Your print ZIP is ready.";
      return;
    }
    byId("status").textContent = run.status === "in_progress" ? "Building 3MF plates…" : "Waiting for a GitHub runner…";
    await new Promise(resolve => setTimeout(resolve, 8000));
  }
  throw new Error("This run is taking longer than expected. You can follow it through View run details.");
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (busy) return;
  showError();
  let set;
  try {
    set = setNumber(byId("set").value);
  } catch (error) {
    showError(error.message);
    return;
  }
  const entered = input.value.trim();
  if (entered) {
    if (!validToken(entered)) {
      showError("Use a fine-grained token beginning with github_pat_.");
      return;
    }
    token = entered;
  }
  if (!token) {
    byId("connection").open = true;
    input.focus();
    showError("Connect GitHub to start a print job.");
    return;
  }
  if (remember.checked) saveToken();
  input.value = "";
  connectionState(true);
  if (byId("storage-note").hidden) byId("connection").open = false;
  busy = true;
  const button = form.querySelector(".start-job");
  button.disabled = true;
  byId("disconnect").disabled = true;
  input.disabled = remember.disabled = true;
  download.hidden = artifactLink.hidden = runLink.hidden = byId("print-help").hidden = true;
  artifact = null;
  byId("status").textContent = "Starting set " + set + "…";
  try {
    const dispatch = await request("/actions/workflows/generate.yml/dispatches", {
      method: "POST",
      body: JSON.stringify({ref: "main", inputs: {
        set_number: set,
        max_per_plate: byId("limit").value,
        calibration: String(byId("calibration").checked),
      }}),
    });
    const {workflow_run_id: runId} = dispatch.status === 204 ? {} : await dispatch.json();
    if (!Number.isSafeInteger(runId) || runId < 1) {
      runLink.href = github + "/actions/workflows/generate.yml";
      runLink.hidden = false;
      throw new Error("GitHub accepted the job without returning a run ID. Find it in the workflow runs.");
    }
    await watchRun(runId);
  } catch (error) {
    byId("status").textContent = "Unable to show the print ZIP.";
    showError(error.message);
    if (runLink.hidden) {
      runLink.href = github + "/actions/workflows/generate.yml";
      runLink.hidden = false;
    }
  } finally {
    busy = false;
    button.disabled = false;
    byId("disconnect").disabled = false;
    input.disabled = remember.disabled = false;
  }
});

byId("disconnect").addEventListener("click", () => {
  token = "";
  input.value = "";
  remember.checked = false;
  forgetSavedToken();
  connectionState(false);
});

download.addEventListener("click", async () => {
  if (!artifact) return;
  download.disabled = true;
  showError();
  try {
    if (!token) throw new Error("Reconnect GitHub to download directly.");
    const response = await request("/actions/artifacts/" + artifact.id + "/zip", {}, true);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = artifact.name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  } catch {
    showError("The browser could not download the ZIP directly. Use Download via GitHub.");
  } finally {
    download.disabled = false;
  }
});
