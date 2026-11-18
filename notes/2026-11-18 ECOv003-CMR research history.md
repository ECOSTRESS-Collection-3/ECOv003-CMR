# ECOv003-CMR Research History, Integration Guide, and Roadmap

**Prepared:** 2026-11-18  
**Package:** `ECOv003-CMR` (`v1.1.0`)  
**Repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`

---

## 1. Overview

`ECOv003-CMR` originated from the migration of the ECOSTRESS Collection 2 Common Metadata Repository (CMR) tooling into a standalone Collection 3 package. Across exploratory scripts (`concept_IDs.py`, `debug_lst_sampling.py`, `debug_stars_search.py`, `example_download.py`, `querying_ECOSTRESS_at_points.py`) and architecture notes (`notes/`), the project investigated NASA LP DAAC Collection 3 metadata structures, filename conventions, Earthdata Cloud authentication, Cloud-Optimized GeoTIFF (COG) point sampling, and interoperability with `ECOv003-granules`.

This document records the complete research history of the package, separated into:
- **Part I — Integrated Research Topics:** What was discovered, how it was implemented in the codebase, and how to use it today.
- **Part II — Pending Research & Integration Topics:** Background context, current state of exploration, expected benefits, and concrete next steps toward full maturity.

---

## Part I: Integrated Research Topics

### 1. Collection 3 Concept ID Discovery and Product Catalog Alignment

#### How It Was Developed
During early Collection 3 migration research (`concept_IDs.py` and `notes/development plan to transform collection 2 code to collection 3.md`), the seven active Collection 3 `.003` Digital Object Identifiers (DOIs) were queried against the NASA CMR Collections API (`https://cmr.earthdata.nasa.gov/search/collections.json?doi=...`). This investigation verified two major structural changes between Collection 2 and Collection 3:
1. Separate Collection 2 meteorological, soil moisture, and surface energy balance products (`L3T_MET`, `L3T_SM`, and `L3T_SEB`) were retired and consolidated into a single tiled auxiliary product: `L3T_ETAUX`.
2. Level-1 calibrated radiance was standardized under `L1CT_RAD` (`ECO_L1CT_RAD.003`), alongside `L2T_LSTE`, `L2T_STARS`, `L3T_JET`, `L4T_ESI`, and `L4T_WUE`.

The verified LPCLOUD concept IDs were codified in `ECOv003_CMR/constants.py` (`CONCEPT_IDS`), and validation logic was added to `ECOSTRESS_CMR_search()` and `download_ECOSTRESS()` so discontinued Collection 2 product codes fail fast with explicit `ValueError` messages.

#### How to Use It Now
```python
from datetime import date
from ECOv003_CMR import CONCEPT_IDS, ECOSTRESS_CMR_search

# Inspect supported Collection 3 products and LPCLOUD Concept IDs
print(CONCEPT_IDS)

# Search one or multiple Collection 3 products across Sentinel-2 tiles
results = ECOSTRESS_CMR_search(
    product=["L2T_LSTE", "L3T_ETAUX"],
    tile=["52NHN", "53NMH"],
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
)
```

Or via the `ECOv003-search` CLI:
```bash
ECOv003-search --product L2T_LSTE L3T_ETAUX --tile 52NHN --start-date 2026-06-01 --end-date 2026-06-07
```

---

### 2. CMR Pagination (`CMR-Search-After`) and Sentinel-2 Tile Centroid Querying

#### How It Was Developed
Exploratory CMR queries (`debug_stars_search.py` and `debug_lst_sampling.py`) demonstrated that multi-day or multi-tile queries can exceed single-page CMR limits and that ECOSTRESS tiled granules map cleanly to Sentinel-2 Military Grid Reference System (MGRS) tiles. `ECOSTRESS_CMR_search_links()` was implemented to resolve the centroid coordinates of a requested Sentinel-2 tile via `sentinel_tiles.grid(tile).centroid_latlon`, issue point bounding-box queries with `page_size=2000`, and iteratively follow `CMR-Search-After` response headers (with duplicate-token loop protection) until every matching `.tif`, `.json`, `.aux.xml`, and `.jpeg` asset URL is retrieved.

#### How to Use It Now
```python
from ECOv003_CMR import ECOSTRESS_CMR_search_links, CONCEPT_IDS

urls = ECOSTRESS_CMR_search_links(
    concept_ID=CONCEPT_IDS["L2T_LSTE"],
    tile="52NHN",
    start_date="2026-06-01",
    end_date="2026-06-10",
)
print(f"Retrieved {len(urls)} asset URLs")
```

---

### 3. Collection 3 Granule ID and Filename Parsing Rules

#### How It Was Developed
Auditing summer 2026 CMR granule listings (`notes/development plan to transform collection 2 code to collection 3.md`) revealed distinct token structures between Collection 2 and Collection 3, as well as between standard orbit/scene products and daily tiled `L2T_STARS` priors:
- **Standard Collection 3 products** (`L1CT_RAD`, `L2T_LSTE`, `L3T_ETAUX`, `L3T_JET`, `L4T_ESI`, `L4T_WUE`) use 8 underscore-delimited segments:  
  `ECOv003_<PRODUCT>_<ORBIT>_<SCENE>_<TILE>_<YYYYMMDDTHHMMSS>_<BUILD>`
- **Collection 3 `L2T_STARS`** omits orbit and scene, using 6 segments:  
  `ECOv003_L2T_STARS_<TILE>_<YYYYMMDD>_<BUILD>`
- Variable suffixes can contain underscores or hyphens (e.g., `view_zenith`, `Emis4_err`, `NDVI-UQ`), and browse metadata files end in `.jpeg.aux.xml`, which must be matched before `.jpeg`.

These rules were implemented across `GranuleID` (`granule_ID.py`), `granule_ID_from_filename.py`, `product_name_from_filename.py`, `variable_from_filename.py`, and `interpret_ECOSTRESS_URLs.py` while preserving backward compatibility with Collection 2 (`ECOv002_*`) filenames.

#### How to Use It Now
```python
from ECOv003_CMR import GranuleID, granule_ID_from_filename, product_name_from_filename
from ECOv003_CMR.variable_from_filename import variable_from_filename

filename = "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02_Emis4_err.tif"
gid = granule_ID_from_filename(filename)

print(str(gid))                            # ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02
print(gid.product, gid.orbit, gid.scene)   # L2T_LSTE 44814 1
print(gid.tile)                            # 52NHN
print(variable_from_filename(filename))    # Emis4_err
```

---

### 4. `ECOv003-granules` Collection 3 Compatibility Adapter

#### How It Was Developed
Testing downloaded Collection 3 directories against `ECOv003-granules` (`notes/development plan for ECOv003-granules.md`) uncovered four compatibility gaps in the upstream granule reader:
1. `L1CT_RAD` was not dispatched (upstream checked for `L1CT_RED`).
2. `L3T_ETAUX` had no product handler.
3. `L2T_STARS` product names were misparsed by the generic tiled-ID parser.
4. Directory-backed granules (the layout written by `download_ECOSTRESS_granule_files()`) were treated as ZIP archives when enumerating `filenames`.

To bridge these gaps immediately without blocking `ECOv003-CMR` users, `ECOv003_CMR/granule_compatibility.py` was built using `_Collection3GranuleMixin` subclasses and `open_ECOSTRESS_granule()`, and `download_ECOSTRESS_granule()` was updated to validate that the opened granule's `.product` matches the expected `GranuleID.product`.

#### How to Use It Now
```python
from ECOv003_CMR.granule_compatibility import open_ECOSTRESS_granule

granule = open_ECOSTRESS_granule("./data/ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01")
print(granule.product)         # 'L3T_ETAUX'
print(granule.variables)       # ['Ta', ...]
print(granule.layer_URI("Ta")) # Full path to the GeoTIFF layer
```

---

### 5. Authenticated Earthdata Cloud Downloads and CLI Tooling

#### How It Was Developed
Prototyping granule downloads (`example_download.py`) and auditing `download_file.py` in `v1.0.1` showed that LP DAAC Earthdata Cloud asset URLs require URS authentication (`urs.earthdata.nasa.gov`) and redirect handling, and that multi-day downloads needed per-granule acquisition date extraction rather than reusing `start_date`. In `v1.1.0`:
- `download_file()` was updated to accept `session: Optional[requests.Session] = None` (defaulting to `setup_earthdata_session()`), follow redirects (`allow_redirects=True`), stream atomically via `.download` temporary files, clean up zero-byte files, and use `tqdm.auto.tqdm` for terminal/notebook compatibility.
- `download_ECOSTRESS()` was updated to extract each granule's true acquisition date via `_acquisition_date_from_granule_id()` and propagate the authenticated session across all files.
- `acquisition_date` was standardized across download functions while retaining `aquisition_date` as a backward-compatible alias.
- Both `ECOv003-search` and `ECOv003-download` CLIs were updated to configure console logging, support `-q/--quiet`, print results cleanly to stdout, and log errors via `logger.error()`.

#### How to Use It Now
```python
from datetime import date
from ECOv003_CMR import download_ECOSTRESS, download_ECOSTRESS_granule, setup_earthdata_session

session = setup_earthdata_session()

# Single granule download
granule = download_ECOSTRESS_granule(
    product="L2T_LSTE",
    tile="11SPS",
    acquisition_date=date(2026, 10, 24),
    orbit=47080,
    scene=14,
    parent_directory="~/data/ECOSTRESS_v003",
    session=session,
)

# Multi-day batch download across products and tiles
granules = download_ECOSTRESS(
    product=["L2T_LSTE", "L2T_STARS"],
    tile="11SLT",
    start_date="2026-06-01",
    end_date="2026-06-07",
    session=session,
)
```

---

### 6. In-Memory COG Point Sampling and Multi-Product Temporal Alignment

#### How It Was Developed
Research in `debug_lst_sampling.py`, `debug_stars_search.py`, and `querying_ECOSTRESS_at_points.py` established how to sample ECOSTRESS rasters at geographic coordinates without downloading full GeoTIFFs:
1. **No-full-download window reads:** `sample_point_from_url()` reads HTTP responses into a `rasterio.io.MemoryFile`, reprojects raster bounds to WGS84 (`EPSG:4326`) to check containment, transforms query coordinates into the raster CRS, reads a $1 \times 1$ `Window`, and treats masked pixels and `NaN` fill values as `"nodata"`.
2. **Collection 3 variable & unit mapping:** `LAYER_MAPPING` was audited against Collection 3 catalogs—mapping `ST_C` to `L2T_LSTE`/`LST` with automatic Kelvin-to-Celsius conversion ($T_C = T_K - 273.15$), exposing `L3T_ETAUX` layers (`Ta_C`/`Ta` already in Celsius, `RH`, `SM`, `Rg`, `Rn`, `cloud`, `water`), and rejecting removed Collection 2 layers (`EVI`, `SAVI`) with `ValueError`.
3. **Cross-product date joining & parallel/sequential parity:** `sample_points_over_date_range()` joins instantaneous `L2T_LSTE` overpasses with daily `L2T_STARS` and `L3T_ETAUX` granules by `YYYYMMDD` date, propagates all non-geometry metadata columns from `GeoDataFrame` or `Series` inputs, and supports both parallel (`max_workers > 1`) and sequential (`max_workers = 1`) execution across multi-point inputs.

#### How to Use It Now
```python
from datetime import date
import geopandas as gpd
from shapely.geometry import Point
from ECOv003_CMR import sample_points_over_date_range

sites = gpd.GeoDataFrame(
    {
        "site_id": ["downtown_la", "lax_airport"],
        "geometry": [Point(-118.2437, 34.0522), Point(-118.4085, 33.9416)],
    },
    crs="EPSG:4326",
)

samples = sample_points_over_date_range(
    geometry=sites,
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
    layers=["ST_C", "emissivity", "NDVI", "albedo", "Ta_C", "RH", "SM"],
    max_workers=10,
    drop_na=True,
)
print(samples[["site_id", "timestamp", "ST_C", "NDVI", "albedo", "Ta_C"]])
```

---

## Part II: Pending Research & Integration Topics

### 1. Automated Batch Concept ID Verification and Refresh (`concept_IDs.py`)

- **Background Information:**  
  `ECOv003_CMR/constants.py` currently stores static LPCLOUD Concept IDs (e.g., `C3998139651-LPCLOUD`), while `ECOv003_CMR/concept_ID_from_DOI.py` only looks up one DOI at a time. Meanwhile, the standalone root script `concept_IDs.py` contains `COLLECTION_3_DOIS`, `query_concept_id_from_doi()`, and `export_ecostress_c3_concept_ids()` to query all seven Collection 3 DOIs in bulk and report per-product lookup statuses.
- **Current State of Research:**  
  Working prototype exists in the repository root (`concept_IDs.py`), but has not been integrated into `ECOv003_CMR/concept_ID_from_DOI.py` or `ECOv003_CMR/constants.py`.
- **Potential Benefit to the Package:**  
  NASA CMR Concept IDs can change when collections are reprocessed or migrated across providers. Exposing a bulk verification/refresh helper inside the package allows automated health checks and programmatic resolution of current Concept IDs without manual edits to `constants.py`.
- **Next Steps for Maturity & Integration:**  
  1. Export `COLLECTION_3_DOIS` in `ECOv003_CMR/constants.py`.
  2. Add `lookup_collection_3_concept_IDs()` (and optional `dynamic_concept_ids: bool = False` support) in `ECOv003_CMR/concept_ID_from_DOI.py`.
  3. Add unit tests mocking CMR collection responses for bulk DOI resolution and remove the standalone root `concept_IDs.py` script.

---

### 2. Upstream Migration of Compatibility Fixes to `ECOv003-granules`

- **Background Information:**  
  As documented in `notes/development plan for ECOv003-granules.md`, `ECOv003_CMR/granule_compatibility.py` exists as a local adapter to work around limitations in `ECOv003-granules` (`L1CT_RAD` vs. `L1CT_RED` dispatch, missing `L3T_ETAUX` support, misparsed `L2T_STARS` product metadata, and ZIP-only file discovery).
- **Current State of Research:**  
  A five-phase development plan is drafted in `notes/development plan for ECOv003-granules.md`, and all seven product layouts are verified locally via `tests/test_granule_compatibility.py`. Upstream changes in `ECOSTRESS-Collection-3/ECOv003-granules` are still pending.
- **Potential Benefit to the Package:**  
  Moving product dispatch, metadata parsing, and directory/ZIP layer discovery into `ECOv003-granules` eliminates duplicate class definitions across repositories, ensures consistent behavior for downstream consumers opening granules directly with `ECOv003_granules.open_granule()`, and simplifies `ECOv003-CMR`.
- **Next Steps for Maturity & Integration:**  
  1. Implement the `open_granule.py`, `tiled_granule.py`, and `L2TSTARS.py` updates in `ECOSTRESS-Collection-3/ECOv003-granules` and publish a new release.
  2. Bump the minimum `ECOv003-granules` version constraint in `ECOv003-CMR/pyproject.toml`.
  3. Deprecate or remove `ECOv003_CMR/granule_compatibility.py` once upstream parity is verified.

---

### 3. Explicit Exception Handling on Unrecognized Granules in `open_ECOSTRESS_granule()`

- **Background Information:**  
  `notes/development plan for ECOv003-granules.md` identifies that returning `None` for unknown or malformed granule names leads to silent failures or delayed `AttributeError`s downstream. Currently, `download_ECOSTRESS_granule()` checks `if not isinstance(granule, ECOSTRESSGranule): raise RuntimeError(...)`, but `open_ECOSTRESS_granule()` falls back to `open_granule_from_library()`, which can still return `None`.
- **Current State of Research:**  
  Enforced in `download_ECOSTRESS_granule()`, but not yet enforced directly inside `open_ECOSTRESS_granule()` or upstream in `ECOv003-granules`.
- **Potential Benefit to the Package:**  
  Guarantees a consistent, fail-fast contract whether a user opens a granule via `download_ECOSTRESS_granule()` or directly via `open_ECOSTRESS_granule()`.
- **Next Steps for Maturity & Integration:**  
  1. Update `open_ECOSTRESS_granule()` to raise a descriptive `ValueError` or `RuntimeError` whenever the returned object is not an `ECOSTRESSGranule` instance or the target path does not exist.
  2. Add regression tests in `tests/test_granule_compatibility.py` for invalid paths and unknown product prefixes.

---

### 4. Reusable Point-Sampling Coverage & Completeness Diagnostics (`querying_ECOSTRESS_at_points.py`)

- **Background Information:**  
  In `querying_ECOSTRESS_at_points.py` and `debug_lst_sampling.py`, exploratory workflows required post-sampling diagnostics to measure per-layer valid observation counts, percentage coverage across `L2T_LSTE`, `L2T_STARS`, and `L3T_ETAUX`, and reasons for missing pixels (`outside_bounds`, `nodata`, QC/cloud masking).
- **Current State of Research:**  
  Currently implemented ad hoc via `print()` statements in `querying_ECOSTRESS_at_points.py` and `examples/geodataframe_sampling_demo.py`. When `drop_na=True` (the default in `sample_points_over_date_range()`), partial observations are dropped before the caller can inspect which product caused the gap.
- **Potential Benefit to the Package:**  
  Providing a built-in summary helper (e.g., `summarize_point_samples(results_df)`) and optional failure-reason tracking gives researchers immediate visibility into temporal coverage differences between instantaneous `L2T_LSTE` swaths and daily `L2T_STARS` / `L3T_ETAUX` products.
- **Next Steps for Maturity & Integration:**  
  1. Extract the per-layer count and percentage coverage logic from `querying_ECOSTRESS_at_points.py` into a `summarize_point_samples()` helper in `ECOv003_CMR/point_sampling.py`.
  2. Move `querying_ECOSTRESS_at_points.py` and `example_download.py` into `examples/` and remove root scratch debug scripts (`debug_lst_sampling.py`, `debug_stars_search.py`).

---

### 5. Gated Live Authenticated Integration Test Suite

- **Background Information:**  
  All three planning documents (`notes/development plan to transform collection 2 code to collection 3.md`, `POINT_SAMPLING_INTEGRATION.md`, and `notes/2026-11-18 ECOv003-CMR v1.0.1 to v1.1.0 development plan.md`) note that the current `pytest` suite runs strictly offline against mocked CMR responses and in-memory GeoTIFFs. Although `.github/workflows/ci.yml` injects `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD` secrets, no marked integration tests exercise real LP DAAC authentication, file downloads, or COG range reads.
- **Current State of Research:**  
  Identified as a manual pre-release check in project documentation; not yet automated as an opt-in `pytest -m integration` test module.
- **Potential Benefit to the Package:**  
  Automatically catches upstream CMR schema changes, Earthdata URS redirect/token regressions, or LP DAAC asset URL changes in CI without slowing down or breaking offline unit tests.
- **Next Steps for Maturity & Integration:**  
  1. Register an `@pytest.mark.integration` marker in `pyproject.toml` (excluded by default via `addopts = "-m 'not integration'"`).
  2. Add `tests/test_live_integration.py` testing one authenticated `download_ECOSTRESS_granule()` call and one `sample_points_over_date_range()` call against verified summer 2026 granules, skipping gracefully when Earthdata credentials are absent.