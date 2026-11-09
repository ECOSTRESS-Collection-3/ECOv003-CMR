# ECOv003-CMR Development Plan & Status

## 1. Objectives and Current Status

This plan tracks the transformation of the ECOSTRESS Collection 2 CMR package into a standalone Collection 3 package, including CMR search, granule downloads, and Cloud-Optimized GeoTIFF (COG) point sampling.

**Status snapshot: 2026-11-09.** Repository packaging, CMR search, and Collection 3 filename/download-directory parsing are complete. A local compatibility adapter covers all seven Collection 3 product names while reusing `ECOv003-granules` classes where available. Point-sampling compatibility and documentation still need work. Overall readiness is estimated at **about 60%**.

| Phase | Status | Summary |
|---|---|---|
| 1. Repository and packaging | Complete | Editable install, wheel contents, package import, and both CLI help commands are verified using the `ECOv003-CMR` mamba environment. |
| 2. CMR metadata and search | Complete | All seven concept IDs and representative summer 2026 searches were verified against live CMR; Search-After paging and Collection 3 URL parsing are covered. |
| 3. Filename parsing | Complete | All seven Collection 3 product layouts are tested; a compatibility adapter handles product dispatch, granule metadata, and file discovery for downloaded directories. |
| 4. Point sampling | Partial | COG sampling logic is carried over, but layer mappings still refer to Collection 2 products that were discontinued. |
| 5. Examples, documentation, and tests | Partial | Collection 3 search, parser, and download-adapter regression tests pass. README, integration notes, and examples still need Collection 3 updates. |

## 2. Architecture Decision

The current repository follows **Option A: a standalone `ECOv003-CMR` package**, separate from `ECOv002-CMR`. Continue with that approach for this migration; do not broaden the work into a unified multi-collection package without a separate decision.

| Criteria | Standalone package (chosen) | Unified multi-collection package (not in current scope) |
|---|---|---|
| Repository structure | Independent `ECOv003-CMR` repository mirroring the Collection 2 package | One repository supporting multiple collections |
| Maintenance | Requires fixes to be applied across package versions | Shared implementation and issue tracking |
| User experience | Separate package per collection | One package with a collection selector |
| Migration scope | Reuse shared logic and validate Collection 3-specific behavior | Refactor APIs and constants to parameterize collection |

## 3. Migration Work Matrix

| Component | Current state | Remaining work |
|---|---|---|
| `authentication.py` | Reused from Collection 2 | Confirm authentication behavior against Collection 3 download URLs. |
| `constants.py` | Updated with seven Collection 3 products and concept IDs | Verify IDs against current CMR results and ensure all product-facing APIs use this map. |
| CMR search | Uses the Collection 3 concept-ID map and Search-After pagination | Phase 2 live queries, empty results, paging, and Collection 3 URL parsing verified. |
| Downloads | Defaults to `~/data/ECOSTRESS_v003`; uses the Collection 3 compatibility adapter and validates parsed product metadata | Verify a real authenticated Collection 3 download/open workflow before release. |
| Filename interpreters | Validated against June 2026 CMR names for all seven products | No remaining Phase 3 work. |
| Point sampling | COG sampling engine retained | Replace or remove mappings for discontinued Collection 2 products; validate Collection 3 variables and units. |
| Packaging | Project name, version lookup, editable install, wheel build, package import, and CLI commands are verified for Collection 3 | No remaining Phase 1 work. |
| Docs and examples | Existing content is largely Collection 2-era | Update package names, supported products, filenames, layers, and examples to Collection 3. |

## 4. Phase-by-Phase Plan

### Phase 1: Repository and Packaging

- [x] Establish the `ECOv003_CMR/`, `examples/`, and `tests/` structure.
- [x] Set project metadata, dependencies, and `ECOv003-search` / `ECOv003-download` entry points in `pyproject.toml`.
- [x] Set the Collection 3 default download directory.
- [x] Fix the package metadata lookup in `ECOv003_CMR/version.py` so it uses the `ECOv003-CMR` distribution.
- [x] Verify editable installation, built wheel contents, and registered CLI entry-point targets.
- [x] Run both CLI `--help` commands in the `ECOv003-CMR` mamba environment.
- [x] Reinstall from the current checkout and verify package import and both CLI commands in the `ECOv003-CMR` mamba environment.

Use the `ECOv003-CMR` mamba environment for project Python work. For shell commands, invoke it explicitly with `mamba run -n ECOv003-CMR ...`; the VS Code workspace interpreter is configured to the same environment.

### Phase 2: CMR Metadata and Search

- [x] Add a Collection 3 concept-ID map and record the lookup results in `ecostress_collection3_concept_ids.csv`.
- [x] Update CMR search and download validation to derive supported products from `CONCEPT_IDS`.
- [x] Verify all seven concept IDs against live CMR collection metadata.
- [x] Search all seven products using June 1, 2026 acquisitions and confirm file links and parsed granule metadata.
- [x] Follow CMR Search-After headers for subsequent pages and test empty-result behavior.
- [x] Add Collection 3 filename parsing regression tests for standard and STARS granules.

The current map covers `L1CT_RAD`, `L2T_LSTE`, `L2T_STARS`, `L3T_ETAUX`, `L3T_JET`, `L4T_ESI`, and `L4T_WUE`. Collection 2 products `L3T_MET`, `L3T_SM`, and `L3T_SEB` were discontinued in Collection 3; do not retain them as Collection 3 search or sampling options unless a supported replacement is verified.

Live CMR validation was kept to summer 2026 acquisitions, per the current Collection 3 availability window. The standard-product and STARS filename layouts differ; the result parser now preserves the exact Collection 3 granule ID and extracts the full variable suffix.

### Phase 3: Filename Interpreters and Parser Rules

- [x] Collect representative Collection 3 filenames from June 2026 CMR results for all seven supported products.
- [x] Audit `product_name_from_filename.py`, `granule_ID_from_filename.py`, and `variable_from_filename.py` against those names.
- [x] Add focused tests for product, granule ID, and variable parsing, including STARS, underscore-containing variable names, Collection 2 compatibility, and JPEG auxiliary XML.
- [x] Verify local `GranuleID` values used by the download-listing workflow for Collection 3 product names.
- [x] Add a local opener that dispatches all seven Collection 3 products, including `L1CT_RAD` and `L3T_ETAUX`, which the dependency dispatcher does not recognize.
- [x] Correct product-name parsing for STARS and discover TIFF files in the download directories used by this package.
- [x] Validate granule objects, metadata fields, variables, and layer paths against local directory fixtures for all seven products.
- [x] Make the download wrapper report when the granule package fails to recognize or correctly parse a product.

`ECOv003-granules` 1.13.2 does not dispatch the current `L1CT_RAD` and `L3T_ETAUX` CMR product names, parses STARS product metadata incorrectly, and assumes ZIP-based file discovery. `granule_compatibility.py` adapts those interfaces locally while continuing to use the dependency's product classes for supported products. A real authenticated data download remains a release-level integration check.

### Phase 4: Point Sampling

- [x] Retain the existing COG range-read and batch-sampling implementation as the starting point.
- [ ] Audit `LAYER_MAPPING` against Collection 3 product availability, variable names, and units.
- [ ] Remove or replace mappings to discontinued `L3T_MET` and `L3T_SM` products. Identify valid Collection 3 replacements, if any, before exposing those layers.
- [ ] Verify the default `L2T_LSTE` / `L2T_STARS` layers against Collection 3 files, including temperature conversion and nodata handling.
- [ ] Add tests for supported mappings and rejection of unsupported layers/products.
- [ ] Run point-sampling examples against Collection 3 data or stable fixtures.

Preserve the current no-full-download COG sampling approach unless Collection 3 validation demonstrates a specific incompatibility.

### Phase 5: Examples, Documentation, and Tests

- [ ] Update `README.md` installation instructions, imports, product list, and API examples to `ECOv003-CMR`.
- [ ] Update `POINT_SAMPLING_INTEGRATION.md` and `examples/README.md` to describe Collection 3.
- [ ] Check each example's product names, layer mappings, filename assumptions, and import paths.
- [ ] Replace stale `ECOv002_CMR` test patch targets and rename tests that still imply the old package.
- [x] Add mock-based CMR search/download-adapter tests and Collection 3 filename/parser regressions.
- [x] Run the complete test suite in the `ECOv003-CMR` mamba environment (36 passed).

## 5. Immediate Priorities

1. Correct the package version lookup and verify import from a clean Collection 3 installation.
2. Resolve stale point-sampling mappings against the actual Collection 3 catalog.
3. Validate point-sampling layers and behavior against Collection 3 files.
4. Update tests and docs, then run CI and end-to-end search/sampling checks.

## 6. Risks and Decision Points

> **CMR metadata:** Concept IDs can change or become unavailable. Verify the recorded IDs and representative results against CMR before release.

> **Product differences:** Collection 3 does not include the Collection 2 `L3T_MET`, `L3T_SM`, and `L3T_SEB` products. Sampling mappings and user documentation must reflect supported Collection 3 products rather than assuming a direct name-for-name migration.

> **Download integration:** Parser and local open behavior pass fixture tests, but a real authenticated Collection 3 download should be verified before release.

> **Release readiness:** A passing import test is insufficient. Verify clean installation, CLI behavior, live or fixture-backed search, download/open flow, and point sampling before publishing.
