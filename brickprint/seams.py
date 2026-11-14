"""Close documented stud and tube seams by re-triangulating their mounting planes."""
import manifold3d
import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import unary_union


def loops(edges):
    following = dict(edges)
    if len(following) != len(edges) or set(following) != set(following.values()):
        return []
    output = []
    while following:
        start = a = next(iter(following))
        loop = []
        while a in following:
            loop.append(a)
            a = following.pop(a)
        if a != start or len(loop) < 3:
            return []
        output.append(loop)
    return output


def directed_boundary(faces):
    edges = [(int(a), int(b)) for face in faces for a, b in zip(face, np.roll(face, -1))]
    seen = {}
    for a, b in edges:
        key = min(a, b), max(a, b)
        seen[key] = None if key in seen else (a, b)
    return [edge for edge in seen.values() if edge is not None]


def stitch_mounts(mesh):
    """Keep the modeled stud/tube walls and replace only their flat contact patches."""
    v = np.asarray(mesh.vertices)
    f = np.asarray(mesh.faces)
    boundary = loops(directed_boundary(f))
    eligible = {}
    for loop in boundary:
        z = v[loop, 2]
        if np.ptp(z) < 1e-7:
            polygon = Polygon(v[loop, :2])
            if polygon.is_valid and polygon.area > 1e-6:
                eligible.setdefault(round(float(z[0]), 6), []).append(loop)
    keep = np.ones(len(f), dtype=bool)
    patches = []
    attached = 0
    for z, mounts in eligible.items():
        coplanar = np.all(np.abs(v[f, 2] - z) < 1e-6, axis=1)
        for direction in (1, -1):
            plane = coplanar & (mesh.face_normals[:, 2] * direction > .9999)
            if not plane.any():
                continue
            outlines = loops(directed_boundary(f[plane]))
            if not outlines:
                continue
            area = unary_union([Polygon(v[face, :2]) for face in f[plane]])
            selected = [loop for loop in mounts if area.contains(Polygon(v[loop, :2]))
                        and area.boundary.distance(Polygon(v[loop, :2])) > 1e-5]
            if not selected:
                continue
            ring_ids = outlines + [loop[::-1] for loop in selected]
            if direction < 0:
                ring_ids = [loop[::-1] for loop in ring_ids]
            rings = [v[loop, :2] for loop in ring_ids]
            poly_faces = manifold3d.triangulate(rings)
            indexes = np.concatenate(ring_ids)
            if direction < 0:
                poly_faces = poly_faces[:, ::-1]
            new_faces = indexes[poly_faces]
            new_mesh = trimesh.Trimesh(vertices=v, faces=new_faces, process=False)
            # The reconstructed face must stay in the old plane footprint.
            if new_mesh.area > area.area + 1e-4 or new_mesh.area <= 0:
                continue
            keep[plane] = False
            patches.append(new_faces)
            attached += len(selected)
    if not patches:
        return mesh, 0
    candidate = trimesh.Trimesh(vertices=v, faces=np.vstack([f[keep], *patches]), process=False)
    candidate.remove_unreferenced_vertices()
    if (candidate.is_watertight and candidate.is_winding_consistent and candidate.volume > 0
            and np.allclose(mesh.bounds, candidate.bounds, atol=1e-6, rtol=0)):
        return candidate, attached
    return mesh, 0
