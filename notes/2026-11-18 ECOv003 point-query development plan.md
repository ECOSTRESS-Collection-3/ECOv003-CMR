# ECOv003-CMR Development Plan: 1M-Sample ECOSTRESS UQ Training Dataset Pipeline

**Prepared:** 2026-11-18  
**Target Package:** `ECOv003-CMR` (`v1.2.0`+)  
**Related Plan:** `2026-11-18 ECOSTRESS UQ training dataset and point query plan.md`

---

## 1. Objective & Scope

Extend `ECOv003-CMR` from a site-centric, fixed-coordinate point sampler into a global, granule-centric, stratified sampling engine capable of generating the **~1,000,000-sample ECOSTRESS Collection 3 training dataset** for uncertainty quantification (UQ), relative humidity spatial downscaling, and evapotranspiration (ET) temporal upscaling.

Specifically, this plan addresses six core architectural extensions:
1. Global Sentinel-2/UTM tile discovery and clear-sky ET granule filtering.
2. Stratified per-tile granule capping and sample-budget allocation.
3. Dynamic per-granule randomized pixel coordinate generation (with spatial dispersion and land-cover stratification options).
4. Granule-grouped multi-point Cloud-Optimized GeoTIFF (COG) extraction using true HTTP byte-range requests (`/vsicurl/`).
5. Expansion of `LAYER_MAPPING` to cover `L3T_JET` ET outputs, `L2T_STARS` UQ priors, and full `L2T_LSTE` / `L3T_ETAUX` inputs.
6. Checkpointed, resumable streaming exports (Parquet/CSV) for large-scale production runs.

---

## 2. Current State vs. Required Capabilities

| Pipeline Stage | Current `ECOv003-CMR` (`v1.1.1`) Capability | Required Capability for 1M-Sample UQ Dataset |
| :--- | :--- | :--- |
| **Spatial Scope** | Requires explicit user-supplied Sentinel-2 `tile` IDs or point coordinates. | Enumerate all global land-intersecting Sentinel-2 MGRS tiles within ECOSTRESS orbital coverage ($\pm 54^\circ$ latitude). |
| **Granule Filtering** | Returns all CMR entries matching product, tile, and date window regardless of cloud cover. | Filter mission-wide granules to clear-sky scenes with valid `L3T_JET` ET retrievals using CMR metadata and `.json` sidecars. |
| **Sampling Design** | Samples fixed user coordinates across every overpass in a date range. | Tally clear-sky granules per tile, cap at the minimum tile count, subsample uniformly/seasonally, and randomize pixel locations independently per acquisition ("rolling the dice" per scene). |
| **Land Cover & Dispersion** | No intra-tile spatial dispersion or land-cover stratification. | Support dispersed intra-granule sampling (uniform random vs. sub-grid/Latin Hypercube) and optional agricultural vs. non-managed land weighting. |
| **COG Read Architecture** | Downloads full compressed `.tif` into `MemoryFile` per `(point, granule, variable)` task. | Group all $K$ points per granule into a single `rasterio.open()` call (`src.sample(coords)`) backed by authenticated `/vsicurl/` HTTP byte-range reads. |
| **Variable Coverage** | 16 layers across `L2T_LSTE`, `L2T_STARS`, and `L3T_ETAUX`. | Add `L3T_JET` (`PTJPLSMinst`, `ETdaily`, partitioning & UQ), `L2T_STARS` UQ layers (`NDVI-UQ`, `albedo-UQ`), and `L2T_LSTE` emissivity/view-angle layers. |
| **Output & Resumability** | Returns an in-memory `pandas.DataFrame` only after all tasks finish. | Stream completed granule batches to disk (Parquet/CSV) with a manifest of processed granules for fault-tolerant resuming. |

---

## 3. Phased Implementation Plan

### Phase 1: Global Tile Discovery & Clear-Sky Metadata Filtering

**Goal:** Identify every valid clear-sky ET granule across the ECOSTRESS mission without downloading GeoTIFFs.

- **1.1 Global MGRS Tile Catalog (`ECOv003_CMR/tile_catalog.py`)**
  - Enumerate all Sentinel-2 MGRS tiles intersecting global land masses within the ECOSTRESS orbital inclination ($\pm 54^\circ$ latitude) using `sentinel_tiles` and a lightweight land mask.
  - Provide `list_ecostress_land_tiles(min_lat=-54.0, max_lat=54.0) -> List[str]`.
- **1.2 CMR Cloud-Cover & JSON Sidecar Inspection (`ECOSTRESS_CMR_search.py` / `interpret_ECOSTRESS_URLs.py`)**
  - Extend CMR granule parsing to extract `cloud_cover` from `granules.json` entries when populated.
  - Add a lightweight helper `fetch_granule_metadata(json_url, session)` to read the per-granule `.json` metadata file (`Product Metadata` / `Standard Metadata`) to check scene cloud fraction and valid retrieval flags prior to raster access.
- **1.3 Multi-Product Completeness Filter**
  - Add `find_clear_sky_et_granules(tiles, start_date, end_date, max_cloud_cover=...)` to verify that each candidate `L3T_JET` overpass has matching `L2T_LSTE`, `L3T_ETAUX`, and same-date `L2T_STARS` assets.

---

### Phase 2: Stratified Granule Capping & Sample Budget Allocation

**Goal:** Enforce global spatial/biome uniformity and seasonal balance across the mission archive.

- **2.1 Per-Tile Granule Tallying & Capping (`ECOv003_CMR/stratified_sampling.py`)**
  - Group candidate clear-sky granules by Sentinel-2 tile.
  - Compute the minimum valid granule count across tiles:
    $$N_{\text{cap}} = \min_{t \in \text{Tiles}} N_t$$
    (with an optional `min_granules_floor` parameter so anomalously sparse ocean/coastal tiles can be excluded rather than collapsing $N_{\text{cap}}$).
  - Subsample $N_{\text{cap}}$ granules per tile using a reproducible `random_state` (with optional seasonal/quarter stratification so all four seasons are balanced per tile).
- **2.2 Per-Granule Pixel Quota Calculation**
  - Given total target samples $N_{\text{target}} \approx 1{,}000{,}000$ and selected granule count $G = |\text{Tiles}| \times N_{\text{cap}}$, compute the per-granule quota:
    $$K = \left\lceil \frac{N_{\text{target}}}{G} \right\rceil$$
  - Apply a configurable oversampling factor (e.g., $1.2\times$) during candidate coordinate generation to absorb pixels lost to local cloud/water masks.

---

### Phase 3: Dynamic Intra-Granule Random Pixel Generation

**Goal:** Independently randomize pixel locations for each selected granule while resolving open technical questions on spatial dispersion and agricultural vs. non-managed land balance.

- **3.1 Valid-Pixel Mask Extraction**
  - Read the low-resolution overview (or `cloud` / `water` / `QC` raster) of the selected granule to identify valid, cloud-free land pixels `(row, col)` inside the swath footprint.
- **3.2 Configurable Intra-Tile Spatial Dispersion**
  - Implement `sample_granule_coordinates(granule_mask, n_samples, strategy="uniform", random_state=None)` supporting:
    - `"uniform"`: Uniform random selection across all valid land pixels in the granule.
    - `"stratified_grid"`: Partition the $3660 \times 3660$ Sentinel-2 tile into $M \times M$ sub-blocks and draw dispersed samples per block to prevent spatial clustering.
- **3.3 Agricultural vs. Non-Managed Land Stratification**
  - Support optional land-cover raster/class weighting (e.g., MODIS/Copernicus/ESA WorldCover cropland vs. natural vegetation classes) so `sample_granule_coordinates()` can enforce target sampling proportions between managed agricultural land and natural ecosystems.

---

### Phase 4: Granule-Grouped Multi-Point COG Extraction (`/vsicurl/`)

**Goal:** Eliminate redundant full-file downloads by extracting all $K$ points per granule in a single remote COG read per variable.

- **4.1 Authenticated GDAL `/vsicurl/` Environment (`ECOv003_CMR/authentication.py`)**
  - Add `configure_gdal_earthdata_env(session)` using `rasterio.Env` with URS cookie/bearer-token settings (`GDAL_HTTP_COOKIEFILE`, `GDAL_HTTP_COOKIEJAR`, `CPL_VSIL_CURL_ALLOWED_EXTENSIONS=.tif`, `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`) so GDAL issues RFC 7233 HTTP byte-range requests directly against LP DAAC Earthdata Cloud URLs.
  - Retain `MemoryFile` fallback if `/vsicurl/` encounters transient redirect issues.
- **4.2 Granule-Grouped Batch Sampler (`sample_points_from_granule()`)**
  - Refactor `point_sampling.py` so that for a single granule and list of $K$ `(lon, lat)` coordinates, each requested variable URL is opened **once** and all $K$ pixels are extracted in a single vectorized `src.sample(proj_coords, masked=True)` call.
  - Expected speedup: $10\times$–$50\times$ reduction in HTTP requests and network transfer volume compared to single-point `MemoryFile` downloads.

---

### Phase 5: Expanded `LAYER_MAPPING` for UQ, ET, and Energy Balance Variables

**Goal:** Expose all required inputs, uncertainties, and ET/energy balance outputs in `LAYER_MAPPING`.

| Layer Name | Collection 3 Product | Source Variable | Units / Role |
| :--- | :--- | :--- | :--- |
| `PTJPLSMinst`, `ETdaily` | `L3T_JET` | `PTJPLSMinst`, `ETdaily` | Instantaneous & daily ET targets ($\text{W/m}^2$ / $\text{mm/day}$) |
| `ETcanopy`, `ETsoil`, `ETinterception` | `L3T_JET` | Canopy, soil, interception components | ET partitioning outputs (verify exact C3 COG variable names) |
| `NDVI-UQ`, `albedo-UQ` | `L2T_STARS` | `NDVI-UQ`, `albedo-UQ` | Surface reflectance/vegetation prior uncertainties |
| `view_zenith`, `height` | `L2T_LSTE` | `view_zenith`, `height` | Sensor view geometry and surface elevation ($\text{deg}$, $\text{m}$) |
| `Emis1`–`Emis5`, `Emis*_err` | `L2T_LSTE` | Band emissivities & uncertainties | Spectral emissivity inputs and UQ |
| `ST_C`, `LST`, `LST_err`, `QC`, `EmisWB` | `L2T_LSTE` | Existing C3 LSTE variables | Already supported in `v1.1.1` |
| `NDVI`, `albedo` | `L2T_STARS` | Existing C3 STARS variables | Already supported in `v1.1.1` |
| `Ta_C`, `RH`, `SM`, `Rg`, `Rn`, `cloud`, `water` | `L3T_ETAUX` | Existing C3 ETAUX variables | Already supported in `v1.1.1` |

*(Note: Verify exact `L3T_JET` variable suffixes against live June 2026 `ECOSTRESS_CMR_search(product="L3T_JET", ...)` listings before finalizing the `L3T_JET` entries.)*

---

### Phase 6: Checkpointed Production Runner & Validation

**Goal:** Enable fault-tolerant execution of the 1,000,000-sample extraction campaign.

- **6.1 Streaming Export & Manifest Checkpointing (`build_uq_training_dataset()`)**
  - Process granules in parallel worker pools (`ThreadPoolExecutor`), flushing completed granule batches incrementally to partitioned Parquet files (e.g., `dataset_part_0001.parquet`) and appending completed granule IDs to a `completed_granules.txt` manifest.
  - On restart, skip any granule ID already recorded in `completed_granules.txt`.
- **6.2 Post-Extraction Coverage & Balance Diagnostics**
  - Emit summary statistics verifying:
    - Total valid samples collected ($\approx 1{,}000{,}000$).
    - Granule count uniformity across UTM tiles.
    - Seasonal distribution across months/quarters.
    - Land-cover proportions (agricultural vs. natural ecosystems) and per-variable completeness.
- **6.3 Testing Strategy**
  - Add offline unit tests in `tests/test_stratified_sampling.py` using synthetic multi-tile granule catalogs and in-memory multi-band/multi-variable COG fixtures to verify tile capping, per-granule coordinate randomization, vectorized `src.sample()`, and checkpoint resuming.