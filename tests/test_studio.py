import csv
import gzip
import io
import json
import os
import time
import zipfile
from collections import Counter
from pathlib import Path
from threading import Event
from xml.etree import ElementTree as ET

import httpx
import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient

from brickprint.app import create_app
from brickprint.batches import CORE, export_batches, placements
from brickprint.geometry import LDraw, ModelError, validate
from brickprint.jobs import Studio
from brickprint.sources import SetNotFound, catalog_paths, fetch, inventory

CUBE = trimesh.creation.box(extents=[8, 8, 11.2])
OPTIONS = {'batches': True, 'max_per_plate': 2, 'calibration': False}


def ldraw_box(name, keywords='', missing=False):
    head = (f'0 {name}\n0 Author: Test\n0 !LDRAW_ORG Part UPDATE TEST\n'
            '0 !LICENSE Licensed under CC BY 4.0 : see CAreadme.txt\n0 BFC CERTIFY CCW\n'
            f'0 !KEYWORDS {keywords}\n')
    if missing:
        return head + '1 16 0 0 0 1 0 0 0 1 0 0 0 1 no-file.dat\n'
    transform = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]])
    triangles = (CUBE.triangles @ transform.T) / 0.4
    return head + '\n'.join('3 16 ' + ' '.join(f'{x:.8g}' for x in t.flat) for t in triangles)


@pytest.fixture
def roots(tmp_path):
    cache = tmp_path / 'catalog'
    cache.mkdir()
    data = {
        'sets': 'set_num,name,num_parts,img_url\n60000-1,Demo Fire Motorcycle,13,\n70000-1,Sub-Set,3,\n',
        'inventories': 'id,version,set_num\n1,1,60000-1\n2,2,60000-1\n3,1,70000-1\n4,1,fig-1\n',
        'inventory_parts': ('inventory_id,part_num,color_id,quantity,is_spare\n'
                            '1,3005,1,500,False\n2,3005,1,2,False\n2,3005,1,1,False\n'
                            '2,3005,2,3,False\n2,3005,1,99,True\n2,head,1,1,False\n'
                            '2,weapon,1,1,False\n2,sticker,1,1,False\n2,missing,1,1,False\n'
                            '3,3005,1,2,False\n3,bl-special,1,1,False\n'
                            '4,3005,1,7,False\n4,head,1,1,False\n2,badref,1,1,False\n'),
        'inventory_sets': 'inventory_id,set_num,quantity\n2,70000-1,2\n',
        'inventory_minifigs': 'inventory_id,fig_num,quantity\n2,fig-1,1\n3,fig-1,1\n',
        'parts': ('part_num,name,part_cat_id,part_material\n3005,Brick 1 x 1,1,Plastic\n'
                  'head,Minifig Head,2,Plastic\nweapon,Space Gun,4,Plastic\n'
                  'sticker,Sticker Sheet,3,Plastic\nmissing,Rare Part,1,Plastic\n'
                  'bl-special,Verified Special Brick,1,Plastic\nbadref,Missing dependency,1,Plastic\n'),
        'part_categories': 'id,name\n1,Bricks\n2,Minifig Heads\n3,Stickers\n4,Minifig Shields Weapons and Tools\n',
        'colors': 'id,name,rgb\n1,Blue,0000FF\n2,Red,FF0000\n',
    }
    for name, data_csv in data.items():
        with gzip.open(cache / (name + '.csv.gz'), 'wt', encoding='utf-8') as file:
            file.write(data_csv)
    with zipfile.ZipFile(cache / 'complete.zip', 'w') as archive:
        archive.writestr('ldraw/parts/3005.dat', ldraw_box('Brick 1 x 1', 'Rebrickable bl-special'))
        archive.writestr('ldraw/parts/badref.dat', ldraw_box('Broken Sample', missing=True))
        archive.writestr('ldraw/parts/one.dat', ldraw_box('One', 'BrickLink ambiguous'))
        archive.writestr('ldraw/parts/two.dat', ldraw_box('Two', 'BrickLink ambiguous'))
        archive.writestr('ldraw/CAlicense4.txt', 'Fixture text')
    return tmp_path


def no_network(*_args):
    pytest.fail('Cached sources should prevent download')


def test_inventory_and_minifigure_filter(roots):
    meta, rows, excluded = inventory(catalog_paths(roots / 'catalog', print, no_network), '60000', print)
    assert meta['excluded_minifigure_assemblies'] == 3 and meta['inventory_version'] == 2
    assert {row['part_number'] for row in excluded} == {'head', 'weapon', 'sticker'}
    counts = {(row['part_number'], row['color']): row['quantity_required'] for row in rows}
    assert counts == {('3005', 'Blue'): 7, ('3005', 'Red'): 3, ('bl-special', 'Blue'): 2,
                      ('missing', 'Blue'): 1, ('badref', 'Blue'): 1}
    with pytest.raises(SetNotFound):
        inventory(catalog_paths(roots / 'catalog', print), 'NOEXIST', print)


def test_print_filters_and_mixed_plate_quantities(roots):
    paths = catalog_paths(roots / 'catalog', print, no_network)
    for table, row in (
        ('inventory_parts', '2,bolt,2,4,False\n2,launcher,1,1,False\n'),
        ('parts', 'bolt,"Projectile, Spring Shooter Bolt",1,Plastic\n'
                  'launcher,"Launcher, Spring Shooter",1,Plastic\n'),
    ):
        with gzip.open(paths[table], 'at', encoding='utf-8') as file:
            file.write(row)
    meta, rows, excluded = inventory(paths, '60000-1', print, include_minifigures=True,
                                     include_projectiles=False)
    counts = {(row['part_number'], row['color_id']): row['quantity_required'] for row in rows}
    assert counts['head', '1'] == 4
    assert counts['3005', '1'] == 28
    assert counts['launcher', '1'] == 1
    assert ('bolt', '2') not in counts
    assert any(row['part_number'] == 'bolt' and row['reason'] == 'projectiles disabled' for row in excluded)
    assert meta['excluded_minifigure_assemblies'] == 0
    assert not meta['missing_minifigure_inventories']

    studio = Studio(roots)
    job = studio.enqueue('60000-1', dict(OPTIONS, group_by_color=False, max_per_plate=None,
                                         include_minifigures=True, include_projectiles=False))
    studio.run(job)
    snapshot = studio.snapshot(job)
    assert snapshot['state'] == 'complete'
    assert snapshot['plate_count'] == 1
    folder = studio.folder(job, snapshot['metadata']) / 'Printing_Batches'
    manifest = json.loads((folder / 'batch_layouts.json').read_text())
    plate, = manifest['plates']
    assert plate['color'] == 'Mixed'
    assert {item['color_id'] for item in plate['objects']} == {'1', '2'}
    assert manifest['quantity_summary']['required'] == sum(counts.values())


def test_exact_mapping_ambiguous_and_conversion(roots):
    ldraw = LDraw(roots / 'catalog' / 'complete.zip')
    try:
        ldraw.index()
        assert ldraw.resolve('3005', {}) == ('3005', 'exact catalog ID')
        assert ldraw.resolve('bl-special', {}) == ('3005', 'LDraw Rebrickable keyword')
        with pytest.raises(ModelError, match='Ambiguous'):
            ldraw.resolve('ambiguous', {})
        with pytest.raises(ModelError, match='Missing LDraw geometry'):
            ldraw.convert('badref')
        mesh, credits, _ = ldraw.convert('3005')
        _, report = validate(mesh, [8, 8, 11.2])
        assert report['validation_status'] == 'checked'
        assert report['dimensions_mm'] == pytest.approx([8, 8, 11.2])
        assert credits['parts/3005.dat']['author'] == 'Test'
        with pytest.raises(ModelError, match='differ'):
            validate(mesh.copy().apply_scale(10), [8, 8, 11.2])
        mesh.update_faces(np.arange(len(mesh.faces) - 1))
        _, report = validate(mesh)
        assert report['validation_status'] == 'review' and report['boundary_edges'] > 0
    finally:
        ldraw.close()


def test_download_retry_and_atomic_cache(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={'Retry-After': '3'})
        return httpx.Response(200, content=b'official source fixture')
    waits = []
    output = tmp_path / 'asset.zip'
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        fetch('https://example.test/catalog', output, lambda _: None, client=client, sleep=waits.append)
    assert waits == [3]
    assert output.read_bytes() == b'official source fixture'
    assert list(tmp_path.iterdir()) == [output]


def test_override_uses_verified_mm_scale(roots):
    local = roots / 'local_models'
    local.mkdir()
    CUBE.copy().apply_scale(0.1).export(local / 'brick.obj')
    config = {'3005': {'source': 'Mecabricks', 'file': 'brick.obj', 'mm_per_unit': 10,
                       'credit': 'Fixture author', 'permission': 'Fixture license'}}
    (roots / 'model_sources.json').write_text(json.dumps(config))
    studio = Studio(roots, no_network)
    job_id = studio.enqueue('60000', OPTIONS)
    studio.run(job_id)
    result = studio.store.results(job_id)['3005']
    assert result['source_design'] == 'brick.obj'
    assert result['model_source'].startswith('Mecabricks')
    assert result['dimensions_mm'] == pytest.approx([8, 8, 11.2])


def test_interruption_resume_and_cache(roots, monkeypatch):
    studio = Studio(roots, no_network)
    job_id = studio.enqueue('60000', OPTIONS)
    original = studio.store.record

    def stop_after_record(*args):
        original(*args)
        studio.stop.set()

    monkeypatch.setattr(studio.store, 'record', stop_after_record)
    studio.run(job_id)
    first = studio.store.results(job_id)
    assert len(first) == 1
    assert studio.store.get(job_id)['state'] == 'queued'
    studio.store.update(job_id, state='running')
    resumed = Studio(roots, no_network)
    resumed.store.recover()
    assert resumed.store.next() == job_id
    assert resumed.store.results(job_id) == first
    resumed.run(job_id)
    assert resumed.store.get(job_id)['state'] == 'complete'
    assert len(list(resumed.models.glob('*.stl'))) == 1
    duplicate_job = resumed.enqueue('60000', OPTIONS)
    resumed.run(duplicate_job)
    duplicate_results = resumed.store.results(duplicate_job)
    assert duplicate_results['3005']['download_status'] == 'cached'
    assert duplicate_results['bl-special']['cache_key'] == duplicate_results['3005']['cache_key']


def test_web_job_zip_and_plate_instances(roots):
    studio = Studio(roots, no_network)
    with TestClient(create_app(studio)) as http:
        assert 'Generate Printable Set' in http.get('/').text
        assert http.post('/api/jobs', json={'set_number': '../x'}).status_code == 400
        assert http.post('/api/jobs', headers={'Origin': 'https://other.test'},
                         json={'set_number': '60000'}).status_code == 403
        response = http.post('/api/jobs', json={'set_number': '60000', 'max_per_plate': 2})
        assert response.status_code == 202
        job_id = response.json()['id']
        for _ in range(100):
            state = http.get(f'/api/jobs/{job_id}').json()
            if state['state'] in {'complete', 'failed'}:
                break
            time.sleep(.05)
        assert state['state'] == 'complete', state['message']
        assert state['checked'] == 2 and state['missing'] == 2 and state['plate_count'] == 7
        assert state['quantity_summary'] == dict(required=14, checked=12, review=0, missing=2)
        download = http.get(f'/api/jobs/{job_id}/download')
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        base = 'LEGO_Set_60000-1/'
        assert archive.testzip() is None
        assert len([name for name in archive.namelist() if name.startswith(base + 'STL/') and name.endswith('.stl')]) == 1
        missing = list(csv.DictReader(io.StringIO(archive.read(base + 'Reports/missing_parts.csv').decode('utf-8-sig'))))
        assert {row['part_number'] for row in missing} == {'missing', 'badref'}
        assert any('dependency' in row['message'] for row in missing)
        manifest = json.loads(archive.read(base + 'Printing_Batches/batch_layouts.json'))
        folder = base + 'Printing_Batches/'
        plate_counts = list(csv.DictReader(io.StringIO(archive.read(folder + 'plate_counts.csv').decode('utf-8-sig'))))
        assert sum(int(row['Copies']) for row in plate_counts) == 12
        audit = list(csv.DictReader(io.StringIO(archive.read(folder + 'quantity_check.csv').decode('utf-8-sig'))))
        assert sum(int(row['Unplaced']) for row in audit) == 2
        by_color = Counter()
        for plate in manifest['plates']:
            by_color[plate['color']] += len(plate['objects'])
            assert len(plate['objects']) <= 2
            backup = archive.read(base + 'Printing_Batches/' + plate['stl_file'])
            mesh = trimesh.load_mesh(io.BytesIO(backup), file_type='stl')
            assert len(mesh.split()) == len(plate['objects'])
            with zipfile.ZipFile(io.BytesIO(archive.read(base + 'Printing_Batches/' + plate['file']))) as model:
                xml = ET.fromstring(model.read('3D/3dmodel.model'))
                assert xml.get('unit') == 'millimeter'
                items = xml.findall(f'{{{CORE}}}build/{{{CORE}}}item')
                assert len({item.get('objectid') for item in items}) == len(plate['objects']) == len(items)
                objects = xml.findall(f'{{{CORE}}}resources/{{{CORE}}}object')
                assert {obj.get('id') for obj in objects} == {item.get('objectid') for item in items}
        assert by_color == {'Blue': 9, 'Red': 3}


def test_packing_no_collisions_or_excluded_corner(roots):
    studio = Studio(roots, no_network)
    rows = [{'part_number': 'large', 'color': 'Gray', 'color_id': '1', 'quantity_required': 25}]
    results = {'large': {'validation_status': 'checked', 'dimensions_mm': [71, 45, 20]}}
    plates, skipped = placements(rows, results, studio.profile, 12)
    assert not skipped and sum(len(p['objects']) for p in plates) == 25
    for plate in plates:
        items = plate['objects']
        for i, obj in enumerate(items):
            x, y, w, h = [obj[field] for field in ('x', 'y', 'width', 'depth')]
            assert x >= 5 and y >= 5 and x + w <= 251 and y + h <= 251
            assert x + w + 5 <= 246 or y >= 25
            for other in items[i+1:]:
                assert (x + w + 5 <= other['x'] or other['x'] + other['width'] + 5 <= x
                        or y + h + 5 <= other['y'] or other['y'] + other['depth'] + 5 <= y)


@pytest.mark.skipif(not os.getenv('BRICKPRINT_TEST_CATALOG'), reason='Set BRICKPRINT_TEST_CATALOG to the official cache path')
def test_real_catalog_and_ldraw():
    directory = Path(os.environ['BRICKPRINT_TEST_CATALOG'])
    meta, rows, excluded = inventory(catalog_paths(directory, print, no_network), '60000-1', print)
    assert meta['set_name'] == 'Fire Motorcycle'
    assert meta['excluded_minifigure_assemblies'] == 1
    assert meta['required_quantity'] > 10 and all(not row['part_number'].startswith('fig-') for row in rows)
    assert any('Plate' in row['part_name'] for row in rows)
    assert any(row['part_number'] == '4599b' for row in rows)
    assert all(row['part_number'] != '4599b' for row in excluded)
    ldraw = LDraw(directory / 'complete.zip')
    try:
        ldraw.index()
        assert ldraw.resolve('3062b', {})[0] == '3062b'
        assert ldraw.resolve('54200', {})[0] == '54200'
        assert ldraw.resolve('3556', {})[0] == '3001'
        with pytest.raises(ModelError, match='Ambiguous'):
            ldraw.resolve('41769', {})
        candidate, _ = ldraw.resolve('3001', {})
        mesh, _, _ = ldraw.convert(candidate)
        mesh, report = validate(mesh, [32, 16, 11.2], mounting_seams=True)
        assert report['watertight'] and report['validation_status'] == 'checked'
        assert mesh.is_volume
        assert trimesh.load_mesh(io.BytesIO(mesh.export(file_type='stl')), file_type='stl').extents == pytest.approx([32, 16, 11.2])
    finally:
        ldraw.close()


def test_one_worker_per_data_directory(roots):
    first, second = Studio(roots, no_network), Studio(roots, no_network)
    first.start()
    try:
        with pytest.raises(RuntimeError, match='Another'):
            second.start()
    finally:
        first.close()
    second.start()
    second.close()


def test_same_color_3mf_packs_mixed_designs_and_preserves_review_status(roots):
    folder = roots / 'Printing_Batches'
    folder.mkdir()
    stls = roots / 'STL'
    stls.mkdir()
    box = CUBE.copy()
    box.apply_translation(-box.bounds[0])
    box.export(stls / 'checked.stl')
    box.update_faces(np.arange(len(box.faces) - 1))
    box.export(stls / 'review.stl')
    rows = [dict(part_number=part, color='Gray', color_id='1', quantity_required=quantity)
            for part, quantity in [('checked', 1), ('review', 5), ('unavailable', 2)]]
    rows.append(dict(part_number='checked', color='Blue', color_id='2', quantity_required=2))
    results = {part: dict(validation_status=part, dimensions_mm=[8, 8, 11.2], stl_filename=f'{part}.stl')
               for part in ['checked', 'review', 'unavailable']}
    assert export_batches(folder, rows, results, Studio(roots).profile, 10, lambda _: None) == 2
    manifest = json.loads((folder / 'batch_layouts.json').read_text())
    assert manifest['quantity_summary'] == dict(required=10, checked=3, review=5, missing=2)
    gray, blue = manifest['plates']
    assert gray['file'].endswith('_Gray_6x_Review.3mf')
    assert blue['file'].endswith('_Blue_2x.3mf')
    assert Counter(item['part_number'] for item in gray['objects']) == {'checked': 1, 'review': 5}
    with zipfile.ZipFile(folder / gray['file']) as model:
        xml = ET.fromstring(model.read('3D/3dmodel.model'))
    assert len(xml.findall(f'{{{CORE}}}resources/{{{CORE}}}object')) == 6
    assert len({item.get('transform') for item in xml.findall(f'{{{CORE}}}build/{{{CORE}}}item')}) == 6
    assert {'unavailable'} == {item['part_number'] for item in manifest['skipped']}
    mesh = trimesh.load_mesh(folder / gray['stl_file'])
    assert len(mesh.faces) == len(CUBE.faces) + len(box.faces) * 5
