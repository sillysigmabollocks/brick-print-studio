"""Simple collision-free plates and geometry-only core 3MF packages."""
import csv
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from functools import lru_cache

import numpy as np
import trimesh

CORE = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CONTENT = 'http://schemas.openxmlformats.org/package/2006/content-types'


def subtract_rectangle(free, occupied):
    """Keep the maximal open rectangles after reserving a footprint."""
    x0, y0, x1, y1 = occupied
    remaining = set()
    for a, b, c, d in free:
        if c <= x0 or a >= x1 or d <= y0 or b >= y1:
            remaining.add((a, b, c, d))
            continue
        if a < x0:
            remaining.add((a, b, x0, d))
        if c > x1:
            remaining.add((x1, b, c, d))
        if b < y0:
            remaining.add((a, b, c, y0))
        if d > y1:
            remaining.add((a, y1, c, d))
    return sorted(r for r in remaining if not any(
        r != q and q[0] <= r[0] and q[1] <= r[1] and q[2] >= r[2] and q[3] >= r[3]
        for q in remaining))


def find_position(free, width, depth, gap):
    fits = []
    for x, y, right, top in free:
        for w, d, rotation in ((width, depth, 0), (depth, width, 90)):
            spare_x, spare_y = right - x - w - gap, top - y - d - gap
            if min(spare_x, spare_y) >= -1e-7:
                fits.append((min(spare_x, spare_y), max(spare_x, spare_y), y, x, w, d, rotation))
    return min(fits, default=None)


def placements(rows, results, profile, limit, *, include_review=False):
    width, depth, height = profile['build_volume_mm']
    gap, margin = profile['spacing_mm'], profile['bed_margin_mm']
    x0, y0, x1, y1 = profile['excluded_rectangle_mm']
    bed = [(margin, margin, width - margin + gap, depth - margin + gap)]
    # Footprints use positive-X/Y padding. The excluded zone is padded the same way.
    empty = subtract_rectangle(bed, (x0, y0, x1 + gap, y1 + gap))
    by_color, skipped = defaultdict(list), []
    for row in rows:
        part = row['part_number']
        result = results[part]
        validation = result['validation_status']
        if validation != 'checked' and not (include_review and validation == 'review'):
            skipped.append(dict(row, reason='Mesh is unavailable' if validation == 'unavailable' else 'Mesh requires review'))
            continue
        w, d, h = result['dimensions_mm']
        position = find_position(empty, w, d, gap)
        if h > height or position is None:
            skipped.append(dict(row, reason='Part exceeds the usable build area in its exported orientation'))
            continue
        by_color[row['color_id'], row['color']].append((row, w, d, h, validation, position))
    plates = []
    for (color_id, color), designs in sorted(by_color.items()):
        open_plates = []
        for row, w, d, h, validation, empty_position in sorted(
                designs, key=lambda data: (-max(data[1:3]), -data[1] * data[2], data[0]['part_number'])):
            for _ in range(row['quantity_required']):
                for index, (plate, free) in enumerate(open_plates):
                    fit = find_position(free, w, d, gap)
                    if fit is not None:
                        break
                else:
                    plate = dict(color_id=color_id, color=color, validation_status='checked', objects=[])
                    plates.append(plate)
                    index, free, fit = len(open_plates), empty, empty_position
                    open_plates.append((plate, free))
                _, _, y, x, placed_w, placed_d, rotation = fit
                plate['objects'].append(dict(part_number=row['part_number'], validation_status=validation,
                                             x=x, y=y, width=placed_w, depth=placed_d, height=h,
                                             rotation_degrees=rotation))
                if validation == 'review':
                    plate['validation_status'] = 'review'
                if len(plate['objects']) == limit:
                    open_plates.pop(index)
                else:
                    occupied = (x, y, x + placed_w + gap, y + placed_d + gap)
                    open_plates[index] = (plate, subtract_rectangle(free, occupied))
    return plates, skipped


def save_3mf(path, plate, meshes):
    model = ET.Element('model', {'xmlns': CORE, 'unit': 'millimeter'})
    ET.SubElement(model, 'metadata', {'name': 'Title'}).text = f"{plate['color']} LEGO parts"
    resources, build = ET.SubElement(model, 'resources'), ET.SubElement(model, 'build')
    for index, item in enumerate(plate['objects'], 1):
        mesh = meshes[item['part_number']]
        asset_id = str(index)
        name = f"{item['part_number']} copy {index}"
        obj = ET.SubElement(resources, 'object', {'id': asset_id, 'type': 'model', 'name': name})
        shape = ET.SubElement(obj, 'mesh')
        vertices = ET.SubElement(shape, 'vertices')
        for x, y, z in np.asarray(mesh.vertices):
            ET.SubElement(vertices, 'vertex', dict(x=f'{x:.7g}', y=f'{y:.7g}', z=f'{z:.7g}'))
        triangles = ET.SubElement(shape, 'triangles')
        for a, b, c in np.asarray(mesh.faces):
            ET.SubElement(triangles, 'triangle', dict(v1=str(a), v2=str(b), v3=str(c)))
        x, y = item['x'], item['y']
        if item['rotation_degrees']:
            transform = f"0 1 0 -1 0 0 0 0 1 {x + item['width']:.8g} {y:.8g} 0"
        else:
            transform = f'1 0 0 0 1 0 0 0 1 {x:.8g} {y:.8g} 0'
        ET.SubElement(build, 'item', {'objectid': asset_id, 'transform': transform})
    types = ET.Element('Types', {'xmlns': CONTENT})
    ET.SubElement(types, 'Default', dict(Extension='rels', ContentType='application/vnd.openxmlformats-package.relationships+xml'))
    ET.SubElement(types, 'Default', dict(Extension='model', ContentType='application/vnd.ms-package.3dmanufacturing-3dmodel+xml'))
    rels = ET.Element('Relationships', {'xmlns': REL})
    ET.SubElement(rels, 'Relationship', dict(Target='/3D/3dmodel.model', Id='rel0',
                                            Type='http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel'))
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in (('[Content_Types].xml', types), ('_rels/.rels', rels), ('3D/3dmodel.model', model)):
            archive.writestr(name, ET.tostring(data, encoding='utf-8', xml_declaration=True))


def save_plate_stl(path, plate, meshes):
    placed = []
    for item in plate['objects']:
        mesh = meshes[item['part_number']].copy()
        x, y = item['x'], item['y']
        if item['rotation_degrees']:
            mesh.apply_transform([[0, -1, 0, x + item['width']], [1, 0, 0, y],
                                  [0, 0, 1, 0], [0, 0, 0, 1]])
        else:
            mesh.apply_translation([x, y, 0])
        placed.append(mesh)
    trimesh.util.concatenate(placed).export(path, file_type='stl')


def export_batches(folder, rows, results, profile, limit, status):
    plates, skipped = placements(rows, results, profile, limit, include_review=True)

    @lru_cache(maxsize=32)
    def load_mesh(source):
        return trimesh.load_mesh(folder.parent / 'STL' / source)

    for index, plate in enumerate(plates, 1):
        review = plate['validation_status'] == 'review'
        copies = len(plate['objects'])
        color = re.sub(r'[^a-zA-Z0-9]+', '_', plate['color']).strip('_') or 'Unknown'
        suffix = '_Review' if review else ''
        name = f'Plate_{index:03d}_{color}_{copies}x{suffix}'
        status(f'Writing print plate {index} of {len(plates)} · {plate["color"]} · {copies} copies')
        meshes = {part: load_mesh(results[part]['stl_filename'])
                  for part in {item['part_number'] for item in plate['objects']}}
        plate['file'] = f'{name}.3mf'
        target = folder / plate['file']
        target.parent.mkdir(exist_ok=True)
        save_3mf(target, plate, meshes)
        plate['stl_file'] = f'STL_Fallback/{plate["file"][:-4]}.stl'
        destination = folder / plate['stl_file']
        destination.parent.mkdir(parents=True, exist_ok=True)
        save_plate_stl(destination, plate, meshes)
    summary = audit_quantities(folder, rows, plates, skipped)
    manifest = {'quantity_summary': summary, 'profile': profile, 'max_parts_per_plate': limit, 'plates': plates, 'skipped': skipped}
    (folder / 'batch_layouts.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (folder / 'START_HERE.txt').write_text(
        'Open one Plate_*.3mf per empty slicer plate. Each file contains one LEGO color with all copies for that plate.\n'
        f"Set inventory: {summary['required']} required copies. "
        f"{summary['checked']} with checked meshes, {summary['review']} with meshes to review, "
        f"{summary['missing']} unplaced.\n"
        'Open plate_counts.csv for the copy count and color of each file. Use one format per plate.\n'
        'Use quantity_check.csv to check every required part and color.\n'
        'If a 3MF imports incorrectly, open the matching STL_Fallback file instead. It contains the same copies.\n'
        'Inspect files ending in _Review. The manifest lists the individual meshes that need review.\n'
        'See the skipped entries in batch_layouts.json for parts without a model or a usable plate position.\n',
        encoding='utf-8')
    return len(plates)


def audit_quantities(folder, rows, plates, skipped):
    key = lambda row: (row['part_number'], row['color_id'])
    required = Counter()
    packed = {'checked': Counter(), 'review': Counter()}
    for row in rows:
        required[key(row)] += row['quantity_required']
    for plate in plates:
        for item in plate['objects']:
            packed[item['validation_status']][item['part_number'], plate['color_id']] += 1
    missing = Counter()
    reasons = defaultdict(set)
    for row in skipped:
        missing[key(row)] += row['quantity_required']
        reasons[key(row)].add(row['reason'])
    if required != packed['checked'] + packed['review'] + missing:
        raise RuntimeError('Print plate quantities do not match the required inventory.')
    with (folder / 'quantity_check.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['Part number', 'Color', 'Required', 'Placed (mesh checked)',
                         'Placed (mesh needs review)', 'Unplaced', 'Reason'])
        for row in rows:
            pair = key(row)
            writer.writerow([row['part_number'], row['color'], required[pair], packed['checked'][pair],
                             packed['review'][pair], missing[pair], ' / '.join(sorted(reasons[pair]))])
    with (folder / 'plate_counts.csv').open('w', newline='', encoding='utf-8-sig') as file:
        writer = csv.writer(file)
        writer.writerow(['Part numbers', 'Color', 'Copies', 'Mesh status', '3MF file', 'STL file'])
        for plate in plates:
            parts = ' / '.join(sorted({item['part_number'] for item in plate['objects']}))
            writer.writerow([parts, plate['color'], len(plate['objects']), plate['validation_status'],
                             plate.get('file', ''), plate['stl_file']])
    return dict(required=required.total(), checked=packed['checked'].total(),
                review=packed['review'].total(), missing=missing.total())
