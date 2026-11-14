"""Persistent job queue, geometry cache and export reports."""
import csv
import hashlib
import json
import logging
import shutil
import sqlite3
import threading
import time
import re
import uuid
import zipfile
from contextlib import closing
from pathlib import Path

import numpy as np

from .batches import export_batches
from .geometry import (LDRAW_URL, PIPELINE_VERSION, REFERENCE_SCALE, LDraw, ModelError,
                       digest_file, local_mesh, resolve_config, validate)
from .sources import PART_ID, SET_ID, catalog_paths, fetch, inventory

PROFILE = Path(__file__).with_name('printer_profile.json')
ACTIVE = ('queued', 'running')
LOG = logging.getLogger(__name__)
RESULT_FIELDS = ('model_source', 'stl_filename', 'download_status', 'validation_status', 'message')
INVENTORY_FIELDS = ('part_number', 'part_name', 'color_id', 'color', 'color_hex', 'quantity_required')


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def atomic_bytes(path, contents):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_bytes(contents)
    temp.replace(path)


def json_file(path, content):
    atomic_bytes(path, (json.dumps(content, indent=2, ensure_ascii=False) + '\n').encode())


def csv_file(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            safe = {k: ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r'))
                        and not v.removeprefix('-').isdigit() else v) for k, v in row.items()}
            writer.writerow(safe)


class JobStore:
    def __init__(self, root):
        self.path = root / 'jobs.sqlite3'
        with closing(self.connect()) as conn, conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, request TEXT NOT NULL, state TEXT NOT NULL,
                    message TEXT NOT NULL, options TEXT NOT NULL, created REAL NOT NULL,
                    metadata TEXT, inventory TEXT, excluded TEXT, plate_count INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS progress (
                    job_id TEXT, part TEXT, result TEXT NOT NULL, PRIMARY KEY (job_id, part)
                );
                CREATE TABLE IF NOT EXISTS geometry (
                    key TEXT PRIMARY KEY, result TEXT NOT NULL
                );
            """)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def new(self, request, options):
        job_id = uuid.uuid4().hex
        with closing(self.connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            current = conn.execute("SELECT id FROM jobs WHERE request=? AND options=? AND state IN ('queued','running')",
                                   (request, dump(options))).fetchone()
            if current:
                return current['id']
            conn.execute('INSERT INTO jobs(id,request,state,message,options,created) VALUES(?,?,?,?,?,?)',
                         (job_id, request, 'queued', 'Waiting to start', dump(options), time.time()))
        return job_id

    def update(self, job_id, **columns):
        with closing(self.connect()) as conn, conn:
            conn.execute('UPDATE jobs SET ' + ', '.join(f'{key}=?' for key in columns) + ' WHERE id=?',
                         (*columns.values(), job_id))

    def get(self, job_id):
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            return None
        job = dict(row)
        for key in ('options', 'metadata', 'inventory', 'excluded'):
            job[key] = json.loads(job[key]) if job[key] is not None else None
        return job

    def list(self):
        with closing(self.connect()) as conn:
            jobs = conn.execute('SELECT id,request,state,metadata FROM jobs ORDER BY created DESC LIMIT 20')
            return [dict(id=j['id'], request=j['request'], state=j['state'],
                         set_name=json.loads(j['metadata'])['set_name'] if j['metadata'] else None) for j in jobs]

    def next(self):
        with closing(self.connect()) as conn:
            job = conn.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
        return job['id'] if job else None

    def recover(self):
        with closing(self.connect()) as conn, conn:
            conn.execute("UPDATE jobs SET state='queued', message='Resuming interrupted job' WHERE state='running'")

    def resume(self, job_id):
        with closing(self.connect()) as conn, conn:
            changed = conn.execute("UPDATE jobs SET state='queued', message='Waiting to resume' "
                                   "WHERE id=? AND state='failed'", (job_id,))
            return changed.rowcount > 0

    def results(self, job_id):
        with closing(self.connect()) as conn:
            return {row['part']: json.loads(row['result']) for row in conn.execute(
                'SELECT part,result FROM progress WHERE job_id=? ORDER BY part', (job_id,))}

    def record(self, job_id, part, result):
        with closing(self.connect()) as conn, conn:
            conn.execute('INSERT OR REPLACE INTO progress VALUES(?,?,?)', (job_id, part, dump(result)))

    def get_geometry(self, key):
        with closing(self.connect()) as conn:
            row = conn.execute('SELECT result FROM geometry WHERE key=?', (key,)).fetchone()
        return json.loads(row['result']) if row else None

    def record_geometry(self, key, result):
        with closing(self.connect()) as conn, conn:
            conn.execute('INSERT OR REPLACE INTO geometry VALUES(?,?)', (key, dump(result)))


class JobInterrupted(Exception):
    pass


class Studio:
    def __init__(self, root, downloader=fetch):
        self.root, self.downloader = Path(root), downloader
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog = self.root / 'catalog'
        self.models = self.root / 'model_cache'
        self.models.mkdir(exist_ok=True)
        self.store = JobStore(self.root)
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.worker = None
        self.worker_lock = None
        self.weights = {}
        self.profile = self.read_profile()

    def read_profile(self):
        profile = json.loads(PROFILE.read_text(encoding='utf-8'))
        config = self.root / 'print_profile.json'
        if config.exists():
            overrides = json.loads(config.read_text(encoding='utf-8'))
            for field in ('nozzle_mm','material','layer_height_mm','process','supports','bed_margin_mm','spacing_mm'):
                if field in overrides:
                    profile[field] = overrides[field]
        for field, low, high in (('nozzle_mm', .2, .8), ('layer_height_mm', .05, .48),
                                 ('bed_margin_mm', 0, 35), ('spacing_mm', 2, 35)):
            value = profile[field]
            if not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError(f'Invalid print profile setting {field}.')
        if profile['layer_height_mm'] > .8 * profile['nozzle_mm']:
            raise ValueError('Layer height exceeds 80% of the selected nozzle.')
        return profile

    def start(self):
        lock = sqlite3.connect(self.root / 'worker.sqlite3', timeout=0, check_same_thread=False)
        try:
            lock.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as error:
            lock.close()
            raise RuntimeError('Another Brick Print Studio process is using this data directory.') from error
        self.worker_lock = lock
        try:
            self.store.recover()
            self.stop.clear()
            self.worker = threading.Thread(target=self.loop, name='brickprint-worker', daemon=True)
            self.worker.start()
        except Exception:
            lock.close()
            self.worker_lock = None
            raise

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.worker:
            self.worker.join(timeout=2)

    def enqueue(self, set_number, options):
        set_number = set_number.strip().upper()
        if not SET_ID.fullmatch(set_number):
            raise ValueError('Enter a set number such as 75328-1.')
        job_id = self.store.new(set_number, dict(options, profile=self.profile))
        self.wake.set()
        return job_id

    def loop(self):
        try:
            while not self.stop.is_set():
                job_id = self.store.next()
                if job_id:
                    self.run(job_id)
                else:
                    self.wake.wait(timeout=1)
                    self.wake.clear()
        finally:
            if self.worker_lock:
                self.worker_lock.close()
                self.worker_lock = None

    def snapshot(self, job_id):
        job = self.store.get(job_id)
        if not job:
            return None
        results = self.store.results(job_id)
        rows = job.pop('inventory') or []
        job['parts'] = [{k: v for k, v in (dict(row, **results.get(row['part_number'], {}))).items()
                         if k in (*INVENTORY_FIELDS, *RESULT_FIELDS, 'dimensions_mm')}
                        for row in rows]
        job['excluded_count'] = sum(row['quantity_required'] for row in (job.pop('excluded') or []))
        job['quantity_summary'] = None
        if job['state'] == 'complete' and job['options']['batches']:
            manifest = self.folder(job_id, job['metadata']) / 'Printing_Batches' / 'batch_layouts.json'
            if manifest.is_file():
                job['quantity_summary'] = json.loads(manifest.read_text(encoding='utf-8')).get('quantity_summary')
        job['processed'] = len(results)
        job['checked'] = sum(row['validation_status'] == 'checked' for row in results.values())
        job['review'] = sum(row['validation_status'] == 'review' for row in results.values())
        job['missing'] = sum(row['validation_status'] == 'unavailable' for row in results.values())
        return job

    def run(self, job_id):
        job = self.store.get(job_id)
        self.store.update(job_id, state='running', message='Preparing job')

        def status(message):
            if self.stop.is_set():
                raise JobInterrupted()
            self.store.update(job_id, message=message)

        library = None
        try:
            metadata, rows, excluded = job['metadata'], job['inventory'], job['excluded']
            if metadata is None:
                paths = catalog_paths(self.catalog, status, self.downloader)
                metadata, rows, excluded = inventory(paths, job['request'], status)
                self.store.update(job_id, metadata=dump(metadata), inventory=dump(rows), excluded=dump(excluded))
            config = resolve_config(self.root)
            options = job['options']
            archive_path = self.catalog / 'complete.zip'
            designs = {row['part_number']: row['part_name'] for row in rows}
            calibration_parts = ('3001', '3023') if options['calibration'] else ()
            if (designs or calibration_parts) and not archive_path.exists():
                status('Downloading the official LDraw library for the first time')
                self.downloader(LDRAW_URL, archive_path, status)
            if designs or calibration_parts:
                status('Indexing the official LDraw model library')
                archive_stat = archive_path.stat()
                stamp = (archive_stat.st_size, archive_stat.st_mtime_ns)
                if stamp not in self.weights:
                    self.weights = {stamp: digest_file(archive_path)}
                release_key = self.weights[stamp]
                try:
                    library = LDraw(archive_path)
                except zipfile.BadZipFile as error:
                    raise ValueError(f'LDraw archive is unreadable. Remove {archive_path} and resume.') from error
                library.index()
            results = self.store.results(job_id)
            for index, (part, name) in enumerate(designs.items(), 1):
                result = results.get(part)
                if result and (not result.get('cache_key') or (self.models / (result['cache_key'] + '.stl')).exists()):
                    continue
                status(f'Processing design {index} of {len(designs)} · {part} · {name}')
                result = self.process(part, config, library, release_key)
                self.store.record(job_id, part, result)
                results[part] = result
            status('Preparing inventory and validation reports')
            count = self.export(job_id, metadata, rows, excluded, results, options, status,
                                library, config, release_key if library else '')
            self.store.update(job_id, state='complete', message='Finished', plate_count=count)
        except JobInterrupted:
            self.store.update(job_id, state='queued', message='Paused at the latest checkpoint')
        except Exception as error:
            LOG.exception('Job %s failed', job_id)
            self.store.update(job_id, state='failed', message=str(error) or type(error).__name__)
        finally:
            if library:
                library.close()

    def process(self, part, config, library, release_key):
        try:
            if not PART_ID.fullmatch(part):
                raise ModelError('Catalog part number uses unsupported file characters.')
            override = config.get(part.lower(), {})
            local_file = override.get('file')
            mapping = {part.lower(): override['ldraw_id']} if 'ldraw_id' in override else {}
            attempts = []
            if local_file:
                source = 'Mecabricks (licensed local export)' if override.get('source') == 'Mecabricks' else 'Licensed local export'
                try:
                    return self.cached_model(part, source, None, 'explicit local mapping', override, library, release_key)
                except (ValueError, OSError, RuntimeError, TypeError) as error:
                    attempts.append(f'{source}: {error}')
            try:
                design, evidence = library.resolve(part, mapping)
                result = self.cached_model(part, 'LDraw', design, evidence, override, library, release_key)
                if attempts:
                    result['fallback_details'] = attempts
                return result
            except (ValueError, OSError, RuntimeError, TypeError) as error:
                attempts.append(f'LDraw: {error}')
                raise ModelError(' · '.join(attempts)) from error
        except (ValueError, OSError, RuntimeError, TypeError, IndexError, zipfile.BadZipFile) as error:
            return dict(part_number=part, model_source='', stl_filename='', download_status='unavailable',
                        validation_status='unavailable', message=str(error))

    def cached_model(self, part, source, design, evidence, override, library, release_key):
        local = source != 'LDraw'
        if local:
            directory = (self.root / 'local_models').resolve()
            path = (directory / override['file']).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise ModelError('Mapped local file is missing or outside local_models.')
            if not all(isinstance(override.get(field), str) and override[field].strip() for field in ('permission', 'credit')):
                raise ModelError('Local import requires explicit permission and attribution details.')
            scale = float(override.get('mm_per_unit', 0))
            expected = override.get('expected_mm', REFERENCE_SCALE.get(part))
            if not 0 < scale <= 1000 or not isinstance(expected, list) or len(expected) != 3:
                raise ModelError('A positive mm_per_unit and three reference expected_mm dimensions are required.')
            if not np.isfinite(expected).all() or min(expected) <= 0:
                raise ModelError('Expected dimensions must be positive and finite.')
            fingerprint = [digest_file(path), scale, expected, override['permission'], override['credit'], source]
        else:
            expected = REFERENCE_SCALE.get(part) or REFERENCE_SCALE.get(design)
            fingerprint = [release_key, design, expected]
        key = hashlib.sha256(dump([PIPELINE_VERSION, fingerprint]).encode()).hexdigest()
        stl_path = self.models / f'{key}.stl'
        model = self.store.get_geometry(key)
        is_cached = model is not None and stl_path.is_file()
        if not is_cached:
            if local:
                mesh = local_mesh(path, scale)
                credits = {path.name: {'author': override['credit'], 'permission': override['permission']}}
                notes = []
            else:
                mesh, credits, notes = library.convert(design)
            mesh, report = validate(mesh, expected, mounting_seams=not local and (part in REFERENCE_SCALE or design in REFERENCE_SCALE))
            if notes:
                report['warnings'].extend(notes)
                report['validation_status'] = 'review'
            model = dict(report, source_design=design or path.name, attribution=credits)
            atomic_bytes(stl_path, mesh.export(file_type='stl'))
            self.store.record_geometry(key, model)
        return dict(model, part_number=part, cache_key=key, model_source=source, mapping_evidence=evidence,
                    download_status='cached' if is_cached else 'converted',
                    message=' '.join(model['warnings']) or 'Basic mesh checks passed. Inspect slicing and physical fit.')

    def folder(self, job_id, metadata):
        return self.root / 'output' / job_id / f'LEGO_Set_{metadata["set_number"]}'

    def archive(self, job_id, metadata):
        return self.folder(job_id, metadata).with_suffix('.zip')

    def export(self, job_id, metadata, rows, excluded, results, options, status, library, config, release_key):
        target = self.folder(job_id, metadata)
        stage = target.with_name(target.name + '.working')
        if stage.exists():
            shutil.rmtree(stage)
        for name in ('STL', 'Reports', 'Printing_Batches'):
            (stage / name).mkdir(parents=True, exist_ok=True)
        by_geometry, used_names = {}, set()
        for part, result in results.items():
            key = result.get('cache_key')
            if key:
                if key not in by_geometry:
                    preferred = part
                    filename = f'{preferred}.stl'
                    if filename.casefold() in used_names or re.match(r'^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', preferred, re.I):
                        filename = f'part_{key[:12]}.stl'
                    shutil.copyfile(self.models / f'{key}.stl', stage / 'STL' / filename)
                    by_geometry[key] = filename
                    used_names.add(filename.casefold())
                result['stl_filename'] = by_geometry[key]
                self.store.record(job_id, part, result)
        rich_rows = [dict(row, **{key: results[row['part_number']].get(key, '') for key in RESULT_FIELDS}) for row in rows]
        reports = stage / 'Reports'
        csv_file(stage / 'inventory.csv', rich_rows, (*INVENTORY_FIELDS, *RESULT_FIELDS))
        json_file(stage / 'inventory.json', dict(metadata, parts=rich_rows))
        csv_file(reports / 'missing_parts.csv', (row for row in rich_rows if row['validation_status'] == 'unavailable'),
                 (*INVENTORY_FIELDS, *RESULT_FIELDS))
        csv_file(reports / 'excluded_items.csv', excluded, (*INVENTORY_FIELDS, 'reason'))
        printer = options['profile']
        json_file(stage / 'print_profile.json', printer)
        count = 0
        if options['batches']:
            count = export_batches(stage / 'Printing_Batches', rich_rows, results, printer,
                                   options['max_per_plate'], status)
        if library:
            status('Writing model attribution and license files')
            for filename, contents in library.license_files().items():
                (reports / filename).write_bytes(contents)
        calibration = {}
        if options['calibration']:
            (stage / 'Calibration').mkdir()
            for part in ('3001', '3023'):
                result = self.process(part, config, library, release_key)
                calibration[part] = result
                if result.get('cache_key'):
                    result['stl_filename'] = f'{part}.stl'
                    shutil.copyfile(self.models / (result['cache_key'] + '.stl'), stage / 'Calibration' / result['stl_filename'])
            (stage / 'Calibration' / 'README.txt').write_text(
                'Print one 2x4 brick and one 1x2 plate at 100% scale. Check each against a genuine piece, '
                'then each other. Review mesh warnings and sliced walls before printing. Adjust hole/XY '
                'compensation in small steps only after measuring.\n', encoding='utf-8')
        attribution = {}
        for result in [*results.values(), *calibration.values()]:
            for dependency, credit in result.get('attribution', {}).items():
                attribution[dependency] = credit
        json_file(reports / 'attribution.json', dict(
            inventory_url='https://rebrickable.com/downloads/', model_url=LDRAW_URL,
            changes='Surface expansion, conversion to millimeters, mesh cleanup, and optional plate placement',
            files=attribution))
        json_file(reports / 'validation_report.json', dict(units='millimeters', parts=list(results.values()),
                                                          calibration=calibration))
        (stage / 'README.txt').write_text(
            f'{metadata["set_name"]} ({metadata["set_number"]})\n\n'
            'Inventory data from Rebrickable. Model provenance and licenses are in Reports.\n'
            'Import STL at 100% as millimeters. Files in the STL folder contain individual designs.\n'
            'When print plates are enabled, start with Printing_Batches/START_HERE.txt.\n'
            'Open each 3MF independently. It contains one color with multiple designs with every copy assigned to that plate.\n'
            'Use the matching STL_Fallback plate if the slicer fails to load all 3MF copies.\n'
            'Review supports, wall thickness, orientation, dimensions and toolpaths in your slicer.\n'
            'Files ending in _Review include flagged meshes. Inspect and repair those before printing.\n'
            'Checked means basic mesh checks passed. Physical fit has to be tested.\n'
            f'Use the {printer["printer"]} profile with {printer["nozzle_mm"]} mm nozzle, '
            f'{printer["material"]}, and {printer["process"]} or equivalent.\n', encoding='utf-8')
        status('Compressing the downloadable ZIP')
        archive = self.archive(job_id, metadata)
        temporary_zip = archive.with_suffix('.zip.tmp')
        with zipfile.ZipFile(temporary_zip, 'w', zipfile.ZIP_DEFLATED) as output:
            for path in sorted(stage.rglob('*')):
                output.write(path, Path(target.name) / path.relative_to(stage))
        if target.exists():
            shutil.rmtree(target)
        stage.replace(target)
        temporary_zip.replace(archive)
        return count
