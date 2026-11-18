# ECOv003-CMR v1.0.1 to v1.1.0 Development Plan

**Status:** Proposed  
**Prepared:** 2026-11-18  
**Target repository:** `ECOSTRESS-Collection-3/ECOv003-CMR`  
**Target release:** `v1.1.0`

## 1. Objective

Resolve functional bugs and integration gaps identified in the `v1.0.1` codebase audit—specifically authenticated granule downloads, sequential multi-point sampling, CLI logging/error output, and repository hygiene—while maintaining full backward compatibility with the existing `ECOv003_CMR` public API.

## 2. Summary of Findings in v1.0.1

| Area | File(s) | Observed Behavior | Desired Behavior |
|---|---|---|---|
| **Authenticated Downloads** | `ECOv003_CMR/download_file.py`, `download_ECOSTRESS_granule_files.py`, `download_ECOSTRESS_granule.py`, `download_ECOSTRESS.py` | `download_file()` uses unauthenticated `requests.get()`, failing on protected LP DAAC Earthdata Cloud assets. | Accept and propagate an authenticated `requests.Session` (defaulting to `setup_earthdata_session()`). |
| **CLI Error & Info Logging** | `ECOv003_CMR/download_ECOSTRESS.py`, `ECOSTRESS_CMR_search.py` | `logger.info(..., file=sys.stderr)` raises `TypeError` on exception; neither CLI configures logging, resulting in silent console runs. | Configure CLI logging cleanly and use `logger.error()` / `sys.stderr` properly. |
| **Sequential Point Sampling** | `ECOv003_CMR/point_sampling.py` | In `sample_points_over_date_range(..., max_workers=1)`, `stars_only_dates` and `primary_dates` loops are outside the `for idx, point, metadata in points_data:` loop, skipping earlier points or raising `UnboundLocalError`. | Indent both blocks inside the per-point loop so multi-point sequential execution matches parallel execution. |
| **Multi-Day Download Date Propagation** | `ECOv003_CMR/download_ECOSTRESS.py` | Passes `aquisition_date=start_date` for every granule across multi-day ranges. | Extract each granule's actual acquisition date from its identifier. |
| **Progress Bar Import** | `ECOv003_CMR/download_file.py` | Imports `tqdm.notebook.tqdm`, emitting widget warnings in terminal/CLI contexts. | Use `tqdm.auto.tqdm` for seamless CLI and notebook rendering. |
| **Parameter Spelling** | `ECOv003_CMR/download_ECOSTRESS_granule.py`, `download_ECOSTRESS_granule_files.py` | Parameter is spelled `aquisition_date` (missing `c`). | Support `acquisition_date` as primary while keeping `aquisition_date` as a backward-compatible alias. |
| **Packaging & Repo Hygiene** | `pyproject.toml`, `makefile`, root debug scripts | Duplicate `pytest` entry in `[project.optional-dependencies]`; `make test-integration` points to nonexistent files; root debug scripts reference `2022` Collection 2 dates/packages. | Deduplicate dependencies, update/remove dead Makefile targets, and clean up or update root debug scripts. |

---

## 3. Implementation Phases

### Phase 1: Authenticated Download Pipeline & Progress Reporting

- [ ] Update `download_file()` in `ECOv003_CMR/download_file.py` to accept `session: Optional[requests.Session] = None`, initializing via `setup_earthdata_session()` when not provided.
- [ ] Replace `from tqdm.notebook import tqdm` with `from tqdm.auto import tqdm` in `ECOv003_CMR/download_file.py`.
- [ ] Propagate `session: Optional[requests.Session] = None` through:
  - `download_ECOSTRESS_granule_files()`
  - `download_ECOSTRESS_granule()`
  - `download_ECOSTRESS()`
- [ ] Support `acquisition_date` alongside `aquisition_date` (deprecated alias) in `download_ECOSTRESS_granule()` and `download_ECOSTRESS_granule_files()`.
- [ ] Derive the per-granule acquisition date when iterating over multi-day search results in `download_ECOSTRESS()`.

### Phase 2: Point Sampling Reliability

- [ ] Fix loop indentation in the `max_workers == 1` branch of `sample_points_over_date_range()` (`ECOv003_CMR/point_sampling.py`) so `stars_only_dates` and standalone `L3T_`/`L4T_` granules are evaluated for **every** point in `points_data`.
- [ ] Guard against `UnboundLocalError` when earlier points in `points_data` have no matching granules.
- [ ] Verify parity between `max_workers=1` and `max_workers>1` outputs across mixed `L2T_LSTE`, `L2T_STARS`, and `L3T_ETAUX` inputs.

### Phase 3: CLI Experience & Logging

- [ ] Fix `logger.info(f"Error: {err}", file=sys.stderr)` in `ECOv003_CMR/download_ECOSTRESS.py` by replacing it with `logger.error(f"Error: {err}")`.
- [ ] Add basic logging configuration in `ECOSTRESS_CMR_search.main()` and `download_ECOSTRESS.main()` so informational progress and granule listings appear on console runs by default.
- [ ] Add `--quiet` / `--verbose` flags if needed, or ensure clean stdout/stderr separation when piping results.

### Phase 4: Repository & Packaging Cleanup

- [ ] Remove duplicate `"pytest"` entry under `[project.optional-dependencies] -> dev` in `pyproject.toml`.
- [ ] Bump version in `pyproject.toml` from `1.0.1` to `1.1.0`.
- [ ] Update or remove the broken `test-integration` target in `makefile`.
- [ ] Audit root-level debug scripts (`debug_lst_sampling.py`, `debug_stars_search.py`, `querying_ECOSTRESS_at_points.py`): update to Collection 3 (`2026` dates, `ECOv003_CMR` imports) or remove obsolete Collection 2 scratch files.

### Phase 5: Testing & Pre-Release Validation

- [ ] Add unit tests in `tests/test_download_ECOSTRESS_granule.py` verifying:
  - `session` propagation into `download_file()`.
  - `acquisition_date` and `aquisition_date` compatibility.
  - CLI `main()` error handling and console output without `TypeError`.
- [ ] Add unit tests in `tests/test_point_sampling.py` covering multi-point sequential sampling (`max_workers=1`) with STARS-only and ETAUX-only dates, including points with empty granule lists.
- [ ] Run full offline test suite (`pytest`) across Python 3.11–3.14.
- [ ] Execute live authenticated end-to-end checks against Earthdata Cloud:
  - Download and open `L2T_LSTE`, `L2T_STARS`, and `L3T_ETAUX` granules via `download_ECOSTRESS_granule()` and `ECOv003-download`.
  - Sample points over a June 2026 date range via `sample_points_over_date_range()`.
- [ ] Build wheel and sdist (`python -m build`), verify package metadata, and tag `v1.1.0`.

---

## 4. Acceptance Criteria

1. `download_ECOSTRESS_granule()` and `ECOv003-download` successfully authenticate using `~/.netrc`, environment variables, or an explicit `requests.Session`.
2. `ECOv003-search` and `ECOv003-download` display progress/results cleanly on stdout and report errors to stderr without raising `TypeError`.
3. `sample_points_over_date_range(..., max_workers=1)` produces identical results to `max_workers > 1` for multi-point GeoDataFrames across all supported products.
4. All existing and newly added unit tests pass (`pytest`), and live authenticated smoke tests succeed before tagging `v1.1.0`.