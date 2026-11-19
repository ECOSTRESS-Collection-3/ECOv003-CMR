#!/usr/bin/env python3
"""
Fast global L3T_JET scene counts by cloud cover threshold using NASA CMR's
lightweight granules.csv endpoint (no spatial polygons or asset URL arrays)
and 5-day parallel temporal windows.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import io
import time
from typing import List, Optional, Tuple

import pandas as pd
import requests
from tqdm.auto import tqdm

CMR_CSV_URL = "https://cmr.earthdata.nasa.gov/search/granules.csv"
L3T_JET_CONCEPT_ID = "C4057232489-LPCLOUD"
L2T_LSTE_CONCEPT_ID = "C3998139651-LPCLOUD"


def _date_windows(start_str: str, end_str: str, chunk_days: int = 5) -> List[Tuple[date, date]]:
    s = date.fromisoformat(start_str)
    e = date.fromisoformat(end_str)
    windows = []
    cur = s
    while cur <= e:
        w_end = min(e, cur + timedelta(days=chunk_days - 1))
        windows.append((cur, w_end))
        cur = w_end + timedelta(days=1)
    return windows


def _fetch_csv_window(
    concept_id: str,
    window: Tuple[date, date],
    max_cloud_cover: Optional[float] = None,
) -> pd.DataFrame:
    w_start, w_end = window
    params = {
        "concept_id": concept_id,
        "temporal": f"{w_start}T00:00:00Z,{w_end}T23:59:59Z",
        "page_size": 2000,
    }
    if max_cloud_cover is not None:
        params["cloud_cover"] = f"0,{max_cloud_cover}"

    frames = []
    headers = {}
    prev_token = None
    sess = requests.Session()

    while True:
        resp = sess.get(CMR_CSV_URL, params=params, headers=headers, timeout=(15, 60))
        resp.raise_for_status()
        text = resp.text.strip()
        if not text:
            break
        df_page = pd.read_csv(io.StringIO(text))
        if df_page.empty:
            break
        frames.append(df_page)

        token = resp.headers.get("CMR-Search-After")
        if not token or token == prev_token:
            break
        prev_token = token
        headers = {"CMR-Search-After": token}

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_cmr_csv_catalog(
    concept_id: str,
    start_date: str,
    end_date: str,
    max_cloud_cover: Optional[float] = None,
    chunk_days: int = 5,
    max_workers: int = 16,
    desc: str = "CMR CSV",
) -> pd.DataFrame:
    windows = _date_windows(start_date, end_date, chunk_days=chunk_days)
    frames = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_fetch_csv_window, concept_id, w, max_cloud_cover) for w in windows]
        for fut in tqdm(as_completed(futures), total=len(windows), desc=desc, unit="win"):
            df = fut.result()
            if not df.empty:
                frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["granule", "join_key", "cloud_cover"])

    raw = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Granule UR"])
    # Strip product prefix ('ECOv003_L3T_JET_' or 'ECOv003_L2T_LSTE_') and build suffix ('_01')
    # leaving exact '<ORBIT>_<SCENE>_<TILE>_<TIMESTAMP>' join key
    parts = raw["Granule UR"].str.split("_")
    raw["join_key"] = parts.str[3:7].str.join("_")
    raw["cloud_cover"] = pd.to_numeric(raw.get("Cloud Cover"), errors="coerce")
    return raw[["Granule UR", "join_key", "cloud_cover"]].rename(columns={"Granule UR": "granule"})


def main(start_date: str = "2025-10-31", end_date: str = "2026-10-31") -> None:
    t0 = time.perf_counter()

    jet_df = fetch_cmr_csv_catalog(
        L3T_JET_CONCEPT_ID, start_date, end_date, max_cloud_cover=None, desc="L3T_JET (all)"
    )
    # Only fetch L2T_LSTE <= 20% cloud cover since 10% and 0% are subsets of 20%
    lste_clear = fetch_cmr_csv_catalog(
        L2T_LSTE_CONCEPT_ID, start_date, end_date, max_cloud_cover=20.0, desc="L2T_LSTE (<=20%)"
    ).drop_duplicates(subset=["join_key"])

    matched = jet_df[["granule", "join_key"]].merge(
        lste_clear[["join_key", "cloud_cover"]],
        on="join_key",
        how="inner",
    )

    elapsed = time.perf_counter() - t0
    print(f"\n=== Global ECOSTRESS C3 L3T_JET Scene Counts ({start_date} to {end_date}) ===")
    print(f"All L3T_JET scenes   : {len(jet_df):,}")
    for threshold in (20.0, 10.0, 0.0):
        count = int((matched["cloud_cover"] <= threshold).sum())
        pct = (100.0 * count / len(jet_df)) if len(jet_df) > 0 else 0.0
        print(f"<= {threshold:4.1f}% cloud cover : {count:,} scenes ({pct:.1f}%)")
    print(f"\nCompleted in {elapsed:.2f}s")


if __name__ == "__main__":
    main()