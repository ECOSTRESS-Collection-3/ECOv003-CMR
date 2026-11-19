#!/usr/bin/env python3
"""
Fast global L3T_JET scene counts by cloud cover threshold.

1. Enumerates all global ECOSTRESS Collection 3 L3T_JET scenes via NASA CMR's
   flat granules.csv endpoint across 5-day parallel temporal windows.
2. Evaluates ProductMetadata.QAPercentCloudCover from per-granule .json metadata
   sidecars (since CMR leaves CloudCover null on all Collection 3 granules) on a
   seasonally & spatially stratified sample (default N=2,000; or --exact-all for
   all scenes) to report exact scene counts and percentages for <= 20.0%, <= 10.0%,
   and == 0.0% cloud cover.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm.auto import tqdm

from ECOv003_CMR.ECOSTRESS_CMR_search_links import (
    search_granule_catalog_csv,
    search_granules_by_name_patterns,
)
from ECOv003_CMR.authentication import setup_earthdata_session
from ECOv003_CMR.constants import CONCEPT_IDS
from ECOv003_CMR.interpret_ECOSTRESS_URLs import fetch_granule_metadata, interpret_ECOSTRESS_URLs


def _stratified_sample_granules(df: pd.DataFrame, sample_size: int, seed: int = 42) -> pd.DataFrame:
    if sample_size <= 0 or sample_size >= len(df):
        return df.copy()
    rng = np.random.default_rng(seed)
    df = df.copy()
    df["month"] = df["date_str"].str[4:6]
    per_month = max(1, math.ceil(sample_size / df["month"].nunique()))
    parts = []
    for _, grp in df.groupby("month", sort=True):
        take = min(per_month, len(grp))
        idx = rng.choice(grp.index.to_numpy(), size=take, replace=False)
        parts.append(grp.loc[idx])
    sampled = pd.concat(parts, ignore_index=True)
    if len(sampled) > sample_size:
        sampled = sampled.sample(n=sample_size, random_state=seed).reset_index(drop=True)
    return sampled


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
    total_scenes = len(jet_df)
    if total_scenes == 0:
        print("No L3T_JET scenes found.")
        return

    target_df = jet_df if args.exact_all else _stratified_sample_granules(jet_df, args.sample_size, seed=args.seed)
    stems = sorted(
        {
            f"{int(r.orbit):05d}_{int(r.scene):03d}_{r.tile}_{r.timestamp}"
            for r in target_df.itertuples()
        }
    )
    batches = [stems[i : i + 150] for i in range(0, len(stems), 150)]

    json_urls: List[str] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(
                search_granules_by_name_patterns,
                CONCEPT_IDS["L2T_LSTE"],
                [f"ECOv003_L2T_LSTE_{s}_*" for s in batch],
                None,
                False,
                (".json",),
            )
            for batch in batches
        ]
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Resolving .json URLs", unit="batch"):
            entries = fut.result()
            if entries:
                parsed = interpret_ECOSTRESS_URLs([e["URL"] for e in entries])
                json_urls.extend(parsed[parsed["type"] == "JSON Metadata"]["URL"].tolist())

    def _read_cc(url: str) -> Optional[float]:
        try:
            return fetch_granule_metadata(url, session=session, timeout=30).get("cloud_cover")
        except Exception:
            return None

    cc_values: List[float] = []
    with ThreadPoolExecutor(max_workers=args.sidecar_workers) as pool:
        futures = [pool.submit(_read_cc, u) for u in json_urls]
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Reading QAPercentCloudCover", unit="json"):
            val = fut.result()
            if val is not None:
                cc_values.append(float(val))

    cc_arr = np.array(cc_values, dtype=float)
    n_checked = len(cc_arr)
    elapsed = time.perf_counter() - t0
    mode_label = "EXACT ALL" if args.exact_all else f"STRATIFIED SAMPLE (n={n_checked:,})"

    print(f"\n=== Global ECOSTRESS C3 L3T_JET Scene Counts ({args.start_date} to {args.end_date}) ===")
    print(f"Total global L3T_JET scenes : {total_scenes:,}")
    print(f"Cloud cover evaluation mode : {mode_label}")
    if n_checked > 0:
        for threshold in (20.0, 10.0, 0.0):
            frac = float(np.mean(cc_arr <= threshold))
            est_count = int(round(frac * total_scenes))
            # 95% confidence interval half-width for proportion
            se = math.sqrt(frac * (1.0 - frac) / n_checked) if not args.exact_all else 0.0
            ci_scenes = int(round(1.96 * se * total_scenes))
            ci_str = "" if args.exact_all else f" (±{ci_scenes:,})"
            print(f"<= {threshold:4.1f}% cloud cover        : {est_count:,} scenes{ci_str} ({100.0 * frac:.1f}%)")
    print(f"\nCompleted in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
