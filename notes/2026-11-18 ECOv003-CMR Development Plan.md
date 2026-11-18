# ECOv003-CMR Exhaustive Development Plan: From Collection 3 Migration (`v1.1.1`) to Global 1M-Sample UQ Point-Query Pipeline (`v1.2.0`)

**Prepared:** 2026-11-18  
**Repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`  
**Current Version:** `v1.1.1`  
**Target Version:** `v1.2.0`  

---

## 1. Executive Summary

`ECOv003-CMR` provides programmatic access to NASA's Common Metadata Repository (CMR) and LP DAAC Earthdata Cloud (`LPCLOUD`) archives for ECOSTRESS Collection 3 (`.003`). Through `v1.1.1`, the package established complete Collection 3 product support, authenticated granule downloads, `ECOv003-granules` compatibility, CLI tooling (`ECOv003-search`, `ECOv003-download`), and site-centric Cloud-Optimized GeoTIFF (COG) point sampling.

To support the ROSES Biosphere proposal—specifically uncertainty quantification (UQ) via transport maps, spatial downscaling of relative humidity (`RH`), and temporal upscaling of evapotranspiration (`ET`)—`v1.2.0` extends `ECOv003-CMR` into a **global, granule-centric, stratified point-sampling engine**. The next target release will enable automated generation of a **~1,000,000-sample non-tower ECOSTRESS training dataset** spanning global land-intersecting Sentinel-2 MGRS tiles ($\pm 54^\circ$ latitude) across the mission record, backed by true `/vsicurl/` HTTP byte-range reads and fault-tolerant Parquet checkpointing.

---

## 2. How Current Version (`v1.1.1`) Was Achieved

The current architecture in `v1.1.1` was built across six foundational engineering milestones:

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
- Implemented `ECOSTRESS_CMR_search_links()` (`ECOv003_CMR/ECOSTRESS_CMR_search_links.py`) using `sentinel_tiles.grid(tile).centroid_latlon`, `page_size=2000`, and iterative `CMR-Search-After` pagination with duplicate-token loop protection.
- Implemented `GranuleID` (`granule_ID.py`), `granule_ID_from_filename.py`, `product_name_from_filename.py`, `variable_from_filename.py`, and `interpret_ECOSTRESS_URLs.py` to parse both 8-segment standard Collection 3 filenames (`ECOv003_<PRODUCT>_<ORBIT>_<SCENE>_<TILE>_<YYYYMMDDTHHMMSS>_<BUILD>`) and 6-segment daily `L2T_STARS` filenames (`ECOv003_L2T_STARS_<TILE>_<YYYYMMDD>_<BUILD>`), including multi-token variable names (`view_zenith`, `Emis4_err`, `NDVI-UQ`) and `.jpeg.aux.xml` sidecars.

### 2.3 Authenticated Earthdata Cloud Downloads & CLI Tooling
- Built `setup_earthdata_session()` (`ECOv003_CMR/authentication.py`) resolving credentials in priority order: explicit arguments $\rightarrow$ `EARTHDATA_USERNAME`/`EARTHDATA_PASSWORD` environment variables $\rightarrow$ `~/.netrc`.
- Updated `download_file()` (`ECOv003_CMR/download_file.py`) to propagate authenticated `requests.Session` objects across URS redirects, write atomically via `.download` temporary files, remove zero-byte files, and display `tqdm.auto.tqdm` progress bars.
- Updated `download_ECOSTRESS()` (`ECOv003_CMR/download_ECOSTRESS.py`) to extract true per-granule acquisition dates via `_acquisition_date_from_granule_id()` and standardized `ECOv003-search` / `ECOv003-download` CLI logging and exit codes.

### 2.4 `ECOv003-granules` Collection 3 Compatibility Adapter
- Created `ECOv003_CMR/granule_compatibility.py` (`_Collection3GranuleMixin` and `open_ECOSTRESS_granule()`) to support directory-backed downloads (in addition to `.zip` archives), `L1CT_RAD` dispatch, `L3T_ETAUX` handling, and `L2T_STARS` metadata parsing, validated by `download_ECOSTRESS_granule()`.

### 2.5 In-Memory COG Point Sampling & Temporal Joining
- Implemented `sample_point_from_url()`, `sample_points_over_date_range()`, and `sample_points_from_geodataframe()` (`ECOv003_CMR/point_sampling.py`) supporting:
  - Automatic CRS reprojection from any projected `GeoDataFrame`/`GeoSeries` to `EPSG:4326`.
  - 16 mapped layers in `LAYER_MAPPING` across `L2T_LSTE`, `L2T_STARS`, and `L3T_ETAUX` with automatic Kelvin-to-Celsius conversion (`ST_C = LST - 273.15`).
  - Parallel (`ThreadPoolExecutor`) and sequential (`max_workers=1`) execution parity and preservation of all non-geometry input metadata columns.

### 2.6 Offline CI Test Suite
- Established offline unit tests (`tests/test_cmr_search.py`, `tests/test_download_ECOSTRESS_granule.py`, `tests/test_granule_compatibility.py`, `tests/test_point_sampling.py`, `tests/test_import_dependencies.py`) running across Python 3.11–3.14 in `.github/workflows/ci.yml`.

---

## 3. Scientific & Architectural Requirements for `v1.2.0`

| Pipeline Stage | `v1.1.1` Current Behavior | `v1.2.0` Target Behavior |
| :--- | :--- | :--- |
| **Spatial Discovery** | Requires user-supplied `tile` IDs or point coordinates. | Enumerate all global land-intersecting Sentinel-2 MGRS tiles within ECOSTRESS orbital coverage ($\pm 54^\circ$ latitude). |
| **CMR Query Footprint** | Queries a single point at tile centroid (`lon,lat,lon,lat`), missing partial-tile diagonal swaths. | Query using the tile's full WGS84 bounding box (`geometry.bounds`) or regional spatial chunks and filter by exact `_<TILE>_` granule token. |
| **Clear-Sky Filtering** | Returns all matching CMR assets regardless of cloud cover or product completeness. | Filter for daytime clear-sky scenes where `L3T_JET`, `L2T_LSTE`, `L3T_ETAUX`, and same-date `L2T_STARS` all exist. |
| **Stratified Selection** | Samples fixed user coordinates across every overpass in a date window. | Tally clear-sky granules per tile, cap at $N_{\text{cap}} = \min_t N_t$ (subject to `min_granules_floor`), balance seasons, and allocate $K = \lceil N_{\text{target}} / G \rceil$ pixels per granule. |
| **Intra-Granule Sampling** | No dynamic intra-scene coordinate generation or land-cover balancing. | Independently randomize $K$ valid cloud-free land pixels per scene ("rolling the dice") with `"uniform"` or `"stratified_grid"` dispersion and cropland/natural land weighting. |
| **Cross-Product Join** | Indexes `L3T_*` granules by `YYYYMMDD`, overwriting multiple overpasses on the same day. | Join instantaneous products (`L2T_LSTE`, `L3T_ETAUX`, `L3T_JET`, `L4T_*`) by `(orbit, scene, tile, timestamp)` and daily `L2T_STARS` by `(tile, YYYYMMDD)`. |
| **COG Read Architecture** | Downloads full compressed `.tif` into `MemoryFile` per `(point, granule, variable)`. | Group all $K$ points per granule into a single `rasterio.open()` + `src.sample(proj_coords, masked=True)` call over authenticated `/vsicurl/`. |
| **Variable Coverage** | 16 layers across `L2T_LSTE`, `L2T_STARS`, and `L3T_ETAUX`. | Add verified `L3T_JET` ET & model ensemble outputs, `L2T_STARS` UQ priors (`NDVI-UQ`, `albedo-UQ`), `L2T_LSTE` spectral emissivities/angles, and `L4T_ESI`/`L4T_WUE`. |
| **Output & Checkpointing** | Returns in-memory `pandas.DataFrame` only after completion. | Stream partitioned Parquet/CSV batches to disk with a `completed_granules.txt` manifest and coverage diagnostics. |

---

## 4. Foreseeable Caveats, Conflicts & Mitigations

1. **GDAL `rasterio.Env` Thread-Safety Conflict:**
   - *Conflict:* Entering/exiting `rasterio.Env(...)` inside `ThreadPoolExecutor` worker threads mutates process-global GDAL configuration options and causes race conditions on `libcurl` cookie jars.
   - *Mitigation:* Configure a single process-wide `rasterio.Env` context in the main thread before spawning workers (or use path-scoped `/vsicurl?...` options) and pre-warm authentication cookies before multi-threaded reads.
2. **Bearer Token Leakage to AWS S3 Presigned Redirects:**
   - *Conflict:* LP DAAC Earthdata Cloud URLs redirect through `urs.earthdata.nasa.gov` onto AWS S3 presigned URLs. Sending an unconditional `Authorization: Bearer ...` header via `GDAL_HTTP_HEADERS` causes AWS S3 to return `400 Bad Request` (`Only one auth mechanism allowed`).
   - *Mitigation:* Use `.netrc` + cookie-jar authentication (`GDAL_HTTP_NETRC=YES`, `GDAL_HTTP_COOKIEFILE`, `GDAL_HTTP_COOKIEJAR`, `CPL_VSIL_CURL_USE_HEAD=NO`) rather than global `Authorization` headers, retaining `MemoryFile` as a fallback.
3. **CMR Tile Centroid Blind Spot:**
   - *Conflict:* `ECOSTRESS_CMR_search_links()` currently queries a zero-area point box at `sentinel_tiles.grid(tile).centroid_latlon`, silently dropping valid diagonal swaths that miss the exact tile center.
   - *Mitigation:* Query CMR using the tile's full WGS84 bounding box (`geometry.bounds`) and verify exact `_<TILE>_` granule ID matching.
4. **Same-Day Multi-Overpass Collisions:**
   - *Conflict:* `point_sampling.py` currently indexes `L3T_*` and `L4T_*` products by `date_str` (`YYYYMMDD`), overwriting earlier overpasses when a tile is imaged twice on the same UTC date.
   - *Mitigation:* Key instantaneous products by `(orbit, scene, tile, timestamp)` and key only `L2T_STARS` by `(tile, YYYYMMDD)`.
5. **Minimum Tile Capping Collapse ($N_{\text{cap}} = \min_t N_t$):**
   - *Conflict:* Persistently cloudy tropical tiles or tiny coastal/island tiles may have $0$–$2$ clear-sky granules, collapsing $N_{\text{cap}}$ globally and discarding >99% of the archive.
   - *Mitigation:* Enforce a configurable `min_granules_floor` threshold to exclude anomalously sparse tiles and stratify granule selection across calendar quarters/seasons.
6. **Verified Collection 3 `L3T_JET` Variable Names & Daytime Restriction:**
   - *Conflict:* Earlier notes listed placeholder partitioning names (`ETcanopy`, `ETsoil`, `ETinterception`). Collection 3 `ECO_L3T_JET.003` publishes `PTJPLSMinst`, `ETdaily`, `ETinstUncertainty`, `STICJPLdaily`, `BESSJPLdaily`, and `PMJPLdaily`, and only produces daytime retrievals (`Rg > 0`).
   - *Mitigation:* Map exact `L3T_JET` variable suffixes in `LAYER_MAPPING` and document the daytime-only scope of `L3T_JET`-filtered training sets.
7. **Swath Footprint Sparsity & Homogeneous Land-Cover Tiles:**
   - *Conflict:* ECOSTRESS swaths rarely fill 100% of a $3660 \times 3660$ MGRS tile, and individual tiles may be 0% cropland or >85% cropland.
   - *Mitigation:* Read low-resolution overviews of `L3T_ETAUX` `cloud`/`water` or `L2T_LSTE` `QC` first so candidate pixels are drawn strictly from valid swath footprints, and apply agricultural vs. natural land-cover stratification at regional/biome or global batch levels rather than rigidly per tile.
8. **NASA CMR Rate Limits & Wheel Size Constraints:**
   - *Conflict:* Issuing ~60,000 individual `(tile, product)` CMR queries triggers HTTP `429`/`503` throttling, and bundling global rasters inside the wheel bloats PyPI builds across Python 3.11–3.14.
   - *Mitigation:* Query CMR in regional bounding boxes or temporal windows with `page_size=2000` and exponential backoff, group granules by tile locally, declare `pyarrow` cleanly in `pyproject.toml`, and cache external land-cover masks on demand.

---

## 5. File-by-File Implementation Roadmap & Checklist for `v1.2.0`

### Phase 1: Global MGRS Tile Discovery & Clear-Sky CMR Filtering
- [ ] **1.1 Create `ECOv003_CMR/tile_catalog.py`:**
  - [ ] Implement `list_ecostress_land_tiles(min_lat=-54.0, max_lat=54.0) -> List[str]` enumerating all Sentinel-2 MGRS tiles intersecting global landmasses within ECOSTRESS orbital inclination.
  - [ ] Ensure land-mask resolution does not require bundling multi-hundred-MB rasters in the PyPI wheel (use lightweight Natural Earth landmass polygons or an on-demand cached mask).
- [ ] **1.2 Update `ECOv003_CMR/ECOSTRESS_CMR_search_links.py` & `ECOv003_CMR/ECOSTRESS_CMR_search.py`:**
  - [ ] Support full tile WGS84 bounding-box queries (`geometry.bounds`) in addition to centroid point queries, filtering returned granules to exact `_<TILE>_` matches.
  - [ ] Add retry/exponential backoff handling for HTTP `429` and `503` CMR responses.
  - [ ] Extract entry-level CMR metadata (`cloud_cover`, `time_start`, `producer_granule_id`) when populated and support optional `max_cloud_cover` filtering without dropping granules where CMR `cloud_cover` is `None`.
- [ ] **1.3 Update `ECOv003_CMR/interpret_ECOSTRESS_URLs.py`:**
  - [ ] Propagate `cloud_cover` and `acquisition_datetime` columns into the interpreted listing `DataFrame`.
  - [ ] Implement `fetch_granule_metadata(json_url, session)` to inspect per-granule `.json` sidecars for scene cloud fraction and quality flags prior to raster access.
- [ ] **1.4 Add Multi-Product Completeness Filter in `ECOv003_CMR/stratified_sampling.py`:**
  - [ ] Implement `find_clear_sky_et_granules(tiles, start_date, end_date, max_cloud_cover=..., session=None)` verifying that every candidate `L3T_JET` overpass has matching `(orbit, scene, tile, timestamp)` granules in `L2T_LSTE` and `L3T_ETAUX` plus a matching `(tile, YYYYMMDD)` granule in `L2T_STARS`.

---

### Phase 2: Stratified Granule Capping & Sample Budget Allocation
- [ ] **2.1 Implement Per-Tile Granule Tallying & Capping (`ECOv003_CMR/stratified_sampling.py`):**
  - [ ] Group verified clear-sky ET granules by Sentinel-2 MGRS tile and compute per-tile counts $N_t$.
  - [ ] Compute $N_{\text{cap}} = \min_{t \in \text{EligibleTiles}} N_t$ with a configurable `min_granules_floor` parameter to exclude anomalously sparse coastal/island tiles.
  - [ ] Implement `select_stratified_granules(granules_df, min_granules_floor=..., seasonal_balance=True, random_state=None)` so each eligible tile contributes exactly $N_{\text{cap}}$ granules balanced across calendar quarters/seasons.
- [ ] **2.2 Implement Per-Granule Pixel Quota Allocation:**
  - [ ] Compute per-granule pixel quota $K = \lceil N_{\text{target}} / G \rceil$ where $G = |\text{EligibleTiles}| \times N_{\text{cap}}$ and $N_{\text{target}} \approx 1{,}000{,}000$.
  - [ ] Apply a configurable `oversample_factor` (default `1.2`) during candidate generation to absorb pixels lost to local cloud/water masks while capping accepted samples per granule at $K$.

---

### Phase 3: Dynamic Intra-Granule Random Pixel Generation
- [ ] **3.1 Implement Swath & Clear-Sky Mask Extraction (`ECOv003_CMR/stratified_sampling.py`):**
  - [ ] Read low-resolution overviews (or full raster masks) of `L3T_ETAUX` `cloud` and `water` (and `L2T_LSTE` `QC` where requested) to identify valid, cloud-free, non-water land pixel indices `(row, col)` inside the swath footprint before drawing coordinates.
- [ ] **3.2 Implement Configurable Intra-Tile Spatial Dispersion:**
  - [ ] Implement `sample_granule_coordinates(granule_mask, n_samples, strategy="stratified_grid", grid_divisions=6, random_state=None)` supporting:
    - `"uniform"`: Uniform random selection across valid land pixels in the granule.
    - `"stratified_grid"`: Partition the $3660 \times 3660$ tile into $M \times M$ sub-blocks and draw dispersed samples per occupied block so pixel coordinates are independently randomized ("rolling the dice") per acquisition without spatial clustering.
- [ ] **3.3 Implement Agricultural vs. Non-Managed Land Stratification:**
  - [ ] Add optional land-cover class weighting (`cropland_fraction_target`, `land_cover_provider`) using an external land-cover mask (e.g., ESA WorldCover or MODIS MCD12Q1) with biome/batch-level quota tracking so tiles with 0% or 100% cropland do not fail sampling.

---

### Phase 4: Granule-Grouped Multi-Point `/vsicurl/` COG Extraction
- [ ] **4.1 Implement Process-Safe GDAL `/vsicurl/` Environment (`ECOv003_CMR/authentication.py`):**
  - [ ] Implement `configure_gdal_earthdata_env(session)` returning a `rasterio.Env` configured for Earthdata URS `.netrc`/cookie authentication (`GDAL_HTTP_NETRC=YES`, `GDAL_HTTP_COOKIEFILE`, `GDAL_HTTP_COOKIEJAR`, `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif`, `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`, `CPL_VSIL_CURL_USE_HEAD=NO`) without leaking `Authorization` headers to S3 redirects.
  - [ ] Pre-warm URS session cookies on the main thread before entering `ThreadPoolExecutor` workers, and retain `MemoryFile` fallback on `/vsicurl/` errors.
- [ ] **4.2 Implement Granule-Grouped Batch Sampler (`ECOv003_CMR/point_sampling.py`):**
  - [ ] Implement `sample_points_from_granule(granule_urls, coords, layers, session=None, use_vsicurl=True)` to open each variable GeoTIFF **once** and extract all $K$ coordinates via a single vectorized `src.sample(proj_coords, masked=True)` call.
  - [ ] Refactor `sample_points_over_date_range()` to group points by granule and use `sample_points_from_granule()` internally while preserving 100% backward compatibility with `sample_point_from_url()`.
  - [ ] Fix same-day multi-overpass joining in `point_sampling.py` to match instantaneous products (`L2T_LSTE`, `L3T_ETAUX`, `L3T_JET`, `L4T_*`) by `(orbit, scene, tile, timestamp)` and daily `L2T_STARS` by `(tile, YYYYMMDD)`.

---

### Phase 5: Expanded `LAYER_MAPPING` & Granule Error Hardening
- [ ] **5.1 Expand `LAYER_MAPPING` (`ECOv003_CMR/point_sampling.py`):**
  - [ ] Add `L3T_JET` layers: `PTJPLSMinst`, `ETdaily`, `ETinstUncertainty`, `STICJPLdaily`, `BESSJPLdaily`, `PMJPLdaily`.
  - [ ] Add `L2T_STARS` uncertainty layers: `NDVI-UQ`, `albedo-UQ`.
  - [ ] Add `L2T_LSTE` spectral emissivity and geometry layers: `Emis1`–`Emis5`, `Emis1_err`–`Emis5_err`, `view_zenith`, `height`.
  - [ ] Add `L4T_ESI` (`ESI`) and `L4T_WUE` (`WUE`) layers.
  - [ ] Update `_apply_layer_names()` to handle any required unit conversions or aliases cleanly.
- [ ] **5.2 Harden `open_ECOSTRESS_granule()` (`ECOv003_CMR/granule_compatibility.py`):**
  - [ ] Raise an explicit `ValueError` or `RuntimeError` if `product_location` does not exist or `open_granule_from_library()` returns `None` instead of an `ECOSTRESSGranule`.
- [ ] **5.3 Integrate Bulk Concept ID Verification (`ECOv003_CMR/constants.py` & `concept_ID_from_DOI.py`):**
  - [ ] Export `COLLECTION_3_DOIS` in `constants.py` and add `lookup_collection_3_concept_IDs()` in `concept_ID_from_DOI.py`.

---

### Phase 6: Checkpointed Production Runner, Diagnostics & Packaging (`v1.2.0`)
- [ ] **6.1 Create `ECOv003_CMR/uq_dataset_builder.py`:**
  - [ ] Implement `build_uq_training_dataset(...)` orchestrating tile discovery, clear-sky ET filtering, tile capping, per-granule coordinate randomization, and `/vsicurl/` batch sampling across a `ThreadPoolExecutor` pool.
  - [ ] Stream completed granule batches incrementally to partitioned Parquet files (`dataset_part_XXXX.parquet`, with optional CSV export) and record completed granule IDs in `completed_granules.txt` for fault-tolerant resuming.
- [ ] **6.2 Implement Coverage & Balance Diagnostics (`point_sampling.py` & `uq_dataset_builder.py`):**
  - [ ] Implement `summarize_point_samples(results_df)` reporting per-layer valid counts, completeness percentages, and missing-pixel reasons (`outside_bounds`, `nodata`, cloud-masked).
  - [ ] Emit post-build UQ dataset summary reports verifying total valid sample count ($\approx 1{,}000{,}000$), tile uniformity, seasonal distribution, and agricultural vs. natural land-cover proportions.
- [ ] **6.3 Update Exports, Dependencies, Tests & Documentation:**
  - [ ] Export all new public functions in `ECOv003_CMR/__init__.py` and `ECOv003_CMR/ECOv003_CMR.py`.
  - [ ] Add `pyarrow` (and any lightweight land-mask dependency) to `pyproject.toml` and bump version to `1.2.0`.
  - [ ] Add unit tests in `tests/test_point_sampling.py` and `tests/test_stratified_sampling.py` covering expanded `LAYER_MAPPING`, same-day multi-overpass joining, vectorized `sample_points_from_granule()`, tile capping, `"uniform"` vs. `"stratified_grid"` coordinate generation, land-cover weighting, and Parquet/manifest checkpoint resuming.
  - [ ] Add an `@pytest.mark.integration` test suite (`tests/test_live_integration.py`) gated behind Earthdata credentials in `pyproject.toml`.
  - [ ] Update `README.md` and add a runnable example script in `examples/` demonstrating stratified UQ dataset generation.