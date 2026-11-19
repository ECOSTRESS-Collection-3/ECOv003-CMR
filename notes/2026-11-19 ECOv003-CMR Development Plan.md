# ECOv003-CMR Development Plan: From Collection 3 Migration (`v1.1.1`) to Global 1M-Sample Stratified Point-Query Pipeline (`v1.2.0`, `v1.3.0`, `v1.3.1` & `v1.4.0`)

**Prepared:** 2026-11-19  
**Repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`  
**Previous Versions:** `v1.1.1` (Collection 3 Baseline), `v1.2.0` (Concurrent `/vsicurl/` Stratified Sampler), `v1.3.0` (Two-Pass ET-First CMR Discovery & Wildcard Batch Resolution)  
**Current Version:** `v1.3.1` (Implemented & Verified: CMR `granules.csv` + 5-Day Windows, HTTP `POST` Wildcard Batches, Sidecar `QAPercentCloudCover` Filtering, `64`-Socket Pool Sizing, Pre-Flight Capacity & Biome Planner, Dry-Run Mode & Rejection-Aware Backfill)  
**Future Target Version:** `v1.4.0` (On-Demand Land-Cover & Cropland Stratification)

---

## 1. Executive Summary

`ECOv003-CMR` provides programmatic access to NASA's Common Metadata Repository (CMR) and LP DAAC Earthdata Cloud (`LPCLOUD`) archives for ECOSTRESS Collection 3 (`.003`). Across `v1.1.1` through `v1.3.1`, the package evolved from a site-centric download and point-query library into a production-hardened, globally scalable, spatially and seasonally stratified point-sampling engine (`build_stratified_dataset()`), motivated by generating a **~1,000,000-sample non-tower ECOSTRESS training dataset** across the full 1-year Collection 3 record (`2025-10-31` to `2026-10-31`) for uncertainty quantification (UQ) via transport maps, spatial downscaling of relative humidity (`RH`), and temporal upscaling of evapotranspiration (`ET`).

Through live benchmarking against LP DAAC Earthdata Cloud granules (`11SLT` single-tile benchmark and the multi-region `one_hundred_dataset.py` scale example across 16 science and UQ layers), **mean per-granule extraction latency was reduced from 56.71s (`v1.2.0` baseline) to 13.00s (`v1.2.0` concurrent) and down to 8.72s–9.76s (`v1.3.0`–`v1.3.1`)—an overall $5.8\times$–$6.5\times$ per-granule speedup**—reducing the amortized global 1,000,000-sample runtime estimate from **3.98 hours** to **40.07–40.15 minutes** on 16 workers with **100.0% layer completeness** (`59 passed` offline unit tests + live `one_hundred_dataset.py` `--dry-run` / extraction and global `L3T_JET` cloud-cover census verification).

In `v1.3.1`, global discovery, cloud filtering, and a priori sampling design capabilities were completed and verified against the full 1-year global `L3T_JET` archive (**348,477** scenes):
1. **CMR `granules.csv` + 5-Day Parallel Windows:** Replaced `granules.umm_json` (~8 MB/page with G-Ring polygons and `RelatedUrls`) with flat `granules.csv` (~35 KB/page, **~97% smaller**) across 5-day parallel windows (`chunk_days=5`, `max_workers=6` with jittered retry backoff), enumerating all **348,477** global `L3T_JET` scenes in **2m 01s–2m 09s** with zero spatial overlap duplicates.
2. **HTTP `POST` Wildcard Pattern Batching:** Updated `search_granules_by_name_patterns()` to send `application/x-www-form-urlencoded` `POST` requests to `granules.json`, eliminating `414 Request-URI Too Large` errors on batches of 150 `readable_granule_name[]` wildcard patterns and resolving 14 batches in **4–5 seconds**.
3. **Sidecar `QAPercentCloudCover` Filtering & `64`-Socket Pool Sizing:** Removed `cloud_cover=0,...` query parameters from CMR requests (where `CloudCover` is null on all Collection 3 granules), mounted `HTTPAdapter(pool_connections=64, pool_maxsize=64)` in `setup_earthdata_session()` to eliminate `urllib3` pool-full warnings under 32-thread concurrency, and implemented concurrent `.json` sidecar inspection (`fetch_granule_metadata()`, `ProductMetadata.QAPercentCloudCover`), establishing global `L3T_JET` cloud-cover distributions (**54.5%** $\le 20\%$, **41.4%** $\le 10\%$, **6.0%** $\le 0\%$).
4. **A Priori Sampling Design, Dry-Run Mode & Rejection-Aware Backfill:** Added `plan_stratified_sampling()`, `estimate_cloud_cover_distribution()`, `dry_run=True` on `build_stratified_dataset()` / `one_hundred_dataset.py` / `one_million_dataset.py`, empirical cloud-rejection backfill multipliers, and humid-tropical tile coverage (`20LLQ`) in the 100-observation scale pilot (`136/136` valid samples at `13.13 samples/s`).

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

## 3. Architectural Evolution: `v1.1.1` $\rightarrow$ `v1.2.0` $\rightarrow$ `v1.3.0` $\rightarrow$ `v1.3.1`

| Pipeline Stage | `v1.1.1` Baseline | `v1.2.0` Stratified Sampler | `v1.3.0`–`v1.3.1` Production Hardening & Scale |
| :--- | :--- | :--- | :--- |
| **Spatial Discovery** | Required user-supplied `tile` IDs or point coordinates (`sentinel_tiles.nearest()`). | `list_ecostress_land_tiles()` attempted nested MGRS loop (240s, 0 tiles on `sentinel-tiles` `1.2.0`). | Vectorized `sentinel_tiles.sentinel_polygons` lookup (`14,749` global land tiles in `0.62s`); `find_sentinel2_tile()` uses true polygon intersection (`sentinel_tiles.tiles(point)`) with `sentinel_tiles.land(t)` filtering. |
| **CMR Query Strategy & Scale** | Queried single tile centroid (`lon,lat,lon,lat`), missing diagonal swaths. | Queried full tile bounds (`use_tile_bounds=True`), but issued `4 × N_tiles` sequential per-tile requests globally. | **CMR `granules.csv` + `POST` wildcard resolution:** Enumerates global `L3T_JET` overpasses via `granules.csv` across 5-day parallel windows (~97% smaller payloads, zero spatial-overlap duplicates), runs `plan_stratified_sampling()` / `select_stratified_granules()`, and resolves `.tif`/`.json` URLs via `POST` `readable_granule_name[]` wildcard batches strictly for selected granules. |
| **Cloud Cover Filtering** | None (returned all scenes). | Passed `max_cloud_cover` against `granules.json` `cloud_cover` (null on Collection 3). | Removed `cloud_cover` query params from CMR requests; reads `ProductMetadata.QAPercentCloudCover` concurrently from per-granule `.json` sidecars (`fetch_granule_metadata()`) and backfills dropped tiles using empirical cloud-rejection multipliers. |
| **A Priori Sampling Design** | None (required full extraction to measure yield). | Manual inspection of logs after discovery. | `plan_stratified_sampling()` forecasts eligible tiles, tropical/temperate/boreal biome counts, $N_{\text{cap}}$, $G$, $K$, and wall time in <1s; `dry_run=True` caches catalogs and exits cleanly before Stage `[5/6]`. |
| **Socket & Catalog Resilience** | Re-queried CMR on every run without socket timeouts. | In-memory URL caching within a single run only. | Strict `(15s, 90s)` `(connect, read)` socket timeouts, `64`-socket `HTTPAdapter` pooling, jittered exponential retry backoff on `Timeout`/`ConnectionError`/HTTP `429,500,502,503,504`, `tqdm` progress bars, and SHA-256 validated `candidate_granules.parquet`. |
| **Intra-Granule Sampling & Quotas** | Fixed user coordinates across overpasses. | Dynamic `"stratified_grid"` / `"uniform"` coordinate randomization with fixed `1.25×` oversample. | Bounded adaptive quota refill (`max_refill_attempts = 2`) with coordinate deduplication when multi-product `NaN` dropouts cause shortfalls, plus `"stratified_grid"` dispersion parity when `cropland_mask` is supplied. |
| **COG Read & Concurrency** | Downloaded full `.tif` into `MemoryFile` per `(point, granule, variable)`. | Concurrent `/vsicurl/` reads in `sample_points_from_granule()` (unbounded nested pools); site queries still used full-file `MemoryFile` downloads. | Shared `threading.Semaphore(max_concurrent_streams)` bounding active HTTP streams, deterministic GDAL HTTP retries (`429,502,503,504`), live `tqdm` extraction progress/throughput telemetry, and unified granule-grouped `/vsicurl/` site queries. |
| **Auth & Cookie Lifecycle** | One-time `mkstemp` cookie file without Netscape serialization or cleanup. | Pre-warmed `requests.Session` once at start of run. | `@contextmanager` `configure_gdal_earthdata_env()` exports `session.cookies` via `http.cookiejar.MozillaCookieJar`, refreshes cookies across synchronous `batch_size` windows, and removes temp files on exit. |
| **Diagnostics & Memory** | In-memory `DataFrame` only. | Partitioned Parquet writes, but `pd.concat` loaded all rows into RAM at Stage 6. | Constant-RAM ($O(1)$) streaming `pyarrow.parquet.ParquetFile` column metadata/batch diagnostics in `summarize_point_samples()`. |

---

## 4. Implemented `v1.3.0` & `v1.3.1` Workstreams

1. **Vectorized Global MGRS Land-Tile Discovery (`ECOv003_CMR/tile_catalog.py`):**
   - Queries `sentinel_tiles.sentinel_polygons` directly (`Land == True` within `[-54.0, 54.0]` latitude), enumerating all **14,749** ECOSTRESS-covered land MGRS tiles in **0.62s** (replacing a 239.5s brute-force MGRS grid loop).
2. **CMR `granules.csv` Global Catalog & `POST` Wildcard Batch Resolution (`ECOv003_CMR/constants.py`, `ECOSTRESS_CMR_search_links.py`, `stratified_sampling.py`, `stratified_dataset_builder.py`):**
   - Added `CMR_CSV_SEARCH_URL` and `search_granule_catalog_csv()` using NASA CMR's flat `granules.csv` endpoint (~35 KB/page vs. ~8 MB/page, **~97% smaller**) across 5-day parallel temporal windows (`chunk_days=5`, `max_workers=6` with jittered exponential retry backoff), enumerating all **348,477** global `L3T_JET` scenes in **~2m 01s**.
   - Updated `search_granules_by_name_patterns()` to issue `application/x-www-form-urlencoded` HTTP `POST` requests to `granules.json`, avoiding `414 Request-URI Too Large` errors on 150-pattern batches and resolving 14 batches in **4–5 seconds**.
   - Deferred `.tif` and `.json` asset URL resolution in `build_stratified_dataset()` until Stage `[4/6]` right after `select_stratified_granules()` caps each tile to $N_{\text{cap}}$ (with automatic rejection-aware tile backfill if any companion granule is absent or exceeds `max_cloud_cover`).
3. **Sidecar `QAPercentCloudCover` Filtering & Stratified Global Cloud Census (`ECOv003_CMR/stratified_sampling.py`, `count_L3T_JET_scenes_by_cloud_percent.py`):**
   - Removed `cloud_cover=0,...` query parameters from CMR requests after proving CMR leaves `CloudCover` null on all Collection 3 granules.
   - Added `filter_granules_by_sidecar_cloud_cover()` and `estimate_cloud_cover_distribution()` to fetch per-granule `.json` sidecars concurrently (`max_workers=32` via `fetch_granule_metadata()`) and report threshold pass rates, 95% confidence intervals, and latitude-band statistics (`count_L3T_JET_scenes_by_cloud_percent.py` completed in **190.96s** with zero connection pool warnings).
4. **A Priori Sampling Design Planner, Dry-Run Mode & Rejection-Aware Backfill (`ECOv003_CMR/stratified_sampling.py`, `stratified_dataset_builder.py`, `__init__.py`):**
   - Implemented `plan_stratified_sampling()` to evaluate candidate `min_granules_floor` thresholds offline in <1s, reporting eligible tiles, `tropical` / `temperate` / `boreal` biome counts, $N_{\text{cap}}$, selected granules $G$, per-granule pixel quota $K$, and estimated Stage `[5/6]` wall time.
   - Replaced the fixed `need * 3` Stage `[4/6]` backfill slice with `_backfill_multiplier_for_cloud_cover(max_cloud_cover)` (`4×` for $\ge 20\%$, `5×` for $10\%\text{–}20\%$, `12×` for $< 10\%$).
   - Added `dry_run: bool = False` to `build_stratified_dataset()`, `one_hundred_dataset.py`, and `one_million_dataset.py` to execute discovery, cache `candidate_granules.parquet`, print/save the `stratification_plan`, and exit before Stage `[5/6]`.
5. **Persistent Candidate Granule Catalog Caching (`ECOv003_CMR/stratified_dataset_builder.py`):**
   - Saves verified candidate catalogs to `candidate_granules.parquet` with JSON-serialized `variable_urls` and Parquet schema metadata encoding `(start_date, end_date, max_cloud_cover, tile_count, tiles_sha256, queried_products)`.
   - Reloads matching catalogs offline in **0.06s** when `refresh_catalog=False`, and automatically re-queries if requested layers require uncached products.
6. **Bounded HTTP Stream Concurrency, Live Extraction Telemetry & Deterministic Retry Backoff (`ECOv003_CMR/stratified_dataset_builder.py`, `point_sampling.py`, `authentication.py`):**
   - Decouples outer `max_workers` from inner `layer_workers` and enforces a global `threading.Semaphore(max_concurrent_streams)` across all `/vsicurl/` reads.
   - Wraps Stage `[5/6]` COG extraction in `logging_redirect_tqdm()` with a `tqdm` progress bar displaying live accepted sample counts and rolling `samples/s` throughput.
   - Configures deterministic GDAL HTTP retry options (`GDAL_HTTP_MAX_RETRY=3`, `GDAL_HTTP_RETRY_DELAY=2`, `GDAL_HTTP_RETRY_CODES=429,502,503,504`) alongside jittered exponential backoff on `MemoryFile` fallbacks.
7. **Netscape URS Cookie Export, `64`-Socket Pool Sizing, Synchronous Batch Re-Warming & Cleanup (`ECOv003_CMR/authentication.py`, `stratified_dataset_builder.py`):**
   - Mounted `HTTPAdapter(pool_connections=64, pool_maxsize=64)` in `setup_earthdata_session()` to eliminate `urllib3` pool exhaustion warnings under 32-thread concurrency.
   - Converts `configure_gdal_earthdata_env()` into a `@contextmanager` that serializes pre-warmed `session.cookies` into Netscape format (`http.cookiejar.MozillaCookieJar`) for GDAL `libcurl` and deletes temporary `earthdata_gdal_*.cookies` files in `finally`.
   - Partitions pending granules into synchronous `batch_size` windows (default `250`) to refresh cookies cleanly between batches.
8. **Constant-RAM Streaming Parquet Diagnostics (`ECOv003_CMR/point_sampling.py`, `stratified_dataset_builder.py`):**
   - Extends `summarize_point_samples()` to accept Parquet file paths and compute per-layer valid/missing counts directly from `pyarrow.parquet.ParquetFile` row-group statistics (falling back to streaming `iter_batches()` when stats are absent).
9. **Adaptive Per-Granule Quota Refill & Cropland Dispersion Parity (`ECOv003_CMR/stratified_dataset_builder.py`, `stratified_sampling.py`):**
   - Adds a bounded adaptive refill loop (`max_refill_attempts = 2`) in `_process_granule()` with coordinate deduplication (`seen_coords`) so multi-product `NaN` dropouts do not cause silent sample shortfalls.
   - Routes user-supplied `cropland_mask` sampling in `sample_granule_coordinates()` through `_draw_dispersed_indices()` so `"stratified_grid"` dispersion applies equally to agricultural and natural land pools.
10. **Granule-Grouped `/vsicurl/` Site Queries, True MGRS Containment & Companion Scale Runners (`ECOv003_CMR/point_sampling.py`, `one_million_dataset.py`, `one_hundred_dataset.py`):**
    - Refactors `sample_points_over_date_range()` and `sample_points_from_geodataframe()` onto `_build_granule_sampling_batches()` and `sample_points_from_granule()` (`/vsicurl/`), joining daily `L2T_STARS` priors by `(tile, YYYYMMDD)`.
    - Updates `find_sentinel2_tile()` to use `sentinel_tiles.tiles(Point(lon, lat))` with `sentinel_tiles.land(t)` filtering (`land_only=True`, `return_all=False`).
    - Provides paired root CLI runners writing to git-ignored `./experimental_data/`: `one_million_dataset.py` (`./experimental_data/one_million_dataset`, `2025-10-31` to `2026-10-31`, `1,000,000` target samples, `--max-workers 12`, `--max-concurrent-streams 48`) and `one_hundred_dataset.py` (`./experimental_data/one_hundred_dataset`, 5-tile pilot including humid-tropical `20LLQ`, validated with `--dry-run` and live extraction producing `136/136` valid rows at `13.13 samples/s`).

---

## 5. Technical Challenges Encountered & How They Were Overcome

During live integration, global 1-year discovery runs, and unit testing across `v1.3.0` and `v1.3.1`, eleven concrete technical challenges surfaced and were resolved:

1. **Redundant Spatial CMR Sweeps Across Nighttime & Non-ET Overpasses:**
   - *Challenge:* Running blind spatial bounding-box searches across all four products (`L3T_JET`, `L2T_LSTE`, `L3T_ETAUX`, `L2T_STARS`) downloaded ~80–85% irrelevant metadata (all nighttime `L2T_LSTE`/`L3T_ETAUX` scenes, failed-ET overpasses, and 365 daily `L2T_STARS` tiles/year) that were subsequently discarded during the inner join with `L3T_JET`, while large $30^\circ \times 30^\circ \times 92\text{-day}$ boxes hit deep `CMR-Search-After` pagination cursors.
   - *Resolution:* Replaced blind spatial sweeps with ET-first global temporal catalog enumeration (`search_granule_catalog_csv()`) and deferred pattern-batch URL resolution (`resolve_granule_asset_urls()` via `readable_granule_name[]`) strictly for selected granules.
2. **CMR Leaving `CloudCover` Null Across All Collection 3 Products (`L3T_JET` & `L2T_LSTE`):**
   - *Challenge:* Probing CMR `CMR-Hits` and `granules.csv` across the 1-year window (`2025-10-31` to `2026-10-31`) revealed **348,477** global `L3T_JET` scenes, but passing `cloud_cover=0,20` to CMR returned **0 hits** for **both** `L3T_JET` and `L2T_LSTE`—confirming that NASA CMR leaves `CloudCover` null on all Collection 3 granules and excludes null-`CloudCover` granules whenever a numeric `cloud_cover` query filter is sent. Meanwhile, actual scene cloud fraction (`QAPercentCloudCover`) is stored inside each granule's ~3 KB `.json` sidecar (`fetch_granule_metadata()`).
   - *Resolution:* Removed `params["cloud_cover"]` from CMR query URLs in `search_granule_catalog_csv()` / `search_granules_by_name_patterns()`, and implemented concurrent `.json` sidecar inspection (`filter_granules_by_sidecar_cloud_cover()`) via `fetch_granule_metadata()` when `max_cloud_cover` filtering is requested.
3. **`granules.umm_json` Payload Overhead vs. `granules.csv` + 5-Day Parallel Windows:**
   - *Challenge:* Even without `links`, `granules.umm_json` transmits full G-Ring spatial polygons and ~20 `RelatedUrls` checksum blocks per granule (~6–10 MB per 2,000-row page), and 31-day monthly chunks require 15–35 sequential `CMR-Search-After` round-trips (~54s/chunk).
   - *Resolution:* Switched global catalog enumeration to CMR's flat **`granules.csv`** endpoint (`https://cmr.earthdata.nasa.gov/search/granules.csv`, ~35 KB per 2,000-row page—**~97% smaller**) across **5-day parallel temporal windows** (`chunk_days=5`, `max_workers=6` with jittered exponential retry backoff), enumerating all **348,477** global `L3T_JET` scenes in **2m 01s–2m 09s**.
4. **HTTP `414 Request-URI Too Large` on `GET` Wildcard Pattern Batches:**
   - *Challenge:* Sending 150 `readable_granule_name[]` wildcard parameters in a `GET` query string to `cmr.earthdata.nasa.gov/search/granules.json` generated a ~12 KB URL, triggering `414 Client Error: Request-URI Too Large`.
   - *Resolution:* Updated `_request_with_backoff()` and `search_granules_by_name_patterns()` to send `application/x-www-form-urlencoded` HTTP `POST` requests (`sess.post(url, data=params, headers=headers)`), resolving 14 batches (2,100 patterns) in **4–5 seconds**.
5. **`urllib3` Default `pool_maxsize=10` Connection Discard Warnings Under 32-Thread Concurrency:**
   - *Challenge:* `requests.Session` defaults its `HTTPAdapter` `pool_maxsize` to `10`, emitting `Connection pool is full, discarding connection` warnings when 32 worker threads concurrently fetch `.json` sidecars or COGs from `data.lpdaac.earthdatacloud.nasa.gov` and `d1nklfio7vscoe.cloudfront.net`.
   - *Resolution:* Mounted `HTTPAdapter(pool_connections=64, pool_maxsize=64)` in `setup_earthdata_session()` so all concurrent worker sockets remain pooled and reused cleanly (`52.48 json/s` with zero warnings).
6. **Unbounded Socket Reads Freezing Overnight CMR Discovery (`requests.get` without `timeout`):**
   - *Challenge:* Omitting a `timeout` parameter on `requests.get()` inside `ECOSTRESS_CMR_search_links.py` allowed worker threads to block indefinitely on `socket.recv()` when a paginated CMR connection dropped mid-stream.
   - *Resolution:* Added explicit `(15.0, 90.0)` second `(connect, read)` socket timeouts, per-thread unauthenticated `requests.Session` connection pooling, and jittered exponential retry backoff on `Timeout` / `ConnectionError`.
7. **NASA CMR Rejecting Earthdata URS Basic Auth Headers (`401 Unauthorized`):**
   - *Challenge:* Threading the authenticated `requests.Session` (configured with `session.auth = (username, password)` for `urs.earthdata.nasa.gov`) into `ECOSTRESS_CMR_search_links()` caused `cmr.earthdata.nasa.gov/search/granules.json` to return `401 Client Error: Unauthorized`, because CMR search endpoints reject URS Basic Auth credentials.
   - *Resolution:* Updated `_get_cmr_session()` / `_request_with_backoff()` in `ECOSTRESS_CMR_search_links.py` to never attach URS Basic Auth credentials to public `cmr.earthdata.nasa.gov` search requests.
8. **`sentinel_tiles.grid(tile)` Returning `RasterGrid` Instead of a Shapely Polygon:**
   - *Challenge:* `sentinel_tiles.grid(tile)` returns a `rasters.RasterGrid` object (which lacks `.bounds` and `.intersects()`), causing `list_ecostress_land_tiles()` to spend 239.5s returning `0` tiles and causing tile-bounds CMR queries to fall back to single centroid points.
   - *Resolution:* Vectorized `list_ecostress_land_tiles()` directly over `sentinel_tiles.sentinel_polygons` (`14,749` land tiles in `0.62s`) and switched bounding-box resolution to `sentinel_tiles.footprint(tile).bounds`.
9. **Open-Ocean MGRS Tile False Positives in `find_sentinel2_tile()`:**
   - *Challenge:* `sentinel_tiles.tiles(Point(-140.0, 0.0))` returned `'07MFV'` because the global MGRS polygon index tiles both land and open ocean.
   - *Resolution:* Added `land_only: bool = True` to `find_sentinel2_tile()` in `point_sampling.py`, filtering `sentinel_tiles.tiles(point)` through `sentinel_tiles.land(t)` so open-ocean coordinates cleanly return `None` (or `[]` when `return_all=True`).
10. **Silent Long-Running Discovery & Extraction Phases:**
    - *Challenge:* Multi-minute CMR discovery and multi-thousand-granule extraction phases lacked progress bars and milestone logs, making it hard to distinguish active pagination from network stalls.
    - *Resolution:* Added `tqdm` progress bars (`dynamic_ncols=True`) wrapped in `logging_redirect_tqdm()` to catalog enumeration, asset URL resolution, sidecar cloud filtering, and Stage `[5/6]` (`Extracting COGs`) alongside milestone logs.
11. **Netscape Cookie Serialization for GDAL `/vsicurl/`:**
    - *Challenge:* Pre-warming an Earthdata URL in `requests.Session` stores session tokens in an in-memory `RequestsCookieJar`, whereas GDAL's underlying `libcurl` requires a Netscape-formatted cookie file on disk (`GDAL_HTTP_COOKIEFILE`) to avoid per-thread OAuth redirect loops.
    - *Resolution:* Implemented `_export_session_cookies_to_netscape()` using `http.cookiejar.MozillaCookieJar(cookie_file).save(...)` inside `configure_gdal_earthdata_env()` and removed the temporary cookie file in a `finally` block upon context exit.

---

## 6. Quantified Performance & Global Archive Census (`v1.2.0` $\rightarrow$ `v1.3.1`)

### 6.1 Extraction & Discovery Benchmarks

Live benchmarks were executed via `make test-sampler` (`examples/stratified_sampling_demo.py`, single tile `11SLT`, 2 granules), `python one_hundred_dataset.py` (multi-region 5-tile pilot across `11SLT`, `11SPS`, `52NHN`, `53NMH`, and humid-tropical `20LLQ`, June 1–30, 2026), and `python count_L3T_JET_scenes_by_cloud_percent.py` (`2025-10-31` to `2026-10-31`):

| Benchmark Metric | `v1.2.0` Baseline (Sequential Layers) | `v1.2.0` Optimized (Concurrent Layers) | `v1.3.0` Single-Tile (`11SLT`, 2 granules) | `v1.3.1` Multi-Region Scale Example (`one_hundred_dataset.py`) | Total Improvement (`v1.2.0` Base $\rightarrow$ `v1.3.1`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Global Land Tile Discovery** | `239.53s` (`0` tiles) | `239.53s` | **`0.62s` (`14,749` tiles)** | **`0.62s` (`14,749` tiles)** | **$386\times$ faster** (`-99.7%`) |
| **Global 1-Year `L3T_JET` Catalog Enumeration (`348,477` scenes)** | N/A (per-tile spatial) | N/A | `~15m` (`umm_json` 31d) | **`121s–129s` (`granules.csv` 5d)** | **$7.0\times$ faster** (`-85.7%`) |
| **Cached Catalog Reload (`candidate_granules.parquet`)** | N/A | N/A | `0.08s` | **`0.06s`** (zero CMR calls) | **Instant offline restart** |
| **Total Wall Time** | `65.78s` (2 granules) | `19.77s` (2 granules) | **`18.97s`** (2 granules) | **`14.11s`–`33.30s`** (102–136 samples) | **Up to $4.66\times$ faster** (`-78.5%`) |
| **Mean Per-Granule Latency** | `56.71s / granule` | `13.00s / granule` | **`9.76s / granule`** | **`8.72s–9.63s / granule`** | **$5.89\times$–$6.50\times$ faster** |
| **Extraction Throughput** | `0.44 samples/s` | `1.96 samples/s` | **`2.36 samples/s`** ($K=13$) | **`7.02–13.13 samples/s`** ($K=17$, 4 workers) | **Up to $29.8\times$ faster** |
| **Amortized Global 1M Estimate ($4{,}000$ granules, $K=250$, 16 workers)** | `3.98 hours` | `56.77 minutes` | **`45.44 minutes`** | **`40.07–40.15 minutes`** | **$5.96\times$ faster** (`-83.2%`) |
| **Layer Completeness (16 layers)** | `100.0%` (`26/26`) | `100.0%` (`26/26`) | **`100.0%` (`26/26`)** | **`100.0%` (`136/136`)** | **Zero data loss** |
| **Offline Unit Test Suite** | `52 passed` | `52 passed` | **`57 passed`** (`3.02s`) | **`59 passed`** (`3.03s`) | **`+7` new regression tests** |

### 6.2 Empirical 1-Year Global `L3T_JET` Cloud-Cover Census (`2025-10-31` to `2026-10-31`)

Measured via `count_L3T_JET_scenes_by_cloud_percent.py` (`granules.csv` full enumeration + seasonally stratified sample $n=2{,}927$ `ProductMetadata.QAPercentCloudCover` sidecars with `64`-socket pool sizing, completed in `190.96s` at `52.48 json/s`):

| Cloud Cover Threshold (`QAPercentCloudCover`) | Estimated Global Scenes | 95% Confidence Interval | Share of Global `L3T_JET` |
| :--- | :--- | :--- | :--- |
| **All `L3T_JET` scenes** | **348,477** | Exact | **100.0%** |
| **`<= 20.0%` cloud cover** | **189,775** | $\pm 6{,}287$ | **54.5%** |
| **`<= 10.0%` cloud cover** | **144,415** | $\pm 6{,}219$ | **41.4%** |
| **`<= 0.0%` cloud cover** | **20,835** | $\pm 2{,}993$ | **6.0%** |

---

## 7. Completed `v1.3.0` & `v1.3.1` Checklists

### Completed in `v1.3.0`
- [x] **Vectorized Global MGRS Land-Tile Catalog (`ECOv003_CMR/tile_catalog.py`):** Discovered all 14,749 ECOSTRESS-covered land MGRS tiles in 0.62s via `sentinel_tiles.sentinel_polygons`.
- [x] **Persistent Candidate Catalog Caching (`ECOv003_CMR/stratified_dataset_builder.py`):** Added SHA-256 cache-keyed `candidate_granules.parquet` persistence with `catalog_path` and `refresh_catalog`.
- [x] **Bounded Stream Concurrency, Live Extraction Telemetry & Deterministic Retries (`stratified_dataset_builder.py`, `point_sampling.py`, `authentication.py`):** Added `max_concurrent_streams` semaphore, `layer_workers`, `tqdm` extraction progress/rate bar, GDAL HTTP retry options, and jittered fallback backoff.
- [x] **Netscape Cookie Export & Synchronous Batch Re-Warming (`authentication.py`, `stratified_dataset_builder.py`):** Converted `configure_gdal_earthdata_env()` to a `@contextmanager` with `MozillaCookieJar` export, `batch_size` windows, and temp cookie cleanup.
- [x] **Constant-RAM Streaming Parquet Diagnostics (`point_sampling.py`, `stratified_dataset_builder.py`):** Implemented $O(1)$-RAM `pyarrow.parquet` column metadata/batch summarization.
- [x] **Adaptive Quota Refill & Cropland Dispersion Parity (`stratified_dataset_builder.py`, `stratified_sampling.py`):** Added bounded quota-refill retries with coordinate deduplication and unified `"stratified_grid"` dispersion for `cropland_mask`.
- [x] **Granule-Grouped `/vsicurl/` Site Queries, Land-Tile Lookup & Paired `experimental_data/` Runners (`point_sampling.py`, `one_million_dataset.py`, `one_hundred_dataset.py`):** Unified `sample_points_over_date_range()` and `sample_points_from_geodataframe()` onto `sample_points_from_granule()`, updated `find_sentinel2_tile()` to use `sentinel_tiles.tiles()` + `sentinel_tiles.land()`, and validated `one_hundred_dataset.py` into `./experimental_data/`.
- [x] **Code Hygiene, Tests & Documentation:** Consolidated `product_name_from_filename()`, added `DeprecationWarning` on `aquisition_date`, added `version.py` fallback, bumped `pyproject.toml` to `1.3.0`, and updated `README.md`.

### Completed in `v1.3.1` (CMR `granules.csv`, `POST` Batches, Sidecar `QAPercentCloudCover`, `64`-Socket Pooling & A Priori Sampling Design)
- [x] **CMR `granules.csv` 5-Day Parallel Catalog Enumeration (`ECOv003_CMR/constants.py`, `ECOSTRESS_CMR_search_links.py`):** Added `CMR_CSV_SEARCH_URL` and `search_granule_catalog_csv()` using `granules.csv` across 5-day parallel windows (`chunk_days=5`, `max_workers=6` with jittered retry backoff), cutting payload transfer by ~97% and enumerating all **348,477** global `L3T_JET` scenes in **~2m 01s**.
- [x] **HTTP `POST` Wildcard Pattern Batching (`ECOSTRESS_CMR_search_links.py`):** Updated `search_granules_by_name_patterns()` to send `application/x-www-form-urlencoded` `POST` requests to `granules.json`, eliminating `414 Request-URI Too Large` errors on 150-pattern batches.
- [x] **Sidecar `QAPercentCloudCover` Filtering (`stratified_sampling.py`, `stratified_dataset_builder.py`):** Removed `cloud_cover` query params from CMR requests, implemented concurrent `.json` sidecar filtering (`filter_granules_by_sidecar_cloud_cover()` via `fetch_granule_metadata()`), and added automatic tile backfill in `build_stratified_dataset()`.
- [x] **Connection Pool Sizing (`ECOv003_CMR/authentication.py`):** Mounted `HTTPAdapter(pool_connections=64, pool_maxsize=64)` in `setup_earthdata_session()`, eliminating `urllib3` `Connection pool is full` warnings under 32-thread concurrency.
- [x] **Stratified Global Cloud-Cover Census (`count_L3T_JET_scenes_by_cloud_percent.py`):** Verified global `L3T_JET` cloud-cover distribution (**54.5%** $\le 20\%$, **41.4%** $\le 10\%$, **6.0%** $\le 0\%$) in **190.96s**.
- [x] **A Priori Sampling Design Planner (`ECOv003_CMR/stratified_sampling.py`, `__init__.py`):** Implemented `plan_stratified_sampling()` to forecast eligible MGRS tile counts, `tropical`/`temperate`/`boreal` biome representation, $N_{\text{cap}}$, selected granules $G$, per-granule pixel quota $K$, and estimated wall time in <1s, plus reusable `estimate_cloud_cover_distribution()`.
- [x] **Rejection-Rate-Aware Backfill Sizing & Dry-Run Mode (`ECOv003_CMR/stratified_dataset_builder.py`):** Added `_backfill_multiplier_for_cloud_cover()` (`4×` for $\ge 20\%$, `5×` for $10\%\text{–}20\%$, `12×` for $< 10\%$) and `dry_run: bool = False` in `build_stratified_dataset()`.
- [x] **Scale Runner Enhancements (`one_hundred_dataset.py`, `one_million_dataset.py`, `count_L3T_JET_scenes_by_cloud_percent.py`):** Added `--dry-run`, humid-tropical tile `20LLQ` in the 100-observation pilot, auto-reuse of `./experimental_data/one_million_dataset/candidate_granules.parquet`, and updated 1M defaults (`--max-workers 12`, `--max-concurrent-streams 48`), verified with `59 passed` offline unit tests and live `136/136` extraction.
- [ ] **Version Metadata Bump & Pre-Flight Global Dry Run:** Bump `pyproject.toml` and `ECOv003_CMR/version.py` to `1.3.1` and run `python one_million_dataset.py --dry-run` to inspect global biome counts prior to launching the 1M extraction.

---

## 8. Roadmap for `v1.4.0`: On-Demand Land-Cover & Cropland Stratification

To support global agricultural vs. non-managed ecosystem stratification without requiring users to manually download, mosaic, and reproject external land-cover rasters for thousands of Sentinel-2 tiles, `v1.4.0` introduces built-in land-cover stratification:

### 8.1 On-Demand Land-Cover Provider (`ECOv003_CMR/land_cover.py`)
- Fetch and warp external land-cover classifications (e.g., ESA WorldCover 10m COGs or MODIS MCD12Q1) on demand to match a target Sentinel-2 MGRS tile's grid and affine transform.
- Cache aligned tile-level binary cropland masks in `~/.cache/ECOv003_CMR/land_cover/` so each MGRS tile is downloaded and reprojected at most once across all ECOSTRESS overpasses.

### 8.2 Global & Batch-Level Cropland Quota Tracking (`ECOv003_CMR/stratified_dataset_builder.py` & `stratified_sampling.py`)
- Expose `cropland_fraction_target` and `land_cover_source` directly on `build_stratified_dataset()`.
- Track realized cropland vs. non-managed sample counts across execution batches so tiles with limited or zero cropland (e.g., boreal forest, desert, or alpine tiles) do not cause quota failures, and downstream agricultural tiles dynamically compensate to achieve the global target proportion.