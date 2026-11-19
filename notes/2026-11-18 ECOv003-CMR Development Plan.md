# ECOv003-CMR Development Plan: From Collection 3 Migration (`v1.1.1`) to Global 1M-Sample Stratified Point-Query Pipeline (`v1.2.0`)

**Prepared:** 2026-11-18  
**Repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`  
**Previous Version:** `v1.1.1`  
**Current Version:** `v1.2.0` (Implemented & Benchmarked on `point_query`)  

---

## 1. Executive Summary

`ECOv003-CMR` provides programmatic access to NASA's Common Metadata Repository (CMR) and LP DAAC Earthdata Cloud (`LPCLOUD`) archives for ECOSTRESS Collection 3 (`.003`). Through `v1.1.1`, the package established complete Collection 3 product support, authenticated granule downloads, `ECOv003-granules` compatibility, CLI tooling (`ECOv003-search`, `ECOv003-download`), and site-centric Cloud-Optimized GeoTIFF (COG) point sampling.

In **`v1.2.0`**, `ECOv003-CMR` has been extended into a **general-purpose, granule-centric, spatially and seasonally stratified point-sampling engine** (`build_stratified_dataset()`), originally motivated by generating a **~1,000,000-sample non-tower ECOSTRESS training dataset** for uncertainty quantification (UQ) via transport maps, spatial downscaling of relative humidity (`RH`), and temporal upscaling of evapotranspiration (`ET`).

Through empirical profiling and iterative architectural optimization against live LP DAAC Earthdata Cloud granules, per-granule extraction latency across 16 science/UQ layers was reduced from **56.71s** to **13.00s** ($4.4\times$ speedup), bringing the amortized global 1,000,000-sample runtime down from **3.98 hours** to **56.77 minutes** on 16 workers with **100.0% layer completeness**.

---

## 2. How Baseline Version (`v1.1.1`) Was Achieved

The baseline architecture in `v1.1.1` was built across six foundational engineering milestones:

### 2.1 Collection 3 Product Catalog & LPCLOUD Concept ID Alignment
- Queried the seven active ECOSTRESS Collection 3 `.003` DOIs against the NASA CMR Collections API (`https://cmr.earthdata.nasa.gov/search/collections.json?doi=<DOI>`) and codified the verified LPCLOUD Concept IDs in `ECOv003_CMR/constants.py` (`CONCEPT_IDS`):
  - `L1CT_RAD` (`C4142244484-LPCLOUD`) — Calibrated at-sensor radiance
  - `L2T_LSTE` (`C3998139651-LPCLOUD`) — Land surface temperature & emissivity
  - `L2T_STARS` (`C3998139658-LPCLOUD`) — Surface reflectance, `NDVI`, and `albedo` priors
  - `L3T_ETAUX` (`C4057520953-LPCLOUD`) — Tiled auxiliary meteorology, soil moisture, and radiation (consolidating retired Collection 2 `L3T_MET`, `L3T_SM`, and `L3T_SEB`)
  - `L3T_JET` (`C4057232489-LPCLOUD`) — JPL evapotranspiration product
  - `L4T_ESI` (`C4057232495-LPCLOUD`) — Evaporative Stress Index
  - `L4T_WUE` (`C4057232498-LPCLOUD`) — Water Use Efficiency
- Added strict product validation in `ECOSTRESS_CMR_search()` and `download_ECOSTRESS()` so discontinued Collection 2 product codes raise descriptive `ValueError` exceptions immediately.

### 2.2 Paginated CMR Granule Search & URL Interpretation
- Implemented `ECOSTRESS_CMR_search_links()` (`ECOv003_CMR/ECOSTRESS_CMR_search_links.py`) with `page_size=2000` and iterative `CMR-Search-After` pagination with duplicate-token loop protection.
- Implemented `GranuleID` (`granule_ID.py`), `granule_ID_from_filename.py`, `product_name_from_filename.py`, `variable_from_filename.py`, and `interpret_ECOSTRESS_URLs.py` to parse both 8-segment standard Collection 3 filenames (`ECOv003_<PRODUCT>_<ORBIT>_<SCENE>_<TILE>_<YYYYMMDDTHHMMSS>_<BUILD>`) and 6-segment daily `L2T_STARS` filenames (`ECOv003_L2T_STARS_<TILE>_<YYYYMMDD>_<BUILD>`), including multi-token variable names (`view_zenith`, `Emis4_err`, `NDVI-UQ`) and `.jpeg.aux.xml` sidecars.

### 2.3 Authenticated Earthdata Cloud Downloads & CLI Tooling
- Built `setup_earthdata_session()` (`ECOv003_CMR/authentication.py`) resolving credentials in priority order: explicit arguments $\rightarrow$ `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` environment variables $\rightarrow$ `~/.netrc`.
- Updated `download_file()` (`ECOv003_CMR/download_file.py`) to propagate authenticated `requests.Session` objects across URS redirects, write atomically via `.download` temporary files, remove zero-byte files, and display `tqdm.auto.tqdm` progress bars.
- Updated `download_ECOSTRESS()` (`ECOv003_CMR/download_ECOSTRESS.py`) to extract true per-granule acquisition dates via `_acquisition_date_from_granule_id()` and standardized `ECOv003-search` / `ECOv003-download` CLI logging and exit codes.

### 2.4 `ECOv003-granules` Collection 3 Compatibility Adapter
- Created `ECOv003_CMR/granule_compatibility.py` (`_Collection3GranuleMixin` and `open_ECOSTRESS_granule()`) to support directory-backed downloads (in addition to `.zip` archives), `L1CT_RAD` dispatch, `L3T_ETAUX` handling, and `L2T_STARS` metadata parsing, validated by `download_ECOSTRESS_granule()`.

### 2.5 In-Memory COG Point Sampling & Temporal Joining
- Implemented `sample_point_from_url()`, `sample_points_over_date_range()`, and `sample_points_from_geodataframe()` (`ECOv003_CMR/point_sampling.py`) supporting automatic CRS reprojection to `EPSG:4326`, Kelvin-to-Celsius conversion (`ST_C = LST - 273.15`), and parallel/sequential execution parity.

### 2.6 Offline CI Test Suite
- Established offline unit tests (`tests/test_cmr_search.py`, `tests/test_download_ECOSTRESS_granule.py`, `tests/test_granule_compatibility.py`, `tests/test_point_sampling.py`, `tests/test_import_dependencies.py`) running across Python 3.11–3.14 in `.github/workflows/ci.yml`.

---

## 3. Architectural Evolution: `v1.1.1` $\rightarrow$ `v1.2.0`

| Pipeline Stage | `v1.1.1` Behavior | `v1.2.0` Implemented Architecture |
| :--- | :--- | :--- |
| **API Generalization** | Site-centric point queries only. | General-purpose stratified sampling engine (`build_stratified_dataset()` in `stratified_dataset_builder.py`) with `DEFAULT_STRATIFIED_LAYERS` and optional `UQ_LAYERS` preset. |
| **Spatial Discovery** | Required user-supplied `tile` IDs or point coordinates. | `list_ecostress_land_tiles()` (`tile_catalog.py`) enumerates all global land-intersecting Sentinel-2 MGRS tiles within ECOSTRESS orbital coverage ($\pm 54^\circ$ latitude) using cached Natural Earth landmass polygons. |
| **CMR Query Footprint** | Queried a single point at tile centroid (`lon,lat,lon,lat`), missing partial-tile diagonal swaths. | Queries full tile WGS84 bounding boxes (`geometry.bounds`, `use_tile_bounds=True`) with exact `_<TILE>_` granule filtering, HTTP `429`/`503` exponential backoff, and `cloud_cover` metadata extraction. |
| **Clear-Sky Filtering** | Returned all matching CMR assets regardless of cloud cover or product completeness. | `find_clear_sky_et_granules()` verifies daytime clear-sky `L3T_JET` overpasses with matching `(orbit, scene, tile, timestamp)` `L2T_LSTE` and `L3T_ETAUX` granules plus same-date `(tile, YYYYMMDD)` `L2T_STARS` granules, caching all variable URLs in memory. |
| **Stratified Selection** | Sampled fixed user coordinates across every overpass in a date window. | `select_stratified_granules()` caps per-tile counts at $N_{\text{cap}} = \min_{t \in \text{Eligible}} N_t$ (subject to `min_granules_floor`), balances calendar quarters, and computes per-granule quota $K = \lceil N_{\text{target}} / G \rceil$. |
| **Intra-Granule Sampling** | No dynamic intra-scene coordinate generation or land-cover balancing. | `extract_valid_swath_mask()` + `sample_granule_coordinates()` independently randomize $K$ valid clear-sky land pixels per scene ("rolling the dice") with `"stratified_grid"` or `"uniform"` dispersion and optional cropland weighting. |
| **Cross-Product Join** | Indexed `L3T_*` granules by `YYYYMMDD`, overwriting multiple overpasses on the same day. | Joins instantaneous products (`L2T_LSTE`, `L3T_ETAUX`, `L3T_JET`, `L4T_*`) by `(orbit, scene, tile, timestamp)` and daily `L2T_STARS` by `(tile, YYYYMMDD)`. |
| **COG Read Architecture** | Downloaded full compressed `.tif` into `MemoryFile` per `(point, granule, variable)`. | `sample_points_from_granule()` opens all requested variable COGs **concurrently** (`ThreadPoolExecutor`) over authenticated `/vsicurl/` HTTP byte-range requests and extracts all $K$ coordinates via vectorized `src.sample(proj_coords, masked=True)`. |
| **Variable Coverage** | 16 layers across `L2T_LSTE`, `L2T_STARS`, and `L3T_ETAUX`. | 46 mapped layers in `LAYER_MAPPING`, adding verified `L3T_JET` ET & partitioning (`PTJPLSMinst`, `ETdaily`, `ETuncertainty`, `PTJPLSMcanopy`, `STICJPLdaily`, `BESSJPLdaily`, `PMJPLdaily`), `L2T_STARS` UQ (`NDVI-UQ`, `albedo-UQ`), `L2T_LSTE` spectral emissivities/angles, and `L4T_ESI`/`L4T_WUE`. |
| **Output & Checkpointing** | Returned an in-memory `pandas.DataFrame` only after completion. | Streams partitioned Parquet/CSV batches (`dataset_part_XXXX.parquet`) to disk with a `completed_granules.txt` manifest, `summarize_point_samples()` diagnostics, and automated 1M runtime extrapolation. |

---

## 4. Empirical Engineering & Optimization Process (`v1.2.0`)

During development and live testing (`make test-sampler` on Sentinel-2 tile `11SLT`, June 1–7, 2026 across 16 layers), the pipeline underwent three empirical engineering iterations:

### Iteration 1: General-Purpose API Refactoring & Instrumentation
- **Observation:** While the initial scientific driver was generating a 1,000,000-sample UQ dataset, the underlying spatial/seasonal stratification and `/vsicurl/` batch sampling mechanics are domain-agnostic.
- **Action:** Renamed `uq_dataset_builder.py` $\rightarrow$ `stratified_dataset_builder.py` and `build_uq_training_dataset()` $\rightarrow$ `build_stratified_dataset()`, preserving `UQ_LAYERS` as a convenience layer list. Added `time.perf_counter()` instrumentation per stage and a `make test-sampler` target.

### Iteration 2: Baseline `/vsicurl/` Benchmark (Sequential Layer Reads)
- **Measurement (`11SLT`, 2 granules, $K=13$, 16 layers, `max_workers=2`):**
  - Total wall time: **65.78s** (`2.42s` CMR search, `4.01s` cookie pre-warmup, `59.26s` COG extraction, `0.09s` Parquet aggregation).
  - Mean per-granule latency: **56.71s / granule**.
  - Amortized global 1,000,000-sample estimate ($4{,}000$ granules, $K=250$, 16 workers): **3.98 hours** (naive linear scaling at $K=13$: `26.38 days`).
- **Bottleneck Diagnosis:**
  1. Each granule worker re-queried `ECOSTRESS_CMR_search` (`~2s` per granule) even though Stage 3 (`find_clear_sky_et_granules`) had already retrieved all `.tif` URLs.
  2. Each granule worker opened `L3T_ETAUX` `cloud` and `water` COGs separately (`~6s`) before opening the 16 science layers.
  3. Inside `sample_points_from_granule()`, all 16 remote GeoTIFF URLs were opened **sequentially** (`16 × ~3s ≈ 48s` of serial HTTP redirect/header latency).

### Iteration 3: Three Targeted Throughput Optimizations
- **Optimization 1 — Pre-Fetched Stage 3 URL Caching:** Updated `find_clear_sky_et_granules()` to merge and attach `variable_urls` directly onto each verified granule metadata row, eliminating all per-granule CMR API queries during extraction.
- **Optimization 2 — Single-Pass Pre-Masked Swath Discovery:** Updated `extract_valid_swath_mask()` to accept `primary_data_url` (using `L3T_JET` `PTJPLSMinst`, which is already cloud- and water-masked), eliminating 2 separate mask COG opens per granule.
- **Optimization 3 — Concurrent Intra-Granule COG Layer Reads:** Refactored `sample_points_from_granule()` to open and sample all 16 requested GeoTIFF layers concurrently via `ThreadPoolExecutor(max_workers=8)`.

### Empirical Benchmark Comparison (`11SLT`, 2 Granules, 16 Layers)

| Benchmark Metric | Baseline `v1.2.0` (Sequential Layers) | Optimized `v1.2.0` (Concurrent + Cached URLs) | Improvement |
| :--- | :--- | :--- | :--- |
| **Total Wall Time (2 granules)** | `65.78s` | **`19.77s`** | **$3.3\times$ faster** |
| **CMR Granule Search** | `2.42s` (plus `~2s`/granule re-queries) | **`2.61s`** (one-time; `0.00s` per granule) | **Eliminated re-queries** |
| **COG Extraction Wall Time** | `59.26s` | **`13.27s`** | **$4.5\times$ faster** |
| **Mean Granule Latency** | `56.71s / granule` | **`13.00s / granule`** | **$4.4\times$ faster** |
| **Small-Batch Throughput ($K=13$)** | `0.44 samples/s` | **`1.96 samples/s`** | **$4.5\times$ faster** |
| **Layer Completeness (16 layers)** | `100.0%` (`26/26` valid) | **`100.0%`** (`26/26` valid) | **Zero data loss** |
| **1M Global Estimate (Amortized)** | `3.98 hours` | **`56.77 minutes`** | **$4.2\times$ faster** |

---

## 5. Observed & Theoretical Capabilities of `v1.2.0`

### 5.1 Observed Capabilities (Verified via `make test` & `make test-sampler`)
- **Automated Test Suite:** 52 offline unit tests passing across Python 3.11–3.14 (`make test` in `3.25s`), plus gated live NASA CMR integration tests (`pytest -m integration`).
- **Authenticated `/vsicurl/` Byte-Range Extraction:** Process-wide `rasterio.Env` with URS cookie pre-warming avoids S3 presigned redirect header conflicts and reads arbitrary subsets of COGs directly from `LPCLOUD`.
- **Per-Granule Latency:** **~13.0s per granule** across 16 variables spanning 4 distinct ECOSTRESS products (`L2T_LSTE`, `L2T_STARS`, `L3T_ETAUX`, `L3T_JET`), including full-resolution ($3660 \times 3660$) swath mask evaluation (~730k–1.0M valid land pixels per scene) and `stratified_grid` coordinate randomization.
- **Fault-Tolerant Checkpointing:** Incremental Parquet/CSV partition writes (`dataset_part_XXXX.parquet`) and `completed_granules.txt` manifest tracking verified across multi-worker runs.

### 5.2 Theoretical Scaling & Production Envelope (1,000,000-Sample Campaign)
Because GDAL `/vsicurl/` fetches compressed $512 \times 512$ internal GeoTIFF tiles via HTTP byte-range requests, opening a remote COG and sampling $K=250$ points incurs virtually the same network latency (`~13s` per granule) as sampling $K=13$ points:

| Scale Regime | Granules ($G$) | Quota / Granule ($K$) | Concurrency | Theoretical Throughput | Estimated Wall Time |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Single-Tile Smoke Test** (`11SLT`, 1 wk) | `2` | `13` | `2` workers | `~1.96 samples/s` | **`~20 seconds`** *(observed)* |
| **Regional Campaign** (e.g., CONUS / Western US, ~150 tiles) | `~1,200` | `834` | `16` workers | `~1,025 samples/s` | **`~16–20 minutes`** |
| **Global Mission Campaign** ($\pm 54^\circ$ land tiles, $N_{\text{cap}} \approx 4\text{–}8$) | `~4,000` | `250` | `16` workers | `~308 samples/s` | **`~57 minutes`** |
| **Global High-Concurrency Cloud Run** (AWS `us-west-2` EC2/batch) | `~4,000` | `250` | `32` workers | `~615+ samples/s` | **`~20–30 minutes`** |

*(Note: Running inside AWS `us-west-2`—the same region hosting NASA LP DAAC `LPCLOUD` S3 buckets—reduces per-COG HTTP round-trip latency from ~120ms to <10ms, further accelerating `/vsicurl/` extraction by $2\times\text{–}3\times$.)*

---

## 6. Completed `v1.2.0` Checklist & `v1.3.0` Next Steps

### Completed in `v1.2.0`
- [x] **Global MGRS Tile Catalog (`ECOv003_CMR/tile_catalog.py`):** Implemented `list_ecostress_land_tiles(min_lat=-54.0, max_lat=54.0)` with cached Natural Earth landmass geometry.
- [x] **Full-Bounds CMR Queries & Backoff (`ECOSTRESS_CMR_search_links.py`, `ECOSTRESS_CMR_search.py`, `interpret_ECOSTRESS_URLs.py`):** Enabled WGS84 tile bounding-box queries (`use_tile_bounds=True`), exact `_<TILE>_` filtering, HTTP `429`/`503` backoff, `cloud_cover` metadata propagation, and `fetch_granule_metadata()`.
- [x] **Stratified Granule & Pixel Selection (`ECOv003_CMR/stratified_sampling.py`):** Implemented `find_clear_sky_et_granules()` (with URL caching), `select_stratified_granules()`, `compute_per_granule_quota()`, `extract_valid_swath_mask()` (with `primary_data_url`), and `sample_granule_coordinates()` (`"stratified_grid"`, `"uniform"`, and cropland weighting).
- [x] **Concurrent `/vsicurl/` Batch Sampler & Expanded Layers (`ECOv003_CMR/point_sampling.py`):** Added 46 mapped layers across all Collection 3 products, fixed same-day multi-overpass joining, implemented concurrent `sample_points_from_granule()`, and added `summarize_point_samples()`.
- [x] **General Stratified Dataset Builder & Benchmarks (`ECOv003_CMR/stratified_dataset_builder.py`):** Implemented `build_stratified_dataset()` with Parquet/CSV checkpointing, `completed_granules.txt` manifest resuming, stage timings, and 1M runtime extrapolation.
- [x] **Packaging, Tests & Documentation:** Bumped `pyproject.toml` to `1.2.0` with `pyarrow`, added `tests/test_stratified_sampling.py` and `tests/test_live_integration.py`, added `make test-sampler`, and updated `README.md` and `examples/stratified_sampling_demo.py`.

### Planned Enhancements for `v1.3.0`
- [ ] **Regional Bounding-Box CMR Batching:** Group global land tiles into ~60 regional spatial chunks during `find_clear_sky_et_granules()` so global 5,000-tile CMR discovery completes in ~2 minutes rather than issuing 5,000 individual tile requests.
- [ ] **Built-In Land-Cover Mask Provider:** Add an optional on-demand ESA WorldCover / MODIS MCD12Q1 cropland mask loader so `cropland_fraction_target` can be passed directly to `build_stratified_dataset()`.
- [ ] **Upstream `ECOv003-granules` Consolidation:** Migrate `_Collection3GranuleMixin` fixes into `ECOv003-granules` upstream and deprecate `granule_compatibility.py`.