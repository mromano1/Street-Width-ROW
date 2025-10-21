# Street Width ROW with GeoPandas
This notebook reproduces the documented Street_Width_ROW_GeoPandas_Documented.py script in an interactive format.
It:

1. Loads Roadbed and Sidewalk polygons (EPSG:2263 recommended)
2. Derives an approximate centerline per polygon (oriented bounding box axis)
3. Generates perpendicular transects every N feet along each centerline
4. Clips each transect to polygon edges
5. Exports to both a GeoPackage (multi‑layer) and Shapefiles

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
rtree is optional but speeds up spatial operations.

### 2) Inputs

Shapefiles (polygons):
Roadbed_... .shp
SIDEWALK_... .shp
Recommended CRS: EPSG:2263 (US feet). The script will set/convert to 2263 if needed.

### 3) Key parameters

--road_interval_ft, --side_interval_ft: spacing between transects (default 20 ft).
--road_reach_ft, --side_reach_ft: half-length of each raw perpendicular line before clipping (defaults: 600 ft roadbeds, 200 ft sidewalks).
--sample_limit: first N features per layer for preview (-1 = process all).
--no_shp: disable Shapefile export (GeoPackage only).

### 4) Run the script

Preview (first 10 features):
