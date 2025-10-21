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
<mark>rtree</mark> is optional but speeds up spatial operations.

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
