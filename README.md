# Street Width ROW using Python/GeoPandas

1. **Load** roadbed & sidewalk polygons
2. **Create centerlines** (via oriented bounding box long axis)
3. **Generate perpendicular transects** every _N_ feet along each centerline
4. **Clip** each transect so it ends exactly at polygon boundaries
5. **Export** results to a GeoPackage and Shapefiles
6. (Optional) **Visualize** centerlines and transects

### Why these libraries?
- **GeoPandas**: idiomatic vector GIS operations (read/write, CRS handling, vectorized ops) using GDAL/Fiona/Shapely under the hood.
- **Shapely ≥ 2.0**: modern, robust geometry predicates/ops (buffer, clip, intersection, line interpolation). Crucial for clipping transects to polygon edges.
- **Fiona** (via GeoPandas I/O): stable read/write of Shapefile/GeoPackage formats.
- **Matplotlib**: lightweight map previews for QA (no heavy styling required).

> **Note**: I use an **oriented minimum bounding rectangle** centerline (fast & robust for elongated ROW polygons). If you need more “center-of-mass” fidelity for very irregular shapes, you can swap in a skeletonization method later (e.g., momepy) while keeping the rest of the pipeline the same.

# Requirements
-Python 3.10+
-geopandas, shapely >= 2.0, fiona
-(Optional: rtree or pygeos for spatial indexing performance)*

If you see a Shapely/NumPy array-interface error, ensure you are using the default Fiona reader via GeoPandas. This notebook uses GeoPandas' standard I/O.

### 1) Environment setup

```python
# Create and activate an environment
conda create -n row python=3.11 geopandas shapely fiona rtree -c conda-forge
conda activate row
```
><mark>rtree</mark> is optional but speeds up spatial operations.

### 2) Inputs

Shapefiles (polygons):
Roadbed_... .shp
SIDEWALK_... .shp
Recommended CRS: EPSG:2263 (US feet). The script will set/convert to 2263 if needed.

### 3) Key parameters

```python
#---Parameters: edit these for your data/env ---

# Required inputs (polygon shapefiles)
ROADBED_SHP  = "/path/to/Roadbed_Exported_test.shp"
SIDEWALK_SHP = "/path/to/SIDEWALK_Export_test.shp"

# Outputs
OUT_GPKG = "/path/to/ROW_outputs.gpkg"   # multi-layer GeoPackage
# Shapefiles will be written alongside the notebook working directory unless you change the paths below.

# Spacing & reach (feet; EPSG:2263 recommended)
ROAD_INTERVAL_FT = 20.0   # spacing between roadbed transects
SIDE_INTERVAL_FT = 20.0   # spacing between sidewalk transects
ROAD_REACH_FT    = 600.0  # half-length of raw perpendicular for roadbeds (longer = safer across wide ROW)
SIDE_REACH_FT    = 200.0  # half-length for sidewalks (narrower)

# Quick preview limit: set to None for all features; N for faster iteration
SAMPLE_LIMIT = 10

# Also export Shapefiles as standalone layers?
EXPORT_SHP = True

# Target CRS: State Plane NY Long Island (US foot) — change if your region differs
TARGET_CRS = "EPSG:2263"
```

### 4) Imports & Setup

```python
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Tuple

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
import matplotlib.pyplot as plt

# Optional: make plots look crisper in notebooks
%matplotlib inline
```

### 5) Utility Helpers
- `_delete_if_exists` & `_delete_shapefile`: ensure clean exports across re-runs
- CRS handling lives in the main pipeline; these helpers only manage files

```python
def _delete_if_exists(path: Path) -> None:
    """Delete a single file if it exists (ignore errors)."""
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass

def _delete_shapefile(shp_path: Path) -> None:
    """Delete a shapefile *family* (.shp/.shx/.dbf/.prj/.cpg/.sbn/.sbx/.shp.xml/.qix) if present.

    This avoids stale sidecar conflicts when re-running exports.
    """
    shp_path = Path(shp_path)
    stem = shp_path.with_suffix("")  # remove .shp
    for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".shp.xml", ".qix"]:
        _delete_if_exists(stem.parent / f"{stem.name}{ext}")
```

### 6) Geometry Foundations
We build centerlines from the oriented minimum bounding rectangle (MBR) and then:
1. Sample points along that centerline every *interval* feet
2. At each sample, compute the **tangent** direction of the centerline
3. Build a **perpendicular** “raw” transect (long line = ±reach)
4. **Clip** the transect to the polygon, keeping the interior span (exact edge-to-edge)

This produces width-spanning transects that are perpendicular to an axis aligned with the polygon’s dominant orientation — ideal for ROW estimation.

```python
def oriented_bbox_axis(poly: Polygon) -> LineString:
    """Return a straight line representing the *long* edge of the polygon's oriented MBR.

    This provides a stable, fast proxy for a “centerline” through elongated polygons.
    """
    mbr = poly.minimum_rotated_rectangle
    coords = list(mbr.exterior.coords)[:-1]  # drop duplicate closing coord
    edges = [(coords[i], coords[(i + 1) % 4]) for i in range(4)]
    lengths = [Point(a).distance(Point(b)) for a, b in edges]
    a, b = edges[lengths.index(max(lengths))]
    return LineString([a, b])


def sample_points_along_line(line: LineString, interval: float) -> List[Point]:
    """Return points every `interval` along `line` from 0 → length."""
    pts: List[Point] = []
    L = line.length
    if L <= 0:
        return pts
    d = 0.0
    while d <= L + 1e-9:  # small epsilon for float safety
        pts.append(line.interpolate(d))
        d += interval
    return pts


def unit_tangent(line: LineString, s: float) -> Tuple[float, float]:
    """Approximate a unit tangent vector at position `s` along a line.

    Uses a small forward/backward difference (±0.01 linear units).
    """
    L = line.length
    if L == 0:
        return (1.0, 0.0)
    s0 = max(0.0, min(L, s - 0.01))
    s1 = max(0.0, min(L, s + 0.01))
    p0, p1 = line.interpolate(s0), line.interpolate(s1)
    dx, dy = p1.x - p0.x, p1.y - p0.y
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    return (dx / n, dy / n)


def perpendicular_transect(point: Point, tangent: Tuple[float, float], reach: float) -> LineString:
    """Build a long line centered on `point`, perpendicular to `tangent`, half-length = `reach`."""
    tx, ty = tangent
    nx, ny = -ty, tx
    a = Point(point.x - nx * reach, point.y - ny * reach)
    b = Point(point.x + nx * reach, point.y + ny * reach)
    return LineString([a, b])


def clip_transect(tran: LineString, poly: Polygon):
    """Trim `tran` to the segment that lies inside `poly`, with endpoints on the boundary if possible.

    If no boundary intersections are found (e.g., transect fully inside),
    intersect with the polygon interior and keep the longest segment.
    """
    inter = tran.intersection(poly.boundary)
    pts: List[Point] = []

    # 1) No boundary hits → fallback to interior intersection
    if inter.is_empty:
        clipped = tran.intersection(poly)
        if clipped.is_empty:
            return None
        if clipped.geom_type == "MultiLineString":
            return max(list(clipped.geoms), key=lambda ls: ls.length)
        return clipped if clipped.geom_type == "LineString" else None

    # 2) Gather boundary intersection points
    if inter.geom_type == "Point":
        pts = [inter]
    elif inter.geom_type == "MultiPoint":
        pts = list(inter.geoms)
    elif inter.geom_type == "GeometryCollection":
        pts = [g for g in inter.geoms if g.geom_type == "Point"]

    # 3) If still fewer than two points → fallback to interior
    if len(pts) < 2:
        clipped = tran.intersection(poly)
        if clipped.is_empty:
            return None
        if clipped.geom_type == "MultiLineString":
            return max(list(clipped.geoms), key=lambda ls: ls.length)
        return clipped if clipped.geom_type == "LineString" else None

    # 4) Order the points along the transect and connect extremes
    pts.sort(key=lambda p: tran.project(p))
    return LineString([pts[0], pts[-1]])
```


