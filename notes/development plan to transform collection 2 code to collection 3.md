# ECOv003-CMR Development Plan & Strategy

## 1. Executive Summary & Objectives

This document outlines the engineering plan to develop **ECOv003-CMR**, expanding the Python software toolset for NASA ECOSTRESS Collection 3 data access, metadata search via the NASA Common Metadata Repository (CMR), and Cloud-Optimized GeoTIFF (COG) point sampling.

### Core Objectives
* **Collection 3 Readiness**: Adapt CMR search endpoints, DOIs, Concept IDs, and product catalogs for Collection 3 (L2T, L3T, L4T).
* **High-Performance Point Sampling**: Maintain zero-download COG HTTP range request capabilities for fast point extraction across GeoDataFrames.
* **Codebase Optimization**: Leverage the ~85% shared logic between Collection 2 and Collection 3 while maintaining clean separation or unified multi-collection capabilities.

---

## 2. Architecture Options & Strategy Comparison

| Criteria | Option A: Standalone Package (`ECOv003-CMR`) | Option B: Unified Multi-Collection Package (`ECOSTRESS-CMR`) |
| :--- | :--- | :--- |
| **Repository Structure** | Independent repository (`ECOv003-CMR`) mirroring `ECOv002-CMR`. | Single repository (`ECOSTRESS-CMR`) supporting `collection=2` and `collection=3`. |
| **Maintenance Burden** | High (dual codebase maintenance for bug fixes and updates). | Low (single codebase, central updates and issue tracking). |
| **User Experience** | Requires installing separate packages per collection version. | Single package import (`ECOSTRESS_CMR.search(..., collection=3)`). |
| **Refactoring Effort** | Low (copy-paste-modify existing `ECOv002-CMR` repository). | Moderate (refactor `constants.py` and search functions to accept collection parameters). |

> **Strategic Recommendation**: Option B (Unified Package) is recommended to prevent technical debt and eliminate code duplication. However, if strict repository isolation is required by project governance, Option A provides a standalone migration route.

---

## 3. Code Redundancy & Component Modification Matrix

| Module | Redundancy % | Action Required | Key Technical Changes |
| :--- | :---: | :---: | :--- |
| `authentication.py` | 100% | Reuse | Identical Earthdata credentials (`.netrc`, environment variables, `requests.Session`). |
| `point_sampling.py` | 90% | Update Mappings | Update `LAYER_MAPPING` dictionary for Collection 3 band names and aliases. |
| `constants.py` | 10% | Rewrite | Update Concept IDs, DOIs, product definitions, and default CMR search URLs. |
| `granule_ID_from_filename.py` | 50% | Audit / Update | Adjust regular expressions for Collection 3 build numbers and naming conventions. |
| `variable_from_filename.py` | 60% | Audit / Update | Validate string splitting tokens against Collection 3 product filename patterns. |
| `ECOSTRESS_CMR_search.py` | 85% | Modify Parameters | Pass Collection 3 Concept IDs to CMR queries. |
| `download_ECOSTRESS.py` | 90% | Update Paths | Adjust output directory defaults to `~/data/ECOSTRESS_v003`. |

---

## 4. Phase-by-Phase Implementation Plan

### Phase 1: Repository & Environment Setup
1. **Repository Initialization**:
   * Create repository structure (`ECOv003_CMR/`, `examples/`, `tests/`).
   * Configure `pyproject.toml` with CLI entry points: `ECOv003-search` and `ECOv003-download`.
2. **Dependency Management**:
   * Define core dependencies: `geopandas`, `rasterio`, `rasters`, `sentinel-tiles`, `shapely`, `requests`, `pandas`, `tqdm`.
   * Integrate with `ECOv003-granules` once published.

### Phase 2: Metadata & CMR Integration
1. **Update `constants.py`**:
   * Map Collection 3 DOIs (e.g., `10.5067/ECOSTRESS/ECO_L2T_LSTE.003`).
   * Populate `CONCEPT_IDS` mapping table for all supported products:
     * **Level 2**: `L2T_LSTE`, `L2T_STARS`
     * **Level 3**: `L3T_MET`, `L3T_SM`, `L3T_SEB`, `L3T_JET`
     * **Level 4**: `L4T_ESI`, `L4T_WUE`
2. **Refactor CMR Search Routines**:
   * Update `ECOSTRESS_CMR_search_links.py` and `ECOSTRESS_CMR_search.py` to query CMR using updated metadata queries.

### Phase 3: Filename Interpreters & Parser Rules
1. **Filename Regex Verification**:
   * Audit `product_name_from_filename.py`, `granule_ID_from_filename.py`, and `variable_from_filename.py`.
   * Implement test cases covering edge-case filenames for Collection 3 granules across all processing levels.

### Phase 4: Point Sampling Engine Adjustment
1. **Layer Shortcut Updates**:
   * Update `LAYER_MAPPING` in `point_sampling.py`:
     ```python
     LAYER_MAPPING = {
         'ST_C': ('L2T_LSTE', 'LST'),       # Kelvin to Celsius conversion
         'LST': ('L2T_LSTE', 'LST'),         # Land Surface Temp (K)
         'EmisWB': ('L2T_LSTE', 'EmisWB'),   # Wideband Emissivity
         'NDVI': ('L2T_STARS', 'NDVI'),     # Vegetation Index
         'albedo': ('L2T_STARS', 'albedo'), # Surface Albedo
         'Ta_C': ('L3T_MET', 'Ta'),         # Air Temperature (C)
         'SM': ('L3T_SM', 'SM'),            # Soil Moisture
     }
     ```
2. **COG Stream Optimization**:
   * Preserve multi-threaded HTTP range queries (`rasterio.io.MemoryFile` + `ThreadPoolExecutor`) for batch extraction over GeoDataFrames.

### Phase 5: Example Workflows & Testing
1. **Demo Scripts (`examples/`)**:
   * `point_sampling_demo.py`: Single-coordinate time-series sampling.
   * `geodataframe_sampling_demo.py`: Batch point sampling over a date range.
   * `csv_to_geodataframe_demo.py`: End-to-end CSV ingest, spatial sampling, and output export.
2. **Test Suite (`tests/`)**:
   * Unit tests for tile lookup via `sentinel-tiles`.
   * Integration tests for mock CMR API responses.
   * Regression tests comparing Collection 2 vs Collection 3 sampling results.

---

## 5. Risk Management & Key Decision Points

> **Critical Dependency**: Collection 3 CMR Concept IDs must be fully published and verified on LP DAAC / NASA Earthdata before completing Phase 2.

> **Backward Compatibility**: Ensure utility functions fail gracefully with informative error messages if users attempt to query Collection 3 date ranges prior to the official Collection 3 data release.
