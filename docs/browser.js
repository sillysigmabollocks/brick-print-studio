"use strict";

const byId = id => document.getElementById(id);
const form = byId("generate");
const generate = form.querySelector("button[type=submit]");
const download = byId("download");
const status = byId("status");
const error = byId("error");
let worker;
let objectUrl;

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
  error.textContent = message;
  error.hidden = !message;
}

function startWorker() {
  const instance = new Worker("./worker.js?v=browser-1");
  instance.onmessage = ({data}) => {
    if (data.type === "progress") {
      status.textContent = data.message;
      return;
    }
    generate.disabled = false;
    if (data.type === "error") {
      status.textContent = "Could not generate the print ZIP.";
      showError(data.message);
      return;
    }
    const summary = data.result;
    status.textContent = `${summary.plates} plates · ${summary.checked + summary.review} of ${summary.required} copies placed · ${summary.missing} unplaced.`;
    objectUrl = URL.createObjectURL(new Blob([data.bytes], {type: "application/zip"}));
    download.href = objectUrl;
    download.download = summary.filename;
    download.hidden = false;
  };
  instance.onerror = () => {
    instance.terminate();
    worker = null;
    generate.disabled = false;
    status.textContent = "Could not start the browser print engine.";
    showError("Reload the page and try again, or use the GitHub Actions generator.");
  };
  return instance;
}

form.addEventListener("submit", event => {
  event.preventDefault();
  if (generate.disabled) return;
  showError();
  try {
    const set = setNumber(byId("set").value);
    if (!worker) worker = startWorker();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
    download.hidden = true;
    generate.disabled = true;
    status.textContent = `Preparing set ${set}…`;
    worker.postMessage({set, limit: Number(byId("limit").value), calibration: byId("calibration").checked});
  } catch (problem) {
    generate.disabled = false;
    showError(problem.message);
  }
});
