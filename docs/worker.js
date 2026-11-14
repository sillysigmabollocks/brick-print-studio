"use strict";

const runtime = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const catalog = "https://raw.githubusercontent.com/sillysigmabollocks/brick-print-studio/refs/heads/browser-assets/";
const cacheName = "brick-print-studio-catalog-v1";
const report = message => self.postMessage({type: "progress", message});
let engine;

async function prepare() {
  report("Checking the latest published catalog…");
  const response = await fetch(catalog + "manifest.json?engine=2", {cache: "no-cache"});
  if (response.status === 404) throw new Error("The first catalog publish is still pending. Check the repository’s browser assets workflow and try again.");
  if (!response.ok) throw new Error("Could not load the catalog index (HTTP " + response.status + ").");
  const manifest = await response.json();
  if (!manifest["engine-v2.zip"]) throw new Error("The updated print engine is still publishing. Try Generate again in a few minutes.");
  const cache = await self.caches?.open(cacheName).catch(() => null);
  const used = new Set();
  async function file(name) {
    const digest = manifest[name];
    if (!/^[a-f0-9]{64}$/.test(digest ?? "")) throw new Error("Catalog index is missing " + name);
    const key = catalog + name + "?sha256=" + digest;
    used.add(key);
    let source = await cache?.match(key);
    if (!source) {
      source = await fetch(key);
      if (!source.ok) throw new Error("Could not download " + name + " (HTTP " + source.status + ").");
      const bytes = await source.arrayBuffer();
      const hash = await crypto.subtle.digest("SHA-256", bytes);
      const actual = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
      if (actual !== digest) throw new Error("The catalog changed during download. Please try again.");
      await cache?.put(key, new Response(bytes)).catch(() => {});
      return new Uint8Array(bytes);
    }
    return new Uint8Array(await source.arrayBuffer());
  }

  report("Loading the browser print engine…");
  let py;
  try {
    const {loadPyodide} = await import(runtime + "pyodide.mjs");
    py = await loadPyodide({indexURL: runtime});
    await py.loadPackage(["numpy", "scipy", "shapely", "httpx"]);
  } catch (error) {
    console.error("Could not initialize the print engine", error);
    throw new Error("The browser could not load the print engine from jsDelivr. Try Generate again, or use the GitHub Actions generator.");
  }
  for (const wheel of ["trimesh-5.2.1-py3-none-any.whl", "networkx-3.4.2-py3-none-any.whl"]) {
    py.unpackArchive(await file(wheel), "zip", {extractDir: py.runPython(
      "import sysconfig; sysconfig.get_path('purelib')"
    )});
  }
  py.unpackArchive(await file("engine-v2.zip"), "zip", {extractDir: "/"});
  const directory = "/print-data/catalog/";
  py.FS.mkdirTree(directory);
  for (const name of ["sets", "inventories", "inventory_parts", "inventory_sets",
    "inventory_minifigs", "parts", "part_categories", "colors"]) {
    report("Loading Rebrickable catalog · " + name);
    py.FS.writeFile(directory + name + ".csv.gz", await file(name + ".csv.gz"));
  }
  const chunks = Object.keys(manifest).filter(name => /^ldraw-\d+$/.test(name)).sort();
  if (!chunks.length) throw new Error("The published LDraw archive is missing.");
  const archive = py.FS.open(directory + "complete.zip", "w");
  try {
    for (const [index, name] of chunks.entries()) {
      report(`Loading LDraw models · ${index + 1} of ${chunks.length}`);
      const bytes = await file(name);
      py.FS.write(archive, bytes, 0, bytes.length);
    }
  } finally {
    py.FS.close(archive);
  }
  if (cache) await Promise.all((await cache.keys()).filter(key => !used.has(key.url)).map(key => cache.delete(key)));
  return py;
}

self.onmessage = async ({data}) => {
  try {
    if (!engine) engine = await prepare();
    engine.globals.set("set_id", data.set);
    engine.globals.set("plate_limit", data.limit);
    engine.globals.set("fit_test", data.calibration);
    engine.globals.set("group_by_color", data.groupByColor);
    engine.globals.set("include_minifigures", data.includeMinifigures);
    engine.globals.set("include_projectiles", data.includeProjectiles);
    engine.globals.set("report", report);
    const result = JSON.parse(engine.runPython(
      "import sys; sys.path.insert(0, chr(47)); from brickprint.browser import generate; " +
      "generate(set_id, plate_limit, fit_test, report, group_by_color=group_by_color, " +
      "include_minifigures=include_minifigures, include_projectiles=include_projectiles)"
    ));
    const bytes = engine.FS.readFile("/print-export.zip");
    engine.FS.unlink("/print-export.zip");
    self.postMessage({type: "complete", result, bytes: bytes.buffer}, [bytes.buffer]);
  } catch (error) {
    self.postMessage({type: "error", message: String(error.message || error).split("\n").filter(Boolean).at(-1)});
  }
};
