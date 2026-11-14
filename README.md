# Brick Print Studio

For browser-based jobs with no local Python setup, see [Run on GitHub](GITHUB.md).
Enter an official LEGO set number, then download a ZIP of the models that can be matched and converted. The app runs on your computer. It uses Rebrickable's official catalog downloads and LDraw's official model archive without an account or API key.

## Start on a Mac

1. Install Python 3.11 or 3.12 from [python.org](https://www.python.org/downloads/macos/).
2. Unzip the project and open the `lego-print-studio` folder.
3. Open `Start.command` and leave the Terminal window open. This installs the dependencies on first launch and opens the app. If you prefer Terminal, open it in this folder and run `bash Start.command`.
4. Go to [127.0.0.1:8765](http://127.0.0.1:8765) if the browser does not open. Enter a set number such as `60000-1` and click **Generate Printable Set**.

On Windows, install Python 3.11 or 3.12 with the Python launcher, unzip, and double-click `Start-Windows.cmd`. Unused browser tabs can be closed while a job runs. If you close the app, reopen it to resume in-progress jobs.

### Start manually

macOS or Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m brickprint
```

Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m brickprint
```

Use `--port 8766` if port 8765 is occupied. `--no-browser` skips browser launch. Run one server per data directory. Use the `BRICKPRINT_DATA_DIR` environment variable to choose another directory.

## Generate and print

- Use the full set number when the catalog offers multiple versions. The first job downloads roughly 156 MB of catalog and model data. Subsequent jobs use the local copies.
- A set's catalog piece count comes from Rebrickable. **Pieces to source** counts only required parts after exclusions. It can differ from the catalog total.
- Print plates are enabled by default. Use **Printing options** to change the maximum number of pieces per plate, turn off plates, or include the fit test.
- Click **Download Print ZIP** and unzip. Go to `Printing_Batches` and import a `Plate_*.3mf` into an empty slicer plate. Each file holds a single LEGO color, with all assigned designs and copies placed as separate objects. If the pieces exceed the bed or plate limit, the remaining copies go in additional 3MFs for the same color. Use a separate slicer plate for each file. The layout manifest records each plate’s color and the pieces on it.
- The results show copies placed and unplaced across the whole set. In the ZIP, `Printing_Batches/plate_counts.csv` lists the expected count for each file and `quantity_check.csv` reconciles the exact required, checked, review and unplaced counts for each part and color. The STL fallback and 3MF in the same row are two formats of the same plate.
- If a 3MF import loses copies or positions, use the matching file under `Printing_Batches/STL_Fallback` instead. This is a single STL containing all the placed copies for that plate. Import it at 100% as millimeters.
- Files ending in `_Review.3mf` include one or more flagged meshes. The manifest identifies the flagged objects so you can inspect and repair them in your slicer. Unavailable models and parts that cannot fit are listed in the reports. The `STL` folder contains individual designs for editing or replacing a model.
- To upgrade, close the old app, extract this project over the old source folder while keeping your `data` folder, and relaunch. Run the same set again to generate the new files from the cached models and catalog.

### Elegoo Centauri Carbon 2

The layout uses the official 256 × 256 × 256 mm machine profile, its front-right exclusion zone, 5 mm bed margins and 5 mm spacing. Placement uses conservative bounding rectangles and may rotate a part 90° around the vertical axis. It does not tilt the part or calculate supports. Allow extra clearance for brims and supports when slicing.

The supplied recommendation is PLA with the official `0.12mm Fine @Elegoo CC2 0.4 nozzle` process and the matching printer and filament presets. Use supports in critical regions when needed. Check each part's orientation, wall paths and support contact in the slicer. Print the optional two-piece fit check and compare the stud and underside engagement against genuine pieces before printing a full set. Only adjust compensation after measuring. Printed tolerances depend on the printer, nozzle and filament.

To customize, copy `brickprint/printer_profile.json` to `data/print_profile.json` and edit the nozzle, material, layer height, process, supports, margin or spacing. Restart the app. The selected layer height must be supported by your installed slicer profile. The app validates basic numeric bounds, while the slicer controls the final printing settings.

## What is in the ZIP

```text
LEGO_Set_<set number>/
  inventory.csv
  inventory.json
  print_profile.json
  STL/
  Printing_Batches/
    START_HERE.txt
    batch_layouts.json
    plate_counts.csv
    quantity_check.csv
    Plate_*.3mf
    STL_Fallback/
  Reports/
    missing_parts.csv
    excluded_items.csv
    validation_report.json
    attribution.json
    LDraw license files
  Calibration/            optional
  README.txt
```

An STL is generated once per resolved geometry and reused across colors and catalog aliases. The validation report names the source design, mapping evidence, mesh dimensions, repairs, warnings, and source credits. **Mesh checked** means the part passed basic mesh checks. **Needs review** means a usable surface was exported with warnings, for example an open seam or multiple shells. It stays in the STL folder and is included on its color’s plate when it fits. **Unavailable** identifies a missing model, unresolved ID, unsupported geometry, or failed scale check. Missing parts and batch skips have separate reports.

## Sources, licensing, and coverage

| Source | Verified capability and project decision |
|---|---|
| [Rebrickable downloads](https://rebrickable.com/downloads/) and [API documentation](https://rebrickable.com/api/v3/docs/) | Official downloadable sets, inventories, parts, colors, categories, nested sets and figure listings. The API requires a key and recommends CSV downloads where possible. The app reads the bulk files locally and attributes the inventory. See [Rebrickable’s terms](https://rebrickable.com/terms/). |
| [BrickLink subsets API](https://www.bricklink.com/v3/api.page?page=get-subsets) and [authentication](https://www.bricklink.com/v3/api.page?page=auth) | Official catalog subsets support figure breakdown controls. Authentication uses OAuth 1. The implemented inventory source is Rebrickable. |
| [Mecabricks Workshop export](https://stage.mecabricks.com/en/forum/discussions/63c9d6455ca7e62179f35958) | Mecabricks documents member-facing STL export in the Workshop. A supported public bulk geometry API and permission to automate the export could not be verified. Authorized local Workshop exports can take priority over LDraw. |
| [LDraw downloads](https://library.ldraw.org/updates), [file format](https://ldraw.org/article/218.html), and [licensing](https://www.ldraw.org/docs-main/licenses/legal-info.html) | The official parts archive supplies hierarchical CAD surfaces. Conversion uses 0.4 mm per LDraw unit. The converter checks source-file license headers and includes author, contributor, license and change details in the ZIP. |

Rebrickable catalogs figure assemblies separately. The app skips the figure inventories entirely and also filters dedicated figure categories, including weapons and gear categorized as minifigure accessories. An ordinary building part listed in the set inventory stays included even when the same design appears in a figure inventory. Verified dual-use building designs, including the stud-connected 4599a and 4599b taps, are preserved when the catalog groups them with accessories. Unclassified catalog entries are excluded with a reason. An uncategorized accessory can only be identified from available metadata. Spare pieces, sticker sheets, instructions, packaging, and catalog rows for paper, fabric, metal or electronics are excluded. Printed graphics, stock colors, electronic functions and flexible material behavior are outside the geometry export.

Geometry lookup uses exact IDs, LDraw's explicit BrickLink and Rebrickable cross-references, and official identity aliases. It requires a unique match or a confirmed exact ID. It never strips variant suffixes or selects a nearest-looking shape. Some official files represent assemblies, surface-only geometry, textures or obsolete models. Textured dependencies and unresolvable IDs are reported. Verified brick, plate and panel designs receive planar seam repair that preserves their stud and tube surfaces. Other models get conservative weld, winding and edge cleanup. The checks cover basic mesh topology, scale plausibility and reference dimensions for common designs. They do not certify self-intersections, printing clearance, wall thickness or clutch fit.

For printer specifications see [Elegoo](https://www.elegoo.com/products/centauri-carbon-2), the [official ElegooSlicer machine profile](https://github.com/elegooofficial/ElegooSlicer/blob/main/resources/profiles/Elegoo/machine/ECC2/Elegoo%20Centauri%20Carbon%202%200.4%20nozzle.json), and its [0.12 mm process](https://github.com/elegooofficial/ElegooSlicer/blob/main/resources/profiles/Elegoo/process/ECC2/0.12mm%20Fine%20%40Elegoo%20CC2%200.4%20nozzle.json).

### Optional explicit mappings and local exports

The standard workflow needs no custom configuration. If you have a known exact match or a model you are authorized to convert, place the file under `data/local_models/` and create `data/model_sources.json`. Example fields:

```json
{
  "3005": {
    "source": "Mecabricks",
    "file": "3005-export.stl",
    "mm_per_unit": 1,
    "expected_mm": [8, 8, 11.2],
    "permission": "Describe the actual license or permission for this export",
    "credit": "Name the author and model source",
    "ldraw_id": "3005"
  }
}
```

Use measured source dimensions to set `mm_per_unit` correctly. The values above illustrate the format. Local STL, OBJ and PLY meshes are supported. Source credit and permission information are included in reports. You can specify only `ldraw_id` when correcting a mapping to an official exact match. Start a new job after editing mappings.

## Caches and tests

- `data/catalog/` stores official downloads. To refresh, stop the app, remove that subfolder, reopen the app, and submit a new job.
- `data/model_cache/` stores converted models keyed by source and converter version. `data/jobs.sqlite3` records the queue and per-design progress. `data/output/` contains each run and its ZIP. Interrupted jobs recover automatically. **Resume job** retries a failed run and uses completed checkpoints. A download interrupted before finishing restarts that archive.
- Install `requirements-test.txt` and run `python -m pytest -q` inside the project. Use `BRICKPRINT_TEST_CATALOG` to point at a populated `data/catalog/` directory and include the live-catalog integration test. Tests cover filtering and quantities, mapping, STL conversion and dimensions, retries, caching, resumption, missing-part reports, ZIP output and plate placement.
