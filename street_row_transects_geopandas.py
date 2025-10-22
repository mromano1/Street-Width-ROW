#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from typing import List, Tuple
import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon, MultiPolygon

def oriented_bbox_axis(poly: Polygon) -> LineString:
    mbr = poly.minimum_rotated_rectangle
    coords = list(mbr.exterior.coords)[:-1]
    edges = [(coords[i], coords[(i + 1) % 4]) for i in range(4)]
    lengths = [Point(a).distance(Point(b)) for a, b in edges]
    a, b = edges[lengths.index(max(lengths))]
    return LineString([a, b])

def sample_points_along_line(line: LineString, interval: float):
    pts = []
    L = line.length
    if L <= 0:
        return pts
    d = 0.0
    while d <= L + 1e-9:
        pts.append(line.interpolate(d))
        d += interval
    return pts

def unit_tangent(line: LineString, s: float):
    L = line.length
    if L == 0:
        return (1.0, 0.0)
    s0 = max(0.0, min(L, s - 0.01))
    s1 = max(0.0, min(L, s + 0.01))
    p0, p1 = line.interpolate(s0), line.interpolate(s1)
    dx, dy = p1.x - p0.x, p1.y - p0.y
    n = (dx * dx + dy * dy) ** 0.5 or 1.0
    return (dx / n, dy / n)

def perpendicular_transect(point: Point, tangent, reach: float) -> LineString:
    tx, ty = tangent
    nx, ny = -ty, tx
    a = Point(point.x - nx * reach, point.y - ny * reach)
    b = Point(point.x + nx * reach, point.y + ny * reach)
    return LineString([a, b])

def clip_transect(tran: LineString, poly: Polygon):
    inter = tran.intersection(poly.boundary)
    pts = []
    if inter.is_empty:
        clipped = tran.intersection(poly)
        if clipped.is_empty:
            return None
        if clipped.geom_type == "MultiLineString":
            return max(list(clipped.geoms), key=lambda ls: ls.length)
        return clipped if clipped.geom_type == "LineString" else None
    if inter.geom_type == "Point":
        pts = [inter]
    elif inter.geom_type == "MultiPoint":
        pts = list(inter.geoms)
    elif inter.geom_type == "GeometryCollection":
        pts = [g for g in inter.geoms if g.geom_type == "Point"]
    if len(pts) < 2:
        clipped = tran.intersection(poly)
        if clipped.is_empty:
            return None
        if clipped.geom_type == "MultiLineString":
            return max(list(clipped.geoms), key=lambda ls: ls.length)
        return clipped if clipped.geom_type == "LineString" else None
    pts.sort(key=lambda p: tran.project(p))
    return LineString([pts[0], pts[-1]])

def build_transects(poly: Polygon, interval: float, reach: float):
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

def process(roadbed_path, sidewalk_path, road_interval_ft, side_interval_ft, road_reach_ft, side_reach_ft, sample_limit, target_crs):
    road = gpd.read_file(roadbed_path)
    side = gpd.read_file(sidewalk_path)
    road = road.set_crs(target_crs) if road.crs is None else road.to_crs(target_crs)
    side = side.set_crs(target_crs) if side.crs is None else side.to_crs(target_crs)
    if sample_limit is not None:
        road = road.head(sample_limit)
        side = side.head(sample_limit)
    road_centers, road_trs = [], []
    for poly in road.geometry:
        if poly is None: continue
        if poly.geom_type == "MultiPolygon":
            for p in poly.geoms:
                c, trs = build_transects(p, road_interval_ft, road_reach_ft)
                road_centers.append(c); road_trs.extend(trs)
        elif poly.geom_type == "Polygon":
            c, trs = build_transects(poly, road_interval_ft, road_reach_ft)
            road_centers.append(c); road_trs.extend(trs)
    side_centers, side_trs = [], []
    for poly in side.geometry:
        if poly is None: continue
        if poly.geom_type == "MultiPolygon":
            for p in poly.geoms:
                c, trs = build_transects(p, side_interval_ft, side_reach_ft)
                side_centers.append(c); side_trs.extend(trs)
        elif poly.geom_type == "Polygon":
            c, trs = build_transects(poly, side_interval_ft, side_reach_ft)
            side_centers.append(c); side_trs.extend(trs)
    gdf_rc = gpd.GeoDataFrame(geometry=road_centers, crs=target_crs)
    gdf_rt = gpd.GeoDataFrame(geometry=road_trs, crs=target_crs)
    gdf_sc = gpd.GeoDataFrame(geometry=side_centers, crs=target_crs)
    gdf_st = gpd.GeoDataFrame(geometry=side_trs, crs=target_crs)
    return gdf_rc, gdf_rt, gdf_sc, gdf_st

def write_outputs(gdf_rc, gdf_rt, gdf_sc, gdf_st, out_gpkg: str, export_shp: bool):
    out_gpkg_path = Path(out_gpkg)
    out_gpkg_path.parent.mkdir(parents=True, exist_ok=True)
    try: out_gpkg_path.unlink(missing_ok=True)
    except Exception: pass
    gdf_rc.to_file(out_gpkg, layer="roadbed_centerlines", driver="GPKG")
    gdf_rt.to_file(out_gpkg, layer="roadbed_transects",   driver="GPKG")
    gdf_sc.to_file(out_gpkg, layer="sidewalk_centerlines", driver="GPKG")
    gdf_st.to_file(out_gpkg, layer="sidewalk_transects",   driver="GPKG")
    if export_shp:
        shp_dir = out_gpkg_path.parent
        gdf_rc.to_file(shp_dir / "roadbed_centerlines.shp")
        gdf_rt.to_file(shp_dir / "roadbed_transects.shp")
        gdf_sc.to_file(shp_dir / "sidewalk_centerlines.shp")
        gdf_st.to_file(shp_dir / "sidewalk_transects.shp")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roadbed", required=True)
    ap.add_argument("--sidewalk", required=True)
    ap.add_argument("--out-gpkg", required=True)
    ap.add_argument("--road-interval", type=float, default=20.0)
    ap.add_argument("--side-interval", type=float, default=20.0)
    ap.add_argument("--road-reach", type=float, default=600.0)
    ap.add_argument("--side-reach", type=float, default=200.0)
    ap.add_argument("--sample-limit", type=int, default=None)
    ap.add_argument("--target-crs", default="EPSG:2263")
    ap.add_argument("--export-shp", action="store_true")
    args = ap.parse_args()

    gdf_rc, gdf_rt, gdf_sc, gdf_st = process(
        args.roadbed, args.sidewalk, args.road_interval, args.side_interval,
        args.road_reach, args.side_reach, args.sample_limit, args.target_crs,
    )
    write_outputs(gdf_rc, gdf_rt, gdf_sc, gdf_st, args.out_gpkg, args.export_shp)
    print("✅ Done.")
    print(f"Roadbed centerlines: {len(gdf_rc)} | transects: {len(gdf_rt)}")
    print(f"Sidewalk centerlines: {len(gdf_sc)} | transects: {len(gdf_st)}")
    print(f"Wrote: {args.out_gpkg}")
    if args.export_shp:
        print("Also wrote Shapefiles next to the GPKG.")

if __name__ == "__main__":
    main()
