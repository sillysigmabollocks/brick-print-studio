# Run Brick Print Studio on GitHub

The GitHub Pages site can start and monitor the generator directly for this repository. GitHub Actions runs the Python code and makes the print ZIP available in the workflow summary. Once set up, all printing jobs can be started from a browser.

## One-time setup

Create a new GitHub repository for Brick Print Studio and commit the contents of this folder at its root. Include the hidden `.github` directory and its workflow. The Pages route below uses a public repository on GitHub Free. Choose visibility yourself before pushing. Keep local work, print ZIPs, source catalogs, and other data out of the repository.

If you use Git and the GitHub CLI, extract this package and run these commands from the `lego-print-studio` folder on your computer. The `gh auth` commands use GitHub’s browser sign-in.

```sh
gh auth login --web --git-protocol https
gh auth refresh -h github.com -s workflow
git init -b main
git add .
git commit -m "Add Brick Print Studio and GitHub generator"
gh repo create brick-print-studio --public --source=. --remote=origin --push
```

Then open the repository’s **Settings → Pages**. Select **Deploy from a branch**, select **main** and **/docs**, and click **Save**. Bookmark the URL shown in Pages once deployment succeeds. You can also run the generator through **Actions → Generate Print ZIP** as soon as the workflow is on the default branch.

## Generate in your browser

Open [the browser generator](https://sillysigmabollocks.github.io/brick-print-studio/browser.html), enter a set number or link, and select **Generate Print ZIP**. Your browser creates the ZIP and shows the download on the same page. The first run downloads about 160 MB of Rebrickable catalog and LDraw model data, plus the Python runtime. The browser caches the catalog and model files when site storage is available. The **Build browser generator assets** workflow refreshes those files weekly.

## Develop the browser page

Use Node 22.12 or newer. From the repository root, install the web dependencies and start the Vite development server:

```sh
npm --prefix studio ci
npm --prefix studio run dev
```

Open the URL Vite prints. Run `npm --prefix studio run build` after editing the React frontend. It writes the compiled browser page and its versioned assets to `docs/browser.html` and `docs/showcase/`. Commit those files with the source changes so the existing Pages deployment serves the new build. The browser page loads the same print worker and catalog as before.

## Generate with GitHub Actions

1. Open the webpage and paste a LEGO set number or a link from LEGO, BrickLink, Rebrickable, or Brickset.
2. Under **Connect GitHub**, paste a fine-grained personal access token scoped only to `brick-print-studio`, with **Actions → Read and write**. The page sends it directly to GitHub. Select **Remember token on this browser** before generating to save it before the request is sent. The saved token is accessible to pages on the same GitHub Pages origin. Use **Disconnect and forget token** to clear it from this browser.
3. Select **Generate Print ZIP**. Once the run completes, download the ZIP on the same page. If the browser blocks the direct download, use **Download via GitHub**. Artifacts are retained for seven days.
4. Open the 3MF files under `Printing_Batches` in your slicer. Review flagged meshes and the unplaced-quantity report.

The published page targets `sillysigmabollocks/brick-print-studio` on `main`. For a separate deployment, change the repository URLs in `docs/github.js`. The **Actions → Generate Print ZIP** form also works directly after GitHub sign-in.

The GitHub-hosted run uses the repository’s current code and downloads its catalog inputs during the run. The original local launcher is included.
