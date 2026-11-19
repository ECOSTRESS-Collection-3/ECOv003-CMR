#!/usr/bin/env python3
"""
Export all globally available ECOSTRESS Collection 3 L3T_JET scenes to CSV
using NASA CMR's lightweight granules.csv endpoint across parallel temporal
windows, with optional sidecar QAPercentCloudCover filtering.
"""

import argparse
from pathlib import Path
import time
from typing import Optional

import pandas as pd

from ECOv003_CMR import (
    CONCEPT_IDS,
    setup_earthdata_session,
)
from ECOv003_CMR.ECOSTRESS_CMR_search_links import search_granule_catalog_csv
from ECOv003_CMR.stratified_sampling import resolve_granule_asset_urls


def fetch_global_l3t_jet_scenes(
    start_date: str = "2025-10-31",
    end_date: str = "2026-10-31",
    max_cloud_cover: Optional[float] = None,
) -> pd.DataFrame:
    """
    Enumerate all global ECOSTRESS Collection 3 L3T_JET scenes via CMR granules.csv
    and optionally filter by ProductMetadata.QAPercentCloudCover from .json sidecars.
    """
    session = setup_earthdata_session(require_auth=max_cloud_cover is not None)
    df = search_granule_catalog_csv(
        concept_ID=CONCEPT_IDS["L3T_JET"],
        start_date=start_date,
        end_date=end_date,
        chunk_days=5,
        max_workers=6,
        session=session,
        desc="Fetching L3T_JET catalog (CMR CSV)",
        verbose=True,
    )
    if df.empty:
        return df

    if max_cloud_cover is not None:
        df = resolve_granule_asset_urls(
            granules_df=df,
            max_cloud_cover=max_cloud_cover,
            session=session,
            verbose=True,
        )
        if "variable_urls" in df.columns:
            df = df.drop(columns=["variable_urls"])

    return (
        df.drop_duplicates(subset=["granule"])
        .sort_values(["timestamp", "tile"], kind="mergesort")
        .reset_index(drop=True)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export all globally available ECOSTRESS Collection 3 L3T_JET scenes to CSV."
    )
    parser.add_argument("--start-date", type=str, default="2025-10-31", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-10-31", help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--max-cloud-cover",
        type=float,
        default=None,
        help="Optional maximum sidecar QAPercentCloudCover percentage (e.g., 20.0)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="ecostress_c3_l3t_jet_global_2025-10-31_2026-10-31.csv",
        help="Output CSV file path",
    )
    args = parser.parse_args()

    t0 = time.perf_counter()
    df = fetch_global_l3t_jet_scenes(
        start_date=args.start_date,
        end_date=args.end_date,
        max_cloud_cover=args.max_cloud_cover,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    elapsed = time.perf_counter() - t0

    print(f"
Saved {len(df):,} unique L3T_JET scenes to {output_path.resolve()} in {elapsed:.2f}s")
    if not df.empty:
        print(f"Unique MGRS tiles : {df['tile'].nunique():,}")
        print(f"Date span         : {df['time_start'].min()} -> {df['time_start'].max()}")
        valid_cc = df["cloud_cover"].dropna()
        if not valid_cc.empty:
            print(
                f"Cloud cover (%)   : mean={valid_cc.mean():.1f}%, "
                f"median={valid_cc.median():.1f}%, <=20%={(valid_cc <= 20.0).sum():,} scenes"
            )


if __name__ == "__main__":
    main()
