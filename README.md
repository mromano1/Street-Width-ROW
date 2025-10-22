# Street Width ROW using Python/GeoPandas

This notebook builds “tape‑measure” transects across each Right‑of‑Way (ROW) polygon (roadbeds and sidewalks). For each polygon, we create a fast, stable proxy **centerline** from the polygon’s **oriented minimum bounding rectangle**, sample points along it, emit **perpendicular** lines, and **clip** those lines exactly to the polygon edges so each transect spans boundary‑to‑boundary. The result is a defensible set of width measurements at regular intervals.



## Why these libraries?

- **GeoPandas**: idiomatic vector GIS operations (read/write, CRS handling, vectorized ops) using GDAL/Fiona/Shapely under the hood.  
- **Shapely ≥ 2.0**: modern, robust geometry predicates/ops (buffer, clip, intersection, line interpolation). Crucial for clipping transects to polygon edges.  
- **Fiona** (via GeoPandas I/O): stable read/write of Shapefile/GeoPackage formats.  
- **Matplotlib**: lightweight map previews for QA (no heavy styling required).

> **Note**: This notebook uses an **oriented minimum bounding rectangle** centerline (fast & robust for elongated ROW polygons). If you need more “center‑of‑mass” fidelity for very irregular shapes, you can swap in a skeletonization method later (e.g., `momepy`) while keeping the rest of the pipeline the same.



## Notes & Extensions

- **CRS**: Distances (interval, reach) assume a projected CRS in linear units (feet/meters). This notebook defaults to **EPSG:2263** (NY State Plane feet).
- **Edge cases**: Very irregular or branched polygons may not be well-captured by a single straight-axis centerline. Consider swapping in `momepy.skeletonize` to derive a medial axis if needed.
- **Attributes**: If you need attributes on transects (e.g., join back to original polygon IDs), carry IDs through the loops and build GeoDataFrames with those columns before exporting.
- **Performance**: For huge layers, run per borough/tile, or increase interval and reduce reach for faster processing during prototyping.



## 1) Environment setup

Create and activate a conda environment with the geospatial stack (run in a terminal, not in this notebook):

```bash
conda create -n row python=3.11 geopandas shapely fiona rtree -c conda-forge
conda activate row
```
> `rtree` is optional but speeds up spatial operations.



## 2) Inputs

Shapefiles (polygons):

- `Roadbed_... .shp`
- `SIDEWALK_... .shp`

Recommended CRS: **EPSG:2263** (US feet). The script will set/convert to 2263 if needed.



## 3) Key parameters

**Exactly what this cell does:**  
- Defines input paths and output locations.  
- Sets spacing (**interval**) between transects and the half‑length (**reach**) of raw perpendiculars before clipping.  
- Configures sampling for quick iteration, Shapefile export toggle, and the target CRS in feet.



```python

# --- Parameters: edit these for your data/env ---

from pathlib import Path

# Required inputs (polygon shapefiles)
ROADBED_SHP  = "/Python/Data/Roadbed_Exported_test.shp"
SIDEWALK_SHP = "/Python/Data/SIDEWALK_Export_test.shp"

# Outputs
OUT_GPKG = "/Python/Output/ROW_outputs.gpkg"   # multi-layer GeoPackage
# Shapefiles will be written alongside the notebook working directory unless you change the paths below.

# Spacing & reach (feet; EPSG:2263 recommended)
ROAD_INTERVAL_FT = 20.0   # spacing between roadbed transects
SIDE_INTERVAL_FT = 20.0   # spacing between sidewalk transects
ROAD_REACH_FT    = 200.0  # half-length of raw perpendicular for roadbeds (longer = safer across wide ROW)
SIDE_REACH_FT    = 50.0  # half-length for sidewalks (narrower)

# Quick preview limit: set to None for all features; N for faster iteration
SAMPLE_LIMIT = None

# Also export Shapefiles as standalone layers?
EXPORT_SHP = True

# Target CRS: State Plane NY Long Island (US foot) — change if your region differs
TARGET_CRS = "EPSG:2263"

```


## 4) Imports & Setup

**Exactly what this cell does:**  
- Imports core libraries.  
- Sets up Matplotlib inline plotting (for QA).  
- Does not alter global styles; plots are intentionally simple.



```python

from __future__ import annotations

import math
from typing import List, Tuple

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
import matplotlib.pyplot as plt

# Optional: make plots render in notebooks
%matplotlib inline

```


## 5) Utility Helpers

**Exactly what this cell does:**  
- Provides safe file deletion helpers to clear previous exports (especially Shapefile sidecars) so you don’t get stale/locked files on re-runs.



```python

def _delete_if_exists(path: Path) -> None:
    """Delete a single file if it exists (ignore errors)."""
    try:
        Path(path).unlink(missing_ok=True)
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


## 6) Geometry Foundations

**Exactly what this cell does:**  
- Builds a straight‑line **centerline proxy** from the polygon’s **minimum rotated rectangle** (longest edge).  
- Samples points along that centerline at a fixed interval.  
- Computes a unit **tangent** at each sample and rotates it 90° to get a **perpendicular** (normal).  
- Creates a long raw transect for each sample and **clips** it to the polygon boundaries so endpoints lie on the edges (or to the longest interior piece if boundary intersections are messy).



```python

def oriented_bbox_axis(poly: Polygon) -> LineString:
    """Return a straight line representing the *long* edge of the polygon's oriented MBR.
    This provides a stable, fast proxy for a “centerline” through elongated polygons.
    """
    mbr = poly.minimum_rotated_rectangle
    coords = list(mbr.exterior.coords)[:-1]  # drop duplicate closing coord
    # There should be 4 unique coords for the rectangle
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


## 7) Build Transects

**Exactly what this cell does:**  
- For a single polygon, computes the centerline, samples points at the configured interval, creates perpendiculars, and clips them.  
- Returns `(centerline, [clipped_transects...])`.



```python

def build_transects(poly: Polygon, interval: float = 20.0, reach: float = 200.0):
    """Return (centerline, [transects...]) for a polygon."""
    center = oriented_bbox_axis(poly)
    pts = sample_points_along_line(center, interval)
    lines = []
    for p in pts:
        t = unit_tangent(center, center.project(p))
        raw = perpendicular_transect(p, t, reach)
        clipped = clip_transect(raw, poly)
        if clipped and clipped.length > 0:
            lines.append(clipped)
    return center, lines

```


## 8) Pipeline

**Exactly what this cell does:**  
1. **Read** roadbed/sidewalk shapefiles (via GeoPandas/Fiona).  
2. **Ensure CRS** is EPSG:2263 (feet) for consistent distance math.  
3. **Optionally sample** first *N* features for quick iteration.  
4. **Loop over polygons** and build centerlines/transects (handling MultiPolygons).  
5. **Assemble GeoDataFrames** for export and return them.



```python

def process(
    roadbed_path: str,
    sidewalk_path: str,
    out_gpkg: str,
    road_interval_ft: float = 20.0,
    side_interval_ft: float = 20.0,
    road_reach_ft: float = 600.0,
    side_reach_ft: float = 200.0,
    sample_limit: int | None = 10,
    export_shapefiles: bool = True,
    target_crs: str = "EPSG:2263",
):
    # 1) Read
    road = gpd.read_file(roadbed_path)
    side = gpd.read_file(sidewalk_path)

    # 2) CRS handling
    if road.crs is None:
        road = road.set_crs(target_crs)
    else:
        road = road.to_crs(target_crs)
    if side.crs is None:
        side = side.set_crs(target_crs)
    else:
        side = side.to_crs(target_crs)

    # 3) Optional sampling
    if sample_limit is not None:
        road = road.head(sample_limit)
        side = side.head(sample_limit)

    # 4) Build per layer
    road_centers, road_trs = [], []
    for poly in road.geometry:
        if poly is None:
            continue
        if isinstance(poly, MultiPolygon):
            for p in poly.geoms:
                c, trs = build_transects(p, interval=road_interval_ft, reach=road_reach_ft)
                road_centers.append(c)
                road_trs.extend(trs)
        elif isinstance(poly, Polygon):
            c, trs = build_transects(poly, interval=road_interval_ft, reach=road_reach_ft)
            road_centers.append(c)
            road_trs.extend(trs)

    side_centers, side_trs = [], []
    for poly in side.geometry:
        if poly is None:
            continue
        if isinstance(poly, MultiPolygon):
            for p in poly.geoms:
                c, trs = build_transects(p, interval=side_interval_ft, reach=side_reach_ft)
                side_centers.append(c)
                side_trs.extend(trs)
        elif isinstance(poly, Polygon):
            c, trs = build_transects(poly, interval=side_interval_ft, reach=side_reach_ft)
            side_centers.append(c)
            side_trs.extend(trs)

    # 5) Assemble GDFs
    gdf_rc = gpd.GeoDataFrame(geometry=road_centers, crs=target_crs)
    gdf_rt = gpd.GeoDataFrame(geometry=road_trs, crs=target_crs)
    gdf_sc = gpd.GeoDataFrame(geometry=side_centers, crs=target_crs)
    gdf_st = gpd.GeoDataFrame(geometry=side_trs, crs=target_crs)

    return gdf_rc, gdf_rt, gdf_sc, gdf_st

```


## 9) Run the Pipeline

**Exactly what this cell does:**  
- Executes the process with your parameters.  
- Prints basic counts to confirm output density.  
- If counts look low, check CRS and increase `*_REACH_FT`.



```python

# Execute the pipeline (edit paths above first)
# NOTE: This will fail if the input paths are placeholders.
gdf_rc, gdf_rt, gdf_sc, gdf_st = process(
    roadbed_path=ROADBED_SHP,
    sidewalk_path=SIDEWALK_SHP,
    out_gpkg=OUT_GPKG,
    road_interval_ft=ROAD_INTERVAL_FT,
    side_interval_ft=SIDE_INTERVAL_FT,
    road_reach_ft=ROAD_REACH_FT,
    side_reach_ft=SIDE_REACH_FT,
    sample_limit=SAMPLE_LIMIT,
    export_shapefiles=EXPORT_SHP,
    target_crs=TARGET_CRS,
)

print(f"Roadbed centerlines: {len(gdf_rc)}")
print(f"Roadbed transects:   {len(gdf_rt)}")
print(f"Sidewalk centerlines:{len(gdf_sc)}")
print(f"Sidewalk transects:  {len(gdf_st)}")

```


## 10) Exports

**Exactly what this cell does:**  
- Writes a clean **GeoPackage** with four layers.  
- Optionally clears and writes **Shapefiles** for compatibility.



```python

# --- GeoPackage (multi-layer) ---
out_gpkg_path = Path(OUT_GPKG)
try:
    out_gpkg_path.unlink(missing_ok=True)  # start clean
except Exception:
    pass

gdf_rc.to_file(OUT_GPKG, layer="roadbed_centerlines", driver="GPKG")
gdf_rt.to_file(OUT_GPKG, layer="roadbed_transects",   driver="GPKG")
gdf_sc.to_file(OUT_GPKG, layer="sidewalk_centerlines", driver="GPKG")
gdf_st.to_file(OUT_GPKG, layer="sidewalk_transects",   driver="GPKG")

print(f"✅ GeoPackage written: {out_gpkg_path.resolve()}")

# --- Shapefiles (standalone) ---
if EXPORT_SHP:
    shp_rc = Path("roadbed_centerlines.shp")
    shp_rt = Path("roadbed_transects.shp")
    shp_sc = Path("sidewalk_centerlines.shp")
    shp_st = Path("sidewalk_transects.shp")

    for shp in (shp_rc, shp_rt, shp_sc, shp_st):
        _delete_shapefile(shp)

    gdf_rc.to_file(shp_rc)
    gdf_rt.to_file(shp_rt)
    gdf_sc.to_file(shp_sc)
    gdf_st.to_file(shp_st)

    print("✅ Shapefiles written: roadbed_centerlines.shp, roadbed_transects.shp, sidewalk_centerlines.shp, sidewalk_transects.shp")

```


## 11) Visualization for QA

**Exactly what this cell does:**  
- Produces a quick two‑panel plot showing centerlines (bold) and transects (thin) for roadbeds and sidewalks.  
- For large datasets, keep `SAMPLE_LIMIT` small to render quickly.



```python

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 12))

# Roadbed
gdf_rt.plot(ax=ax1, linewidth=0.8)  # transects
gdf_rc.plot(ax=ax1, linewidth=2)    # centerlines
ax1.set_title("Roadbed: Centerlines & Transects")
ax1.set_axis_off()

# Sidewalk
gdf_st.plot(ax=ax2, linewidth=0.8)
gdf_sc.plot(ax=ax2, linewidth=2)
ax2.set_title("Sidewalk: Centerlines & Transects")
ax2.set_axis_off()

plt.tight_layout()
plt.show()

```


## Troubleshooting Cheatsheet

- **Transects too short / don’t reach edges** → Increase `ROAD_REACH_FT` / `SIDE_REACH_FT`.
- **Widths look wrong by a scale factor** → CRS mismatch; ensure `TARGET_CRS` is feet and inputs are reprojected.
- **Few/no transects** → Check geometry validity (try `poly.buffer(0)`), verify that polygons aren’t tiny/degenerate.
- **Performance slow** → Use `SAMPLE_LIMIT` during dev; tile data; increase `interval`; keep visualization off until the end.

