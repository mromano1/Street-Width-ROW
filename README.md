# Street Width ROW with GeoPandas
This notebook reproduces the documented Street_Width_ROW_GeoPandas_Documented.py script in an interactive format.
It:

Loads Roadbed and Sidewalk polygons (EPSG:2263 recommended)
Derives an approximate centerline per polygon (oriented bounding box axis)
Generates perpendicular transects every N feet along each centerline
Clips each transect to polygon edges
Exports to both a GeoPackage (multi‑layer) and Shapefiles

# Requirements
Python 3.10+
geopandas, shapely >= 2.0, fiona
(Optional: rtree or pygeos for spatial indexing performance)*

If you see a Shapely/NumPy array-interface error, ensure you are using the default Fiona reader via GeoPandas. This notebook uses GeoPandas' standard I/O.

### 1) Environment setup

```python
# Create and activate an environment
conda create -n row python=3.11 geopandas shapely fiona rtree -c conda-forge
conda activate row
```

