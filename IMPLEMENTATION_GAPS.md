# Implementation Gaps

- The DEM filename and Markdown indicate a 10 m input resolution and 1800 m
  local side length. Raster metadata reports a different geographic pixel size,
  but the Markdown says DEM is treated as local-grid data and not re-derived
  from tif geographic metadata, so `dem_input_resolution_m` remains a config
  value.
- Demand weights are not defined by the Markdown data module, so the demand tool
  returns `None` for weights.
