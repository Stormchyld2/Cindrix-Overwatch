"""The world outline for the map. Uses data/land.json (Natural Earth, public domain) when present,
otherwise a coarse built-in outline so the map still works.

land.json is a list of rings; each ring is a list of [longitude, latitude].
"""

import json
import os

DATA = os.path.join(os.path.dirname(__file__), "data")

# Coarse fallback outline, drawn on a 1000 x 500 grid (x = longitude + 180, y = 90 - latitude, both x 2.778).
_COARSE = """
33,67 111,56 194,50 278,50 328,83 347,111 306,130 289,153 275,181 231,178 231,200 256,200 270,222 278,228 244,211 208,194 175,161 156,136 153,114 111,83 42,83
347,83 444,56 444,22 333,22 306,44 340,70
286,228 333,222 361,250 403,267 389,311 367,328 339,356 317,381 306,403 292,389 297,361 303,306 275,264 281,244
486,117 514,106 528,89 556,56 583,56 611,67 611,125 578,136 556,144 533,144 508,131 483,150 472,150 475,131
483,150 528,147 589,164 619,217 642,219 611,264 611,292 592,322 556,347 539,311 533,264 525,239 478,239 453,208 453,192 464,172
583,56 667,50 778,33 889,50 1000,67 894,106 861,133 839,167 806,194 794,222 778,244 772,206 750,189 722,222 700,194 683,181 661,189 644,206 619,214 597,172 589,150 578,136 611,125 611,67
817,311 861,283 894,281 925,322 906,358 872,347 819,344
486,111 492,89 503,103 503,108
861,161 889,150 894,128 886,140
"""


def _coarse():
    rings = []
    for line in _COARSE.strip().splitlines():
        ring = []
        for pair in line.split():
            x, y = pair.split(",")
            ring.append([float(x) / 2.778 - 180.0, 90.0 - float(y) / 2.778])
        rings.append(ring)
    return rings


def load_land(path=None):
    """Returns (rings, is_detailed)."""
    path = path or os.path.join(DATA, "land.json")
    try:
        with open(path, encoding="utf-8") as f:
            rings = json.load(f)
        if isinstance(rings, list) and rings and all(isinstance(r, list) and len(r) >= 3 for r in rings):
            return rings, True
    except (OSError, ValueError):
        pass
    return _coarse(), False
