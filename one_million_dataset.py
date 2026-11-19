#!/usr/bin/env python3
"""
First-pass global 1,000,000-observation stratified ECOSTRESS Collection 3 dataset
generator.

Usage:
    # Full global 1M-sample run across a multi-month window (resumable via checkpoint manifest)
    python one_million_dataset.py \
        --start-date 2026-06-01 \
        --end-date 2026-09-30 \
        --output-dir ./uq_dataset_1m

    # Fast pilot run on a subset of tiles before launching the global pass
    python one_million_dataset.py \
        --start-date 2026-06-01 \
        --end-date 2026-06-30 \
        --tiles 11SLT 11SPS 52NHN 53NMH \
        --target-samples 10000 \
        --min-granules-floor 2 \
        --output-dir ./uq_dataset_pilot
"""

import argparse
from datetime import datetime
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


def configure_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "one_million_dataset.log"

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
        description="Generate a 1M-observation globally stratified ECOSTRESS Collection 3 UQ training dataset."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./uq_dataset_1m",
        help="Directory for partitioned Parquet outputs, checkpoint manifest, and catalog cache (default: ./uq_dataset_1m).",
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
        default="2026-10-31",
        help="Acquisition window end date in YYYY-MM-DD format (default: 2026-10-31).",
    )
    parser.add_argument(
        "--tiles",
        type=str,
        nargs="+",
        default=None,
        help="Optional subset of Sentinel-2 MGRS tiles (e.g. 11SLT 11SPS). Omit to run globally across all land tiles.",
    )
    parser.add_argument(
        "--target-samples",
        type=int,
        default=1_000_000,
        help="Target total number of valid multi-layer observations (default: 1,000,000).",
    )
    parser.add_argument(
        "--min-granules-floor",
        type=int,
        default=4,
        help="Minimum clear-sky overpasses required for a tile to be included in N_cap balancing (default: 4).",
    )
    parser.add_argument(
        "--max-cloud-cover",
        type=float,
        default=20.0,
        help="Maximum CMR granule cloud cover percentage (default: 20.0).",
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
        default=8,
        help="Concurrent granule workers (default: 8).",
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
        "--refresh-catalog",
        action="store_true",
        help="Force a fresh CMR discovery query instead of reusing candidate_granules.parquet.",
    )
    parser.add_argument(
        "--export-csv",
        action="store_true",
        help="Also write CSV alongside each partitioned Parquet file.",
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
    logger = logging.getLogger("one_million_dataset")

    logger.info("Starting ECOSTRESS Collection 3 UQ dataset build")
    logger.info(
        f"Configuration: window={args.start_date}..{args.end_date}, "
        f"target_samples={args.target_samples:,}, min_granules_floor={args.min_granules_floor}, "
        f"max_cloud_cover={args.max_cloud_cover}%, workers={args.max_workers}x{args.layer_workers} "
        f"(streams={args.max_concurrent_streams}, batch_size={args.batch_size})"
    )

    session = setup_earthdata_session(require_auth=True)

    summary = build_stratified_dataset(
        output_dir=str(output_dir),
        start_date=args.start_date,
        end_date=args.end_date,
        tiles=args.tiles,
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
        refresh_catalog=args.refresh_catalog,
        export_csv=args.export_csv,
        random_state=args.seed,
        session=session,
        verbose=True,
    )

    summary_path = output_dir / "dataset_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at_utc": datetime.utcnow().isoformat() + "Z",
                "config": vars(args),
                "summary": _serialize_summary(summary),
            },
            f,
            indent=2,
        )

    print("\n=== UQ Dataset Generation Summary ===")
    print(f"Output directory  : {output_dir.resolve()}")
    print(f"Collected samples : {summary.get('total_samples', 0):,}")
    print(f"Selected granules : {summary.get('selected_granules', 0):,} (N_cap={summary.get('n_cap', 0)}, K={summary.get('quota_k', 0)})")

    perf = summary.get("performance", {})
    if perf:
        print(f"Total wall time   : {perf.get('timings_s', {}).get('total_s', 0):.2f}s")
        print(f"Mean per-granule  : {perf.get('mean_granule_latency_s', 0):.2f}s")
        print(f"Throughput        : {perf.get('samples_per_second', 0):.2f} samples/s")

    coverage = summary.get("coverage_summary")
    if coverage is not None and not coverage.empty:
        print("\nLayer Coverage:")
        print(coverage.to_string(index=False))

    print(f"\nSaved run metadata to {summary_path}")


if __name__ == "__main__":
    main()