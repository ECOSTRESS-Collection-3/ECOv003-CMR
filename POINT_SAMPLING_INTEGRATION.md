# Collection 3 Point Sampling

`ECOv003_CMR.point_sampling` provides point sampling for ECOSTRESS Collection 3 CMR assets. Public functions are exported from `ECOv003_CMR`:

- `sample_point_from_url(session, url, lon, lat)` samples one pixel from one raster URL.
- `sample_points_over_date_range(geometry, start_date, end_date, ...)` searches for available granules over a date range and samples them.
- `sample_points_from_geodataframe(geometry, layers, datetime_col=..., ...)` samples around datetimes already provided in a GeoDataFrame.
- `find_sentinel2_tile(lon, lat)` returns the Sentinel-2 tile for a coordinate when available.

## Collection 3 product and layer mappings

| Sampling layer | CMR product | CMR variable | Units or meaning |
|---|---|---|---|
| `ST_C` | `L2T_LSTE` | `LST` | Land surface temperature converted from Kelvin to Celsius |
| `LST` | `L2T_LSTE` | `LST` | Land surface temperature in Kelvin |
| `LST_err`, `QC` | `L2T_LSTE` | `LST_err`, `QC` | Uncertainty and quality flags |
| `EmisWB`, `emissivity` | `L2T_LSTE` | `EmisWB` | Wideband emissivity |
| `NDVI`, `albedo` | `L2T_STARS` | `NDVI`, `albedo` | Vegetation index and albedo |
| `Ta_C`, `Ta` | `L3T_ETAUX` | `Ta` | Near-surface air temperature in Celsius |
| `RH`, `SM` | `L3T_ETAUX` | `RH`, `SM` | Relative humidity and soil moisture ratios |
| `Rg`, `Rn` | `L3T_ETAUX` | `Rg`, `Rn` | Global and net radiation in W/m² |
| `cloud`, `water` | `L3T_ETAUX` | `cloud`, `water` | Cloud and water masks |

`L3T_ETAUX` replaces the separate Collection 2 `L3T_MET`, `L3T_SM`, and `L3T_SEB` products. Collection 3 STARS mappings do not include `EVI` or `SAVI`. Unknown layer names raise `ValueError` rather than being silently ignored.

## Authentication

CMR metadata searches are public. Sampling data URLs and downloading granules require NASA Earthdata authentication. Configure `~/.netrc` with `machine urs.earthdata.nasa.gov`, or set `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`. `setup_earthdata_session()` creates the authenticated `requests.Session`; the sampling functions create one automatically if none is passed.

## Sampling all available acquisitions

Provide point geometries and a date range when acquisition timestamps are not known:

```python
from datetime import date
import geopandas as gpd
from shapely.geometry import Point
from ECOv003_CMR import sample_points_over_date_range

sites = gpd.GeoDataFrame(
    {
        "site_id": ["downtown", "airport"],
        "geometry": [Point(-118.2437, 34.0522), Point(-118.4085, 33.9416)],
    },
    crs="EPSG:4326",
)

results = sample_points_over_date_range(
    geometry=sites,
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
    layers=["ST_C", "NDVI", "albedo", "Ta_C"],
    max_workers=4,
)
```

By default, this API samples `ST_C`, `NDVI`, and `albedo`. It accepts a GeoDataFrame, GeoSeries, list of Shapely points, or one point. `max_workers=1` runs sequentially.

## Sampling around known datetimes

When each input point has a datetime, use `sample_points_from_geodataframe()`:

```python
from datetime import datetime
import geopandas as gpd
from shapely.geometry import Point
from ECOv003_CMR import sample_points_from_geodataframe

sites = gpd.GeoDataFrame(
    {
        "site_id": ["downtown"],
        "datetime": [datetime(2026, 6, 1, 12)],
        "geometry": [Point(-118.2437, 34.0522)],
    },
    crs="EPSG:4326",
)

results = sample_points_from_geodataframe(
    geometry=sites,
    layers=["ST_C", "NDVI", "albedo"],
    datetime_col="datetime",
    date_buffer_days=1,
)
```

Pass a GeoDataFrame with the configured datetime column. `tile_col` can name a column containing Sentinel-2 tile identifiers; otherwise tiles are determined from the coordinates.

## Raster values, CRS, and nodata

- Coordinates are interpreted in EPSG:4326; GeoDataFrames must declare a CRS and are reprojected to WGS84 when needed.
- `ST_C` converts `LST` from Kelvin; `Ta_C` is an alias for the `L3T_ETAUX` `Ta` variable, already distributed in Celsius.
- A point outside the raster bounds or on a masked/nodata pixel returns no value from `sample_point_from_url()`.
- Point sampling reads the raster response into memory and extracts the requested pixel; no local raster file is created by this API.
- Tests use in-memory GeoTIFFs and mocked CMR responses. They do not replace a real authenticated download/open check, which remains a pre-release integration test.

Runnable workflows are in [`examples/`](examples/). See the [README](README.md) for installation, product support, and additional API examples.
