# ECOv003-CMR Development Plan: From Collection 3 Migration (`v1.1.1`) to Global 1M-Sample Stratified Point-Query Pipeline (`v1.2.0`, `v1.3.0` & `v1.4.0`)

**Prepared:** 2026-11-19

**Repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`

**Previous Versions:** `v1.1.1` (Collection 3 Baseline), `v1.2.0` (Concurrent `/vsicurl/` Stratified Sampler)

**Current Version:** `v1.3.0` (Implemented & Benchmarked: Two-Pass ET-First CMR Discovery, Wildcard Batch Resolution, UMM-JSON/CSV Catalog Indexing, Paired Scale Examples & Socket/Checkpoint Resilience)

**Future Target Version:** `v1.4.0` (On-Demand Land-Cover & Cropland Stratification)

## 1. Executive Summary

`ECOv003-CMR` provides programmatic access to NASA's Common Metadata Repository (CMR) and LP DAAC Earthdata Cloud (`LPCLOUD`) archives for ECOSTRESS Collection 3 (`.003`). Across `v1.1.1` through `v1.3.0`, the package evolved from a site-centric download and point-query library into a production-hardened, globally scalable, spatially and seasonally stratified point-sampling engine (`build_stratified_dataset()`), originally motivated by generating a **\~1,000,000-sample non-tower ECOSTRESS training dataset** across the full 1-year Collection 3 record (`2025-10-31` to `2026-10-31`) for uncertainty quantification (UQ) via transport maps, spatial downscaling of relative humidity (`RH`), and temporal upscaling of evapotranspiration (`ET`).

Through three major releases and live benchmarking against LP DAAC Earthdata Cloud granules (`11SLT` single-tile benchmark and the multi-region `one_hundred_dataset.py` scale example across 16 science and UQ layers), **mean per-granule extraction latency was reduced from 56.71s (`v1.2.0` baseline) to 13.00s (`v1.2.0` concurrent) and down to 8.72s–9.76s (`v1.3.0`)—an overall** $5.8\times$**–**$6.5\times$ **per-granule speedup**—reducing the amortized global 1,000,000-sample runtime estimate from **3.98 hours** to **40.07–45.44 minutes** on 16 workers with **100.0% layer completeness** (`57 passed` offline unit tests + live `one_hundred_dataset.py` verification).

Furthermore, empirical CMR API profiling across the full 1-year global `L3T_JET` archive (`348,477` scenes) and `L2T_LSTE` archive established two critical architectural optimizations for `v1.3.1` / pre-1M launch:
1. **CMR `granules.csv` + 5-Day Parallel Windows:** Switching global catalog enumeration from `granules.umm_json` (~8 MB/page with polygons and `RelatedUrls`) to `granules.csv` (~35 KB/page, **~97% smaller**) across 5-day parallel windows (`chunk_days=5`, `max_workers=6` with retry backoff) enumerates all **348,477** global `L3T_JET` scenes in **~2 minutes** with zero spatial overlap duplicates.
2. **Sidecar `QAPercentCloudCover` Filtering Instead of CMR `cloud_cover` Query Params:** Empirical CMR probes proved that NASA CMR leaves `CloudCover` null on **all** ECOSTRESS Collection 3 products (`L3T_JET` and `L2T_LSTE`), causing server-side `cloud_cover=0,20` CMR queries to return `0` hits, whereas true scene cloud fraction (`QAPercentCloudCover`) lives inside each granule's ~3 KB `.json` metadata sidecar (`fetch_granule_metadata()`).

## 2. How Baseline Version (`v1.1.1`) Was Achieved

The baseline architecture in `v1.1.1` was built across six foundational engineering milestones:

### 2.1 Collection 3 Product Catalog & LPCLOUD Concept ID Alignment

* Queried the seven active ECOSTRESS Collection 3 `.003` DOIs against the NASA CMR Collections API (`https://cmr.earthdata.nasa.gov/search/collections.json?doi=<DOI>`) and codified the verified LPCLOUD Concept IDs in `ECOv003_CMR/constants.py` (`CONCEPT_IDS`):

  * `L1CT_RAD` (`C4142244484-LPCLOUD`) — Calibrated at-sensor radiance

  * `L2T_LSTE` (`C3998139651-LPCLOUD`) — Land surface temperature & emissivity

  * `L2T_STARS` (`C3998139658-LPCLOUD`) — Surface reflectance, `NDVI`, and `albedo` priors

  * `L3T_ETAUX` (`C4057520953-LPCLOUD`) — Tiled auxiliary meteorology, soil moisture, and radiation (consolidating retired Collection 2 `L3T_MET`, `L3T_SM`, and `L3T_SEB`)

  * `L3T_JET` (`C4057232489-LPCLOUD`) — JPL evapotranspiration product

  * `L4T_ESI` (`C4057232495-LPCLOUD`) — Evaporative Stress Index

  * `L4T_WUE` (`C4057232498-LPCLOUD`) — Water Use Efficiency

* Added strict product validation in `ECOSTRESS_CMR_search()` and `download_ECOSTRESS()` so discontinued Collection 2 product codes raise descriptive `ValueError` exceptions immediately.

### 2.2 Paginated CMR Granule Search & URL Interpretation

* Implemented `ECOSTRESS_CMR_search_links()` (`ECOv003_CMR/ECOSTRESS_CMR_search_links.py`) with `page_size=2000` and iterative `CMR-Search-After` pagination with duplicate-token loop protection.

* Implemented `GranuleID` (`granule_ID.py`), `granule_ID_from_filename.py`, `product_name_from_filename.py`, `variable_from_filename.py`, and `interpret_ECOSTRESS_URLs.py` to parse both 8-segment standard Collection 3 filenames (`ECOv003_<PRODUCT>_<ORBIT>_<SCENE>_<TILE>_<YYYYMMDDTHHMMSS>_<BUILD>`) and 6-segment daily `L2T_STARS` filenames (`ECOv003_L2T_STARS_<TILE>_<YYYYMMDD>_<BUILD>`), including multi-token variable names (`view_zenith`, `Emis4_err`, `NDVI-UQ`) and `.jpeg.aux.xml` sidecars.

### 2.3 Authenticated Earthdata Cloud Downloads & CLI Tooling

* Built `setup_earthdata_session()` (`ECOv003_CMR/authentication.py`) resolving credentials in priority order: explicit arguments $\rightarrow$ `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` environment variables $\rightarrow$ `~/.netrc`.

* Updated `download_file()` (`ECOv003_CMR/download_file.py`) to propagate authenticated `requests.Session` objects across URS redirects, write atomically via `.download` temporary files, remove zero-byte files, and display `tqdm.auto.tqdm` progress bars.

* Updated `download_ECOSTRESS()` (`ECOv003_CMR/download_ECOSTRESS.py`) to extract true per-granule acquisition dates via `_acquisition_date_from_granule_id()` and standardized `ECOv003-search` / `ECOv003-download` CLI logging and exit codes.

### 2.4 `ECOv003-granules` Collection 3 Compatibility Adapter

* Created `ECOv003_CMR/granule_compatibility.py` (`_Collection3GranuleMixin` and `open_ECOSTRESS_granule()`) to support directory-backed downloads (in addition to `.zip` archives), `L1CT_RAD` dispatch, `L3T_ETAUX` handling, and `L2T_STARS` metadata parsing, validated by `download_ECOSTRESS_granule()`.

### 2.5 In-Memory COG Point Sampling & Temporal Joining

* Implemented `sample_point_from_url()`, `sample_points_over_date_range()`, and `sample_points_from_geodataframe()` (`ECOv003_CMR/point_sampling.py`) supporting automatic CRS reprojection to `EPSG:4326`, Kelvin-to-Celsius conversion (`ST_C = LST - 273.15`), and parallel/sequential execution parity.

### 2.6 Offline CI Test Suite

* Established offline unit tests (`tests/test_cmr_search.py`, `tests/test_download_ECOSTRESS_granule.py`, `tests/test_granule_compatibility.py`, `tests/test_point_sampling.py`, `tests/test_import_dependencies.py`) running across Python 3.11–3.14 in `.github/workflows/ci.yml`.

## 3. Architectural Evolution: `v1.1.1` $\rightarrow$ `v1.2.0` $\rightarrow$ `v1.3.0`

| Pipeline Stage | `v1.1.1` Baseline | `v1.2.0` Stratified Sampler | `v1.3.0` Production Hardening & Scale |
| :--- | :--- | :--- | :--- |
| **Spatial Discovery** | Required user-supplied `tile` IDs or point coordinates (`sentinel_tiles.nearest()`). | `list_ecostress_land_tiles()` attempted nested MGRS loop (240s, 0 tiles on `sentinel-tiles` `1.2.0`). | Vectorized `sentinel_tiles.sentinel_polygons` lookup (`14,749` global land tiles in `0.62s`); `find_sentinel2_tile()` uses true polygon intersection (`sentinel_tiles.tiles(point)`) with `sentinel_tiles.land(t)` filtering. |
| **CMR Query Strategy & Scale** | Queried single tile centroid (`lon,lat,lon,lat`), missing diagonal swaths. | Queried full tile bounds (`use_tile_bounds=True`), but issued `4 × N_tiles` sequential per-tile requests globally. | **ET-first catalog discovery + lazy wildcard batch resolution:** Enumerates global `L3T_JET` overpasses via lightweight temporal endpoints (`granules.umm_json` / `granules.csv`), prunes tiles below `min_granules_floor`, runs `select_stratified_granules()`, and resolves `.tif`/`.json` URLs via `readable_granule_name[]` wildcard batches strictly for selected granules. |
| **Cloud Cover Filtering** | None (returned all scenes). | Passed `max_cloud_cover` against `granules.json` `cloud_cover` (null on Collection 3). | Identified that CMR leaves `CloudCover` null on all Collection 3 products (`L3T_JET`, `L2T_LSTE`), while per-granule `.json` sidecars (`ProductMetadata.QAPercentCloudCover`) store exact scene cloud cover (`fetch_granule_metadata()`). |
| **Socket & Catalog Resilience** | Re-queried CMR on every run without socket timeouts. | In-memory URL caching within a single run only. | Strict `(15s, 60s)` `(connect, read)` socket timeouts, per-thread connection pooling, retry backoff on `Timeout`/`ConnectionError`/HTTP `429,500,502,503,504`, `tqdm` progress bars, and SHA-256 validated `candidate_granules.parquet`. |
| **Intra-Granule Sampling & Quotas** | Fixed user coordinates across overpasses. | Dynamic `"stratified_grid"` / `"uniform"` coordinate randomization with fixed `1.25×` oversample. | Bounded adaptive quota refill (`max_refill_attempts = 2`) with coordinate deduplication when multi-product `NaN` dropouts cause shortfalls, plus `"stratified_grid"` dispersion parity when `cropland_mask` is supplied. |
| **COG Read & Concurrency** | Downloaded full `.tif` into `MemoryFile` per `(point, granule, variable)`. | Concurrent `/vsicurl/` reads in `sample_points_from_granule()` (unbounded nested pools); site queries still used full-file `MemoryFile` downloads. | Shared `threading.Semaphore(max_concurrent_streams)` bounding active HTTP streams, deterministic GDAL HTTP retries (`429,502,503,504`), live `tqdm` extraction progress/throughput telemetry, and unified granule-grouped `/vsicurl/` site queries. |
| **Auth & Cookie Lifecycle** | One-time `mkstemp` cookie file without Netscape serialization or cleanup. | Pre-warmed `requests.Session` once at start of run. | `@contextmanager` `configure_gdal_earthdata_env()` exports `session.cookies` via `http.cookiejar.MozillaCookieJar`, refreshes cookies across synchronous `batch_size` windows, and removes temp files on exit. |
| **Diagnostics & Memory** | In-memory `DataFrame` only. | Partitioned Parquet writes, but `pd.concat` loaded all rows into RAM at Stage 6. | Constant-RAM ($O(1)$) streaming `pyarrow.parquet.ParquetFile` column metadata/batch diagnostics in `summarize_point_samples()`. |

## 4. Implemented `v1.3.0` Workstreams

1. **Vectorized Global MGRS Land-Tile Discovery (`ECOv003_CMR/tile_catalog.py`):**

   * Queries `sentinel_tiles.sentinel_polygons` directly (`Land == True` within `[-54.0, 54.0]` latitude), enumerating all **14,749** ECOSTRESS-covered land MGRS tiles in **0.62s** (replacing a 239.5s brute-force MGRS grid loop).

2. **UMM-JSON Global Catalog Enumeration & Post-Stratification Wildcard Batch Resolution (`ECOv003_CMR/stratified_sampling.py`, `ECOSTRESS_CMR_search_links.py`, `stratified_dataset_builder.py`):**

   * Added `search_granule_catalog_umm()` (`granules.umm_json`) and `resolve_granule_asset_urls()` (`search_granules_by_name_patterns()` with `options[readable_granule_name][pattern]=true` and `pattern_batch_size=150`).

   * Deferred `.tif` asset URL resolution in `build_stratified_dataset()` until Stage `[4/6]` right after `select_stratified_granules()` caps each tile to $N_{\text{cap}}$ (with automatic tile backfill if any companion granule is absent), avoiding thousands of unnecessary CMR requests for unselected overpasses.

   * Enforced strict `(15.0s, 60.0s)` `(connect, read)` socket timeouts, per-thread unauthenticated `requests.Session` connection pooling, retry backoff on `Timeout`, `ConnectionError`, and HTTP `429`/`500`/`502`/`503`/`504`, and `tqdm` + `logging_redirect_tqdm()` progress bars.

3. **Persistent Candidate Granule Catalog Caching (`ECOv003_CMR/stratified_dataset_builder.py`):**

   * Saves verified candidate catalogs to `candidate_granules.parquet` with JSON-serialized `variable_urls` and Parquet schema metadata encoding `(start_date, end_date, max_cloud_cover, tile_count, tiles_sha256, queried_products)`.

   * Reloads matching catalogs offline when `refresh_catalog=False`, and automatically re-queries if requested layers require uncached products.

4. **Bounded HTTP Stream Concurrency, Live Extraction Telemetry & Deterministic Retry Backoff (`ECOv003_CMR/stratified_dataset_builder.py`, `point_sampling.py`, `authentication.py`):**

   * Decouples outer `max_workers` from inner `layer_workers` and enforces a global `threading.Semaphore(max_concurrent_streams)` (default `32`) across all `/vsicurl/` reads.

   * Wraps Stage `[5/6]` COG extraction in `logging_redirect_tqdm()` with a `tqdm` progress bar displaying live accepted sample counts and rolling `samples/s` throughput.

   * Configures deterministic GDAL HTTP retry options (`GDAL_HTTP_MAX_RETRY=3`, `GDAL_HTTP_RETRY_DELAY=2`, `GDAL_HTTP_RETRY_CODES=429,502,503,504`) alongside jittered exponential backoff on `MemoryFile` fallbacks.

5. **Netscape URS Cookie Export, Synchronous Batch Re-Warming & Cleanup (`ECOv003_CMR/authentication.py`, `stratified_dataset_builder.py`):**

   * Converts `configure_gdal_earthdata_env()` into a `@contextmanager` that serializes pre-warmed `session.cookies` into Netscape format (`http.cookiejar.MozillaCookieJar`) for GDAL `libcurl` and deletes temporary `earthdata_gdal_*.cookies` files in `finally`.

   * Partitions pending granules into synchronous `batch_size` windows (default `250`) to refresh cookies cleanly between batches.

6. **Constant-RAM Streaming Parquet Diagnostics (`ECOv003_CMR/point_sampling.py`, `stratified_dataset_builder.py`):**

   * Extends `summarize_point_samples()` to accept Parquet file paths and compute per-layer valid/missing counts directly from `pyarrow.parquet.ParquetFile` row-group statistics (falling back to streaming `iter_batches()` when stats are absent).

7. **Adaptive Per-Granule Quota Refill & Cropland Dispersion Parity (`ECOv003_CMR/stratified_dataset_builder.py`, `stratified_sampling.py`):**

   * Adds a bounded adaptive refill loop (`max_refill_attempts = 2`) in `_process_granule()` with coordinate deduplication (`seen_coords`) so multi-product `NaN` dropouts do not cause silent sample shortfalls.

   * Routes user-supplied `cropland_mask` sampling in `sample_granule_coordinates()` through `_draw_dispersed_indices()` so `"stratified_grid"` dispersion applies equally to agricultural and natural land pools.

8. **Granule-Grouped `/vsicurl/` Site Queries, True MGRS Containment & Companion Scale Runners (`ECOv003_CMR/point_sampling.py`, `one_million_dataset.py`, `one_hundred_dataset.py`):**

   * Refactors `sample_points_over_date_range()` and `sample_points_from_geodataframe()` onto `_build_granule_sampling_batches()` and `sample_points_from_granule()` (`/vsicurl/`), joining daily `L2T_STARS` priors by `(tile, YYYYMMDD)`.

   * Updates `find_sentinel2_tile()` to use `sentinel_tiles.tiles(Point(lon, lat))` with `sentinel_tiles.land(t)` filtering (`land_only=True`, `return_all=False`).

   * Provides paired root CLI runners writing to git-ignored `./experimental_data/`: `one_million_dataset.py` (`./experimental_data/one_million_dataset`, `2025-10-31` to `2026-10-31`, `1,000,000` target samples) and `one_hundred_dataset.py` (`./experimental_data/one_hundred_dataset`, `100`-observation multi-region scale example validated in `33.30s` end-to-end with `102/102` valid rows across all 16 layers, plus `--catalog-path` reuse).

## 5. Technical Challenges Encountered & How They Were Overcome

During live integration, global 1-year discovery runs, and unit testing of `v1.3.0` against `sentinel-tiles` (`1.2.0`), NASA CMR (`cmr.earthdata.nasa.gov`), and LP DAAC Earthdata Cloud (`LPCLOUD`), nine concrete technical challenges surfaced:

1. **Redundant Spatial CMR Sweeps Across Nighttime & Non-ET Overpasses:**

   * *Challenge:* Running blind spatial bounding-box searches across all four products (`L3T_JET`, `L2T_LSTE`, `L3T_ETAUX`, `L2T_STARS`) downloaded \~80–85% irrelevant metadata (all nighttime `L2T_LSTE`/`L3T_ETAUX` scenes, failed-ET overpasses, and 365 daily `L2T_STARS` tiles/year) that were subsequently discarded during the inner join with `L3T_JET`, while large $30^\circ \times 30^\circ \times 92\text{-day}$ boxes hit deep `CMR-Search-After` pagination cursors.

   * *Resolution:* Replaced blind spatial sweeps with ET-first global temporal catalog enumeration (`search_granule_catalog_umm()`) and deferred pattern-batch URL resolution (`resolve_granule_asset_urls()` via `readable_granule_name[]`) strictly for selected granules.

2. **CMR Leaving `CloudCover` Null Across All Collection 3 Products (`L3T_JET` & `L2T_LSTE`):**

   * *Challenge:* Probing CMR `CMR-Hits` and `granules.csv` across the 1-year window (`2025-10-31` to `2026-10-31`) revealed **348,477** global `L3T_JET` scenes, but passing `cloud_cover=0,20` to CMR returned **0 hits** for **both** `L3T_JET` and `L2T_LSTE`—confirming that NASA CMR leaves `CloudCover` null on all Collection 3 granules and excludes null-`CloudCover` granules whenever a numeric `cloud_cover` query filter is sent. Meanwhile, actual scene cloud fraction (`QAPercentCloudCover`) is stored inside each granule's ~3 KB `.json` sidecar (`fetch_granule_metadata()`).

   * *Resolution (Pending Fix in `v1.3.1`):* Remove `params["cloud_cover"]` from CMR query URLs in `search_granule_catalog_umm()` / `search_granules_by_name_patterns()`, and instead evaluate `QAPercentCloudCover` from per-granule `.json` sidecars concurrently (`fetch_granule_metadata()`) when `max_cloud_cover` filtering is requested.

3. **`granules.umm_json` Payload Overhead vs. `granules.csv` + 5-Day Parallel Windows:**

   * *Challenge:* Even without `links`, `granules.umm_json` transmits full G-Ring spatial polygons and ~20 `RelatedUrls` checksum blocks per granule (~6–10 MB per 2,000-row page), and 31-day monthly chunks require 15–35 sequential `CMR-Search-After` round-trips (~54s/chunk).

   * *Resolution (Pending Fix in `v1.3.1`):* Switch global catalog enumeration to CMR's flat **`granules.csv`** endpoint (`https://cmr.earthdata.nasa.gov/search/granules.csv`, ~35 KB per 2,000-row page—**~97% smaller**) across **5-day parallel temporal windows** (`chunk_days=5`, `max_workers=6` with exponential retry backoff), enumerating all 348,477 global `L3T_JET` scenes in ~2 minutes without needing a second CMR pass just to check `CloudCover`.

4. **Unbounded Socket Reads Freezing Overnight CMR Discovery (`requests.get` without `timeout`):**

   * *Challenge:* Omitting a `timeout` parameter on `requests.get()` inside `ECOSTRESS_CMR_search_links.py` allowed worker threads to block indefinitely on `socket.recv()` when a paginated CMR connection dropped mid-stream.

   * *Resolution:* Added explicit `(15.0, 60.0)` second `(connect, read)` socket timeouts, per-thread unauthenticated `requests.Session` connection pooling, and retry backoff on `Timeout` / `ConnectionError`.

5. **NASA CMR Rejecting Earthdata URS Basic Auth Headers (`401 Unauthorized`):**

   * *Challenge:* Threading the authenticated `requests.Session` (configured with `session.auth = (username, password)` for `urs.earthdata.nasa.gov`) into `ECOSTRESS_CMR_search_links()` caused `cmr.earthdata.nasa.gov/search/granules.json` to return `401 Client Error: Unauthorized`, because CMR search endpoints reject URS Basic Auth credentials.

   * *Resolution:* Updated `_get_cmr_session()` / `_request_with_backoff()` in `ECOSTRESS_CMR_search_links.py` to never attach URS Basic Auth credentials to public `cmr.earthdata.nasa.gov` search requests.

6. **`sentinel_tiles.grid(tile)` Returning `RasterGrid` Instead of a Shapely Polygon:**

   * *Challenge:* `sentinel_tiles.grid(tile)` returns a `rasters.RasterGrid` object (which lacks `.bounds` and `.intersects()`), causing `list_ecostress_land_tiles()` to spend 239.5s returning `0` tiles and causing tile-bounds CMR queries to fall back to single centroid points.

   * *Resolution:* Vectorized `list_ecostress_land_tiles()` directly over `sentinel_tiles.sentinel_polygons` (`14,749` land tiles in `0.62s`) and switched bounding-box resolution to `sentinel_tiles.footprint(tile).bounds`.

7. **Open-Ocean MGRS Tile False Positives in `find_sentinel2_tile()`:**

   * *Challenge:* `sentinel_tiles.tiles(Point(-140.0, 0.0))` returned `'07MFV'` because the global MGRS polygon index tiles both land and open ocean.

   * *Resolution:* Added `land_only: bool = True` to `find_sentinel2_tile()` in `point_sampling.py`, filtering `sentinel_tiles.tiles(point)` through `sentinel_tiles.land(t)` so open-ocean coordinates cleanly return `None` (or `[]` when `return_all=True`).

8. **Silent Long-Running Discovery & Extraction Phases:**

   * *Challenge:* Multi-minute CMR discovery and multi-thousand-granule extraction phases lacked progress bars and milestone logs, making it hard to distinguish active pagination from network stalls.

   * *Resolution:* Added `tqdm` progress bars (`dynamic_ncols=True`) wrapped in `logging_redirect_tqdm()` to catalog enumeration, asset URL resolution, and Stage `[5/6]` (`Extracting COGs`) alongside milestone logs.

9. **Netscape Cookie Serialization for GDAL `/vsicurl/`:**

   * *Challenge:* Pre-warming an Earthdata URL in `requests.Session` stores session tokens in an in-memory `RequestsCookieJar`, whereas GDAL's underlying `libcurl` requires a Netscape-formatted cookie file on disk (`GDAL_HTTP_COOKIEFILE`) to avoid per-thread OAuth redirect loops.

   * *Resolution:* Implemented `_export_session_cookies_to_netscape()` using `http.cookiejar.MozillaCookieJar(cookie_file).save(...)` inside `configure_gdal_earthdata_env()` and removed the temporary cookie file in a `finally` block upon context exit.

## 6. Quantified Performance Progression (`v1.2.0` $\rightarrow$ `v1.3.0`)

Live benchmarks were executed via `make test-sampler` (`examples/stratified_sampling_demo.py`, single tile `11SLT`, 2 granules) and `python one_hundred_dataset.py` (multi-region 4-tile pilot across `11SLT`, `11SPS`, `52NHN`, `53NMH`, June 1–30, 2026; 6 selected granules, `N_cap=2`, `K=17`, 102 accepted samples across 16 science & UQ layers):

| Benchmark Metric | `v1.2.0` Baseline (Sequential Layers) | `v1.2.0` Optimized (Concurrent Layers) | `v1.3.0` Single-Tile (`11SLT`, 2 granules) | `v1.3.0` Multi-Region Scale Example (`one_hundred_dataset.py`, 6 granules) | Total Improvement (`v1.2.0` Base $\rightarrow$ `v1.3.0`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Global Land Tile Discovery** | `239.53s` (`0` tiles) | `239.53s` | **`0.62s` (`14,749` tiles)** | **`0.62s` (`14,749` tiles)** | $386\times$ **faster** (`-99.7%`) |
| **Total Wall Time** | `65.78s` (2 granules) | `19.77s` (2 granules) | **`18.97s`** (2 granules) | **`33.30s`** (6 granules, 102 samples) | $3.47\times$ **faster** (`-71.2%`) |
| **COG Extraction Wall Time** | `59.26s` (2 granules) | `13.27s` (2 granules) | **`11.00s`** (2 granules) | **`14.53s`** (6 granules) | $5.39\times$ **faster** (`-81.4%`) |
| **Parquet Aggregation Time** | `0.09s` (`pd.concat`) | `0.09s` (`pd.concat`) | **`0.00s`** (`pyarrow` metadata) | **`0.00s`** (`pyarrow` metadata) | $O(1)$ **RAM, `<1ms`** |
| **Mean Per-Granule Latency** | `56.71s / granule` | `13.00s / granule` | **`9.76s / granule`** | **`8.72s / granule`** | $6.50\times$ **faster** (`-84.6%`) |
| **Extraction Throughput** | `0.44 samples/s` | `1.96 samples/s` | **`2.36 samples/s`** ($K=13$) | **`7.02 samples/s`** ($K=17$, 4 workers) | $16.0\times$ **faster** (`+1,495%`) |
| **Amortized Global 1M Estimate (**$4{,}000$ **granules,** $K=250$**, 16 workers)** | `3.98 hours` | `56.77 minutes` | **`45.44 minutes`** | **`40.07 minutes`** | $5.96\times$ **faster** (`-83.2%`) |
| **Layer Completeness (16 layers)** | `100.0%` (`26/26`) | `100.0%` (`26/26`) | **`100.0%` (`26/26`)** | **`100.0%` (`102/102`)** | **Zero data loss** |
| **Offline Unit Test Suite** | `52 passed` | `52 passed` | **`57 passed`** (`3.02s`) | **`57 passed`** (`3.02s`) | **`+5` new regression tests** |

## 7. Completed `v1.3.0` Checklist & Pending `v1.3.1` Fixes

### Completed in `v1.3.0`

* \[x\] **Vectorized Global MGRS Land-Tile Catalog (`ECOv003_CMR/tile_catalog.py`):** Discovered all 14,749 ECOSTRESS-covered land MGRS tiles in 0.62s via `sentinel_tiles.sentinel_polygons`.

* \[x\] **UMM-JSON Global Catalog & Post-Stratification Wildcard Batch Resolution (`stratified_sampling.py`, `ECOSTRESS_CMR_search_links.py`, `stratified_dataset_builder.py`):** Added `search_granule_catalog_umm()` and `resolve_granule_asset_urls()` (`readable_granule_name[]` batches), deferring `.tif` URL resolution until Stage `[4/6]` after $N_{\text{cap}}$ balancing.

* \[x\] **Persistent Candidate Catalog Caching (`ECOv003_CMR/stratified_dataset_builder.py`):** Added SHA-256 cache-keyed `candidate_granules.parquet` persistence with `catalog_path` and `refresh_catalog`.

* \[x\] **Bounded Stream Concurrency, Live Extraction Telemetry & Deterministic Retries (`stratified_dataset_builder.py`, `point_sampling.py`, `authentication.py`):** Added `max_concurrent_streams` semaphore, `layer_workers`, `tqdm` extraction progress/rate bar, GDAL HTTP retry options, and jittered fallback backoff.

* \[x\] **Netscape Cookie Export & Synchronous Batch Re-Warming (`authentication.py`, `stratified_dataset_builder.py`):** Converted `configure_gdal_earthdata_env()` to a `@contextmanager` with `MozillaCookieJar` export, `batch_size` windows, and temp cookie cleanup.

* \[x\] **Constant-RAM Streaming Parquet Diagnostics (`point_sampling.py`, `stratified_dataset_builder.py`):** Implemented $O(1)$-RAM `pyarrow.parquet` column metadata/batch summarization.

* \[x\] **Adaptive Quota Refill & Cropland Dispersion Parity (`stratified_dataset_builder.py`, `stratified_sampling.py`):** Added bounded quota-refill retries with coordinate deduplication and unified `"stratified_grid"` dispersion for `cropland_mask`.

* \[x\] **Granule-Grouped `/vsicurl/` Site Queries, Land-Tile Lookup & Paired `experimental_data/` Runners (`point_sampling.py`, `one_million_dataset.py`, `one_hundred_dataset.py`):** Unified `sample_points_over_date_range()` and `sample_points_from_geodataframe()` onto `sample_points_from_granule()`, updated `find_sentinel2_tile()` to use `sentinel_tiles.tiles()` + `sentinel_tiles.land()`, and validated `one_hundred_dataset.py` (`33.30s`, `7.02 samples/s`, 102/102 valid rows) into `./experimental_data/`.

* \[x\] **Code Hygiene, Tests & Documentation:** Consolidated `product_name_from_filename()`, added `DeprecationWarning` on `aquisition_date`, added `version.py` fallback, bumped `pyproject.toml` to `1.3.0`, updated `README.md`, and verified `57 passed` unit tests.

### Pending Fixes (`v1.3.1` / Pre-1M Launch): CMR `granules.csv` + Sidecar `QAPercentCloudCover` Filtering

* \[ \] **Switch Global Catalog Enumeration to CMR `granules.csv` (`ECOv003_CMR/constants.py`, `ECOSTRESS_CMR_search_links.py`):** Add `CMR_CSV_SEARCH_URL = f"{CMR_SEARCH_URL}granules.csv"` and update `search_granule_catalog_umm()` (or add `search_granule_catalog_csv()`) to query `granules.csv` across **5-day parallel temporal windows** (`chunk_days=5`, `max_workers=6` with retry backoff), cutting payload transfer by **\~97%** (~35 KB/page vs. ~8 MB/page) and eliminating the redundant second global CMR pass on `L2T_LSTE`.

* \[ \] **Remove `cloud_cover` Query Parameter from CMR Requests (`ECOSTRESS_CMR_search_links.py`, `stratified_sampling.py`):** Do not pass `cloud_cover=0,{max_cloud_cover}` to NASA CMR (`granules.csv`, `granules.umm_json`, or `granules.json`), since CMR leaves `CloudCover` null on all Collection 3 products (`L3T_JET` and `L2T_LSTE`) and returns `0` hits when filtered server-side.

* \[ \] **Filter `max_cloud_cover` via Per-Granule `.json` Sidecars (`stratified_sampling.py`, `stratified_dataset_builder.py`):** Include `.json` sidecar URLs in `resolve_granule_asset_urls()` (`search_granules_by_name_patterns()`), fetch `.json` metadata concurrently (`32` worker threads via `fetch_granule_metadata()`) to extract `ProductMetadata.QAPercentCloudCover`, filter out scenes exceeding `max_cloud_cover`, and backfill any dropped tiles from `candidate_granules`.

* \[ \] **Update `count_L3T_JET_scenes_by_cloud_percent.py`:** Enumerate all `348,477` global `L3T_JET` scenes via `granules.csv` (`chunk_days=5`, `max_workers=6`), draw a seasonally and spatially stratified sample (e.g., `N=2,000` scenes, with an optional `--exact-all` flag), resolve `.json` sidecar URLs in ~14 `readable_granule_name[]` batches, and inspect `QAPercentCloudCover` concurrently to report accurate scene counts and percentages for `<= 20.0%`, `<= 10.0%`, and `== 0.0%` cloud cover in **<2.5 minutes**.

## 8. Roadmap for `v1.4.0`: On-Demand Land-Cover & Cropland Stratification

To support global agricultural vs. non-managed ecosystem stratification without requiring users to manually download, mosaic, and reproject external land-cover rasters for thousands of Sentinel-2 tiles, `v1.4.0` introduces built-in land-cover stratification:

### 8.1 On-Demand Land-Cover Provider (`ECOv003_CMR/land_cover.py`)

* Fetch and warp external land-cover classifications (e.g., ESA WorldCover 10m COGs or MODIS MCD12Q1) on demand to match a target Sentinel-2 MGRS tile's grid and affine transform.

* Cache aligned tile-level binary cropland masks in `~/.cache/ECOv003_CMR/land_cover/` so each MGRS tile is downloaded and reprojected at most once across all ECOSTRESS overpasses.

### 8.2 Global & Batch-Level Cropland Quota Tracking (`ECOv003_CMR/stratified_dataset_builder.py` & `stratified_sampling.py`)

* Expose `cropland_fraction_target` and `land_cover_source` directly on `build_stratified_dataset()`.

* Track realized cropland vs. non-managed sample counts across execution batches so tiles with limited or zero cropland (e.g., boreal forest, desert, or alpine tiles) do not cause quota failures, and downstream agricultural tiles dynamically compensate to achieve the global target proportion.