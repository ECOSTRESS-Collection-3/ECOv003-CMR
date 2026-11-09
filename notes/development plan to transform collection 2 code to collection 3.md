# ECOv003-CMR Development Plan & Status

## 1. Objectives and Current Status

This plan tracks the transformation of the ECOSTRESS Collection 2 CMR package into a standalone Collection 3 package, including CMR search, granule downloads, and Cloud-Optimized GeoTIFF (COG) point sampling.

**Status snapshot: 2026-11-09.** The package structure and Collection 3 CMR metadata are in place, but several Collection 2 assumptions remain in point sampling, filename handling, tests, and documentation. Overall, the work is estimated at **about 40% complete toward a production-ready Collection 3 package**. This is a readiness estimate, not a measure of coding effort.

| Phase | Status | Summary |
|---|---|---|
| 1. Repository and packaging | Complete | Editable install, wheel contents, package import, and both CLI help commands are verified using the `ECOv003-CMR` mamba environment. |
| 2. CMR metadata and search | Mostly complete | Search and download use the Collection 3 concept-ID map. Seven product IDs are recorded; verify actual CMR queries and result parsing end to end. |
| 3. Filename parsing | Not verified | Filename parsers were carried over. Validate them against real Collection 3 granule names and add focused tests. |
| 4. Point sampling | Partial | COG sampling logic is carried over, but layer mappings still refer to Collection 2 products that were discontinued. |
| 5. Examples, documentation, and tests | Partial | Examples and tests exist, but documentation still describes Collection 2 and some tests refer to the old import path. |

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
| CMR search | Uses the Collection 3 concept-ID map | Test representative searches, empty results, pagination, and parsed Collection 3 URLs/granules. |
| Downloads | Defaults to `~/data/ECOSTRESS_v003` and delegates granule opening to `ECOv003-granules` | Validate granule IDs, output paths, and successful opening with real or representative Collection 3 data. |
| Filename interpreters | Carried over without demonstrated Collection 3 validation | Confirm product, granule ID, and variable parsing on Collection 3 filenames; add tests. |
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
- [ ] Verify representative concept IDs and searches against the live CMR API.
- [ ] Confirm result parsing, granule names, file links, and multi-page search behavior for Collection 3.

The current map covers `L1CT_RAD`, `L2T_LSTE`, `L2T_STARS`, `L3T_ETAUX`, `L3T_JET`, `L4T_ESI`, and `L4T_WUE`. Collection 2 products `L3T_MET`, `L3T_SM`, and `L3T_SEB` were discontinued in Collection 3; do not retain them as Collection 3 search or sampling options unless a supported replacement is verified.

### Phase 3: Filename Interpreters and Parser Rules

- [ ] Collect representative Collection 3 filenames across supported products and file variables.
- [ ] Audit `product_name_from_filename.py`, `granule_ID_from_filename.py`, and `variable_from_filename.py` against those names.
- [ ] Add focused tests for product, granule ID, and variable parsing, including edge cases.
- [ ] Confirm parsed granule IDs are accepted by `ECOv003-granules` and the download workflow.

Do not assume Collection 2 filename positions or prefixes are valid for Collection 3 solely because the parser code is reusable.

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
- [ ] Add mock-based CMR search/download tests and Collection 3 filename/parser regressions.
- [ ] Run the complete test suite in an environment installed from the current project dependencies.

## 5. Immediate Priorities

1. Correct the package version lookup and verify import from a clean Collection 3 installation.
2. Resolve stale point-sampling mappings against the actual Collection 3 catalog.
3. Validate filename parsing and download/open behavior with representative Collection 3 granules.
4. Update tests and docs, then run CI and end-to-end search/sampling checks.

## 6. Risks and Decision Points

> **CMR metadata:** Concept IDs can change or become unavailable. Verify the recorded IDs and representative results against CMR before release.

> **Product differences:** Collection 3 does not include the Collection 2 `L3T_MET`, `L3T_SM`, and `L3T_SEB` products. Sampling mappings and user documentation must reflect supported Collection 3 products rather than assuming a direct name-for-name migration.

> **Filename compatibility:** Parsers were reused without Collection 3-specific regression evidence. A successful CMR query alone does not establish that granule and variable parsing or downstream downloads work.

> **Release readiness:** A passing import test is insufficient. Verify clean installation, CLI behavior, live or fixture-backed search, download/open flow, and point sampling before publishing.
