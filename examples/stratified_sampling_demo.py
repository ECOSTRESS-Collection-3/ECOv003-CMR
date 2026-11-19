#!/usr/bin/env python3
"""
Small-scale demonstration of global/regional stratified point-sample dataset
construction using ECOv003-CMR v1.2.0 with verbose console progress logging
and performance timing benchmarks.
"""

from datetime import date
import logging
from ECOv003_CMR import build_stratified_dataset, setup_earthdata_session

# Enable detailed console logs for ECOv003_CMR and HTTP/GDAL progress
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

session = setup_earthdata_session()

summary = build_stratified_dataset(
    output_dir="./stratified_dataset_test",
    start_date=date(2026, 6, 1),
    end_date=date(2026, 6, 7),
    tiles=["11SLT"],
    target_total_samples=25,
    min_granules_floor=1,
    dispersion_strategy="stratified_grid",
    max_workers=2,
    export_csv=True,
    session=session,
    verbose=True,
)

print("\n=== Stratified Dataset Summary ===")
print(f"Collected samples : {summary['total_samples']}")
print(f"Selected granules : {summary['selected_granules']} (N_cap={summary['n_cap']})")

if "performance" in summary:
    perf = summary["performance"]
    timings = perf["timings_s"]
    assump = perf["amortized_assumptions"]
    print("\n=== Performance Benchmarks & 1M Extrapolation ===")
    print(f"Auth & Tile Setup    : {timings.get('auth_s', 0) + timings.get('tile_discovery_s', 0):.2f}s")
    print(f"CMR Granule Search   : {timings.get('cmr_search_s', 0):.2f}s")
    print(f"Cookie Pre-Warmup    : {timings.get('cookie_warmup_s', 0):.2f}s")
    print(f"COG Extraction Wall  : {timings.get('extraction_s', 0):.2f}s")
    print(f"Parquet Aggregation  : {timings.get('aggregation_s', 0):.2f}s")
    print(f"Total Wall Time      : {timings.get('total_s', 0):.2f}s")
    print(f"Mean Granule Latency : {perf['mean_granule_latency_s']:.2f}s / granule")
    print(f"Throughput           : {perf['samples_per_second']:.2f} samples/s")
    print(
        f"1M Extrapolation (naive linear @ {perf['samples_per_second']:.2f} samples/s) : "
        f"{perf['linear_1m_estimate_human']}"
    )
    print(
        f"1M Extrapolation (amortized @ {assump['global_granules']:,} granules, "
        f"K={assump['points_per_granule_K']}, {assump['workers']} workers) : "
        f"{perf['amortized_global_1m_estimate_human']}"
    )

if "coverage_summary" in summary and not summary["coverage_summary"].empty:
    print("\nLayer Coverage:")
    print(summary["coverage_summary"].to_string(index=False))