#!/usr/bin/env python3
"""
Scale example 100-observation stratified ECOSTRESS Collection 3 dataset
generator accompanying the full-scale one_million_dataset.py runner.

Usage:
    # Fast multi-biome 100-sample pilot run (~35-50s end-to-end, including humid tropical tile)
    python one_hundred_dataset.py

    # Pre-flight capacity plan dry-run without downloading COGs
    python one_hundred_dataset.py --dry-run

    # Sample 100 observations globally by reusing the 1M run's cached catalog
    python one_hundred_dataset.py --tiles-global --start-date 2025-10-31 --end-date 2026-10-31 --min-granules-floor 4
"""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict

from ECOv003_CMR import (
    UQ_LAYERS,
    build_stratified_dataset,
    setup_earthdata_session,
)

# Includes 20LLQ (Amazon tropical) to exercise sidecar QAPercentCloudCover rejection & backfill
DEFAULT_PILOT_TILES = ["11SLT", "11SPS", "52NHN", "53NMH", "20LLQ"]
SHARED_1M_CATALOG = Path("./experimental_data/one_million_dataset/candidate_granules.parquet")


def configure_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "one_hundred_dataset.log"

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a 100-observation stratified ECOSTRESS Collection 3 UQ scale-example dataset."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./experimental_data/one_hundred_dataset",
        help="Directory for partitioned Parquet outputs, checkpoint manifest, and catalog cache.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2026-06-01",
        help="Acquisition window start date in YYYY-MM-DD format (default: 2026-06-01).",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2026-06-30",
        help="Acquisition window end date in YYYY-MM-DD format (default: 2026-06-30).",
    )
    parser.add_argument(
        "--tiles",
        type=str,
        nargs="+",
        default=DEFAULT_PILOT_TILES,
        help="Subset of Sentinel-2 MGRS tiles for the fast scale example.",
    )
    parser.add_argument(
        "--tiles-global",
        action="store_true",
        help="Override --tiles and run across all global land-intersecting Sentinel-2 MGRS tiles.",
    )
    parser.add_argument(
        "--target-samples",
        type=int,
        default=100,
        help="Target total number of valid multi-layer observations (default: 100).",
    )
    parser.add_argument(
        "--min-granules-floor",
        type=int,
        default=2,
        help="Minimum clear-sky overpasses required for a tile to be included in N_cap balancing (default: 2).",
    )
    parser.add_argument(
        "--max-cloud-cover",
        type=float,
        default=20.0,
        help="Maximum sidecar QAPercentCloudCover percentage (default: 20.0).",
    )
    parser.add_argument(
        "--dispersion-strategy",
        type=str,
        choices=["stratified_grid", "uniform"],
        default="stratified_grid",
        help="Intra-granule spatial sampling strategy (default: stratified_grid).",
    )
    parser.add_argument(
        "--grid-divisions",
        type=int,
        default=6,
        help="Grid subdivisions per axis when using stratified_grid dispersion (default: 6).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Concurrent granule workers (default: 4).",
    )
    parser.add_argument(
        "--layer-workers",
        type=int,
        default=8,
        help="Concurrent COG variable threads per granule (default: 8).",
    )
    parser.add_argument(
        "--max-concurrent-streams",
        type=int,
        default=32,
        help="Process-wide semaphore cap on simultaneous /vsicurl/ HTTP streams (default: 32).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="Granules per synchronous URS cookie re-warm window (default: 250).",
    )
    parser.add_argument(
        "--catalog-path",
        type=str,
        default=None,
        help="Optional path to a shared candidate_granules.parquet catalog cache.",
    )
    parser.add_argument(
        "--refresh-catalog",
        action="store_true",
        help="Force a fresh CMR discovery query instead of reusing candidate_granules.parquet.",
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        default=True,
        help="Write CSV alongside each partitioned Parquet file (default: True).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery and stratification capacity planning only without reading COGs.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible granule and pixel sampling (default: 42).",
    )
    return parser.parse_args()


def _serialize_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    serializable = {}
    for key, value in summary.items():
        if hasattr(value, "to_dict"):
            serializable[key] = value.to_dict(orient="records")
        else:
            serializable[key] = value
    return serializable


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    configure_logging(output_dir)
    logger = logging.getLogger("one_hundred_dataset")

    selected_tiles = None if args.tiles_global else args.tiles
    catalog_path = args.catalog_path
    if catalog_path is None and args.tiles_global and SHARED_1M_CATALOG.exists():
        catalog_path = str(SHARED_1M_CATALOG)
        logger.info(f"Auto-reusing shared global catalog cache: {catalog_path}")

    logger.info("Starting ECOSTRESS Collection 3 UQ 100-observation scale example")
    logger.info(
        f"Configuration: window={args.start_date}..{args.end_date}, "
        f"tiles={'GLOBAL' if selected_tiles is None else ','.join(selected_tiles)}, "
        f"target_samples={args.target_samples:,}, min_granules_floor={args.min_granules_floor}, "
        f"max_cloud_cover={args.max_cloud_cover}%, dry_run={args.dry_run}, "
        f"workers={args.max_workers}x{args.layer_workers} "
        f"(streams={args.max_concurrent_streams}, batch_size={args.batch_size})"
    )

    session = setup_earthdata_session(require_auth=True)

    summary = build_stratified_dataset(
        output_dir=str(output_dir),
        start_date=args.start_date,
        end_date=args.end_date,
        tiles=selected_tiles,
        target_total_samples=args.target_samples,
        min_granules_floor=args.min_granules_floor,
        dispersion_strategy=args.dispersion_strategy,
        grid_divisions=args.grid_divisions,
        layers=UQ_LAYERS,
        max_cloud_cover=args.max_cloud_cover,
        max_workers=args.max_workers,
        layer_workers=args.layer_workers,
        max_concurrent_streams=args.max_concurrent_streams,
        batch_size=args.batch_size,
        catalog_path=catalog_path,
        refresh_catalog=args.refresh_catalog,
        export_csv=args.export_csv,
        dry_run=args.dry_run,
        random_state=args.seed,
        session=session,
        verbose=True,
    )

    summary_path = output_dir / "dataset_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "config": vars(args),
                "summary": _serialize_summary(summary),
            },
            f,
            indent=2,
        )

    print("\n=== UQ 100-Observation Scale Example Summary ===")
    print(f"Output directory  : {output_dir.resolve()}")
    print(f"Dry run           : {summary.get('dry_run', False)}")
    print(f"Collected samples : {summary.get('total_samples', 0):,}")
    print(f"Selected granules : {summary.get('selected_granules', 0):,} (N_cap={summary.get('n_cap', 0)}, K={summary.get('quota_k', 0)})")

    plan = summary.get("stratification_plan")
    if plan is not None and not plan.empty:
        print("\nPre-Flight Stratification Plan:")
        print(plan.to_string(index=False))

    perf = summary.get("performance", {})
    if perf and not args.dry_run:
        print(f"\nTotal wall time   : {perf.get('timings_s', {}).get('total_s', 0):.2f}s")
        print(f"Mean per-granule  : {perf.get('mean_granule_latency_s', 0):.2f}s")
        print(f"Throughput        : {perf.get('samples_per_second', 0):.2f} samples/s")

    coverage = summary.get("coverage_summary")
    if coverage is not None and not coverage.empty:
        print("\nLayer Coverage:")
        print(coverage.to_string(index=False))

    print(f"\nSaved run metadata to {summary_path}")


if __name__ == "__main__":
    main()
