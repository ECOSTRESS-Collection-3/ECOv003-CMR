# `ECOv003-CMR` Consolidated Development Plan: Full Release History (`v1.0.0`–`v1.3.1`) and `v1.4.0` Roadmap

**Prepared:** 2026-11-23  
**Repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`  
**Current Released Baseline:** `v1.3.1`  
**Target Next Release:** `v1.4.0` (Download Resilience, Multi-Build CMR Resolution & `ECOv003-granules` Parity)

---

## 1. Executive Summary

`ECOv003-CMR` provides programmatic access to NASA's Common Metadata Repository (CMR) and LP DAAC Earthdata Cloud (`LPCLOUD`) archives for ECOSTRESS Collection 3 (`.003`). Originating as a migration of Collection 2 CMR search and download tooling into a standalone Collection 3 package (`v1.0.x`–`v1.1.1`), the repository evolved across `v1.2.0`, `v1.3.0`, and `v1.3.1` into a globally scalable, spatially and seasonally stratified point-sampling engine (`build_stratified_dataset()`) designed to generate a **~1,000,000-sample non-tower ECOSTRESS training dataset** across the full 1-year Collection 3 record (`2025-10-31` to `2026-10-31`) for transport-map uncertainty quantification (UQ), spatial downscaling of relative humidity (`RH`), and temporal upscaling of evapotranspiration (`ET`).

Across `v1.2.0` through `v1.3.1`, live benchmarks against LP DAAC Earthdata Cloud granules reduced mean per-granule extraction latency from **56.71s** (`v1.2.0` baseline) to **8.72s–9.76s** (`v1.3.0`–`v1.3.1`)—an overall **$5.8\times$–$6.5\times$ speedup**—bringing the amortized global 1,000,000-sample runtime estimate down from **3.98 hours** to **~40.1 minutes** on 16 workers with **100.0% layer completeness**. The upcoming `v1.4.0` release focuses on hardening single-granule downloads against LP DAAC socket read timeouts and multi-build CMR listings (`2026-11-23` issue report), migrating local compatibility shims upstream into `ECOv003-granules`, and executing the pre-flight global 1M dry run.

---

## 2. Scientific Motivation & Dataset Design Milestones

The stratified point-sampling architecture in `ECOv003-CMR` was established across Biosphere / UQ working group milestones to overcome the small sample size and arbitrary input UQ assumptions of tower-only calibration/validation datasets:

| Date | Forum | Key Architectural Decision |
| :--- | :--- | :--- |
| **Apr 14, 2026** | UQ Meeting | Identified tower cal/val dataset size constraints; proposed sampling realistic input UQ values across full life-of-mission ECOSTRESS acquisitions. |
| **Sep 16, 2026** | Maggie Meeting & Slack | Set target of **~1,000,000 non-tower point samples**; mandated uniform Sentinel-2/UTM tile coverage, seasonal balance, and dynamic per-acquisition pixel randomization ("rolling the dice" per scene rather than fixed coordinates). |
| **Oct 1, 2026** | UQ Meeting | Formalized multi-stage stratified sampling pipeline and per-tile granule capping ($N_{\text{cap}} = \min_{t} N_t$) to enforce equal spatial and biome weighting across Earth. |

---

## 3. Complete Version-by-Version Development History (`v1.0.0` – `v1.3.1`)

### 3.1 `v1.0.x` – `v1.1.1`: Collection 3 Migration, Authenticated Downloads & Site Point Sampling

* **Collection 3 Product Catalog & LPCLOUD Concept IDs (`ECOv003_CMR/constants.py`, `concept_ID_from_DOI.py`):**
  * Queried the NASA CMR Collections API (`https://cmr.earthdata.nasa.gov/search/collections.json?doi=<DOI>`) for all seven active Collection 3 (`.003`) products and codified their LPCLOUD Concept IDs (`L1CT_RAD`: `C4142244484-LPCLOUD`, `L2T_LSTE`: `C3998139651-LPCLOUD`, `L2T_STARS`: `C3998139658-LPCLOUD`, `L3T_ETAUX`: `C4057520953-LPCLOUD`, `L3T_JET`: `C4057232489-LPCLOUD`, `L4T_ESI`: `C4057232495-LPCLOUD`, `L4T_WUE`: `C4057232498-LPCLOUD`).
  * Deprecated retired Collection 2 products (`L3T_MET`, `L3T_SM`, `L3T_SEB`, consolidated into `L3T_ETAUX`) and removed Collection 2 layers (`EVI`, `SAVI`) with explicit `ValueError` validation.
  * Added bulk Concept ID refresh helper `lookup_collection_3_concept_IDs()` alongside `COLLECTION_3_DOIS`.
* **Collection 3 Filename & Granule ID Parsing (`granule_ID.py`, `granule_ID_from_filename.py`, `product_name_from_filename.py`, `variable_from_filename.py`, `interpret_ECOSTRESS_URLs.py`):**
  * Supported both 8-segment standard Collection 3 filenames (`ECOv003_<PRODUCT>_<ORBIT>_<SCENE>_<TILE>_<YYYYMMDDTHHMMSS>_<BUILD>`) and 6-segment daily `L2T_STARS` filenames (`ECOv003_L2T_STARS_<TILE>_<YYYYMMDD>_<BUILD>`) while maintaining backward compatibility with Collection 2 (`ECOv002_*`) filenames, underscore/hyphen variable suffixes (`view_zenith`, `Emis4_err`, `NDVI-UQ`), and `.jpeg.aux.xml` metadata sidecars.
* **Paginated CMR Search (`ECOSTRESS_CMR_search_links.py`, `ECOSTRESS_CMR_search.py`):**
  * Implemented `page_size=2000` queries with iterative `CMR-Search-After` pagination and duplicate-token loop protection.
* **Authenticated Earthdata Cloud Downloads & CLIs (`authentication.py`, `download_file.py`, `download_ECOSTRESS*.py`):**
  * Implemented `setup_earthdata_session()` (priority: explicit args $\rightarrow$ `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` $\rightarrow$ `~/.netrc`), atomic `.download` streaming with `tqdm.auto.tqdm` progress bars, per-granule acquisition date extraction (`_acquisition_date_from_granule_id()`), `DeprecationWarning` on legacy `aquisition_date`, and `ECOv003-search` / `ECOv003-download` CLIs.
* **`ECOv003-granules` Compatibility Adapter (`granule_compatibility.py`):**
  * Built `_Collection3GranuleMixin` subclasses and `open_ECOSTRESS_granule()` to handle directory-backed downloads (in addition to `.zip`), `L1CT_RAD`, `L3T_ETAUX`, and `L2T_STARS` metadata parsing, raising `FileNotFoundError` / `ValueError` on missing or unrecognized granules.
* **In-Memory Point Sampling & Offline CI (`point_sampling.py`, `tests/`):**
  * Implemented `sample_point_from_url()`, `sample_points_over_date_range()`, and `sample_points_from_geodataframe()` with automatic `EPSG:4326` reprojection, Kelvin-to-Celsius conversion (`ST_C = LST - 273.15`), and offline `pytest` coverage across Python 3.11–3.14.

---

### 3.2 `v1.2.0`: Stratified Sampling Engine & Concurrent `/vsicurl/` Extraction

* **Multi-Stage Stratified Pipeline (`ECOv003_CMR/stratified_sampling.py`, `stratified_dataset_builder.py`):**
  * Implemented `select_stratified_granules()` enforcing per-tile capping at $N_{\text{cap}} = \min_{t \in \text{EligibleTiles}} N_t$ (with `min_granules_floor`) and balanced quarterly selection (`seasonal_balance=True`).
  * Implemented `compute_per_granule_quota()` ($K = \lceil N_{\text{target}} / G \rceil$ with configurable oversampling) and `sample_granule_coordinates()` supporting `"uniform"` and `"stratified_grid"` intra-granule dispersion.
* **Vectorized `/vsicurl/` Granule Batch Sampling (`point_sampling.py`):**
  * Implemented `sample_points_from_granule()` to open each variable GeoTIFF once per granule across concurrent threads (`src.sample(coords, masked=True)`) over authenticated `/vsicurl/` HTTP byte-range requests with `MemoryFile` fallback.
* **Expanded `LAYER_MAPPING` (`point_sampling.py`):**
  * Expanded layer support to 45+ mappings across `L2T_LSTE` (`ST_C`, `LST`, `LST_err`, `QC`, `EmisWB`, `Emis1`–`Emis5`, `Emis1_err`–`Emis5_err`, `view_zenith`, `height`), `L2T_STARS` (`NDVI`, `NDVI-UQ`, `albedo`, `albedo-UQ`), `L3T_ETAUX` (`Ta_C`, `Ta`, `RH`, `SM`, `Rg`, `Rn`, `cloud`, `water`), `L3T_JET` (`PTJPLSMinst`, `PTJPLSMdaily`, `PTJPLSMcanopy`, `PTJPLSMsoil`, `PTJPLSMinterception`, `ETdaily`, `ETuncertainty`, `STICJPL*`, `BESSJPLdaily`, `PMJPLdaily`), `L4T_ESI` (`ESI`), and `L4T_WUE` (`WUE`).
* **Checkpointed Parquet Streaming (`stratified_dataset_builder.py`):**
  * Added incremental `dataset_part_XXXX.parquet` / `.csv` writes and `completed_granules.txt` manifest checkpointing for fault-tolerant restarts.

---

### 3.3 `v1.3.0` – `v1.3.1`: Global CMR Scaling, Sidecar Cloud Filtering & Production Hardening

* **Vectorized Global MGRS Land-Tile Discovery (`tile_catalog.py`):**
  * Replaced a 239.5s nested MGRS loop with vectorized `sentinel_tiles.sentinel_polygons` filtering (`Land == True` within $\pm 54^\circ$ latitude), enumerating all **14,749** ECOSTRESS land tiles in **0.62s** ($386\times$ speedup).
  * Updated `find_sentinel2_tile()` in `point_sampling.py` to use `sentinel_tiles.tiles(Point(lon, lat))` with `sentinel_tiles.land(t)` filtering (`land_only=True`, `return_all=False`).
* **CMR `granules.csv` Enumeration & HTTP `POST` Wildcard Resolution (`constants.py`, `ECOSTRESS_CMR_search_links.py`, `stratified_sampling.py`):**
  * Added `search_granule_catalog_csv()` using NASA CMR's flat `granules.csv` endpoint (~35 KB/page vs. ~8 MB/page in UMM-JSON, **~97% smaller**) across 5-day parallel temporal windows (`chunk_days=5`, `max_workers=6` with `(15s, 90s)` socket timeouts and jittered backoff), enumerating all **348,477** global `L3T_JET` scenes in **~2m 01s** with zero spatial-overlap duplicates.
  * Updated `search_granules_by_name_patterns()` to send `application/x-www-form-urlencoded` HTTP `POST` requests to `granules.json`, eliminating `414 Request-URI Too Large` errors on 150-pattern batches and never forwarding URS Basic Auth headers to public `cmr.earthdata.nasa.gov` search endpoints.
  * Deferred `.tif`/`.json` URL resolution in `build_stratified_dataset()` until after `select_stratified_granules()` caps each tile to $N_{\text{cap}}$.
* **Sidecar `QAPercentCloudCover` Filtering & Global Cloud Census (`stratified_sampling.py`, `interpret_ECOSTRESS_URLs.py`, `count_L3T_JET_scenes_by_cloud_percent.py`):**
  * Removed `cloud_cover` query parameters from CMR requests after confirming CMR leaves `CloudCover` null on all Collection 3 granules.
  * Implemented concurrent `.json` sidecar inspection (`fetch_granule_metadata()`, `filter_granules_by_sidecar_cloud_cover()`, `estimate_cloud_cover_distribution()`) reading `ProductMetadata.QAPercentCloudCover`, establishing global `L3T_JET` pass rates (**54.5%** $\le 20\%$, **41.4%** $\le 10\%$, **6.0%** $\le 0\%$) and adding empirical rejection-aware backfill (`_backfill_multiplier_for_cloud_cover()`).
* **A Priori Sampling Design Planner & Dry-Run Mode (`stratified_sampling.py`, `stratified_dataset_builder.py`):**
  * Implemented `plan_stratified_sampling()` to forecast eligible tiles, `tropical` / `temperate` / `boreal` biome counts, $N_{\text{cap}}$, selected granules $G$, per-granule quota $K$, and estimated wall time in <1s, plus `dry_run=True` on `build_stratified_dataset()`, `one_hundred_dataset.py`, and `one_million_dataset.py`.
* **Catalog Caching, Bounded Streams, Netscape Cookies & $O(1)$-RAM Diagnostics (`authentication.py`, `point_sampling.py`, `stratified_dataset_builder.py`):**
  * Added SHA-256 validated `candidate_granules.parquet` caching (`0.06s` offline reload), `HTTPAdapter(pool_connections=64, pool_maxsize=64)`, process-wide `threading.Semaphore(max_concurrent_streams)`, Netscape URS cookie export (`MozillaCookieJar`) with synchronous `batch_size` re-warming and temp-file cleanup, adaptive quota refill retries (`max_refill_attempts=2`), unified granule-grouped `/vsicurl/` site queries, and constant-RAM `pyarrow.parquet` statistics in `summarize_point_samples()`.

---

## 4. Architecture & Performance Progression (`v1.1.1` $\rightarrow$ `v1.3.1`)

| Metric / Capability | `v1.1.1` Baseline | `v1.2.0` Concurrent | `v1.3.0` Single-Tile (`11SLT`) | `v1.3.1` Multi-Region (`one_hundred_dataset.py`) |
| :--- | :--- | :--- | :--- | :--- |
| **Global Land Tile Discovery** | Manual tile input | `239.53s` (`0` tiles) | **`0.62s` (`14,749` tiles)** | **`0.62s` (`14,749` tiles)** |
| **Global 1-Yr `L3T_JET` Catalog (`348,477` scenes)** | N/A | N/A | `~15m` (`umm_json` 31d) | **`121s–129s` (`granules.csv` 5d)** |
| **Cached Catalog Reload** | N/A | N/A | `0.08s` | **`0.06s`** (offline) |
| **Mean Per-Granule Latency** | N/A (`56.71s` seq) | `13.00s / granule` | **`9.76s / granule`** | **`8.72s–9.63s / granule`** |
| **Amortized Global 1M Estimate ($4{,}000$ granules, $K=250$, 16 workers)** | `3.98 hours` (seq) | `56.77 minutes` | **`45.44 minutes`** | **`40.07–40.15 minutes`** |
| **Layer Completeness (16 layers)** | N/A | `100.0%` (`26/26`) | **`100.0%` (`26/26`)** | **`100.0%` (`136/136`)** |
| **Offline Unit Test Suite** | Baseline suite | `52 passed` | **`57 passed`** | **`59 passed`** (`3.03s`) |

---

## 5. Pending Development Plan for `v1.4.0`

With land-cover classification omitted, the remaining roadmap for `v1.4.0` consists of three focused workstreams:

### Workstream 1: Single-Granule Download Resilience & Multi-Build Handling

Addresses the three issues identified during end-to-end cross-product testing of `download_ECOSTRESS_granule()` (`notes/2026-11-23 ECOv003-CMR timeout issue.md`):

* **Mid-Stream Socket Timeouts & Retry Backoff in `ECOv003_CMR/download_file.py`:**
  * Add `max_retries: int = 3`, `backoff_base: float = 2.0`, and `timeout: Tuple[float, float] = (15.0, 90.0)` `(connect, read)` to `download_file()`.
  * Remove any existing `.download` partial file unconditionally before each retry attempt and inside the exception handler (fixing truncated non-zero `.download` files remaining on disk when `TimeoutError: [Errno 60] Operation timed out` occurs mid-chunk).
  * Retry transient HTTP status codes (`429, 500, 502, 503, 504`) and `(requests.exceptions.RequestException, TimeoutError, OSError)` exceptions with jittered exponential backoff before raising `ECOSTRESSDownloadFailed`.
* **Latest-Build Selection on Multi-Build Listings in `ECOv003_CMR/download_ECOSTRESS_granule_files.py`:**
  * Update `get_granule_from_listing()` to group unique granule IDs by their base stem (`"_".join(gid.split("_")[:-1])`). When NASA CMR returns multiple build revisions (`_01`, `_02`, `_03`) for the same acquisition stem, select `sorted(granule_IDs)[-1]` (the latest build) and filter `CMR_file_listing_df` to rows matching that single `GranuleID`, raising `ValueError` only when multiple distinct acquisition stems are present.
* **Descriptive `FileNotFoundError` on Empty CMR Search Listings:**
  * Guard `get_granule_from_listing()` with `if listing.empty or "granule" not in listing.columns:` to raise a descriptive `FileNotFoundError("No matching ECOSTRESS granules found in CMR listing")` instead of an `AttributeError` on `listing.granule`.

### Workstream 2: Upstream `ECOv003-granules` Parity & Production 1M Pre-Flight

* **Upstream Migration of `ECOv003_CMR/granule_compatibility.py`:**
  * Migrate `L1CT_RAD` dispatch, `L3T_ETAUX` product handling, `L2T_STARS` product metadata parsing, and directory-backed `.tif` layer discovery upstream into `ECOSTRESS-Collection-3/ECOv003-granules`.
  * Bump the minimum `ECOv003-granules` dependency constraint in `pyproject.toml` and deprecate/remove the local `granule_compatibility.py` shim once upstream parity is verified.
* **Pre-Flight Global 1M Dry Run & Version Bump:**
  * Run `python one_million_dataset.py --dry-run` against the full 14,749-tile global catalog (`2025-10-31` to `2026-10-31`) to record final global biome counts (`tropical`, `temperate`, `boreal`), $N_{\text{cap}}$, and per-granule quota $K$ prior to launching the 1,000,000-sample extraction campaign.
  * Update `pyproject.toml` version metadata to `1.4.0` upon completion of Workstreams 1–3.

### Workstream 3: Verification & Test Coverage for `v1.4.0`

* **Download Resilience Unit Tests (`tests/test_download_ECOSTRESS_granule.py`):**
  * Verify `download_file()` recovers from a simulated mid-stream `TimeoutError` / `requests.exceptions.Timeout`, cleans up partial `.download` files, and succeeds on retry.
  * Verify `get_granule_from_listing()` selects the highest build revision (`_03`) when multiple builds (`_01`, `_02`, `_03`) of the same stem exist, downloads only that build's URLs, raises `ValueError` on distinct granule stems, and raises `FileNotFoundError` on empty listings.
* **Live Integration Tests (`tests/test_live_integration.py`):**
  * Expand `@pytest.mark.integration` coverage to verify authenticated multi-product `download_ECOSTRESS_granule()` and `sample_points_over_date_range()` execution against LP DAAC Earthdata Cloud.