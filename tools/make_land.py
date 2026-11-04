"""Builds cindrix_overwatch/data/land.json from Natural Earth's 110m land outline (public domain).

Run by the 'map-data' workflow, which downloads ne_110m_land.geojson first. Usage:
  python tools/make_land.py ne_110m_land.geojson cindrix_overwatch/data/land.json
"""
import json
import sys


def rings(geojson):
    out = []
    for f in geojson["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            out.append([[round(x, 2), round(y, 2)] for x, y in poly[0]])   # outer ring only
    return out


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        data = rings(json.load(f))
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    print(len(data), "rings,", sum(len(r) for r in data), "points")
