# ECOSTRESS Collection 3 CMR Tools

`ECOv003-CMR` searches NASA's [Common Metadata Repository (CMR)](https://cmr.earthdata.nasa.gov/) for ECOSTRESS Collection 3 granules, downloads granules, and samples raster values at geographic points.

[![CI](https://github.com/ECOSTRESS-Collection-3/ECOv003-CMR/actions/workflows/ci.yml/badge.svg)](https://github.com/ECOSTRESS-Collection-3/ECOv003-CMR/actions/workflows/ci.yml)

## Requirements and installation

Python 3.11 or later is required. Install the package from PyPI:

```bash
python -m pip install ECOv003-CMR
```

## NASA Earthdata authentication

CMR search is public. Downloading and reading ECOSTRESS data requires a NASA Earthdata account and credentials. Configure either `~/.netrc`:

```text
machine urs.earthdata.nasa.gov
    login YOUR_USERNAME
    password YOUR_PASSWORD
```

or the `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` environment variables. Protect the `.netrc` file so that only your account can read it:

```bash
chmod 600 ~/.netrc
```

Create an account at [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov/) and authorize the relevant LP DAAC applications if prompted.

## Supported products

The package supports these Collection 3 CMR product codes:

| Product | Description | Example variables |
|---|---|---|
| `L1CT_RAD` | Calibrated at-sensor radiance | `radiance_1` |
| `L2T_LSTE` | Land surface temperature and emissivity | `LST`, `LST_err`, `QC`, `EmisWB` |
| `L2T_STARS` | Surface reflectance and vegetation/albedo layers | `NDVI`, `albedo` |
| `L3T_ETAUX` | Tiled evapotranspiration auxiliary data | `Ta`, `RH`, `SM`, `Rg`, `Rn`, `cloud`, `water` |
| `L3T_JET` | Jet Propulsion Laboratory evapotranspiration product | `PTJPLSMinst` |
| `L4T_ESI` | Evaporative Stress Index | `ESI` |
| `L4T_WUE` | Water Use Efficiency | `WUE` |

Collection 3 replaces the separate Collection 2 `L3T_MET`, `L3T_SM`, and `L3T_SEB` products with `L3T_ETAUX`. Do not use the discontinued product names for Collection 3 searches.

## Search CMR

Use `ECOSTRESS_CMR_search()` to find files for a product, Sentinel-2 tile, and date range:

```python
from datetime import date
from ECOv003_CMR import ECOSTRESS_CMR_search

results = ECOSTRESS_CMR_search(
    product="L2T_LSTE",
    tile="52NHN",
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
)

geotiffs = results[results["type"] == "GeoTIFF Data"]
print(geotiffs[["product", "variable", "granule", "URL"]].head())
```

The result is a pandas DataFrame with parsed granule and file metadata. Search accepts a product or list of products and a tile or list of tiles. Use `CONCEPT_IDS` for the supported product-to-CMR collection map.

The command-line search accepts the same products:

```bash
ECOv003-search \
  --product L2T_LSTE L2T_STARS \
  --tile 52NHN \
  --start-date 2026-06-01 \
  --end-date 2026-06-07 \
  --output ecostress-files.csv
```

Run `ECOv003-search --help` for all options.

## Download granules

Download and open granules from Python with `download_ECOSTRESS_granule()`:

```python
from datetime import date
from ECOv003_CMR import download_ECOSTRESS_granule

granule = download_ECOSTRESS_granule(
    product="L2T_LSTE",
    tile="52NHN",
    aquisition_date=date(2026, 6, 1),
    parent_directory="./data",
)
print(granule)
```

The default parent directory is `~/data/ECOSTRESS_v003`. The equivalent CLI command is:

```bash
ECOv003-download \
  --product L2T_LSTE \
  --tile 52NHN \
  --start-date 2026-06-01 \
  --parent-directory ./data
```

Downloading requires Earthdata authentication. The CLI accepts multiple products and tiles, date ranges, and optional orbit/scene filters; see `ECOv003-download --help`.

## Point sampling

Point-sampling functions are exported by `ECOv003_CMR`. Coordinates are interpreted as EPSG:4326; GeoDataFrames must declare a CRS and are reprojected to WGS84 when needed. `ST_C` is returned in Celsius, while `LST` remains in Kelvin.

### Search a date range

Use `sample_points_over_date_range()` when you do not know the acquisition times. It searches CMR for acquisitions over the requested period:

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

samples = sample_points_over_date_range(
    geometry=sites,
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
    layers=["ST_C", "NDVI", "albedo", "Ta_C"],
)
print(samples[["site_id", "timestamp", "ST_C", "NDVI", "albedo", "Ta_C"]])
```

The default layers are `ST_C`, `NDVI`, and `albedo`. This function can also accept a single Shapely `Point`, a list of points, or a GeoSeries. It uses `max_workers` to control parallel sampling.

### Sample near known datetimes

Use `sample_points_from_geodataframe()` when your GeoDataFrame has a datetime column for each point. It searches within `date_buffer_days` of each datetime:

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

samples = sample_points_from_geodataframe(
    geometry=sites,
    layers=["ST_C", "NDVI", "albedo"],
    datetime_col="datetime",
    date_buffer_days=1,
)
print(samples[["site_id", "timestamp", "ST_C", "NDVI", "albedo"]])
```

### Available sampling layers

| Layer | Product variable | Units or meaning |
|---|---|---|
| `ST_C` | `L2T_LSTE` / `LST` | Land surface temperature, Celsius (converted from Kelvin) |
| `LST` | `L2T_LSTE` / `LST` | Land surface temperature, Kelvin |
| `LST_err`, `QC`, `EmisWB` / `emissivity` | `L2T_LSTE` | Uncertainty, quality, and wideband emissivity |
| `NDVI`, `albedo` | `L2T_STARS` | Vegetation index and albedo |
| `Ta_C` / `Ta` | `L3T_ETAUX` / `Ta` | Near-surface air temperature, Celsius |
| `RH`, `SM` | `L3T_ETAUX` | Relative humidity and soil moisture ratios |
| `Rg`, `Rn` | `L3T_ETAUX` | Global and net radiation, W/m² |
| `cloud`, `water` | `L3T_ETAUX` | Cloud and water masks |

The former `EVI` and `SAVI` layers are not included in the supported Collection 3 sampling mappings. Unsupported layers raise `ValueError`.

### Sample one raster URL

`sample_point_from_url()` samples one pixel from a raster URL and returns `(value, metadata)`. If the point is outside the raster or has nodata, the value is `None` and the second result describes the reason.

```python
from ECOv003_CMR import setup_earthdata_session, sample_point_from_url

session = setup_earthdata_session()
value, metadata = sample_point_from_url(
    session=session,
    url="URL_FROM_A_CMR_SEARCH_RESULT",
    lon=-118.2437,
    lat=34.0522,
)
```

See the scripts in [`examples/`](examples/) for runnable workflows, including CSV input and multi-site sampling.

## Development and tests

The test suite uses mocked CMR responses and in-memory raster fixtures; it does not require authenticated downloads:

```bash
pytest -q
```

Live authenticated download/open and point-sampling checks are recommended before a release.
