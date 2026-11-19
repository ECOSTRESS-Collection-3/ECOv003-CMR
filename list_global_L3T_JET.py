#!/usr/bin/env python3
"""
Efficiently export all globally available ECOSTRESS Collection 3 L3T_JET scenes
and their cloud cover percentages to CSV using NASA CMR's lightweight UMM-JSON
API with CMR-Search-After pagination.
"""

import argparse
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from tqdm.auto import tqdm

CMR_UMM_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
L3T_JET_CONCEPT_ID = "C4057232489-LPCLOUD"
TRANSIENT_HTTP_STATUS = {429, 500, 502, 503, 504}


def _get_with_backoff(
    session: requests.Session,
    url: str,
    params: Dict[str, Any],
    headers: Dict[str, str],
    max_retries: int = 5,
    backoff_base: float = 1.5,
    timeout: Tuple[float, float] = (15.0, 60.0),
) -> requests.Response:
    for attempt in range(max_retries):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code in TRANSIENT_HTTP_STATUS and attempt < max_retries - 1:
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else backoff_base ** (attempt + 1)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt >= max_retries - 1:
                raise
            time.sleep(backoff_base ** (attempt + 1))
    raise RuntimeError(f"CMR request failed after {max_retries} retries")


def fetch_global_l3t_jet_scenes(
    start_date: str = "2025-10-31",
    end_date: str = "2026-10-31",
    max_cloud_cover: Optional[float] = None,
) -> pd.DataFrame:
    """
    Query all global ECOSTRESS Collection 3 L3T_JET scenes via CMR UMM-JSON
    (omitting verbose asset link arrays for ~5x smaller payloads) and return a
    deduplicated DataFrame sorted chronologically.
    """
    params: Dict[str, Any] = {
        "concept_id": L3T_JET_CONCEPT_ID,
        "temporal": f"{start_date}T00:00:00Z,{end_date}T23:59:59Z",
        "page_size": 2000,
    }
    if max_cloud_cover is not None:
        params["cloud_cover"] = f"0,{max_cloud_cover}"

    session = requests.Session()
    headers: Dict[str, str] = {}
    previous_search_after: Optional[str] = None
    rows: List[Dict[str, Any]] = []
    total_hits: Optional[int] = None

    with tqdm(desc="Fetching L3T_JET catalog", unit="scene") as pbar:
        while True:
            resp = _get_with_backoff(session, CMR_UMM_URL, params=params, headers=headers)
            if total_hits is None:
                hits_hdr = resp.headers.get("CMR-Hits")
                if hits_hdr and hits_hdr.isdigit():
                    total_hits = int(hits_hdr)
                    pbar.total = total_hits
                    pbar.refresh()

            items = resp.json().get("items", [])
            if not items:
                break

            for item in items:
                umm = item.get("umm", {})
                granule_ur = umm.get("GranuleUR", "")
                parts = granule_ur.split("_")

                range_dt = (
                    umm.get("TemporalExtent", {})
                    .get("RangeDateTime", {})
                )
                time_start = range_dt.get("BeginningDateTime")
                time_end = range_dt.get("EndingDateTime")
                cloud_cover = umm.get("CloudExtent", {}).get("CloudCover")

                rows.append(
                    {
                        "granule": granule_ur,
                        "orbit": int(parts[3]) if len(parts) > 6 and parts[3].isdigit() else None,
                        "scene": int(parts[4]) if len(parts) > 6 and parts[4].isdigit() else None,
                        "tile": parts[5] if len(parts) > 6 else None,
                        "timestamp": parts[6] if len(parts) > 6 else None,
                        "time_start": time_start,
                        "time_end": time_end,
                        "cloud_cover": float(cloud_cover) if cloud_cover is not None else None,
                    }
                )

            pbar.update(len(items))

            search_after = resp.headers.get("CMR-Search-After")
            if not search_after:
                break
            if search_after == previous_search_after:
                raise RuntimeError("CMR repeated a Search-After token; stopping pagination")
            previous_search_after = search_after
            headers = {"CMR-Search-After": search_after}

    df = pd.DataFrame(rows)
    if not df.empty:
        df = (
            df.drop_duplicates(subset=["granule"])
            .sort_values(["timestamp", "tile"], kind="mergesort")
            .reset_index(drop=True)
        )
    return df


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
        help="Optional server-side maximum cloud cover percentage (e.g., 20.0)",
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

    print(f"\nSaved {len(df):,} unique L3T_JET scenes to {output_path.resolve()} in {elapsed:.2f}s")
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