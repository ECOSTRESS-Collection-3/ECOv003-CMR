# ECOSTRESS Collection 3 CMR Tools

`ECOv003-CMR` searches NASA's [Common Metadata Repository (CMR)](https://cmr.earthdata.nasa.gov/) for ECOSTRESS Collection 3 granules, downloads granules, parses granule metadata, and samples Cloud-Optimized GeoTIFF (COG) raster values at geographic points.

[![CI](https://github.com/ECOSTRESS-Collection-3/ECOv003-CMR/actions/workflows/ci.yml/badge.svg)](https://github.com/ECOSTRESS-Collection-3/ECOv003-CMR/actions/workflows/ci.yml)

---

## Table of Contents

1. [Requirements and Installation](#requirements-and-installation)
2. [NASA Earthdata Authentication](#nasa-earthdata-authentication)
3. [Supported Collection 3 Products](#supported-collection-3-products)
4. [Command-Line Tools (`ECOv003-search` & `ECOv003-download`)](#command-line-tools)
5. [Python API: Searching NASA CMR](#python-api-searching-nasa-cmr)
6. [Python API: Downloading & Opening Granules](#python-api-downloading--opening-granules)
7. [Python API: Point Sampling](#python-api-point-sampling)
8. [Python API: Granule ID, Filename & Tile Utilities](#python-api-granule-id-filename--tile-utilities)
9. [Examples](#examples)
10. [Development and Testing](#development-and-testing)

---

## Requirements and Installation

Python 3.11 or later is required. Install the package from PyPI:

```bash
pip install ECOv003-CMR
```

To install from source with development tools (`pytest`, `build`, `twine`, `jupyter`):

```bash
git clone https://github.com/ECOSTRESS-Collection-3/ECOv003-CMR.git
cd ECOv003-CMR
pip install -e .[dev]
```

---

## NASA Earthdata Authentication

CMR metadata searches are public. Downloading granule files and sampling raster URLs require a NASA Earthdata Login account ([urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov/)) with LP DAAC applications authorized.

`setup_earthdata_session()` resolves credentials in the following priority order:

1. **Explicit arguments** passed to `setup_earthdata_session(username=..., password=...)`
2. **Environment variables:**
   ```bash
   export EARTHDATA_USERNAME="YOUR_USERNAME"
   export EARTHDATA_PASSWORD="YOUR_PASSWORD"
   ```
3. **`~/.netrc` file** (recommended for local development and CLI usage):
   ```text
   machine urs.earthdata.nasa.gov
       login YOUR_USERNAME
       password YOUR_PASSWORD
   ```
   Restrict permissions so only your user account can read it:
   ```bash
   chmod 600 ~/.netrc
   ```

### Configuring a Session in Python

```python
from ECOv003_CMR import setup_earthdata_session

# Load credentials automatically from environment variables or ~/.netrc
session = setup_earthdata_session()

# Or pass credentials explicitly
session = setup_earthdata_session(username="YOUR_USERNAME", password="YOUR_PASSWORD")

# Or create an unauthenticated session if credentials are optional
session = setup_earthdata_session(require_auth=False)
```

All download and point-sampling functions accept `session=...` and will automatically call `setup_earthdata_session()` if none is provided.

---

## Supported Collection 3 Products

| Product Code | Collection DOI | CMR Concept ID | Description | Representative Variables |
|---|---|---|---|---|
| `L1CT_RAD` | `10.5067/ECOSTRESS/ECO_L1CT_RAD.003` | `C4142244484-LPCLOUD` | Calibrated at-sensor radiance (tiled) | `radiance_1` – `radiance_6` |
| `L2T_LSTE` | `10.5067/ECOSTRESS/ECO_L2T_LSTE.003` | `C3998139651-LPCLOUD` | Land surface temperature and emissivity | `LST`, `LST_err`, `QC`, `EmisWB`, `view_zenith` |
| `L2T_STARS` | `10.5067/ECOSTRESS/ECO_L2T_STARS.003` | `C3998139658-LPCLOUD` | Surface reflectance, vegetation, and albedo | `NDVI`, `albedo` |
| `L3T_ETAUX` | `10.5067/ECOSTRESS/ECO_L3T_ETAUX.003` | `C4057520953-LPCLOUD` | Tiled evapotranspiration auxiliary data | `Ta`, `RH`, `SM`, `Rg`, `Rn`, `cloud`, `water` |
| `L3T_JET` | `10.5067/ECOSTRESS/ECO_L3T_JET.003` | `C4057232489-LPCLOUD` | Jet Propulsion Laboratory ET product | `PTJPLSMinst`, `ETdaily` |
| `L4T_ESI` | `10.5067/ECOSTRESS/ECO_L4T_ESI.003` | `C4057232495-LPCLOUD` | Evaporative Stress Index | `ESI` |
| `L4T_WUE` | `10.5067/ECOSTRESS/ECO_L4T_WUE.003` | `C4057232498-LPCLOUD` | Water Use Efficiency | `WUE` |

> **Migration Note:** Collection 3 replaces the separate Collection 2 `L3T_MET`, `L3T_SM`, and `L3T_SEB` products with `L3T_ETAUX`. Discontinued Collection 2 product codes raise a `ValueError`.

You can access the product-to-concept-ID dictionary directly in Python:

```python
from ECOv003_CMR import CONCEPT_IDS, DOWNLOAD_DIRECTORY, CMR_SEARCH_URL

print(CONCEPT_IDS["L2T_LSTE"])     # 'C3998139651-LPCLOUD'
print(DOWNLOAD_DIRECTORY)          # '~/data/ECOSTRESS_v003'
```

---

## Command-Line Tools

Installing `ECOv003-CMR` registers two CLI commands: `ECOv003-search` and `ECOv003-download`.

### `ECOv003-search`

Searches NASA CMR for ECOSTRESS Collection 3 granules matching one or more products, Sentinel-2 tiles, and a date range.

```bash
# Print matching unique granule IDs to stdout
ECOv003-search \
  --product L2T_LSTE L2T_STARS \
  --tile 52NHN 53NMH \
  --start-date 2026-06-01 \
  --end-date 2026-06-07

# Filter by orbit/scene and export full file listing (URLs, variables, file types) to CSV
ECOv003-search \
  --product L2T_LSTE \
  --tile 52NHN \
  --start-date 2026-06-01 \
  --orbit 44814 \
  --scene 1 \
  --output ecostress-files.csv

# Quiet mode (prints only granule IDs to stdout, ideal for shell piping)
ECOv003-search -p L2T_LSTE -t 52NHN -s 2026-06-01 --quiet
```

**Options for `ECOv003-search`:**

| Flag | Description |
|---|---|
| `-p`, `--product` | **(Required)** One or more product codes (`L1CT_RAD`, `L2T_LSTE`, `L2T_STARS`, `L3T_ETAUX`, `L3T_JET`, `L4T_ESI`, `L4T_WUE`). |
| `-t`, `--tile` | **(Required)** One or more Sentinel-2 tile identifiers (e.g., `11SLT`, `52NHN`). |
| `-s`, `--start-date` | **(Required)** Start date in `YYYY-MM-DD` format. |
| `-e`, `--end-date` | End date in `YYYY-MM-DD` format (defaults to `--start-date`). |
| `--orbit` | Optional integer orbit number filter. |
| `--scene` | Optional integer scene number filter. |
| `-o`, `--output` | Path to save the full file listing as CSV. If omitted, unique granule IDs print to stdout. |
| `--cmr-url` | Custom CMR search endpoint URL (defaults to `https://cmr.earthdata.nasa.gov/search/`). |
| `-q`, `--quiet` | Suppress informational progress messages. |

---

### `ECOv003-download`

Searches CMR and downloads all matching ECOSTRESS granule files (`.tif`, `.json`, `.jpeg`, `.aux.xml`) into per-granule directories. Requires Earthdata authentication.

```bash
# Download all L2T_LSTE granules for tile 52NHN on a single date
ECOv003-download \
  --product L2T_LSTE \
  --tile 52NHN \
  --start-date 2026-06-01 \
  --parent-directory ./data

# Download multiple products across a date range and multiple tiles
ECOv003-download \
  --product L2T_LSTE L2T_STARS L3T_ETAUX \
  --tile 11SLT 11SPS \
  --start-date 2026-06-01 \
  --end-date 2026-06-07 \
  --parent-directory ~/data/ECOSTRESS_v003
```

**Options for `ECOv003-download`:**

| Flag | Description |
|---|---|
| `-p`, `--product` | **(Required)** One or more product codes. |
| `-t`, `--tile` | **(Required)** One or more Sentinel-2 tile identifiers. |
| `-s`, `--start-date` | **(Required)** Start date in `YYYY-MM-DD` format. |
| `-e`, `--end-date` | End date in `YYYY-MM-DD` format (defaults to `--start-date`). |
| `--orbit` | Optional integer orbit number filter. |
| `--scene` | Optional integer scene number filter. |
| `--parent-directory` | Target directory where `<granule_id>/` folders are created (defaults to `~/data/ECOSTRESS_v003`). |
| `--cmr-url` | Custom CMR search endpoint URL. |
| `-q`, `--quiet` | Suppress informational progress messages. |

---

## Python API: Searching NASA CMR

### `ECOSTRESS_CMR_search()`

Queries CMR across one or more products and tiles and returns a structured `pandas.DataFrame` with columns `product`, `variable`, `orbit`, `scene`, `tile`, `type`, `granule`, `filename`, and `URL`.

```python
from datetime import date
from ECOv003_CMR import ECOSTRESS_CMR_search

results = ECOSTRESS_CMR_search(
    product=["L2T_LSTE", "L3T_ETAUX"],
    tile=["52NHN", "53NMH"],
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
    orbit=None,   # Optional int filter
    scene=None,   # Optional int filter
)

# Filter to GeoTIFF science layers
geotiffs = results[results["type"] == "GeoTIFF Data"]
print(geotiffs[["product", "variable", "granule", "URL"]].head())
```

### Lower-Level Search & URL Helpers

* **`ECOSTRESS_CMR_search_links(concept_ID, tile, start_date, end_date, CMR_search_URL=...)`**  
  Queries CMR `granules.json` using the Sentinel-2 tile centroid, automatically paginates through all `CMR-Search-After` headers, and returns a raw `List[str]` of `.tif`, `.json`, `.aux.xml`, and `.jpeg` URLs.
* **`interpret_ECOSTRESS_URLs(URLs, orbit=None, scene=None)`**  
  Parses a `List[str]` of ECOSTRESS URLs into the structured metadata `DataFrame` returned by `ECOSTRESS_CMR_search()`.
* **`concept_ID_from_DOI(DOI, CMR_search_URL=...)`**  
  Looks up the current CMR Concept ID string for any ECOSTRESS Collection 3 DOI (e.g., `"10.5067/ECOSTRESS/ECO_L2T_LSTE.003"`).

---

## Python API: Downloading & Opening Granules

### Download a Single Granule: `download_ECOSTRESS_granule()`

Downloads all files for a single matching granule and returns an opened `ECOSTRESSGranule` object (from `ECOv003-granules`, wrapped with Collection 3 directory/product compatibility):

```python
from datetime import date
from ECOv003_CMR import download_ECOSTRESS_granule, setup_earthdata_session

session = setup_earthdata_session()

granule = download_ECOSTRESS_granule(
    product="L2T_LSTE",
    tile="52NHN",
    acquisition_date=date(2026, 6, 1),
    orbit=44814,             # Optional; required if multiple orbits match the same date/tile
    scene=1,                 # Optional
    parent_directory="./data",
    session=session,
)

print(granule.granule_name)
print(granule.variables)
print(granule.layer_URI("LST"))
```

*(Note: `aquisition_date` is also accepted as a backward-compatible keyword alias for `acquisition_date`.)*

### Batch Download Multiple Granules: `download_ECOSTRESS()`

Searches for and downloads every matching granule across multiple products, tiles, and a multi-day date range, returning a `List[ECOSTRESSGranule]`:

```python
from ECOv003_CMR import download_ECOSTRESS

granules = download_ECOSTRESS(
    product=["L2T_LSTE", "L2T_STARS"],
    tile="11SLT",
    start_date="2026-06-01",
    end_date="2026-06-07",
    parent_directory="./data",
)

for g in granules:
    print(g.product, g.granule_name, g.time_UTC)
```

### Download Raw Files Only: `download_ECOSTRESS_granule_files()` and `download_file()`

* **`download_ECOSTRESS_granule_files(...)`** downloads all files for a granule into `<parent_directory>/<granule_id>/` and returns the directory path `str` without instantiating an `ECOSTRESSGranule` object.
* **`download_file(URL, filename=None, granule_directory=None, session=None)`** streams a single authenticated file download atomically via a `.download` temporary file with a `tqdm` progress bar, automatically skipping files already downloaded on disk and cleaning up zero-byte files.

### Open Already-Downloaded Granules: `open_ECOSTRESS_granule()`

Opens a local Collection 3 granule directory (or `.zip` archive) for any of the seven supported products (`L1CT_RAD`, `L2T_LSTE`, `L2T_STARS`, `L3T_ETAUX`, `L3T_JET`, `L4T_ESI`, `L4T_WUE`):

```python
from ECOv003_CMR.granule_compatibility import open_ECOSTRESS_granule

granule = open_ECOSTRESS_granule("./data/ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01")
print(granule.product)     # 'L3T_ETAUX'
print(granule.variables)   # ['Ta', ...]
```

---

## Python API: Point Sampling

Point-sampling functions read Cloud-Optimized GeoTIFF (COG) windows directly over HTTPS into memory without saving full raster files to disk.

* Coordinates are interpreted in **WGS84 (`EPSG:4326`)**; `GeoDataFrame` and `GeoSeries` inputs in other projected CRS (such as UTM or Web Mercator) are automatically reprojected to `EPSG:4326`.
* Requesting any unsupported layer name raises a `ValueError`.

### Available Sampling Layers

| Layer Name | Source Product | Source Variable | Units / Description |
|---|---|---|---|
| `ST_C` | `L2T_LSTE` | `LST` | Land surface temperature in **Celsius** (automatically converted from Kelvin) |
| `LST` | `L2T_LSTE` | `LST` | Land surface temperature in **Kelvin** |
| `LST_err` | `L2T_LSTE` | `LST_err` | Land surface temperature uncertainty ($\text{K}$) |
| `QC` | `L2T_LSTE` | `QC` | Quality control bitmask flags |
| `emissivity` | `L2T_LSTE` | `EmisWB` | Wideband emissivity (alias for `EmisWB`) |
| `EmisWB` | `L2T_LSTE` | `EmisWB` | Wideband emissivity (unitless, $0$–$1$) |
| `NDVI` | `L2T_STARS` | `NDVI` | Normalized Difference Vegetation Index |
| `albedo` | `L2T_STARS` | `albedo` | Broadband surface albedo |
| `Ta_C` | `L3T_ETAUX` | `Ta` | Near-surface air temperature in **Celsius** |
| `Ta` | `L3T_ETAUX` | `Ta` | Alias for `Ta_C` (Celsius) |
| `RH` | `L3T_ETAUX` | `RH` | Relative humidity ratio ($0$–$1$) |
| `SM` | `L3T_ETAUX` | `SM` | Soil moisture ratio ($0$–$1$) |
| `Rg` | `L3T_ETAUX` | `Rg` | Incoming global solar radiation ($\text{W/m}^2$) |
| `Rn` | `L3T_ETAUX` | `Rn` | Net radiation ($\text{W/m}^2$) |
| `cloud` | `L3T_ETAUX` | `cloud` | Cloud mask |
| `water` | `L3T_ETAUX` | `water` | Water mask |

> **Note:** Former Collection 2 STARS layers `EVI` and `SAVI` are not available in Collection 3 and will raise a `ValueError`.

---

### 1. Sample All Acquisitions in a Date Range: `sample_points_over_date_range()`

Recommended when exact satellite overpass times are unknown. Automatically determines Sentinel-2 tiles (unless specified via `tile=...`), searches CMR across the date range, joins instantaneous `L2T_LSTE` acquisitions with same-date `L2T_STARS` and `L3T_ETAUX` layers, and preserves all non-geometry columns from your input `GeoDataFrame`.

```python
from datetime import date
import geopandas as gpd
from shapely.geometry import Point
from ECOv003_CMR import sample_points_over_date_range

sites = gpd.GeoDataFrame(
    {
        "site_id": ["downtown", "airport"],
        "elevation_m": [89, 38],
        "geometry": [Point(-118.2437, 34.0522), Point(-118.4085, 33.9416)],
    },
    crs="EPSG:4326",
)

samples = sample_points_over_date_range(
    geometry=sites,                                      # GeoDataFrame, GeoSeries, Series, Point, or List[Point]
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
    layers=["ST_C", "emissivity", "NDVI", "albedo", "Ta_C", "RH", "SM"],
    tile=None,                                           # Optional str or List[str] to override tile lookup
    max_workers=10,                                      # Parallel download/sampling threads (use 1 for sequential)
    drop_na=True,                                        # Drop rows where any requested layer is NaN/masked
    verbose=True,
)

print(samples[["site_id", "elevation_m", "timestamp", "ST_C", "NDVI", "albedo", "Ta_C"]])
```

---

### 2. Sample Near Known Acquisition Datetimes: `sample_points_from_geodataframe()`

Use when each row in your `GeoDataFrame` already has a target `datetime` (for example, matching flux tower or field campaign observations):

```python
from datetime import datetime
import geopandas as gpd
from shapely.geometry import Point
from ECOv003_CMR import sample_points_from_geodataframe

observations = gpd.GeoDataFrame(
    {
        "site_id": ["downtown", "airport"],
        "datetime": [datetime(2026, 6, 1, 12, 0), datetime(2026, 6, 4, 14, 30)],
        "geometry": [Point(-118.2437, 34.0522), Point(-118.4085, 33.9416)],
    },
    crs="EPSG:4326",
)

samples = sample_points_from_geodataframe(
    geometry=observations,
    layers=["ST_C", "NDVI", "albedo", "QC"],
    datetime_col="datetime",
    tile_col=None,         # Optional column name containing precomputed Sentinel-2 tile IDs
    date_buffer_days=1,    # Search +/- 1 day around each row's datetime
    verbose=True,
)

print(samples[["site_id", "datetime", "timestamp", "ST_C", "NDVI", "albedo"]])
```

---

### 3. Sample a Single Pixel from a Raster URL: `sample_point_from_url()`

Extracts a single pixel value directly from any ECOSTRESS GeoTIFF URL, handling CRS transformation, bounds checking, and nodata/NaN masking:

```python
from ECOv003_CMR import setup_earthdata_session, sample_point_from_url

session = setup_earthdata_session()
value, metadata = sample_point_from_url(
    session=session,
    url="https://data.lpdaac.earthdatacloud.nasa.gov/.../ECOv003_L2T_LSTE_..._LST.tif",
    lon=-118.2437,
    lat=34.0522,
    max_retries=2,
    timeout=90,
)

if value is not None:
    print(f"Value: {value}, CRS: {metadata['crs']}, Bounds: {metadata['bounds']}")
else:
    # metadata contains the failure reason: 'outside_bounds', 'outside_image', 'nodata', or 'network_error: ...'
    print(f"No valid pixel: {metadata}")
```

---

## Python API: Granule ID, Filename & Tile Utilities

`ECOv003_CMR` exports helpers for parsing Collection 3 filenames and mapping coordinates to Sentinel-2 MGRS tiles:

```python
from ECOv003_CMR import (
    GranuleID,
    granule_ID_from_filename,
    product_name_from_filename,
    find_sentinel2_tile,
)
from ECOv003_CMR.variable_from_filename import variable_from_filename

# Parse a Collection 3 standard granule or file path
gid = granule_ID_from_filename("ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02_LST.tif")
print(str(gid))      # 'ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02'
print(gid.product)   # 'L2T_LSTE'
print(gid.orbit)     # 44814
print(gid.scene)     # 1
print(gid.tile)      # '52NHN'

# Parse a Collection 3 L2T_STARS filename (no orbit/scene)
stars_gid = GranuleID("ECOv003_L2T_STARS_53PMK_20260601_01")
print(stars_gid.product, stars_gid.tile, stars_gid.orbit)  # 'L2T_STARS' '53PMK' None

# Extract product and variable names from any ECOSTRESS filename
print(product_name_from_filename("ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01_Ta.tif"))  # 'L3T_ETAUX'
print(variable_from_filename("ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01_Ta.tif"))      # 'Ta'

# Find the nearest Sentinel-2 tile for a WGS84 longitude/latitude
print(find_sentinel2_tile(-118.2437, 34.0522))  # '11SLT'
```

---

## Examples

Runnable end-to-end scripts are available in [`examples/`](examples/):

* [`examples/download_granules_demo.py`](examples/download_granules_demo.py) — Downloading `L2T_LSTE` and `L2T_STARS` granules via `download_ECOSTRESS_granule()`.
* [`examples/point_sampling_demo.py`](examples/point_sampling_demo.py) — Single-coordinate multi-product sampling (`L2T_LSTE` + `L2T_STARS`) with Kelvin-to-Celsius conversion and summary statistics.
* [`examples/geodataframe_sampling_demo.py`](examples/geodataframe_sampling_demo.py) — Multi-site `GeoDataFrame` batch sampling across a date range using `sample_points_over_date_range()`.
* [`examples/csv_to_geodataframe_demo.py`](examples/csv_to_geodataframe_demo.py) — Loading site coordinates and metadata from a CSV file, converting to `GeoDataFrame`, sampling all acquisitions, and exporting results to CSV.

---

## Development and Testing

The offline test suite uses mocked CMR responses and in-memory GeoTIFF fixtures and does not require network access or Earthdata credentials:

```bash
pytest -v
```

To build distribution wheels and source archives locally:

```bash
make build
```