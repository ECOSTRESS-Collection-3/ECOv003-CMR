#!/usr/bin/env python3
"""
Fast global L3T_JET scene counts by cloud cover threshold.

Enumerates all global ECOSTRESS Collection 3 L3T_JET scenes via NASA CMR's
flat granules.csv endpoint and evaluates ProductMetadata.QAPercentCloudCover
from per-granule .json metadata sidecars using estimate_cloud_cover_distribution().
"""

import argparse
import time

from ECOv003_CMR import (
    CONCEPT_IDS,
    estimate_cloud_cover_distribution,
    setup_earthdata_session,
)
from ECOv003_CMR.ECOSTRESS_CMR_search_links import search_granule_catalog_csv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count global ECOSTRESS C3 L3T_JET scenes by sidecar QAPercentCloudCover threshold."
    )
    parser.add_argument("--start-date", type=str, default="2025-10-31")
    parser.add_argument("--end-date", type=str, default="2026-10-31")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=2000,
        help="Stratified sample size for sidecar QAPercentCloudCover inspection (default: 2000).",
    )
    parser.add_argument(
        "--exact-all",
        action="store_true",
        help="Inspect every single granule sidecar instead of using a stratified sample.",
    )
    parser.add_argument("--sidecar-workers", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    t0 = time.perf_counter()
    session = setup_earthdata_session(require_auth=False)

    jet_df = search_granule_catalog_csv(
        concept_ID=CONCEPT_IDS["L3T_JET"],
        start_date=args.start_date,
        end_date=args.end_date,
        chunk_days=5,
        max_workers=6,
        desc="L3T_JET (CMR CSV)",
        verbose=True,
    )
    if jet_df.empty:
        print("No L3T_JET scenes found.")
        return

    census = estimate_cloud_cover_distribution(
        catalog_df=jet_df,
        thresholds=(20.0, 10.0, 0.0),
        sample_size=None if args.exact_all else args.sample_size,
        session=session,
        sidecar_workers=args.sidecar_workers,
        random_state=args.seed,
        verbose=True,
    )

    elapsed = time.perf_counter() - t0
    mode_label = (
        "EXACT ALL"
        if census["is_exact"]
        else f"STRATIFIED SAMPLE (n={census['checked_scenes']:,})"
    )

    print(f"\n=== Global ECOSTRESS C3 L3T_JET Scene Counts ({args.start_date} to {args.end_date}) ===")
    print(f"Total global L3T_JET scenes : {census['total_scenes']:,}")
    print(f"Cloud cover evaluation mode : {mode_label}")
    thresh_df = census["thresholds"]
    if not thresh_df.empty:
        for row in thresh_df.itertuples():
            ci_str = "" if census["is_exact"] else f" (±{row.ci_95_scenes:,})"
            print(
                f"<= {row.max_cloud_cover:4.1f}% cloud cover        : "
                f"{row.estimated_scenes:,} scenes{ci_str} ({row.pass_rate_pct:.1f}%)"
            )

    band_df = census["by_latitude_band"]
    if not band_df.empty:
        print("\nClear-Sky Pass Rate by Latitude Band:")
        print(band_df.to_string(index=False))

    print(f"\nCompleted in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
