#!/usr/bin/env python3
"""Instant global L3T_JET scene counts by cloud cover threshold via CMR-Hits."""

import requests

CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
L3T_JET_CONCEPT_ID = "C4057232489-LPCLOUD"


def count_l3t_jet_scenes(
    start_date: str = "2025-10-31",
    end_date: str = "2026-10-31",
    max_cloud_cover: float | None = None,
) -> int:
    params = {
        "concept_id": L3T_JET_CONCEPT_ID,
        "temporal": f"{start_date}T00:00:00Z,{end_date}T23:59:59Z",
        "page_size": 0,  # Zero payload; returns exact count in CMR-Hits header
    }
    if max_cloud_cover is not None:
        params["cloud_cover"] = f"0,{max_cloud_cover}"

    resp = requests.get(CMR_URL, params=params, timeout=(10, 30))
    resp.raise_for_status()
    return int(resp.headers["CMR-Hits"])


if __name__ == "__main__":
    for threshold in (None, 20.0, 10.0, 0.0):
        count = count_l3t_jet_scenes(max_cloud_cover=threshold)
        label = "All cloud %" if threshold is None else f"<= {threshold:4.1f}%  "
        print(f"{label} : {count:,} scenes")