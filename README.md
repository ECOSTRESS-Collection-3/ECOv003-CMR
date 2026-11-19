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

# Context manager exports Netscape URS cookies for /vsicurl/ and removes temp files on exit
with configure_gdal_earthdata_env(session=session):
    ...
```

All search, download, and point-sampling functions accept `session=...` and will automatically call `setup_earthdata_session()` if none is provided.

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

`sample_points_from_granule()`, `sample_points_over_date_range()`, and `sample_points_from_geodataframe()` group points by granule, join instantaneous products by `(orbit, scene, tile, timestamp)` and daily `L2T_STARS` priors by `(tile, YYYYMMDD)`, and extract pixels over authenticated `/vsicurl/` HTTP byte-range requests.

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

---

## Python API: Global & Regional Stratified Dataset Builder

`build_stratified_dataset()` scales stratified point-sample dataset generation to global multi-million-sample campaigns with regional bounding-box CMR discovery, persistent Parquet catalog caching (`catalog_path`, `refresh_catalog`), bounded HTTP stream concurrency (`max_concurrent_streams`, `layer_workers`), synchronous URS cookie re-warming (`batch_size`), adaptive per-granule quota refills, and $O(1)$-RAM `pyarrow.parquet` coverage diagnostics:

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
    layer_workers=8,
    max_concurrent_streams=32,
    batch_size=250,
    refresh_catalog=False,
    layers=UQ_LAYERS,
    export_csv=True,
    session=session,
)

print(summary["coverage_summary"])
```

---

## Python API: Granule ID, Filename & Tile Utilities

```python
from ECOv003_CMR import find_sentinel2_tile

# Returns single containing MGRS tile (or None over open ocean)
print(find_sentinel2_tile(-118.2437, 34.0522))  # '11SLT'

# Return all overlapping MGRS tiles along UTM zone boundaries
print(find_sentinel2_tile(-118.2437, 34.0522, return_all=True))
```

---

## Development and Testing

```bash
pytest -v
pytest -m integration -v
make build
```
