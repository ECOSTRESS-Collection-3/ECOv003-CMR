from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import logging
import math
import os
from pathlib import Path
from threading import Lock
import time
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
import requests

from .ECOSTRESS_CMR_search import ECOSTRESS_CMR_search
from .authentication import configure_gdal_earthdata_env, setup_earthdata_session
from .point_sampling import (
    LAYER_MAPPING,
    sample_points_from_granule,
    summarize_point_samples,
)
from .stratified_sampling import (
    compute_per_granule_quota,
    extract_valid_swath_mask,
    find_clear_sky_et_granules,
    sample_granule_coordinates,
    select_stratified_granules,
)
from .tile_catalog import list_ecostress_land_tiles

logger = logging.getLogger(__name__)

DEFAULT_STRATIFIED_LAYERS = [
    "PTJPLSMinst",
    "ETdaily",
    "ETuncertainty",
    "ST_C",
    "LST_err",
    "EmisWB",
    "view_zenith",
    "NDVI",
    "NDVI-UQ",
    "albedo",
    "albedo-UQ",
    "Ta_C",
    "RH",
    "SM",
    "Rg",
    "Rn",
]

UQ_LAYERS = DEFAULT_STRATIFIED_LAYERS.copy()


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    if seconds < 3600:
        return f"{seconds / 60:.2f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.2f}h"
    return f"{seconds / 86400:.2f}d"


def _load_completed_manifest(manifest_path: str) -> set:
    if not os.path.exists(manifest_path):
        return set()
    with open(manifest_path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def _append_completed_manifest(manifest_path: str, granule_id: str) -> None:
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(f"{granule_id}\n")


def build_stratified_dataset(
    output_dir: str,
    start_date: Union[date, str],
    end_date: Union[date, str],
    tiles: Optional[List[str]] = None,
    target_total_samples: int = 1_000_000,
    min_granules_floor: int = 4,
    oversample_factor: float = 1.25,
    dispersion_strategy: str = "stratified_grid",
    grid_divisions: int = 6,
    layers: Optional[List[str]] = None,
    max_cloud_cover: Optional[float] = 20.0,
    max_workers: int = 8,
    export_csv: bool = False,
    random_state: int = 42,
    session: Optional[requests.Session] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Build a spatially and seasonally stratified ECOSTRESS Collection 3 point-sample
    dataset with incremental Parquet checkpointing, manifest resuming, and
    stage-by-stage performance benchmarking.
    """
    t_start = time.perf_counter()
    timings: Dict[str, float] = {}

    def _log(msg: str) -> None:
        if verbose:
            logger.info(msg)

    os.makedirs(output_dir, exist_ok=True)
    manifest_path = os.path.join(output_dir, "completed_granules.txt")
    completed_granules = _load_completed_manifest(manifest_path)

    if layers is None:
        layers = DEFAULT_STRATIFIED_LAYERS.copy()

    t0 = time.perf_counter()
    _log(f"[1/6] Configuring NASA Earthdata session (output_dir={output_dir})")
    if session is None:
        session = setup_earthdata_session()
    timings["auth_s"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    if tiles is None:
        _log("[2/6] Discovering global land-intersecting Sentinel-2 MGRS tiles...")
        tiles = list_ecostress_land_tiles()
    timings["tile_discovery_s"] = time.perf_counter() - t0
    _log(
        f"[2/6] Target tiles ({len(tiles)}): {', '.join(tiles[:10])}"
        f"{'...' if len(tiles) > 10 else ''} ({timings['tile_discovery_s']:.2f}s)"
    )

    t0 = time.perf_counter()
    _log(
        f"[3/6] Querying CMR for complete clear-sky ET overpasses "
        f"({start_date} to {end_date}, max_cloud_cover={max_cloud_cover})..."
    )
    extra_products = sorted({LAYER_MAPPING[l][0] for l in layers})
    candidate_granules = find_clear_sky_et_granules(
        tiles=tiles,
        start_date=start_date,
        end_date=end_date,
        max_cloud_cover=max_cloud_cover,
        extra_products=extra_products,
        session=session,
    )
    timings["cmr_search_s"] = time.perf_counter() - t0
    if candidate_granules.empty:
        _log("[3/6] No complete multi-product clear-sky ET granules found for the given window.")
        return {"total_samples": 0, "selected_granules": 0, "n_cap": 0, "timings": timings}

    tile_counts = candidate_granules.groupby("tile").size().to_dict()
    _log(
        f"[3/6] Found {len(candidate_granules)} complete candidate overpasses across tiles: "
        f"{tile_counts} ({timings['cmr_search_s']:.2f}s)"
    )

    t0 = time.perf_counter()
    selected_granules, n_cap = select_stratified_granules(
        candidate_granules,
        min_granules_floor=min_granules_floor,
        seasonal_balance=True,
        random_state=random_state,
    )
    if selected_granules.empty:
        _log(f"[4/6] No tiles met min_granules_floor={min_granules_floor}.")
        return {"total_samples": 0, "selected_granules": 0, "n_cap": 0, "timings": timings}

    quota_k, candidate_n = compute_per_granule_quota(
        num_selected_granules=len(selected_granules),
        target_total_samples=target_total_samples,
        oversample_factor=oversample_factor,
    )
    timings["selection_s"] = time.perf_counter() - t0
    _log(
        f"[4/6] Stratified selection: {len(selected_granules)} granules across "
        f"{selected_granules['tile'].nunique()} eligible tile(s) (N_cap={n_cap}, "
        f"quota_K={quota_k}, candidate_draw_N={candidate_n}) ({timings['selection_s']:.2f}s)"
    )

    pending = selected_granules[~selected_granules["granule"].isin(completed_granules)].copy()
    _log(
        f"[5/6] Checkpoint status: {len(completed_granules)} already completed, "
        f"{len(pending)} pending granule(s)"
    )

    write_lock = Lock()
    existing_parts = sorted(Path(output_dir).glob("dataset_part_*.parquet"))
    part_counter = len(existing_parts)

    t0 = time.perf_counter()
    warmup_row = pending.iloc[0] if not pending.empty else selected_granules.iloc[0]
    warmup_tile = warmup_row["tile"]
    warmup_urls = warmup_row.get("variable_urls") or {}
    warmup_url = next(iter(warmup_urls.values()), None)
    if warmup_url is None:
        sample_listing = ECOSTRESS_CMR_search(
            product="L3T_ETAUX",
            tile=warmup_tile,
            start_date=start_date,
            end_date=end_date,
        )
        warmup_url = (
            sample_listing[sample_listing["type"] == "GeoTIFF Data"]["URL"].iloc[0]
            if not sample_listing.empty
            else None
        )
    _log(f"[5/6] Pre-warming GDAL /vsicurl/ Earthdata cookies (warmup_tile={warmup_tile})")

    granule_durations: List[float] = []

    def _process_granule(row_dict: Dict[str, Any], idx: int, total: int, seed: int) -> pd.DataFrame:
        g_t0 = time.perf_counter()
        gid = row_dict["granule"]
        tile = row_dict["tile"]
        orbit = row_dict["orbit"]
        scene = row_dict["scene"]
        ts = row_dict["timestamp"]
        date_str = row_dict["date_str"]
        acq_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        var_urls: Dict[str, str] = dict(row_dict.get("variable_urls") or {})
        if not var_urls:
            _log(f"  [{idx + 1}/{total}] {gid}: resolving multi-product COG URLs ({acq_date})...")
            needed_products = sorted({LAYER_MAPPING[l][0] for l in layers} | {"L3T_ETAUX"})
            listing = ECOSTRESS_CMR_search(
                product=needed_products,
                tile=tile,
                start_date=acq_date,
                end_date=acq_date,
            )
            tifs = listing[listing["type"] == "GeoTIFF Data"]
            for _, frow in tifs.iterrows():
                prod = frow["product"]
                if prod == "L2T_STARS" and f"_{date_str}_" in frow["granule"]:
                    var_urls[frow["variable"]] = frow["URL"]
                elif (
                    frow["orbit"] == orbit
                    and frow["scene"] == scene
                    and f"_{ts}_" in frow["granule"]
                ):
                    var_urls[frow["variable"]] = frow["URL"]

        primary_url = var_urls.get("PTJPLSMinst")
        cloud_url = var_urls.get("cloud")
        water_url = var_urls.get("water")
        if not primary_url and not cloud_url:
            _log(f"  [{idx + 1}/{total}] {gid}: missing swath mask raster, skipping")
            return pd.DataFrame()

        _log(f"  [{idx + 1}/{total}] {gid}: reading swath mask & randomizing {candidate_n} candidate pixels...")
        valid_mask, affine, crs = extract_valid_swath_mask(
            cloud_url=cloud_url,
            water_url=water_url,
            primary_data_url=primary_url,
            overview_level=0,
        )
        valid_pixel_count = int(valid_mask.sum())
        coords = sample_granule_coordinates(
            granule_mask=valid_mask,
            affine=affine,
            crs=crs,
            n_samples=candidate_n,
            strategy=dispersion_strategy,
            grid_divisions=grid_divisions,
            random_state=seed,
        )
        _log(
            f"  [{idx + 1}/{total}] {gid}: {valid_pixel_count:,} clear land pixels in swath -> "
            f"sampling {len(coords)} coordinates across {len(layers)} layers concurrently..."
        )
        if not coords:
            return pd.DataFrame()

        meta_rows = [
            {
                "granule": gid,
                "tile": tile,
                "orbit": orbit,
                "scene": scene,
                "timestamp": ts,
                "quarter": row_dict.get("quarter"),
            }
            for _ in coords
        ]
        sampled_df = sample_points_from_granule(
            variable_urls=var_urls,
            coords=coords,
            layers=layers,
            session=session,
            use_vsicurl=True,
            metadata_rows=meta_rows,
            max_workers=8,
        )
        valid_df = sampled_df.dropna(subset=[l for l in layers if l in sampled_df.columns])
        accepted_df = valid_df.head(quota_k)
        g_elapsed = time.perf_counter() - g_t0
        with write_lock:
            granule_durations.append(g_elapsed)
        _log(
            f"  [{idx + 1}/{total}] {gid}: extracted {len(sampled_df)} raw rows, "
            f"{len(valid_df)} complete rows -> kept {len(accepted_df)}/{quota_k} samples ({g_elapsed:.2f}s)"
        )
        return accepted_df

    total_pending = len(pending)
    with configure_gdal_earthdata_env(session=session, warmup_url=warmup_url):
        timings["cookie_warmup_s"] = time.perf_counter() - t0
        t_extract = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _process_granule, row.to_dict(), idx, total_pending, random_state + idx
                ): row["granule"]
                for idx, (_, row) in enumerate(pending.iterrows())
            }
            for future in as_completed(futures):
                gid = futures[future]
                batch_df = future.result()
                with write_lock:
                    if not batch_df.empty:
                        part_counter += 1
                        part_stem = os.path.join(output_dir, f"dataset_part_{part_counter:04d}")
                        batch_df.to_parquet(f"{part_stem}.parquet", index=False)
                        if export_csv:
                            batch_df.to_csv(f"{part_stem}.csv", index=False)
                        _log(f"  [checkpoint] Saved {len(batch_df)} rows to {os.path.basename(part_stem)}.parquet")
                    _append_completed_manifest(manifest_path, gid)
        timings["extraction_s"] = time.perf_counter() - t_extract

    t0 = time.perf_counter()
    _log("[6/6] Aggregating Parquet partitions and computing coverage summary...")
    all_parts = sorted(Path(output_dir).glob("dataset_part_*.parquet"))
    full_df = pd.concat([pd.read_parquet(p) for p in all_parts], ignore_index=True) if all_parts else pd.DataFrame()
    coverage_summary = summarize_point_samples(full_df, layers=layers)
    timings["aggregation_s"] = time.perf_counter() - t0
    timings["total_s"] = time.perf_counter() - t_start

    n_samples = len(full_df)
    n_granules = len(selected_granules)
    mean_granule_s = float(np.mean(granule_durations)) if granule_durations else timings["extraction_s"]
    effective_granule_s = (
        timings["extraction_s"] / total_pending if total_pending > 0 else mean_granule_s
    )
    samples_per_sec = n_samples / timings["extraction_s"] if timings["extraction_s"] > 0 else 0.0
    linear_1m_s = (1_000_000 / samples_per_sec) if samples_per_sec > 0 else float("inf")

    est_global_granules = 4_000
    est_global_workers = max(max_workers, 16)
    est_global_extract_s = est_global_granules * (mean_granule_s / est_global_workers)
    est_global_cmr_s = (timings["cmr_search_s"] / max(1, len(tiles))) * 60
    est_global_1m_s = est_global_extract_s + est_global_cmr_s

    performance = {
        "timings_s": {k: round(v, 3) for k, v in timings.items()},
        "mean_granule_latency_s": round(mean_granule_s, 2),
        "effective_wall_per_granule_s": round(effective_granule_s, 2),
        "samples_per_second": round(samples_per_sec, 2),
        "linear_1m_estimate_s": round(linear_1m_s, 1),
        "linear_1m_estimate_human": _format_duration(linear_1m_s),
        "amortized_global_1m_estimate_s": round(est_global_1m_s, 1),
        "amortized_global_1m_estimate_human": _format_duration(est_global_1m_s),
        "amortized_assumptions": {
            "global_granules": est_global_granules,
            "points_per_granule_K": math.ceil(1_000_000 / est_global_granules),
            "workers": est_global_workers,
        },
    }

    _log(
        f"[6/6] Done! {n_samples} samples in {timings['total_s']:.2f}s "
        f"({samples_per_sec:.2f} samples/s; amortized 1M estimate: {performance['amortized_global_1m_estimate_human']})"
    )

    return {
        "total_samples": n_samples,
        "selected_granules": n_granules,
        "n_cap": n_cap,
        "quota_k": quota_k,
        "coverage_summary": coverage_summary,
        "performance": performance,
    }
