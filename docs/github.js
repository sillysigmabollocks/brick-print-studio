"use strict";

const pagesDomain = location.hostname.match(/^([a-z0-9-]+)\.github\.io$/i);
if (pagesDomain) {
  const owner = pagesDomain[1];
  const project = location.pathname.split("/").filter(Boolean)[0];
  const repository = !project || project === "index.html" ? location.hostname : project;
  if (/^[\w.-]+$/.test(repository)) {
    const generator = document.getElementById("generate");
    generator.href = `https://github.com/${owner}/${repository}/actions/workflows/generate.yml`;
    generator.hidden = false;
    document.getElementById("setup").hidden = true;
  }
}
