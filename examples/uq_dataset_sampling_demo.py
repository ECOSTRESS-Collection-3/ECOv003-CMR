#!/usr/bin/env python3
"""
Small-scale demonstration of global stratified UQ training dataset construction
using ECOv003-CMR v1.2.0 with verbose console progress logging.
"""

from datetime import date
import logging
from ECOv003_CMR import build_uq_training_dataset, setup_earthdata_session

# Enable detailed console logs for ECOv003_CMR and HTTP/GDAL progress
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

session = setup_earthdata_session()

summary = build_uq_training_dataset(
    output_dir="./uq_dataset_test",
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

print("\n=== UQ Dataset Test Summary ===")
print(f"Collected samples : {summary['total_samples']}")
print(f"Selected granules : {summary['selected_granules']} (N_cap={summary['n_cap']})")
if "coverage_summary" in summary and not summary["coverage_summary"].empty:
    print("\nLayer Coverage:")
    print(summary["coverage_summary"].to_string(index=False))