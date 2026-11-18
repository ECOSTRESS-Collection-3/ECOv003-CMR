# ECOSTRESS Collection 3 CMR Tools

`ECOv003-CMR` searches NASA's [Common Metadata Repository (CMR)](https://cmr.earthdata.nasa.gov/) for ECOSTRESS Collection 3 granules, downloads granules, parses granule metadata, samples Cloud-Optimized GeoTIFF (COG) raster values at geographic points, and builds globally or regionally stratified point-sample datasets over `/vsicurl/`.

[![CI](https://github.com/ECOSTRESS-Collection-3/ECOv003-CMR/actions/workflows/ci.yml/badge.svg)](https://github.com/ECOSTRESS-Collection-3/ECOv003-CMR/actions/workflows/ci.yml)

---

## Table of Contents

1. [Requirements and Installation](#requirements-and-installation)
2. [NASA Earthdata Authentication](#nasa-earthdata-authentication)
3. [Supported Collection 3 Products](#supported-collection-3-products)
4. [Command-Line Tools (`ECOv003-search` & `ECOv003-download`)](#command-line-tools)
5. [Python API: Searching NASA CMR](#python-api-searching-nasa-cmr)
6. [Python API: Downloading & Opening Granules](#python-api-downloading--opening-granules)
7. [Python API: Point Sampling & `/vsicurl/` Batch Extraction](#python-api-point-sampling--vsicurl-batch-extraction)
8. [Python API: Global & Regional Stratified Dataset Builder](#python-api-global--regional-stratified-dataset-builder)
9. [Python API: Granule ID, Filename & Tile Utilities](#python-api-granule-id-filename--tile-utilities)
10. [Examples](#examples)
11. [Development and Testing](#development-and-testing)

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
pip install -e ".[dev]"
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
3. **`~/.netrc` file** (recommended for local development, CLI usage, and GDAL `/vsicurl/` byte-range reads):
   ```text
   machine urs.earthdata.nasa.gov
       login YOUR_USERNAME
       password YOUR_PASSWORD
   ```
   Restrict permissions so only your user account can read it:
   ```bash
   chmod 600 ~/.netrc
   ```

### Configuring a Session & GDAL `/vsicurl/` Environment in Python

```python
from ECOv003_CMR import setup_earthdata_session, configure_gdal_earthdata_env

# Load credentials automatically from environment variables or ~/.netrc
session = setup_earthdata_session()

# Configure a process-wide rasterio.Env for authenticated /vsicurl/ byte-range COG reads
with configure_gdal_earthdata_env(session=session):
    ...
```

All download and point-sampling functions accept `session=...` and will automatically call `setup_earthdata_session()` if none is provided.

---

## Supported Collection 3 Products

| Product Code | Collection DOI | CMR Concept ID | Description | Representative Variables |
|---|---|---|---|---|
| `L1CT_RAD` | `10.5067/ECOSTRESS/ECO_L1CT_RAD.003` | `C4142244484-LPCLOUD` | Calibrated at-sensor radiance (tiled) | `radiance_1` – `radiance_6` |
| `L2T_LSTE` | `10.5067/ECOSTRESS/ECO_L2T_LSTE.003` | `C3998139651-LPCLOUD` | Land surface temperature and emissivity | `LST`, `LST_err`, `QC`, `EmisWB`, `Emis1`–`Emis5`, `view_zenith`, `height` |
| `L2T_STARS` | `10.5067/ECOSTRESS/ECO_L2T_STARS.003` | `C3998139658-LPCLOUD` | Surface reflectance, vegetation, albedo & UQ priors | `NDVI`, `NDVI-UQ`, `albedo`, `albedo-UQ` |
| `L3T_ETAUX` | `10.5067/ECOSTRESS/ECO_L3T_ETAUX.003` | `C4057520953-LPCLOUD` | Tiled evapotranspiration auxiliary data | `Ta`, `RH`, `SM`, `Rg`, `Rn`, `cloud`, `water` |
| `L3T_JET` | `10.5067/ECOSTRESS/ECO_L3T_JET.003` | `C4057232489-LPCLOUD` | Jet Propulsion Laboratory ET & ensemble partitioning | `PTJPLSMinst`, `ETdaily`, `ETuncertainty`, `PTJPLSMcanopy`, `STICJPLdaily`, `BESSJPLdaily`, `PMJPLdaily` |
| `L4T_ESI` | `10.5067/ECOSTRESS/ECO_L4T_ESI.003` | `C4057232495-LPCLOUD` | Evaporative Stress Index | `ESI` |
| `L4T_WUE` | `10.5067/ECOSTRESS/ECO_L4T_WUE.003` | `C4057232498-LPCLOUD` | Water Use Efficiency | `WUE` |

> **Migration Note:** Collection 3 replaces the separate Collection 2 `L3T_MET`, `L3T_SM`, and `L3T_SEB` products with `L3T_ETAUX`. Discontinued Collection 2 product codes raise a `ValueError`.

You can access the product-to-concept-ID and DOI dictionaries directly in Python:

```python
from ECOv003_CMR import CONCEPT_IDS, COLLECTION_3_DOIS, DOWNLOAD_DIRECTORY, CMR_SEARCH_URL

print(CONCEPT_IDS["L3T_JET"])       # 'C4057232489-LPCLOUD'
print(COLLECTION_3_DOIS["L3T_JET"]) # '10.5067/ECOSTRESS/ECO_L3T_JET.003'
```

---

## Command-Line Tools

Installing `ECOv003-CMR` registers two CLI commands: `ECOv003-search` and `ECOv003-download`.

### `ECOv003-search`

Searches NASA CMR for ECOSTRESS Collection 3 granules matching one or more products, Sentinel-2 tiles, and a date range.

```bash
# Print matching unique granule IDs to stdout
ECOv003-search \
  --product L2T_LSTE L2T_STARS L3T_JET \
  --tile 52NHN 53NMH \
  --start-date 2026-06-01 \
  --end-date 2026-06-07

# Filter by orbit/scene/cloud cover and export full file listing to CSV
ECOv003-search \
  --product L2T_LSTE \
  --tile 52NHN \
  --start-date 2026-06-01 \
  --orbit 44814 \
  --scene 1 \
  --max-cloud-cover 20 \
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
| `--max-cloud-cover` | Optional maximum CMR cloud cover percentage filter. |
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

Queries CMR across one or more products and tiles using full Sentinel-2 tile WGS84 bounding boxes (`use_tile_bounds=True` by default, with exact `_<TILE>_` granule ID filtering) and returns a structured `pandas.DataFrame` with columns `product`, `variable`, `orbit`, `scene`, `tile`, `type`, `granule`, `filename`, `URL`, `cloud_cover`, and `acquisition_datetime`.

```python
from datetime import date
from ECOv003_CMR import ECOSTRESS_CMR_search

results = ECOSTRESS_CMR_search(
    product=["L2T_LSTE", "L3T_ETAUX", "L3T_JET"],
    tile=["52NHN", "53NMH"],
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
    max_cloud_cover=20.0,
)

# Filter to GeoTIFF science layers
geotiffs = results[results["type"] == "GeoTIFF Data"]
print(geotiffs[["product", "variable", "granule", "URL"]].head())
```

### Lower-Level Search & Concept ID Helpers

- **`ECOSTRESS_CMR_search_entries(...)` & `ECOSTRESS_CMR_search_links(...)`**  
  Query CMR `granules.json` using tile WGS84 bounds or custom regional bounding boxes with automatic `CMR-Search-After` pagination and exponential backoff on HTTP `429`/`503` responses.
- **`interpret_ECOSTRESS_URLs(URLs, orbit=None, scene=None, entry_metadata=None)`**  
  Parses a `List[str]` of ECOSTRESS URLs into the structured metadata `DataFrame`.
- **`fetch_granule_metadata(json_url, session=None)`**  
  Inspects a per-granule `.json` metadata sidecar for `QAPercentCloudCover` / `CloudCover` and product metadata prior to raster access.
- **`concept_ID_from_DOI(DOI)` & `lookup_collection_3_concept_IDs()`**  
  Look up or bulk-verify current LPCLOUD CMR Concept IDs against official Collection 3 DOIs.

---

## Python API: Downloading & Opening Granules

### Download a Single Granule: `download_ECOSTRESS_granule()`

Downloads all files for a single matching granule and returns an opened `ECOSTRESSGranule` object:

```python
from datetime import date
from ECOv003_CMR import download_ECOSTRESS_granule, setup_earthdata_session

session = setup_earthdata_session()

granule = download_ECOSTRESS_granule(
    product="L2T_LSTE",
    tile="52NHN",
    acquisition_date=date(2026, 6, 1),
    orbit=44814,
    scene=1,
    parent_directory="./data",
    session=session,
)

print(granule.granule_name)
print(granule.variables)
print(granule.layer_URI("LST"))
```

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
```

### Open Already-Downloaded Granules: `open_ECOSTRESS_granule()`

Opens a local Collection 3 granule directory (or `.zip` archive) for any of the seven supported products (`L1CT_RAD`, `L2T_LSTE`, `L2T_STARS`, `L3T_ETAUX`, `L3T_JET`, `L4T_ESI`, `L4T_WUE`), raising `FileNotFoundError` or `ValueError` if the path is invalid or unrecognized:

```python
from ECOv003_CMR.granule_compatibility import open_ECOSTRESS_granule

granule = open_ECOSTRESS_granule("./data/ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01")
print(granule.product)     # 'L3T_ETAUX'
print(granule.variables)   # ['Ta', ...]
```

---

## Python API: Point Sampling & `/vsicurl/` Batch Extraction

Point-sampling functions extract pixel values directly from remote Cloud-Optimized GeoTIFFs (COGs) without saving local raster files.

- Coordinates are interpreted in **WGS84 (`EPSG:4326`)**; `GeoDataFrame` and `GeoSeries` inputs in projected CRS (such as UTM or Web Mercator) are automatically reprojected to `EPSG:4326`.
- Instantaneous products (`L2T_LSTE`, `L3T_ETAUX`, `L3T_JET`, `L4T_ESI`, `L4T_WUE`) join across `(orbit, scene, tile, timestamp)` so multiple overpasses on the same UTC date never collide, while daily `L2T_STARS` priors join by `(tile, YYYYMMDD)`.

### Available Sampling Layers

| Layer Name | Source Product | Source Variable | Units / Description |
|---|---|---|---|
| `ST_C` | `L2T_LSTE` | `LST` | Land surface temperature in **Celsius** (converted from Kelvin) |
| `LST`, `LST_err` | `L2T_LSTE` | `LST`, `LST_err` | Land surface temperature and uncertainty ($\text{K}$) |
| `QC` | `L2T_LSTE` | `QC` | Quality control bitmask flags |
| `emissivity`, `EmisWB` | `L2T_LSTE` | `EmisWB` | Wideband emissivity ($0$–$1$) |
| `Emis1` – `Emis5` | `L2T_LSTE` | `Emis1` – `Emis5` | Spectral band emissivities ($0$–$1$) |
| `Emis1_err` – `Emis5_err` | `L2T_LSTE` | `Emis1_err` – `Emis5_err` | Spectral band emissivity uncertainties |
| `view_zenith`, `height` | `L2T_LSTE` | `view_zenith`, `height` | Sensor view zenith angle ($\text{deg}$) and elevation ($\text{m}$) |
| `NDVI`, `NDVI-UQ` | `L2T_STARS` | `NDVI`, `NDVI-UQ` | Normalized Difference Vegetation Index & UQ prior |
| `albedo`, `albedo-UQ` | `L2T_STARS` | `albedo`, `albedo-UQ` | Broadband surface albedo & UQ prior |
| `Ta_C`, `Ta` | `L3T_ETAUX` | `Ta` | Near-surface air temperature in **Celsius** |
| `RH`, `SM` | `L3T_ETAUX` | `RH`, `SM` | Relative humidity ratio ($0$–$1$) and soil moisture ($0$–$1$) |
| `Rg`, `Rn` | `L3T_ETAUX` | `Rg`, `Rn` | Incoming global solar & net radiation ($\text{W/m}^2$) |
| `cloud`, `water` | `L3T_ETAUX` | `cloud`, `water` | Cloud and water masks |
| `PTJPLSMinst`, `PTJPLSMdaily` | `L3T_JET` | `PTJPLSMinst`, `PTJPLSMdaily` | Instantaneous ($\text{W/m}^2$) & daily ($\text{mm/day}$) PT-JPL-SM ET |
| `PTJPLSMcanopy`, `PTJPLSMsoil`, `PTJPLSMinterception` | `L3T_JET` | `PTJPLSMcanopy`, `PTJPLSMsoil`, `PTJPLSMinterception` | PT-JPL-SM ET partitioning components |
| `ETdaily`, `ETuncertainty` | `L3T_JET` | `ETdaily`, `ETuncertainty` | Ensemble daily ET and instantaneous ET uncertainty |
| `STICJPLinst`, `STICJPLdaily`, `STICJPLcanopy` | `L3T_JET` | `STICJPLinst`, `STICJPLdaily`, `STICJPLcanopy` | STIC-JPL instantaneous, daily, and canopy ET |
| `BESSJPLdaily`, `PMJPLdaily` | `L3T_JET` | `BESSJPLdaily`, `PMJPLdaily` | BESS-JPL and Penman-Monteith JPL daily ET |
| `ESI` | `L4T_ESI` | `ESI` | Evaporative Stress Index |
| `WUE` | `L4T_WUE` | `WUE` | Water Use Efficiency |

---

### 1. Granule-Grouped Multi-Point `/vsicurl/` Sampling: `sample_points_from_granule()`

Opens each requested GeoTIFF **once** over authenticated `/vsicurl/` HTTP byte-range requests (falling back to `MemoryFile` if needed) and extracts all $K$ coordinates in a single vectorized `src.sample()` call:

```python
from ECOv003_CMR import (
    setup_earthdata_session,
    configure_gdal_earthdata_env,
    sample_points_from_granule,
    summarize_point_samples,
)

session = setup_earthdata_session()
coords = [(-118.2437, 34.0522), (-118.4085, 33.9416)]
variable_urls = {
    "LST": "https://data.lpdaac.earthdatacloud.nasa.gov/.../ECOv003_L2T_LSTE_..._LST.tif",
    "PTJPLSMinst": "https://data.lpdaac.earthdatacloud.nasa.gov/.../ECOv003_L3T_JET_..._PTJPLSMinst.tif",
    "ETuncertainty": "https://data.lpdaac.earthdatacloud.nasa.gov/.../ECOv003_L3T_JET_..._ETuncertainty.tif",
}

with configure_gdal_earthdata_env(session=session):
    df = sample_points_from_granule(
        variable_urls=variable_urls,
        coords=coords,
        layers=["ST_C", "PTJPLSMinst", "ETuncertainty"],
        session=session,
    )

print(summarize_point_samples(df))
```

### 2. Sample All Acquisitions in a Date Range: `sample_points_over_date_range()`

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
    layers=["ST_C", "emissivity", "NDVI", "albedo", "Ta_C", "RH", "SM", "PTJPLSMinst"],
    max_workers=10,
    drop_na=True,
)
```

### 3. Sample Near Known Acquisition Datetimes: `sample_points_from_geodataframe()`

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
    date_buffer_days=1,
)
```

---

## Python API: Global & Regional Stratified Dataset Builder

`build_stratified_dataset()` automates global, spatially uniform, seasonally balanced dataset generation across ECOSTRESS orbital coverage ($\pm 54^\circ$ latitude):

1. **Global Tile Discovery (`list_ecostress_land_tiles()`):** Enumerates all land-intersecting Sentinel-2 MGRS tiles within $[-54^\circ, 54^\circ]$ latitude.
2. **Clear-Sky Multi-Product Filtering (`find_clear_sky_et_granules()`):** Identifies daytime clear-sky `L3T_JET` overpasses that have matching `L2T_LSTE`, `L3T_ETAUX`, and same-date `L2T_STARS` granules.
3. **Per-Tile Capping & Seasonal Balance (`select_stratified_granules()`):** Caps each eligible tile at $N_{\text{cap}} = \min_t N_t$ (filtering out sparse tiles below `min_granules_floor`) and balances granule selection across calendar quarters.
4. **Dynamic Per-Acquisition Pixel Randomization (`sample_granule_coordinates()`):** Reads the swath `cloud`/`water` mask and independently randomizes $K = \lceil N_{\text{target}} / G \rceil$ valid land pixels per acquisition (`"stratified_grid"` or `"uniform"`, with optional cropland vs. natural land weighting).
5. **Checkpointed Parquet Streaming:** Extracts all layers via `/vsicurl/` and writes incremental `dataset_part_XXXX.parquet` partitions alongside a `completed_granules.txt` manifest so interrupted runs resume cleanly.

```python
from datetime import date
import logging
from ECOv003_CMR import build_stratified_dataset, UQ_LAYERS, setup_earthdata_session

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
session = setup_earthdata_session()

summary = build_stratified_dataset(
    output_dir="./stratified_dataset_output",
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 30),
    tiles=["11SLT", "11SPS", "52NHN"],  # Omit (tiles=None) to run across all global land tiles
    target_total_samples=1000,
    min_granules_floor=1,
    dispersion_strategy="stratified_grid",
    max_workers=4,
    layers=UQ_LAYERS,  # Optional; defaults to DEFAULT_STRATIFIED_LAYERS
    export_csv=True,
    session=session,
)

print(summary["coverage_summary"])
```

---

## Python API: Granule ID, Filename & Tile Utilities

```python
from ECOv003_CMR import (
    GranuleID,
    granule_ID_from_filename,
    product_name_from_filename,
    find_sentinel2_tile,
)
from ECOv003_CMR.variable_from_filename import variable_from_filename

gid = granule_ID_from_filename("ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02_LST.tif")
print(str(gid), gid.product, gid.orbit, gid.scene, gid.tile)

stars_gid = GranuleID("ECOv003_L2T_STARS_53PMK_20260601_01")
print(stars_gid.product, stars_gid.tile, stars_gid.orbit)

print(product_name_from_filename("ECOv003_L3T_JET_44814_001_53NMH_20260601T000306_01_PTJPLSMinst.tif"))
print(variable_from_filename("ECOv003_L3T_JET_44814_001_53NMH_20260601T000306_01_PTJPLSMinst.tif"))
print(find_sentinel2_tile(-118.2437, 34.0522))  # '11SLT'
```

---

## Examples

Runnable end-to-end scripts are available in [`examples/`](examples/):

- [`examples/stratified_sampling_demo.py`](examples/stratified_sampling_demo.py) — Stratified multi-product dataset extraction with `/vsicurl/` byte-range reads, Parquet checkpointing, and layer coverage diagnostics.
- [`examples/download_granules_demo.py`](examples/download_granules_demo.py) — Downloading `L2T_LSTE` and `L2T_STARS` granules via `download_ECOSTRESS_granule()`.
- [`examples/point_sampling_demo.py`](examples/point_sampling_demo.py) — Single-coordinate multi-product sampling (`L2T_LSTE` + `L2T_STARS`) with Kelvin-to-Celsius conversion.
- [`examples/geodataframe_sampling_demo.py`](examples/geodataframe_sampling_demo.py) — Multi-site `GeoDataFrame` batch sampling across a date range using `sample_points_over_date_range()`.
- [`examples/csv_to_geodataframe_demo.py`](examples/csv_to_geodataframe_demo.py) — Loading site coordinates and metadata from a CSV file, converting to `GeoDataFrame`, sampling all acquisitions, and exporting results to CSV.

---

## Development and Testing

The offline test suite uses mocked CMR responses and in-memory GeoTIFF fixtures and does not require network access or Earthdata credentials:

```bash
pytest -v
```

To run the live authenticated NASA CMR integration tests (requires `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`):

```bash
pytest -m integration -v
```

To build distribution wheels and source archives locally:

```bash
make build
```