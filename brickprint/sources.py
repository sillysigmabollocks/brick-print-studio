"""Official catalog downloads and inventory assembly."""
import csv
import gzip
import re
import time
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

CATALOG = 'https://cdn.rebrickable.com/media/downloads/'
LDRAW_URL = 'https://library.ldraw.org/library/updates/complete.zip'
TABLES = ('sets', 'inventories', 'inventory_parts', 'inventory_sets', 'inventory_minifigs',
          'parts', 'part_categories', 'colors')
SET_ID = re.compile(r'[A-Z0-9]{1,20}(?:-[0-9]{1,4})?', re.I | re.ASCII)
PART_ID = re.compile(r'[a-z0-9][a-z0-9_.+-]{0,78}', re.I | re.ASCII)
RETRYABLE = {408, 425, 429, 500, 502, 503, 504}
NONPRINTABLE_CATEGORIES = {
    'stickers', 'instructions', 'packaging', 'original box', 'books', 'electronics',
    'pen & watch', 'minifigs',
}
NONPRINTABLE_NAME = re.compile(
    r'^(?:sticker\b|instruction(?:s| booklet)\b|cardboard\b|packaging\b|'
    r'paper\b|polybag\b|box for\b|bag for\b)', re.I)
# LEGO inventories classify these stud-connected taps as Buildings & Furniture.
# Rebrickable also lists the designs under Minifig Accessories.
GENERAL_BUILDING_PARTS = {'4599a', '4599b'}
FIGURE_NAME = re.compile(r'^(?:minifig(?:ure)?|mini[ -]?doll)\s+'
                         r'(?:head\b|hair\b|torso\b|legs?\b|arms?\b|hands?\b|'
                         r'hips?\b|helmet\b|cape\b|body\b)', re.I)


def fetch(url, destination, status, *, client=None, sleep=time.sleep):
    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(75, connect=20), follow_redirects=True,
                                   headers={'User-Agent': 'BrickPrintStudio/1.0'})
    temp = destination.with_suffix(destination.suffix + '.partial')
    try:
        for attempt in range(4):
            delay = 2 ** (attempt + 1)
            try:
                with client.stream('GET', url) as response:
                    if response.status_code in RETRYABLE:
                        retry = response.headers.get('retry-after')
                        if retry:
                            try:
                                delay = max(delay, float(retry))
                            except ValueError:
                                try:
                                    until = parsedate_to_datetime(retry)
                                    delay = max(delay, (until - datetime.now(timezone.utc)).total_seconds())
                                except (TypeError, ValueError):
                                    pass
                        response.raise_for_status()
                    response.raise_for_status()
                    total = response.headers.get('content-length', '')
                    total = int(total) if total.isdecimal() else 0
                    next_update = 0
                    with temp.open('wb') as file:
                        for chunk in response.iter_bytes(256 * 1024):
                            file.write(chunk)
                            size = file.tell()
                            if size >= next_update:
                                status(f'Downloading {destination.name} · {size / 1048576:.1f} MB'
                                       + (f' / {total / 1048576:.1f} MB' if total else ''))
                                next_update = size + 2 * 1048576
                        if file.tell() == 0:
                            raise ValueError(f'{destination.name} download was empty.')
                    temp.replace(destination)
                    return
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in RETRYABLE:
                    raise RuntimeError(f'{destination.name} download returned HTTP {error.response.status_code}.') from error
                if attempt == 3 or delay > 120:
                    raise RuntimeError(f'{destination.name} download could not complete. Try resuming later.') from error
                status(f'Waiting {delay:.0f} seconds to retry {destination.name}')
                sleep(delay)
    finally:
        temp.unlink(missing_ok=True)
        if owns_client:
            client.close()


def csv_rows(path):
    with gzip.open(path, 'rt', encoding='utf-8-sig', newline='') as file:
        yield from csv.DictReader(file)


def catalog_paths(directory, status, downloader=fetch):
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in TABLES:
        path = directory / f'{name}.csv.gz'
        if not path.exists():
            status(f'Preparing Rebrickable catalog · {name}')
            downloader(CATALOG + path.name, path, status)
        paths[name] = path
    return paths


def classify(part, name, category, material):
    category = category.casefold().strip()
    if (category.startswith(('minifig', 'minidoll')) or FIGURE_NAME.match(name)) and part not in GENERAL_BUILDING_PARTS:
        return 'minifigure-specific part'
    if category in NONPRINTABLE_CATEGORIES or NONPRINTABLE_NAME.match(name):
        return 'nonprintable catalog item'
    if material.casefold().strip() in {'paper', 'cardboard', 'cloth', 'fabric', 'sticker', 'metal'}:
        return f'nonprintable original material ({material})'
    return ''


class SetNotFound(ValueError):
    pass


def inventory(paths, requested, status):
    status('Finding the set and its latest inventory')
    sets = {row['set_num'].upper(): row for row in csv_rows(paths['sets'])}
    target = sets.get(requested)
    if target is None and '-' not in requested:
        matches = [number for number in sets if number.split('-')[0] == requested]
        if len(matches) == 1:
            target = sets[matches[0]]
        elif matches:
            raise SetNotFound('Multiple versions exist. Enter a full set number: ' + ', '.join(sorted(matches)))
    if target is None:
        raise SetNotFound('Set number was not found in the Rebrickable catalog.')
    number = target['set_num']
    latest = {}
    for row in csv_rows(paths['inventories']):
        key, version = row['set_num'], int(row['version'])
        if key not in latest or version > latest[key][0]:
            latest[key] = (version, row['id'])
    child_sets = {}
    for row in csv_rows(paths['inventory_sets']):
        child_sets.setdefault(row['inventory_id'], []).append(row)
    counts = Counter()

    def visit(set_number, quantity, ancestry):
        if set_number in ancestry or set_number not in latest or len(ancestry) > 25:
            raise ValueError(f'Cannot resolve the catalog inventory for sub-set {set_number}.')
        inv_id = latest[set_number][1]
        counts[inv_id] += quantity
        for row in child_sets.get(inv_id, []):
            visit(row['set_num'], quantity * int(row['quantity']), (*ancestry, set_number))

    visit(number, 1, ())
    status('Reading required quantities and excluding minifigures')
    minifigures = sum(counts[row['inventory_id']] * int(row['quantity'])
                     for row in csv_rows(paths['inventory_minifigs']) if row['inventory_id'] in counts)
    quantities = Counter()
    for row in csv_rows(paths['inventory_parts']):
        multiplier = counts.get(row['inventory_id'])
        if multiplier and row['is_spare'].strip().lower() in {'false', '0', 'f'}:
            quantities[row['part_num'], row['color_id']] += multiplier * int(row['quantity'])
    parts_required = {part for part, _ in quantities}
    parts = {row['part_num']: row for row in csv_rows(paths['parts']) if row['part_num'] in parts_required}
    categories = {row['id']: row['name'] for row in csv_rows(paths['part_categories'])}
    colors = {row['id']: row for row in csv_rows(paths['colors'])}
    rows, excluded = [], []
    for (part, color_id), quantity in sorted(quantities.items()):
        if quantity <= 0:
            continue
        definition = parts.get(part, {})
        name = definition.get('name', part)
        category = categories.get(definition.get('part_cat_id'), '')
        reason = classify(part, name, category, definition.get('part_material', ''))
        if not definition or not category:
            reason = 'catalog metadata missing; minifigure status cannot be verified'
        color = colors.get(color_id, {})
        record = dict(part_number=part, part_name=name, color_id=color_id,
                      color=color.get('name', f'Unknown ({color_id})'), color_hex=color.get('rgb', ''),
                      quantity_required=quantity)
        if reason:
            excluded.append(dict(record, reason=reason))
        else:
            rows.append(record)
    metadata = dict(set_number=number, set_name=target['name'], image=target.get('img_url', ''),
                    catalog_piece_count=int(target['num_parts']), excluded_minifigure_assemblies=minifigures,
                    required_quantity=sum(row['quantity_required'] for row in rows),
                    unique_parts=len({row['part_number'] for row in rows}),
                    inventory_version=latest[number][0], inventory_source='Rebrickable')
    return metadata, rows, excluded
