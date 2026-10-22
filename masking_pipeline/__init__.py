"""Coordinate → satellite → land-cover masking pipeline.

Vendored from https://github.com/HaoZou39/masking_pipeline ``main`` at
``104cee672b21428d13710eed7be18231b1e9f38a``. Regional OSM and DEM files are
``data/regional/zhejiang-261020.osm.pbf`` and ``data/regional/wenzhou.tif``.

Run from this directory::

    python run.py --lat 27.501662 --lon 120.194639
"""

from __future__ import annotations

import sys
from pathlib import Path

# Sibling modules use absolute imports so `python run.py` still works.
_PACKAGE_DIR = str(Path(__file__).resolve().parent)
if _PACKAGE_DIR not in sys.path:
    sys.path.insert(0, _PACKAGE_DIR)

UPSTREAM_COMMIT = "104cee672b21428d13710eed7be18231b1e9f38a"
