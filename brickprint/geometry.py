"""LDraw surface expansion and conservative mesh validation in millimeters."""
import hashlib
import json
import re
import zipfile
from collections import defaultdict
from functools import lru_cache

import numpy as np
import trimesh
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely.errors import GEOSException

from .seams import stitch_mounts
from .sources import PART_ID, LDRAW_URL

LDU_TO_MM = 0.4
PIPELINE_VERSION = '9'
LICENSE_URLS = {'CC BY 4.0': 'https://creativecommons.org/licenses/by/4.0/',
                'CC BY 2.0': 'https://creativecommons.org/licenses/by/2.0/'}
REFERENCE_SCALE = {
    '3001': [32, 16, 11.2], '3003': [16, 16, 11.2], '3004': [16, 8, 11.2],
    '3005': [8, 8, 11.2], '3010': [32, 8, 11.2], '3031': [32, 32, 4.8],
    '4865a': [16, 8, 9.6], '3020': [32, 16, 4.8], '3022': [16, 16, 4.8],
    '3023': [16, 8, 4.8], '3024': [8, 8, 4.8],
}


class ModelError(ValueError):
    pass


def digest_file(path):
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


class LDraw:
    def __init__(self, path):
        self.archive = zipfile.ZipFile(path)
        self.files = {name.lower().removeprefix('ldraw/'): name for name in self.archive.namelist()}
        self.aliases = defaultdict(set)
        self.rebrickable_aliases = defaultdict(set)
        self.main = {}
        self.identity_aliases = {}

    def close(self):
        self._expand.cache_clear()
        self._text.cache_clear()
        self.archive.close()

    @lru_cache(maxsize=1200)
    def _text(self, name):
        return self.archive.read(self.files[name]).decode('utf-8-sig', errors='replace')

    def index(self):
        for path in self.files:
            if not re.fullmatch(r'parts/[^/]+\.dat', path):
                continue
            content = self._text(path)
            part = path[6:-4]
            headers = [line.strip() for line in content.splitlines() if line.lstrip().startswith('0 ')]
            kind = next((line.split()[2:] for line in headers if line.startswith('0 !LDRAW_ORG ')), [])
            if not kind or kind[0] not in {'Part', 'Shortcut'} or 'Flexible_Section' in kind:
                continue
            self.main[part] = path
            if 'Alias' in kind or 'Physical_Colour' in kind:
                geometry = [line.split() for line in content.splitlines()
                            if line.lstrip().startswith(('1 ', '3 ', '4 '))]
                if len(geometry) == 1 and geometry[0][0] == '1':
                    ref = geometry[0]
                    identity = [0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]
                    try:
                        same_shape = list(map(float, ref[2:14])) == identity
                    except ValueError:
                        same_shape = False
                    if len(ref) == 15 and same_shape and ref[14].lower().endswith('.dat'):
                        self.identity_aliases[part] = ref[14].lower()[:-4]
            for line in headers:
                if not line.startswith('0 !KEYWORDS '):
                    continue
                for keyword in line[12:].split(','):
                    match = re.fullmatch(r'\s*(BrickLink|Rebrickable)(?:\s+Part)?\s*[:#]?\s+([^\s,]+)\s*',
                                         keyword, re.I)
                    if match and PART_ID.fullmatch(match[2]):
                        index = self.rebrickable_aliases if match[1].lower() == 'rebrickable' else self.aliases
                        index[match[2].lower()].add(part)

    def canonical(self, part):
        visited = set()
        while part in self.identity_aliases:
            target = self.identity_aliases[part]
            if part in visited or target not in self.main:
                break
            visited.add(part)
            part = target
        return part

    def resolve(self, part, manual):
        key = part.lower()
        if key in manual:
            candidate = manual[key].lower()
            if candidate not in self.main:
                raise ModelError(f'Mapped LDraw ID {candidate} is missing from the official archive.')
            return self.canonical(candidate), 'explicit mapping'
        candidates = {self.canonical(item) for item in self.rebrickable_aliases.get(key, set())}
        if len(candidates) == 1:
            return next(iter(candidates)), 'LDraw Rebrickable keyword'
        if len(candidates) > 1:
            exact = self.canonical(key)
            if exact in candidates:
                return exact, 'exact catalog ID confirmed by LDraw Rebrickable keyword'
            raise ModelError('Ambiguous Rebrickable mapping: ' + ', '.join(sorted(candidates)))
        if key in self.main:
            return self.canonical(key), 'exact catalog ID'
        candidates = {self.canonical(item) for item in self.aliases.get(key, set())}
        if len(candidates) == 1:
            return next(iter(candidates)), 'unique LDraw BrickLink keyword matching catalog ID'
        if len(candidates) > 1:
            raise ModelError('Ambiguous BrickLink mapping: ' + ', '.join(sorted(candidates)))
        raise ModelError('No exact or documented design match in the official LDraw archive.')

    def dependency(self, parent, reference):
        reference = reference.lower().replace('\\', '/')
        if reference.startswith('/') or '..' in reference.split('/'):
            raise ModelError('Invalid LDraw reference.')
        candidates = [f'parts/{reference}', f'p/{reference}']
        if parent.startswith('p/'):
            candidates.reverse()
        return next((name for name in candidates if name in self.files), None)

    @lru_cache(maxsize=350)
    def _expand(self, path, ancestry=()):
        if path in ancestry or len(ancestry) > 35:
            raise ModelError(f'Circular or excessively deep LDraw reference at {path}.')
        text = self._text(path)
        license_match = re.search(r'^0 !LICENSE .*?(CC BY 4\.0|CC BY 2\.0|Creative Commons Attribution License version 2\.0)',
                                  text, re.M | re.I)
        if not license_match:
            raise ModelError(f'No supported redistribution license confirmed for {path}.')
        license_name = 'CC BY 4.0' if '4.0' in license_match[1] else 'CC BY 2.0'
        author = re.search(r'^0 Author:\s*(.+)$', text, re.M)
        edits = sorted(set(re.findall(r'^0 !HISTORY \S+ (\[[^\]]+\]|\{[^}]+\})', text, re.M)))
        credits = {path: {'author': author[1].strip() if author else 'LDraw contributors',
                          'contributors': edits, 'license': license_name,
                          'license_url': LICENSE_URLS[license_name]}}
        chunks, notes = [], set()
        clockwise, invert_next = False, False
        for raw in text.splitlines():
            fields = raw.split()
            if not fields:
                continue
            line_type = fields[0]
            if line_type == '0':
                if fields[1:2] == ['BFC']:
                    if 'INVERTNEXT' in fields:
                        invert_next = True
                    if fields[-1] in {'CW', 'CCW'}:
                        clockwise = fields[-1] == 'CW'
                if fields[1:2] in (['!TEXMAP'], ['!:']):
                    raise ModelError(f'{path} uses textured geometry requiring manual conversion.')
                continue
            if line_type == '1':
                values = np.array(fields[2:14], dtype=float)
                matrix = values[3:].reshape(3, 3)
                reference = ' '.join(fields[14:])
                dep = self.dependency(path, reference)
                if dep is None:
                    raise ModelError(f'Missing LDraw geometry dependency: {reference} (from {path}).')
                triangles, dependencies, child_notes = self._expand(dep, (*ancestry, path))
                credits.update(dependencies)
                notes.update(child_notes)
                if len(triangles):
                    transformed = triangles @ matrix.T + values[:3]
                    if (np.linalg.det(matrix) < 0) ^ invert_next:
                        transformed = transformed[:, [0, 2, 1]]
                    chunks.append(transformed)
            elif line_type in {'3', '4'}:
                xyz = np.array(fields[2:], dtype=float).reshape(int(line_type), 3)
                indices = [[0, 1, 2]] if line_type == '3' else [[0, 1, 2], [0, 2, 3]]
                triangle = xyz[indices]
                chunks.append(triangle[:, [0, 2, 1]] if clockwise else triangle)
            invert_next = False
        triangles = np.concatenate(chunks) if chunks else np.empty((0, 3, 3))
        if len(triangles) > 1_500_000:
            raise ModelError(f'{path} exceeds the mesh complexity limit.')
        return triangles, credits, notes

    def convert(self, design):
        path = self.main[design]
        triangles, credits, notes = self._expand(path)
        if not len(triangles):
            raise ModelError('LDraw design has no exportable triangle geometry.')
        # Right-handed rotation from LDraw -Y up to slicer +Z up.
        xyz = triangles[:, :, [0, 2, 1]].copy() * LDU_TO_MM
        xyz[:, :, 2] *= -1
        return triangle_mesh(xyz), credits, sorted(notes)

    def license_files(self):
        return {name: self.archive.read(self.files[name])
                for name in ('calicense.txt', 'calicense4.txt', 'careadme.txt') if name in self.files}


def triangle_mesh(triangles):
    if not np.isfinite(triangles).all():
        raise ModelError('Geometry contains invalid or infinite coordinates.')
    points = triangles.reshape(-1, 3)
    # Weld tiny coordinate-rounding differences from transformed LDraw primitives.
    keys = np.round(points, decimals=4)
    _, indices, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    return trimesh.Trimesh(vertices=points[indices], faces=inverse.reshape(-1, 3), process=False)


def stitch_t_junctions(mesh):
    """Split edges at existing on-edge vertices without moving the represented surface."""
    totals = np.bincount(mesh.edges_unique_inverse)
    edges = mesh.edges_unique[totals == 1]
    if not len(edges):
        return mesh, 0
    vertices = np.asarray(mesh.vertices)
    boundary = np.unique(edges)
    tree = cKDTree(vertices[boundary])
    splits = {}
    for a, b in edges:
        vector = vertices[b] - vertices[a]
        length = np.linalg.norm(vector)
        if length < 1e-6:
            continue
        candidates = boundary[tree.query_ball_point((vertices[a] + vertices[b]) / 2, length / 2 + 0.00012)]
        relative = vertices[candidates] - vertices[a]
        ratios = relative @ vector / length ** 2
        distances = np.linalg.norm(relative - ratios[:, None] * vector, axis=1)
        selected = (ratios * length > 0.00012) & ((1 - ratios) * length > 0.00012) & (distances < 0.00012)
        if np.any(selected):
            order = np.argsort(ratios[selected])
            splits[a, b] = candidates[selected][order].tolist()
    if not splits:
        return mesh, 0
    new_vertices, faces = vertices.tolist(), []
    for face in np.asarray(mesh.faces):
        polygon = []
        for a, b in zip(face, np.roll(face, -1)):
            polygon.append(a)
            polygon.extend(splits.get((a, b), []) if a < b else reversed(splits.get((b, a), [])))
        if len(polygon) == 3:
            faces.append(face.tolist())
        else:
            center = len(new_vertices)
            new_vertices.append(vertices[face].mean(axis=0).tolist())
            faces.extend((center, a, b) for a, b in zip(polygon, polygon[1:] + polygon[:1]))
    return trimesh.Trimesh(vertices=new_vertices, faces=faces, process=False), len(splits)


def validate(mesh, expected=None, *, mounting_seams=False):
    if len(mesh.faces) == 0 or not np.isfinite(mesh.vertices).all():
        raise ModelError('Geometry has no usable faces or contains invalid coordinates.')
    repairs = []
    keep = mesh.nondegenerate_faces(height=1e-7) & mesh.unique_faces()
    if not keep.all():
        repairs.append(f'Removed {int((~keep).sum())} duplicate or degenerate faces')
        mesh.update_faces(keep)
    mesh.remove_unreferenced_vertices()
    if not len(mesh.faces):
        raise ModelError('Geometry collapsed after degenerate triangle removal.')
    if not mesh.is_watertight:
        mesh, count = stitch_t_junctions(mesh)
        if count:
            repairs.append(f'Subdivided {count} edges at existing surface junctions')
    if mounting_seams and not mesh.is_watertight:
        try:
            mesh, attached = stitch_mounts(mesh)
        except (GEOSException, RuntimeError, ValueError):
            attached = 0
        if attached:
            repairs.append(f'Re-triangulated planar contact surfaces to join {attached} modeled seams')
    if not mesh.is_winding_consistent or (mesh.is_watertight and mesh.volume < 0):
        trimesh.repair.fix_winding(mesh)
        if mesh.is_watertight and mesh.volume < 0:
            mesh.invert()
        repairs.append('Corrected face winding')
    dimensions = mesh.extents
    if np.min(dimensions) < 0.05 or np.max(dimensions) > 2000:
        raise ModelError(f'Implausible dimensions in millimeters: {dimensions.round(3).tolist()}.')
    if expected is not None and not np.allclose(sorted(dimensions), sorted(expected), atol=0.35, rtol=0.018):
        raise ModelError(f'Dimensions {dimensions.round(3).tolist()} mm differ from the reference {expected}.')
    incidences = np.bincount(mesh.edges_unique_inverse)
    adjacency = mesh.face_adjacency
    graph = coo_matrix((np.ones(len(adjacency)), (adjacency[:, 0], adjacency[:, 1])),
                       shape=(len(mesh.faces), len(mesh.faces)))
    components = connected_components(graph, directed=False, return_labels=False)
    warnings = []
    if not mesh.is_watertight:
        warnings.append('Open or non-manifold surface; slicer repair or a different model may be required.')
    if not mesh.is_winding_consistent or mesh.volume <= 1e-6:
        warnings.append('Inconsistent winding or nonpositive enclosed volume.')
    if components > 1:
        warnings.append('Multiple surface shells may overlap or contain movable components; inspect in the slicer.')
    mesh.apply_translation(-mesh.bounds[0])
    result = dict(validation_status='review' if warnings else 'checked',
                  dimensions_mm=dimensions.round(5).tolist(), triangles=len(mesh.faces),
                  watertight=bool(mesh.is_watertight), boundary_edges=int(np.sum(incidences == 1)),
                  nonmanifold_edges=int(np.sum(incidences > 2)), shells=components,
                  repairs=repairs, warnings=warnings,
                  checks_not_performed=['self-intersections', 'wall thickness', 'mechanical fit', 'support requirements'])
    return mesh, result


def local_mesh(path, scale):
    if path.suffix.lower() not in {'.stl', '.obj', '.ply'}:
        raise ModelError('Local overrides support STL, OBJ and PLY.')
    loaded = trimesh.load_scene(path, allow_remote=False, process=False).to_geometry()
    if not isinstance(loaded, trimesh.Trimesh) or not len(loaded.faces):
        raise ModelError('Local export has no triangle mesh.')
    return triangle_mesh(loaded.triangles * scale)


def resolve_config(directory):
    path = directory / 'model_sources.json'
    config = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError('model_sources.json must contain an object keyed by Rebrickable part number.')
    normalized = {}
    for part, data in config.items():
        if not PART_ID.fullmatch(part) or not isinstance(data, dict):
            raise ValueError('Invalid part mapping in model_sources.json.')
        identifier = data.get('ldraw_id')
        if identifier is not None and (not isinstance(identifier, str) or not PART_ID.fullmatch(identifier)):
            raise ValueError(f'Invalid ldraw_id for {part}.')
        normalized[part.lower()] = data
    return normalized
