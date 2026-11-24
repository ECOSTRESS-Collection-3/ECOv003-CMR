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
8. [Available Sampling Layers](#available-sampling-layers)
9. [Python API: Global & Regional Stratified Dataset Builder](#python-api-global--regional-stratified-dataset-builder)
10. [Python API: Granule ID, Filename & Tile Utilities](#python-api-granule-id-filename--tile-utilities)
11. [Examples](#examples)
12. [Development and Testing](#development-and-testing)
13. [Version History](#version-history)
14. [Known Issues](#known-issues)

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

`setup_earthdata_session()` mounts a 64-socket HTTP connection pool (`pool_connections=64`, `pool_maxsize=64`) to support high-concurrency COG and sidecar reads cleanly, and resolves credentials in the following priority order:

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

# Context manager exports Netscape URS cookies for /vsicurl/ and removes temp files on exit
with configure_gdal_earthdata_env(session=session):
    ...
```

All search, download, and point-sampling functions accept `session=...` and will automatically call `setup_earthdata_session()` if none is provided. Note that CMR search functions automatically avoid forwarding URS Basic Auth headers to public `cmr.earthdata.nasa.gov` search endpoints while still reusing the session for HTTP connection pooling.

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

---

## Command-Line Tools

Installing `ECOv003-CMR` registers two CLI commands: `ECOv003-search` and `ECOv003-download`.

### `ECOv003-search`

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
```

### `ECOv003-download`

```bash
ECOv003-download \
  --product L2T_LSTE L2T_STARS L3T_ETAUX \
  --tile 11SLT 11SPS \
  --start-date 2026-06-01 \
  --end-date 2026-06-07 \
  --parent-directory ~/data/ECOSTRESS_v003
```

---

## Python API: Searching NASA CMR

```python
from datetime import date
from ECOv003_CMR import ECOSTRESS_CMR_search, setup_earthdata_session

session = setup_earthdata_session(require_auth=False)
results = ECOSTRESS_CMR_search(
    product=["L2T_LSTE", "L3T_ETAUX", "L3T_JET"],
    tile=["52NHN", "53NMH"],
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
    max_cloud_cover=20.0,
    session=session,
)
```

---

## Python API: Downloading & Opening Granules

```python
from datetime import date
from ECOv003_CMR import download_ECOSTRESS, download_ECOSTRESS_granule, setup_earthdata_session

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
```

---

## Python API: Point Sampling & `/vsicurl/` Batch Extraction

`sample_points_from_granule()`, `sample_points_over_date_range()`, and `sample_points_from_geodataframe()` group points by granule, join instantaneous products by `(orbit, scene, tile, timestamp)` and daily `L2T_STARS` priors by `(tile, YYYYMMDD)`, and extract pixels over authenticated `/vsicurl/` HTTP byte-range requests (with automatic jittered-backoff `MemoryFile` fallback).

```python
from datetime import date
import geopandas as gpd
from shapely.geometry import Point
from ECOv003_CMR import sample_points_over_date_range, summarize_point_samples

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
print(summarize_point_samples(samples))
```

`summarize_point_samples()` also accepts a list of Parquet file paths (`summarize_point_samples(parquet_paths)`) to compute layer completeness in $O(1)$ RAM via `pyarrow.parquet` row-group statistics.

---

## Available Sampling Layers

Point sampling and stratified dataset functions accept any combination of the following Collection 3 layer names (`LAYER_MAPPING` in `ECOv003_CMR/point_sampling.py`):

| Product | Supported Layer Names | Notes / Units |
|---|---|---|
| `L2T_LSTE` | `ST_C`, `LST`, `LST_err`, `QC`, `emissivity`, `EmisWB`, `Emis1`–`Emis5`, `Emis1_err`–`Emis5_err`, `view_zenith`, `height` | `ST_C` is automatically converted from Kelvin (`LST - 273.15`); `emissivity` aliases `EmisWB` |
| `L2T_STARS` | `NDVI`, `NDVI-UQ`, `albedo`, `albedo-UQ` | Daily surface priors joined by `(tile, YYYYMMDD)` |
| `L3T_ETAUX` | `Ta_C`, `Ta`, `RH`, `SM`, `Rg`, `Rn`, `cloud`, `water` | `Ta_C` and `Ta` both read `Ta` (already in °C) |
| `L3T_JET` | `PTJPLSMinst`, `PTJPLSMdaily`, `PTJPLSMcanopy`, `PTJPLSMsoil`, `PTJPLSMinterception`, `ETdaily`, `ETuncertainty`, `ETinstUncertainty`, `STICJPLinst`, `STICJPLdaily`, `STICJPLcanopy`, `BESSJPLdaily`, `PMJPLdaily` | Evapotranspiration & ensemble partitioning |
| `L4T_ESI` | `ESI` | Evaporative Stress Index |
| `L4T_WUE` | `WUE` | Water Use Efficiency |

---

## Python API: Global & Regional Stratified Dataset Builder

`build_stratified_dataset()` scales stratified point-sample dataset generation to global multi-million-sample campaigns (~8.7s–9.6s per granule across 16 science/UQ layers; ~40 minutes amortized for 1,000,000 samples across 4,000 global granules on 16 workers) with:
- **CMR `granules.csv` Discovery & `POST` Wildcard Resolution:** Enumerates global `L3T_JET` catalogs across 5-day parallel windows (~97% smaller payloads than JSON/UMM-JSON, zero spatial-overlap duplicates) and resolves `.tif` and `.json` asset URLs lazily via `POST` `readable_granule_name[]` batches strictly for selected granules.
- **Sidecar `QAPercentCloudCover` Filtering & Rejection-Aware Backfill:** Evaluates `max_cloud_cover` concurrently against per-granule `.json` metadata sidecars (`ProductMetadata.QAPercentCloudCover`) and automatically backfills dropped tiles using empirical cloud-rejection multipliers.
- **A Priori Sampling Design & Dry-Run Mode (`plan_stratified_sampling()`, `estimate_cloud_cover_distribution()`, `dry_run=True`):** Forecasts eligible MGRS tile counts, latitudinal biome representation (`tropical`, `temperate`, `boreal`), effective $N_{	ext{cap}}$, selected granules $G$, per-granule pixel quota $K$, and estimated wall time before reading COGs.
- **Persistent Candidate Catalog Caching (`catalog_path`, `refresh_catalog`):** Stores SHA-256 cache-keyed `candidate_granules.parquet` catalogs for <0.1s offline restarts.
- **Bounded HTTP Stream Concurrency (`max_concurrent_streams`, `layer_workers`):** Caps simultaneous `/vsicurl/` connections via a shared `threading.Semaphore`.
- **Synchronous Batch Cookie Re-Warming (`batch_size`):** Refreshes Netscape URS cookies across synchronous granule batches and cleans up temporary cookie files on exit.
- **Adaptive Per-Granule Quota Refills:** Re-draws unvisited clear-sky pixels when multi-product `NaN` dropouts reduce accepted samples below `quota_k`.

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
    tiles=["11SLT", "11SPS", "52NHN", "53NMH", "20LLQ"],  # Omit (tiles=None) for all global land tiles
    target_total_samples=1000,
    min_granules_floor=2,
    dispersion_strategy="stratified_grid",
    max_workers=12,
    layer_workers=8,
    max_concurrent_streams=48,
    batch_size=250,
    refresh_catalog=False,
    dry_run=False,
    layers=UQ_LAYERS,
    export_csv=True,
    session=session,
)

print(summary["stratification_plan"])
print(summary["coverage_summary"])
```

---

## Python API: Granule ID, Filename & Tile Utilities

```python
from ECOv003_CMR import find_sentinel2_tile

# Returns single containing land MGRS tile (or None over open ocean)
print(find_sentinel2_tile(-118.2437, 34.0522))  # '11SLT'

# Return all overlapping land MGRS tiles along UTM zone boundaries
print(find_sentinel2_tile(-118.2437, 34.0522, return_all=True))

# Include ocean-only MGRS tiles if needed
print(find_sentinel2_tile(-140.0, 0.0, land_only=False))  # '07MFV'
```

---

## Examples

### Large-Scale Stratified Dataset Runners

- **`one_hundred_dataset.py`:** Multi-biome 100-observation pilot across 5 Sentinel-2 MGRS tiles (`11SLT`, `11SPS`, `52NHN`, `53NMH`, and humid-tropical `20LLQ`), writing partitioned Parquet/CSV outputs and `dataset_summary.json` into `./experimental_data/one_hundred_dataset`:
  ```bash
  # Pre-flight capacity & biome plan dry run (no COG reads)
  python one_hundred_dataset.py --dry-run

  # Full 100-observation extraction (~14-35s end-to-end)
  python one_hundred_dataset.py
  ```
- **`one_million_dataset.py`:** Global 1,000,000-observation stratified dataset generator across all 14,749 ECOSTRESS-covered land MGRS tiles (`2025-10-31` to `2026-10-31`), writing resumable checkpoints into `./experimental_data/one_million_dataset`:
  ```bash
  # Step 1: Pre-flight dry run (~2m) to cache candidate_granules.parquet and inspect capacity plan
  python one_million_dataset.py --dry-run

  # Step 2: Execute global 1M-sample extraction (resumable via completed_granules.txt)
  python one_million_dataset.py
  ```
- **`count_L3T_JET_scenes_by_cloud_percent.py`:** Global `L3T_JET` archive cloud-cover census using CMR `granules.csv` and concurrent `.json` sidecar `QAPercentCloudCover` inspection:
  ```bash
  python count_L3T_JET_scenes_by_cloud_percent.py --sample-size 2000
  ```

### Additional Scripts in `examples/`

- `examples/point_sampling_demo.py` — Single-coordinate `L2T_LSTE` + `L2T_STARS` sampling in Los Angeles
- `examples/geodataframe_sampling_demo.py` — Multi-site `GeoDataFrame` date-range sampling
- `examples/csv_to_geodataframe_demo.py` — Loading site coordinates from CSV and exporting enriched ECOSTRESS observations
- `examples/download_granules_demo.py` — Downloading `L2T_LSTE` and `L2T_STARS` granules locally
- `examples/stratified_sampling_demo.py` — Single-tile stratified sampling benchmark (`make test-sampler`)

---

## Development and Testing

```bash
pytest -v
pytest -m integration -v
make test-sampler
make build
```

---

## Version History

- **`v1.4.0` (Current Release):**
  - Hardened `download_file()` with explicit `(connect, read)` socket timeouts (`(15.0, 90.0)`), jittered exponential retry backoff on transient HTTP errors and mid-stream `TimeoutError` / `RequestException` / `OSError` stalls, and unconditional cleanup of partial `.download` files before each retry and on failure.
  - Updated `get_granule_from_listing()` and `download_ECOSTRESS_granule_files()` to select the latest build revision when CMR returns multiple builds of the same granule stem and raise `FileNotFoundError` when a CMR search returns zero granules.
  - Added `PackageNotFoundError` fallback version resolution in `ECOv003_CMR/version.py` and expanded live integration tests.
- **`v1.3.1`:**
  - Replaced `granules.umm_json` sweeps with NASA CMR's lightweight `granules.csv` endpoint across 5-day parallel temporal windows (~97% smaller payloads), enumerating all 348,477 global `L3T_JET` scenes in ~2 minutes.
  - Switched wildcard `readable_granule_name[]` resolution to HTTP `POST` requests to eliminate `414 Request-URI Too Large` errors on 150-pattern batches.
  - Removed null CMR `cloud_cover` query parameters and added concurrent `.json` sidecar `ProductMetadata.QAPercentCloudCover` filtering (`filter_granules_by_sidecar_cloud_cover()`, `estimate_cloud_cover_distribution()`) with empirical rejection-aware tile backfill.
  - Mounted a 64-socket `HTTPAdapter` connection pool in `setup_earthdata_session()` to eliminate `urllib3` pool exhaustion under high thread concurrency.
  - Added `plan_stratified_sampling()` and `dry_run=True` mode across `build_stratified_dataset()`, `one_hundred_dataset.py`, and `one_million_dataset.py` to forecast biome coverage, $N_{	ext{cap}}$, quota $K$, and wall time before reading COGs.
- **`v1.3.0`:**
  - Vectorized global land MGRS tile discovery via `sentinel_tiles.sentinel_polygons` (14,749 tiles in 0.62s) and updated `find_sentinel2_tile()` to use true polygon intersection with land filtering.
  - Added SHA-256 validated `candidate_granules.parquet` caching, bounded `/vsicurl/` HTTP stream concurrency (`max_concurrent_streams`), Netscape URS cookie export (`MozillaCookieJar`) with synchronous `batch_size` re-warming, adaptive per-granule quota refills, and $O(1)$-RAM `pyarrow.parquet` diagnostics in `summarize_point_samples()`.
  - Unified site point queries (`sample_points_over_date_range()`, `sample_points_from_geodataframe()`) onto granule-grouped `/vsicurl/` batch reads.
- **`v1.2.0`:**
  - Introduced the global/regional stratified point-sampling engine (`build_stratified_dataset()`, `select_stratified_granules()`, `sample_granule_coordinates()`), vectorized `/vsicurl/` granule sampling (`sample_points_from_granule()`), checkpointed Parquet exports, and expanded `LAYER_MAPPING` to cover `L3T_JET`, `L2T_STARS` UQ priors, `L4T_ESI`, and `L4T_WUE`.
- **`v1.0.0` – `v1.1.1`:**
  - Migrated ECOSTRESS CMR search, download, filename parsing, and COG point sampling from Collection 2 to Collection 3 (`.003`), codified LPCLOUD Concept IDs, added `ECOv003-search` / `ECOv003-download` CLIs, and added directory-backed `ECOv003-granules` compatibility handling (`granule_compatibility.py`).

---

## Known Issues

1. **CMR `CloudCover` Field Is Null on Collection 3 Granules:**
   - NASA CMR does not populate granule-level `CloudCover` metadata for ECOSTRESS Collection 3 products (`ECOSTRESS_CMR_search(..., max_cloud_cover=...)` cannot filter on CMR's `cloud_cover` field). Cloud filtering is instead performed via per-granule `.json` sidecars (`ProductMetadata.QAPercentCloudCover`) in `find_clear_sky_et_granules()` and `build_stratified_dataset()`.
2. **Local `ECOv003-granules` Compatibility Adapter (`granule_compatibility.py`):**
   - `ECOv003_CMR/granule_compatibility.py` remains bundled until upstream `ECOv003-granules` incorporates `L1CT_RAD` dispatch, `L3T_ETAUX` support, `L2T_STARS` product parsing, and directory-backed `.tif` file discovery.
