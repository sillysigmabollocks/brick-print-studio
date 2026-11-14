"use strict";
const byId = id => document.getElementById(id);
const pretty = value => Number(value).toLocaleString();
const statusLabels = {checked: "Mesh checked", review: "Needs review", unavailable: "Unavailable"};
let selectedJob = "";
let snapshot;
let timer;
let tableSignature = "";

async function api(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Check the form and try again.");
  return body;
}

function element(tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
}

async function history(existingJobs) {
  const jobs = existingJobs || await api("/api/jobs");
  const list = byId("history-list");
  if (!jobs.length) return;
  list.replaceChildren(...jobs.map(job => {
    const button = element("button", job.set_name || job.request);
    button.type = "button";
    button.append(element("small", job.request + " · " + job.state));
    button.addEventListener("click", () => select(job.id));
    return button;
  }));
}

function drawParts() {
  if (!snapshot) return;
  const query = byId("filter").value.trim().toLowerCase();
  const filtered = snapshot.parts.filter(part => [part.part_number, part.part_name, part.color,
    statusLabels[part.validation_status] || "pending"].some(value => value.toLowerCase().includes(query)));
  if (!filtered.length) {
    const message = element("td", "No matching parts.");
    message.colSpan = 4;
    const row = document.createElement("tr");
    row.append(message);
    byId("parts").replaceChildren(row);
    return;
  }
  byId("parts").replaceChildren(...filtered.map(part => {
    const row = document.createElement("tr");
    const name = element("td", part.part_number);
    name.append(element("small", part.part_name));
    const status = document.createElement("td");
    status.append(element("span", statusLabels[part.validation_status] || "Pending", "pill " + (part.validation_status || "")));
    if (part.model_source) {
      const origin = part.download_status === "cached" ? " · cached" : "";
      status.append(element("small", part.model_source + origin));
    }
    if (part.validation_status !== "checked" && part.message) status.append(element("small", part.message));
    row.append(name, element("td", part.color), element("td", pretty(part.quantity_required)), status);
    return row;
  }));
}

function render(job) {
  snapshot = job;
  const meta = job.metadata;
  byId("set-id").textContent = meta?.set_number || job.request;
  byId("set-name").textContent = meta?.set_name || "Looking up the set";
  const image = byId("set-image");
  const validImage = meta?.image?.startsWith("https://cdn.rebrickable.com/");
  if (validImage && image.getAttribute("src") !== meta.image) {
    image.hidden = false;
    image.src = meta.image;
  } else if (!validImage) {
    image.hidden = true;
  }
  byId("metrics").hidden = !meta;
  if (meta) {
    byId("catalog-count").textContent = pretty(meta.catalog_piece_count);
    byId("required-count").textContent = pretty(meta.required_quantity);
    byId("design-count").textContent = pretty(meta.unique_parts);
    byId("minifig-count").textContent = pretty(meta.excluded_minifigure_assemblies);
  }
  byId("progress-text").textContent = job.message;
  byId("progress-count").textContent = meta ? pretty(job.processed) + " / " + pretty(meta.unique_parts) : "";
  const progress = byId("progress");
  if (job.state === "complete") progress.value = 100;
  else if (meta?.unique_parts) progress.value = 100 * job.processed / meta.unique_parts;
  else if (job.state === "failed") progress.value = 0;
  else progress.removeAttribute("value");
  byId("status-detail").textContent = meta ? `${job.checked} checked · ${job.review} need review · ${job.missing} unavailable` : "";
  byId("download").hidden = job.state !== "complete";
  byId("download").href = "/api/jobs/" + job.id + "/download";
  byId("resume").hidden = job.state !== "failed";
  byId("plate-count").textContent = job.state === "complete" && job.options.batches ? job.plate_count + " print plates" : "";
  const totals = job.quantity_summary;
  if (totals) {
    byId("plate-count").textContent = `${pretty(job.plate_count)} plates · ${pretty(totals.checked + totals.review)} of ${pretty(totals.required)} copies placed · ${pretty(totals.missing)} unplaced`;
  }
  const plateHelp = byId("plate-help");
  plateHelp.hidden = job.state !== "complete";
  plateHelp.textContent = job.plate_count
    ? "Open one 3MF per empty slicer plate. The filename shows the color and copy count. Inspect files ending in _Review before printing."
    : "This export has no print plates. Generate the set with print plates enabled to pack available models.";
  if (totals?.review) {
    plateHelp.textContent += ` ${pretty(totals.review)} copies have meshes to review.`;
  }
  byId("part-section").hidden = !job.parts.length;
  const signature = job.id + ":" + job.processed + ":" + job.parts.length + ":" + job.state;
  if (tableSignature !== signature) {
    tableSignature = signature;
    drawParts();
  }
}

async function poll(id) {
  try {
    const job = await api("/api/jobs/" + id);
    if (selectedJob !== id) return;
    render(job);
    if (job.state === "queued" || job.state === "running") timer = setTimeout(() => poll(id), 1000);
    else history().catch(() => {});
  } catch (error) {
    if (selectedJob !== id) return;
    byId("progress-text").textContent = "Cannot reach the app. Reconnecting…";
    timer = setTimeout(() => poll(id), 2500);
  }
}

function select(id) {
  clearTimeout(timer);
  selectedJob = id;
  localStorage.setItem("last-job", id);
  byId("results").hidden = false;
  byId("filter").value = "";
  tableSignature = "";
  poll(id);
}

byId("generate").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.submitter;
  const error = byId("form-error");
  error.hidden = true;
  button.disabled = true;
  try {
    const payload = {set_number: byId("set-number").value.trim(), batches: byId("batches").checked,
      max_per_plate: Number(byId("max-per-plate").value || 30), calibration: byId("calibration").checked};
    if (!payload.batches) payload.max_per_plate = 30;
    const job = await api("/api/jobs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    select(job.id);
    history().catch(() => {});
  } catch (problem) {
    error.textContent = problem.message;
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
});
byId("resume").addEventListener("click", async () => {
  try {
    await api("/api/jobs/" + selectedJob + "/resume", {method: "POST"});
    select(selectedJob);
  } catch (error) {
    byId("progress-text").textContent = error.message;
  }
});
byId("filter").addEventListener("input", drawParts);
byId("batches").addEventListener("change", () => { byId("max-per-plate").disabled = !byId("batches").checked; });
byId("set-image").addEventListener("error", () => { byId("set-image").hidden = true; });
api("/api/jobs").then(jobs => {
  const lastId = localStorage.getItem("last-job");
  if (!selectedJob && jobs.some(job => job.id === lastId)) select(lastId);
  return history(jobs);
}).catch(() => {});
api("/api/profile").then(profile => {
  byId("machine").textContent = profile.printer;
  byId("profile").textContent = `${profile.material} · ${profile.nozzle_mm} mm nozzle · ${profile.layer_height_mm} mm layers · ${profile.supports}`;
}).catch(() => {});
