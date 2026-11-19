# ECOv003-CMR Development Plan: From Collection 3 Migration (`v1.1.1`) to Global 1M-Sample Stratified Point-Query Pipeline (`v1.2.0`, `v1.3.0` & `v1.4.0`)

**Prepared:** 2026-11-18  
**Repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`  
**Previous Versions:** `v1.1.1` (Collection 3 Baseline), `v1.2.0` (Concurrent `/vsicurl/` Stratified Sampler)  
**Current Version:** `v1.3.0` (Implemented & Benchmarked: Large-Volume Scaling, Correctness Hardening & API Refinements)  
**Future Target Version:** `v1.4.0` (On-Demand Land-Cover & Cropland Stratification)

---

## 1. Executive Summary

`ECOv003-CMR` provides programmatic access to NASA's Common Metadata Repository (CMR) and LP DAAC Earthdata Cloud (`LPCLOUD`) archives for ECOSTRESS Collection 3 (`.003`). Across `v1.1.1` through `v1.3.0`, the package evolved from a site-centric download and point-query library into a production-hardened, globally scalable, spatially and seasonally stratified point-sampling engine (`build_stratified_dataset()`), originally motivated by generating a **~1,000,000-sample non-tower ECOSTRESS training dataset** for uncertainty quantification (UQ) via transport maps, spatial downscaling of relative humidity (`RH`), and temporal upscaling of evapotranspiration (`ET`).

Through three major releases and live benchmarking against LP DAAC Earthdata Cloud granules (`11SLT`, June 1–7, 2026 across 16 science and UQ layers), **mean per-granule extraction latency was reduced from 56.71s (`v1.2.0` baseline) to 13.00s (`v1.2.0` concurrent) and down to 9.76s (`v1.3.0`)—an overall $5.8\times$ per-granule speedup**—reducing the amortized global 1,000,000-sample runtime estimate from **3.98 hours** to **45.44 minutes** on 16 workers with **100.0% layer completeness** (`57 passed` offline unit tests + live `make test-sampler` verification).

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

## 3. Architectural Evolution: `v1.1.1` $\rightarrow$ `v1.2.0` $\rightarrow$ `v1.3.0`

| Pipeline Stage | `v1.1.1` Baseline | `v1.2.0` Stratified Sampler | `v1.3.0` Production Hardening & Scale |
| :--- | :--- | :--- | :--- |
| **Spatial Discovery** | Required user-supplied `tile` IDs or point coordinates (`sentinel_tiles.nearest()`). | `list_ecostress_land_tiles()` enumerates global land tiles within $\pm 54^\circ$ latitude. | `find_sentinel2_tile()` uses true polygon intersection (`sentinel_tiles.tiles(point)`) with `sentinel_tiles.land(t)` filtering (returning `None` over open ocean and supporting `return_all=True`). |
| **CMR Query Footprint & Scale** | Queried single tile centroid (`lon,lat,lon,lat`), missing diagonal swaths. | Queried full tile bounds (`use_tile_bounds=True`), but issued `4 × N_tiles` per-tile requests globally. | Clusters `len(tiles) > 25` into $30^\circ \times 30^\circ$ WGS84 regional boxes (`sentinel_tiles.footprint(tile).bounds`) and 92-day temporal chunks (`>100×` fewer CMR calls); strips URS Basic Auth when querying `cmr.earthdata.nasa.gov`. |
| **Catalog Persistence** | Re-queried CMR on every run. | In-memory URL caching within a single run only. | Persists `candidate_granules.parquet` with SHA-256 cache-key validation (`catalog_path`, `refresh_catalog`) for `<1s` offline restarts. |
| **Intra-Granule Sampling & Quotas** | Fixed user coordinates across overpasses. | Dynamic `"stratified_grid"` / `"uniform"` coordinate randomization with fixed `1.25×` oversample. | Bounded adaptive quota refill (`max_refill_attempts = 2`) with coordinate deduplication when multi-product `NaN` dropouts cause shortfalls, plus `"stratified_grid"` dispersion parity when `cropland_mask` is supplied. |
| **COG Read & Concurrency** | Downloaded full `.tif` into `MemoryFile` per `(point, granule, variable)`. | Concurrent `/vsicurl/` reads in `sample_points_from_granule()` (unbounded nested pools); site queries still used full-file `MemoryFile` downloads. | Shared `threading.Semaphore(max_concurrent_streams)` bounding active HTTP streams, deterministic GDAL HTTP retries (`429,502,503,504`), and unified granule-grouped `/vsicurl/` sampling across `sample_points_over_date_range()` and `sample_points_from_geodataframe()`. |
| **Auth & Cookie Lifecycle** | One-time `mkstemp` cookie file without Netscape serialization or cleanup. | Pre-warmed `requests.Session` once at start of run. | `@contextmanager` `configure_gdal_earthdata_env()` exports `session.cookies` via `http.cookiejar.MozillaCookieJar`, refreshes cookies across synchronous `batch_size` windows, and removes temp files on exit. |
| **Diagnostics & Memory** | In-memory `DataFrame` only. | Partitioned Parquet writes, but `pd.concat` loaded all rows into RAM at Stage 6. | Constant-RAM ($O(1)$) streaming `pyarrow.parquet.ParquetFile` column metadata/batch diagnostics in `summarize_point_samples()`. |

---

## 4. Implemented `v1.3.0` Workstreams

1. **Regional Bounding-Box & Temporal-Chunked CMR Discovery (`ECOv003_CMR/stratified_sampling.py`, `ECOSTRESS_CMR_search.py`, `ECOSTRESS_CMR_search_links.py`):**
   - Automatically clusters tile sets exceeding `regional_batch_threshold=25` into $30^\circ \times 30^\circ$ WGS84 regional bounding boxes and 92-day temporal chunks (`page_size=2000`), filtering entries locally against `allowed_tiles`.
   - Threads `session` for HTTP keep-alive connection pooling while ensuring URS Basic Auth headers are never sent to public `cmr.earthdata.nasa.gov` search endpoints.
   - Logs and rejects unparseable asset URLs during tile filtering instead of silently passing them.
2. **Persistent Candidate Granule Catalog Caching (`ECOv003_CMR/stratified_dataset_builder.py`):**
   - Saves verified multi-product candidate catalogs to `candidate_granules.parquet` with JSON-serialized `variable_urls` and Parquet schema metadata encoding `(start_date, end_date, max_cloud_cover, tile_count, tiles_sha256, queried_products)`.
   - Reloads matching catalogs offline when `refresh_catalog=False`, and automatically re-queries if requested layers require uncached products.
3. **Bounded HTTP Stream Concurrency & Deterministic Retry Backoff (`ECOv003_CMR/stratified_dataset_builder.py`, `point_sampling.py`, `authentication.py`):**
   - Decouples outer `max_workers` from inner `layer_workers` and enforces a global `threading.Semaphore(max_concurrent_streams)` (default `32`) across all `/vsicurl/` reads.
   - Configures deterministic GDAL HTTP retry options (`GDAL_HTTP_MAX_RETRY=3`, `GDAL_HTTP_RETRY_DELAY=2`, `GDAL_HTTP_RETRY_CODES=429,502,503,504`) alongside jittered exponential backoff on `MemoryFile` fallbacks.
4. **Netscape URS Cookie Export, Synchronous Batch Re-Warming & Cleanup (`ECOv003_CMR/authentication.py`, `stratified_dataset_builder.py`):**
   - Converts `configure_gdal_earthdata_env()` into a `@contextmanager` that serializes pre-warmed `session.cookies` into Netscape format (`http.cookiejar.MozillaCookieJar`) for GDAL `libcurl` and deletes temporary `earthdata_gdal_*.cookies` files in `finally`.
   - Partitions pending granules into synchronous `batch_size` windows (default `250`) to refresh cookies cleanly between batches.
5. **Constant-RAM Streaming Parquet Diagnostics (`ECOv003_CMR/point_sampling.py`, `stratified_dataset_builder.py`):**
   - Extends `summarize_point_samples()` to accept Parquet file paths and compute per-layer valid/missing counts directly from `pyarrow.parquet.ParquetFile` row-group statistics (falling back to streaming `iter_batches()` when stats are absent).
6. **Adaptive Per-Granule Quota Refill & Cropland Dispersion Parity (`ECOv003_CMR/stratified_dataset_builder.py`, `stratified_sampling.py`):**
   - Adds a bounded adaptive refill loop (`max_refill_attempts = 2`) in `_process_granule()` with coordinate deduplication (`seen_coords`) so multi-product `NaN` dropouts do not cause silent sample shortfalls.
   - Routes user-supplied `cropland_mask` sampling in `sample_granule_coordinates()` through `_draw_dispersed_indices()` so `"stratified_grid"` dispersion applies equally to agricultural and natural land pools.
7. **Granule-Grouped `/vsicurl/` Site Queries & True MGRS Containment (`ECOv003_CMR/point_sampling.py`):**
   - Refactors `sample_points_over_date_range()` and `sample_points_from_geodataframe()` onto `_build_granule_sampling_batches()` and `sample_points_from_granule()` (`/vsicurl/`), joining daily `L2T_STARS` priors by `(tile, YYYYMMDD)` and eliminating redundant per-point full-file `MemoryFile` downloads.
   - Updates `find_sentinel2_tile()` to use `sentinel_tiles.tiles(Point(lon, lat))` with `sentinel_tiles.land(t)` filtering (`land_only=True`, `return_all=False`).
8. **Code Hygiene & Deprecation Warnings (`granule_ID.py`, `download_ECOSTRESS_granule*.py`, `version.py`):**
   - Consolidates duplicate `product_name_from_granule_ID()` into `product_name_from_filename()`.
   - Emits `DeprecationWarning` when the legacy misspelled `aquisition_date` argument is passed.
   - Wraps `importlib.metadata.version("ECOv003-CMR")` in `version.py` with a `PackageNotFoundError` fallback reading `pyproject.toml`.

---

## 5. Technical Challenges Encountered & How They Were Overcome

During live integration and unit testing of `v1.3.0` against `sentinel-tiles` (`1.2.0`), NASA CMR (`cmr.earthdata.nasa.gov`), and LP DAAC Earthdata Cloud (`LPCLOUD`), four concrete technical challenges surfaced and were resolved:

1. **NASA CMR Rejecting Earthdata URS Basic Auth Headers (`401 Unauthorized`):**
   - *Challenge:* Threading the authenticated `requests.Session` (configured with `session.auth = (username, password)` for `urs.earthdata.nasa.gov`) into `ECOSTRESS_CMR_search_links()` caused `cmr.earthdata.nasa.gov/search/granules.json` to return `401 Client Error: Unauthorized`, because CMR search endpoints reject URS Basic Auth credentials.
   - *Resolution:* Updated `_request_with_backoff()` in `ECOSTRESS_CMR_search_links.py` to bypass `session` when `session.auth` is set (`requests.get(...)`), reserving URS Basic Auth strictly for Earthdata Login / LP DAAC data endpoints.
2. **`sentinel_tiles.grid(tile)` Returning `RasterGrid` Instead of a Shapely Polygon:**
   - *Challenge:* `sentinel_tiles.grid(tile)` returns a `rasters.RasterGrid` object (which lacks `.bounds` and `.intersects()`), causing regional bounding-box clustering (`_cluster_tiles_to_regional_boxes`) to raise `AttributeError` and tile-bounds CMR queries to fall back to single centroid points (`lon,lat,lon,lat`).
   - *Resolution:* Switched bounding-box resolution in `ECOSTRESS_CMR_search_links.py` and `stratified_sampling.py` to `sentinel_tiles.footprint(tile).bounds` (which returns the exact WGS84 tile polygon bounds), restoring full-tile swath discovery.
3. **Open-Ocean MGRS Tile False Positives in `find_sentinel2_tile()`:**
   - *Challenge:* `sentinel_tiles.tiles(Point(-140.0, 0.0))` returned `'07MFV'` because the global MGRS polygon index tiles both land and open ocean.
   - *Resolution:* Added `land_only: bool = True` to `find_sentinel2_tile()` in `point_sampling.py`, filtering `sentinel_tiles.tiles(point)` through `sentinel_tiles.land(t)` so open-ocean coordinates cleanly return `None` (or `[]` when `return_all=True`).
4. **Netscape Cookie Serialization for GDAL `/vsicurl/`:**
   - *Challenge:* Pre-warming an Earthdata URL in `requests.Session` stores session tokens in an in-memory `RequestsCookieJar`, whereas GDAL's underlying `libcurl` requires a Netscape-formatted cookie file on disk (`GDAL_HTTP_COOKIEFILE`) to avoid per-thread OAuth redirect loops.
   - *Resolution:* Implemented `_export_session_cookies_to_netscape()` using `http.cookiejar.MozillaCookieJar(cookie_file).save(...)` inside `configure_gdal_earthdata_env()` and removed the temporary cookie file in a `finally` block upon context exit.

---

## 6. Quantified Performance Progression (`v1.2.0` $\rightarrow$ `v1.3.0`)

Live benchmarks were executed via `make test-sampler` (`examples/stratified_sampling_demo.py`) on Sentinel-2 tile `11SLT` (June 1–7, 2026; 2 clear-sky overpasses, 16 science & UQ layers across `L2T_LSTE`, `L2T_STARS`, `L3T_ETAUX`, and `L3T_JET`, `max_workers=2`, `max_concurrent_streams=32`):

| Benchmark Metric | `v1.2.0` Baseline (Sequential Layers) | `v1.2.0` Optimized (Concurrent Layers) | `v1.3.0` Production (Netscape Cookies + Semaphore + Streaming Parquet) | Total Improvement (`v1.2.0` Base $\rightarrow$ `v1.3.0`) |
| :--- | :--- | :--- | :--- | :--- |
| **Total Wall Time (2 granules)** | `65.78s` | `19.77s` | **`18.97s`** | **$3.47\times$ faster** (`-71.2%`) |
| **COG Extraction Wall Time** | `59.26s` | `13.27s` | **`11.00s`** | **$5.39\times$ faster** (`-81.4%`) |
| **Cookie Pre-Warmup Time** | `4.01s` | `3.89s` | **`3.19s`** (Netscape jar export) | **`-20.4%`** |
| **Parquet Aggregation Time** | `0.09s` (`pd.concat`) | `0.09s` (`pd.concat`) | **`0.00s`** (`pyarrow` metadata) | **$O(1)$ RAM, `<1ms`** |
| **Mean Per-Granule Latency** | `56.71s / granule` | `13.00s / granule` | **`9.76s / granule`** | **$5.81\times$ faster** (`-82.8%`) |
| **Small-Batch Throughput ($K=13$)** | `0.44 samples/s` | `1.96 samples/s` | **`2.36 samples/s`** | **$5.36\times$ faster** (`+436%`) |
| **Naive Linear 1M Estimate ($K=13$)** | `26.38 days` | `5.90 days` | **`4.90 days`** | **$5.38\times$ faster** |
| **Amortized Global 1M Estimate ($4{,}000$ granules, $K=250$, 16 workers)** | `3.98 hours` | `56.77 minutes` | **`45.44 minutes`** | **$5.26\times$ faster** (`-81.0%`) |
| **Layer Completeness (16 layers)** | `100.0%` (`26/26`) | `100.0%` (`26/26`) | **`100.0%` (`26/26`)** | **Zero data loss** |
| **Offline Unit Test Suite** | `52 passed` | `52 passed` | **`57 passed`** (`2.77s`) | **`+5` new regression tests** |

---

## 7. Completed `v1.3.0` Checklist

- [x] **Regional Bounding-Box & Temporal-Chunked CMR Discovery (`ECOv003_CMR/stratified_sampling.py`, `ECOSTRESS_CMR_search_links.py`):** Clustered `len(tiles) > 25` into $30^\circ \times 30^\circ$ WGS84 boxes using `sentinel_tiles.footprint(tile).bounds` and 92-day temporal chunks; bypassed Basic Auth on CMR search endpoints.
- [x] **Persistent Candidate Catalog Caching (`ECOv003_CMR/stratified_dataset_builder.py`):** Added SHA-256 cache-keyed `candidate_granules.parquet` persistence with `catalog_path` and `refresh_catalog`.
- [x] **Bounded Stream Concurrency & Deterministic Retries (`stratified_dataset_builder.py`, `point_sampling.py`, `authentication.py`):** Added `max_concurrent_streams` semaphore, `layer_workers`, GDAL HTTP retry options, and jittered fallback backoff.
- [x] **Netscape Cookie Export & Synchronous Batch Re-Warming (`authentication.py`, `stratified_dataset_builder.py`):** Converted `configure_gdal_earthdata_env()` to a `@contextmanager` with `MozillaCookieJar` export, `batch_size` windows, and temp cookie cleanup.
- [x] **Constant-RAM Streaming Parquet Diagnostics (`point_sampling.py`, `stratified_dataset_builder.py`):** Implemented $O(1)$-RAM `pyarrow.parquet` column metadata/batch summarization.
- [x] **Adaptive Quota Refill & Cropland Dispersion Parity (`stratified_dataset_builder.py`, `stratified_sampling.py`):** Added bounded quota-refill retries with coordinate deduplication and unified `"stratified_grid"` dispersion for `cropland_mask`.
- [x] **Granule-Grouped `/vsicurl/` Site Queries & Land-Tile Lookup (`point_sampling.py`):** Unified `sample_points_over_date_range()` and `sample_points_from_geodataframe()` onto `sample_points_from_granule()` and updated `find_sentinel2_tile()` to use `sentinel_tiles.tiles()` + `sentinel_tiles.land()`.
- [x] **Code Hygiene, Tests & Documentation:** Consolidated `product_name_from_filename()`, added `DeprecationWarning` on `aquisition_date`, added `version.py` fallback, bumped `pyproject.toml` to `1.3.0`, updated `README.md`, and verified `57 passed` unit tests + live `make test-sampler`.

---

## 8. Roadmap for `v1.4.0`: On-Demand Land-Cover & Cropland Stratification

To support global agricultural vs. non-managed ecosystem stratification without requiring users to manually download, mosaic, and reproject external land-cover rasters for thousands of Sentinel-2 tiles, `v1.4.0` introduces built-in land-cover stratification:

### 8.1 On-Demand Land-Cover Provider (`ECOv003_CMR/land_cover.py`)
- Fetch and warp external land-cover classifications (e.g., ESA WorldCover 10m COGs or MODIS MCD12Q1) on demand to match a target Sentinel-2 MGRS tile's grid and affine transform.
- Cache aligned tile-level binary cropland masks in `~/.cache/ECOv003_CMR/land_cover/` so each MGRS tile is downloaded and reprojected at most once across all ECOSTRESS overpasses.

### 8.2 Global & Batch-Level Cropland Quota Tracking (`ECOv003_CMR/stratified_dataset_builder.py` & `stratified_sampling.py`)
- Expose `cropland_fraction_target` and `land_cover_source` directly on `build_stratified_dataset()`.
- Track realized cropland vs. non-managed sample counts across execution batches so tiles with limited or zero cropland (e.g., boreal forest, desert, or alpine tiles) do not cause quota failures, and downstream agricultural tiles dynamically compensate to achieve the global target proportion.