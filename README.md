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

### Utility Helpers
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



