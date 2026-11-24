# `ECOv003-CMR` Consolidated Development Plan: Full Release History (`v1.0.0`–`v1.4.0`)

**Prepared:** 2026-11-23  
**Repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`  
**Current Target Release:** `v1.4.0` (Download Resilience, Multi-Build CMR Resolution & `ECOv003-granules` Parity)

---

## 1. Executive Summary

`ECOv003-CMR` provides programmatic access to NASA's Common Metadata Repository (CMR) and LP DAAC Earthdata Cloud (`LPCLOUD`) archives for ECOSTRESS Collection 3 (`.003`). Originating as a migration of Collection 2 CMR search and download tooling into a standalone Collection 3 package (`v1.0.x`–`v1.1.1`), the repository evolved across `v1.2.0`, `v1.3.0`, and `v1.3.1` into a globally scalable, spatially and seasonally stratified point-sampling engine (`build_stratified_dataset()`) designed to generate a **~1,000,000-sample non-tower ECOSTRESS training dataset** across the full 1-year Collection 3 record (`2025-10-31` to `2026-10-31`) for transport-map uncertainty quantification (UQ), spatial downscaling of relative humidity (`RH`), and temporal upscaling of evapotranspiration (`ET`).

Across `v1.2.0` through `v1.3.1`, live benchmarks against LP DAAC Earthdata Cloud granules reduced mean per-granule extraction latency from **56.71s** (`v1.2.0` baseline) to **8.72s–9.76s** (`v1.3.0`–`v1.3.1`)—an overall $5.8\times$–$6.5\times$ speedup—bringing the amortized global 1,000,000-sample runtime estimate down from **3.98 hours** to **~40.1 minutes** on 16 workers with **100.0% layer completeness**. Release `v1.4.0` hardens single-granule downloads against LP DAAC socket read timeouts and multi-build CMR listings (`2026-11-23` issue report), updates packaging/documentation, and prepares the pre-flight global 1M dry run.

---

## 2. Scientific Motivation & Dataset Design Milestones

| Date | Forum | Key Architectural Decision |
| :--- | :--- | :--- |
| **Apr 14, 2026** | UQ Meeting | Identified tower cal/val dataset size constraints; proposed sampling realistic input UQ values across full life-of-mission ECOSTRESS acquisitions. |
| **Sep 16, 2026** | Maggie Meeting & Slack | Set target of **~1,000,000 non-tower point samples**; mandated uniform Sentinel-2/UTM tile coverage, seasonal balance, and dynamic per-acquisition pixel randomization ("rolling the dice" per scene rather than fixed coordinates). |
| **Oct 1, 2026** | UQ Meeting | Formalized multi-stage stratified sampling pipeline and per-tile granule capping ($N_{\text{cap}} = \min_{t} N_t$) to enforce equal spatial and biome weighting across Earth. |

---

## 3. Release History (`v1.0.0` – `v1.4.0`)

### 3.1 `v1.0.x` – `v1.1.1`: Collection 3 Migration, Authenticated Downloads & Site Point Sampling
- Codified LPCLOUD Concept IDs for all seven Collection 3 products (`L1CT_RAD`, `L2T_LSTE`, `L2T_STARS`, `L3T_ETAUX`, `L3T_JET`, `L4T_ESI`, `L4T_WUE`) and deprecated discontinued Collection 2 products/layers (`L3T_MET`, `L3T_SM`, `L3T_SEB`, `EVI`, `SAVI`).
- Implemented Collection 3 filename/granule ID parsing, `CMR-Search-After` pagination, `setup_earthdata_session()`, `ECOv003-search` / `ECOv003-download` CLIs, `granule_compatibility.py`, and in-memory COG point sampling.

### 3.2 `v1.2.0`: Stratified Sampling Engine & Concurrent `/vsicurl/` Extraction
- Implemented `select_stratified_granules()`, `compute_per_granule_quota()`, `sample_granule_coordinates()` (`"uniform"` and `"stratified_grid"` dispersion), `sample_points_from_granule()` (`/vsicurl/`), checkpointed Parquet streaming, and expanded `LAYER_MAPPING` (45+ layers).

### 3.3 `v1.3.0` – `v1.3.1`: Global CMR Scaling, Sidecar Cloud Filtering & Production Hardening
- Vectorized global land MGRS tile discovery via `sentinel_tiles.sentinel_polygons` (14,749 tiles in 0.62s) and updated `find_sentinel2_tile()` to use polygon intersection with land filtering.
- Added CMR `granules.csv` 5-day parallel catalog enumeration (348,477 `L3T_JET` scenes in ~2m 01s), HTTP `POST` wildcard pattern batches, concurrent `.json` sidecar `ProductMetadata.QAPercentCloudCover` filtering, 64-socket `HTTPAdapter` pooling, `plan_stratified_sampling()`, `dry_run=True`, SHA-256 `candidate_granules.parquet` caching, Netscape URS cookie export (`MozillaCookieJar`), and $O(1)$-RAM `pyarrow.parquet` diagnostics.

### 3.4 `v1.4.0`: Single-Granule Download Resilience & Multi-Build Resolution
- Hardened `download_file()` with explicit `(connect, read)` socket timeouts (`(15.0, 90.0)`), jittered exponential retry backoff on transient HTTP status codes and mid-stream `TimeoutError` / `RequestException` / `OSError` failures, and unconditional cleanup of partial `.download` files.
- Updated `get_granule_from_listing()` and `download_ECOSTRESS_granule_files()` to select the latest build revision when CMR returns multiple builds of the same granule stem and raise `FileNotFoundError` when a CMR search returns zero granules.
- Updated `version.py` with a `PackageNotFoundError` fallback, bumped `pyproject.toml` to `1.4.0`, updated `README.md`, and expanded unit and integration test suites.
