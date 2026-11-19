from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import hashlib
import json
import logging
import math
import os
from pathlib import Path
from threading import Lock, Semaphore
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from tqdm.auto import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

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
    resolve_granule_asset_urls,
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


def _compute_catalog_cache_key(
    tiles: List[str],
    start_date: Union[date, str],
    end_date: Union[date, str],
    max_cloud_cover: Optional[float],
) -> Dict[str, Any]:
    sorted_tiles = sorted(set(tiles))
    tiles_digest = hashlib.sha256(",".join(sorted_tiles).encode("utf-8")).hexdigest()
    return {
        "start_date": str(start_date),
        "end_date": str(end_date),
        "max_cloud_cover": max_cloud_cover,
        "tile_count": len(sorted_tiles),
        "tiles_sha256": tiles_digest,
    }


def _save_candidate_catalog(
    catalog_path: str,
    catalog_df: pd.DataFrame,
    cache_key: Dict[str, Any],
    queried_products: List[str],
) -> None:
    serial_df = catalog_df.copy()
    if "variable_urls" in serial_df.columns:
        serial_df["variable_urls"] = serial_df["variable_urls"].apply(
            lambda d: json.dumps(d) if isinstance(d, dict) else (d or "{}")
        )
    table = pa.Table.from_pandas(serial_df, preserve_index=False)
    meta_payload = dict(cache_key)
    meta_payload["queried_products"] = sorted(set(queried_products))
    existing_meta = dict(table.schema.metadata or {})
    existing_meta[b"ecov003_catalog_meta"] = json.dumps(meta_payload).encode("utf-8")
    table = table.replace_schema_metadata(existing_meta)
    pq.write_table(table, catalog_path)


def _load_candidate_catalog(
    catalog_path: str,
    expected_key: Dict[str, Any],
    required_products: List[str],
) -> Optional[pd.DataFrame]:
    if not os.path.exists(catalog_path):
        return None
    try:
        table = pq.read_table(catalog_path)
        raw_meta = (table.schema.metadata or {}).get(b"ecov003_catalog_meta")
        if not raw_meta:
            return None
        meta = json.loads(raw_meta.decode("utf-8"))
        for k, v in expected_key.items():
            if meta.get(k) != v:
                return None
        cached_products = set(meta.get("queried_products", []))
        if not set(required_products).issubset(cached_products):
            return None

        df = table.to_pandas()
        if "variable_urls" in df.columns:
            df["variable_urls"] = df["variable_urls"].apply(
                lambda s: json.loads(s) if isinstance(s, str) else (s or {})
            )
        return df
    except Exception as exc:
        logger.warning(f"Failed to load cached granule catalog {catalog_path}: {exc}")
        return None


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
    layer_workers: int = 8,
    max_concurrent_streams: int = 32,
    batch_size: int = 250,
    catalog_path: Optional[str] = None,
    refresh_catalog: bool = False,
    export_csv: bool = False,
    random_state: int = 42,
    session: Optional[requests.Session] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """
    Build a spatially and seasonally stratified ECOSTRESS Collection 3 point-sample
    dataset with CMR CSV catalog discovery, lazy post-stratification asset URL
    & sidecar QAPercentCloudCover resolution, bounded HTTP stream concurrency,
    synchronous URS cookie refresh across batches, adaptive quota refills, and
    O(1)-memory Parquet diagnostics.
    """
    t_start = time.perf_counter()
    timings: Dict[str, float] = {}

    def _log(msg: str) -> None:
        if verbose:
            logger.info(msg)

    os.makedirs(output_dir, exist_ok=True)
    manifest_path = os.path.join(output_dir, "completed_granules.txt")
    completed_granules = _load_completed_manifest(manifest_path)

    if catalog_path is None:
        catalog_path = os.path.join(output_dir, "candidate_granules.parquet")

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
    extra_products = sorted({LAYER_MAPPING[l][0] for l in layers})
    required_products = list(dict.fromkeys(["L3T_JET", "L2T_LSTE", "L3T_ETAUX", "L2T_STARS"] + extra_products))
    cache_key = _compute_catalog_cache_key(tiles, start_date, end_date, max_cloud_cover)

    candidate_granules = None if refresh_catalog else _load_candidate_catalog(
        catalog_path=catalog_path,
        expected_key=cache_key,
        required_products=required_products,
    )
    if candidate_granules is not None:
        _log(f"[3/6] Loaded {len(candidate_granules):,} cached candidate overpasses from {catalog_path}")
    else:
        _log(
            f"[3/6] Querying CMR for complete clear-sky ET overpasses "
            f"({start_date} to {end_date}, max_cloud_cover={max_cloud_cover})..."
        )
        candidate_granules = find_clear_sky_et_granules(
            tiles=tiles,
            start_date=start_date,
            end_date=end_date,
            max_cloud_cover=max_cloud_cover,
            extra_products=extra_products,
            min_granules_floor=min_granules_floor,
            resolve_urls=False,
            session=session,
            cmr_workers=max(1, min(6, max_workers)),
            verbose=verbose,
        )
        if not candidate_granules.empty:
            _save_candidate_catalog(catalog_path, candidate_granules, cache_key, required_products)
    timings["cmr_search_s"] = time.perf_counter() - t0

    if candidate_granules.empty:
        _log("[3/6] No complete multi-product clear-sky ET granules found for the given window.")
        return {"total_samples": 0, "selected_granules": 0, "n_cap": 0, "timings": timings}

    tile_counts = candidate_granules.groupby("tile").size().to_dict()
    tile_preview = dict(list(tile_counts.items())[:10])
    suffix = f" ... (+{len(tile_counts) - 10} more tiles)" if len(tile_counts) > 10 else ""
    _log(
        f"[3/6] Found {len(candidate_granules):,} candidate overpasses across "
        f"{len(tile_counts):,} tiles: {tile_preview}{suffix} ({timings['cmr_search_s']:.2f}s)"
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

    # Resolve GeoTIFF asset URLs & sidecar QAPercentCloudCover lazily for selected granules
    if "variable_urls" not in selected_granules.columns or not selected_granules["variable_urls"].apply(
        lambda d: isinstance(d, dict) and len(d) > 0
    ).all():
        resolved_selected = resolve_granule_asset_urls(
            granules_df=selected_granules,
            extra_products=extra_products,
            max_cloud_cover=max_cloud_cover,
            session=session,
            cmr_workers=max(1, min(6, max_workers)),
            verbose=verbose,
        )
        # Backfill any tile that lost a granule due to sidecar cloud cover or a missing companion
        if len(resolved_selected) < len(selected_granules):
            selected_set = set(selected_granules["granule"])
            remaining_candidates = candidate_granules[
                ~candidate_granules["granule"].isin(selected_set)
            ]
            resolved_counts = resolved_selected.groupby("tile").size().to_dict() if not resolved_selected.empty else {}
            deficits = {
                t: n_cap - resolved_counts.get(t, 0)
                for t in selected_granules["tile"].unique()
                if resolved_counts.get(t, 0) < n_cap
            }
            if deficits and not remaining_candidates.empty:
                backfill_rows = []
                for t, need in deficits.items():
                    t_pool = remaining_candidates[remaining_candidates["tile"] == t].head(need * 3)
                    if not t_pool.empty:
                        backfill_rows.append(t_pool)
                if backfill_rows:
                    backfill_resolved = resolve_granule_asset_urls(
                        granules_df=pd.concat(backfill_rows, ignore_index=True),
                        extra_products=extra_products,
                        max_cloud_cover=max_cloud_cover,
                        session=session,
                        cmr_workers=max(1, min(6, max_workers)),
                        verbose=False,
                    )
                    if not backfill_resolved.empty:
                        combined = pd.concat([resolved_selected, backfill_resolved], ignore_index=True)
                        resolved_selected = (
                            combined.groupby("tile", group_keys=False)
                            .head(n_cap)
                            .reset_index(drop=True)
                        )
        selected_granules = resolved_selected

    if selected_granules.empty:
        _log("[4/6] No complete clear-sky multi-product granules remained after URL & sidecar resolution.")
        return {"total_samples": 0, "selected_granules": 0, "n_cap": 0, "timings": timings}

    quota_k, candidate_n = compute_per_granule_quota(
        num_selected_granules=len(selected_granules),
        target_total_samples=target_total_samples,
        oversample_factor=oversample_factor,
    )
    timings["selection_s"] = time.perf_counter() - t0
    _log(
        f"[4/6] Stratified selection: {len(selected_granules):,} granules across "
        f"{selected_granules['tile'].nunique():,} eligible tile(s) (N_cap={n_cap}, "
        f"quota_K={quota_k}, candidate_draw_N={candidate_n}) ({timings['selection_s']:.2f}s)"
    )

    pending = selected_granules[~selected_granules["granule"].isin(completed_granules)].copy()
    _log(
        f"[5/6] Checkpoint status: {len(completed_granules):,} already completed, "
        f"{len(pending):,} pending granule(s) (batch_size={batch_size}, max_concurrent_streams={max_concurrent_streams})"
    )

    write_lock = Lock()
    stream_semaphore = Semaphore(max(1, max_concurrent_streams))
    existing_parts = sorted(Path(output_dir).glob("dataset_part_*.parquet"))
    part_counter = len(existing_parts)

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
            session=session,
        )
        warmup_url = (
            sample_listing[sample_listing["type"] == "GeoTIFF Data"]["URL"].iloc[0]
            if not sample_listing.empty
            else None
        )

    granule_durations: List[float] = []
    valid_layer_cols = [l for l in layers if l in LAYER_MAPPING]

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
                session=session,
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

        valid_mask, affine, crs = extract_valid_swath_mask(
            cloud_url=cloud_url,
            water_url=water_url,
            primary_data_url=primary_url,
            overview_level=0,
        )
        valid_pixel_count = int(valid_mask.sum())
        if valid_pixel_count == 0:
            return pd.DataFrame()

        seen_coords: Set[Tuple[float, float]] = set()
        valid_frames: List[pd.DataFrame] = []
        collected_count = 0
        next_draw = candidate_n
        max_refill_attempts = 2

        for attempt in range(max_refill_attempts + 1):
            needed = quota_k - collected_count
            if needed <= 0:
                break
            draw_target = next_draw if attempt == 0 else min(
                valid_pixel_count - len(seen_coords),
                max(needed * 2, int(math.ceil(needed * oversample_factor))),
            )
            if draw_target <= 0:
                break

            raw_coords = sample_granule_coordinates(
                granule_mask=valid_mask,
                affine=affine,
                crs=crs,
                n_samples=draw_target + len(seen_coords),
                strategy=dispersion_strategy,
                grid_divisions=grid_divisions,
                random_state=seed + (attempt * 100_003),
            )
            new_coords = [c for c in raw_coords if c not in seen_coords][:draw_target]
            if not new_coords:
                break
            seen_coords.update(new_coords)

            meta_rows = [
                {
                    "granule": gid,
                    "tile": tile,
                    "orbit": orbit,
                    "scene": scene,
                    "timestamp": ts,
                    "quarter": row_dict.get("quarter"),
                }
                for _ in new_coords
            ]
            sampled_df = sample_points_from_granule(
                variable_urls=var_urls,
                coords=new_coords,
                layers=layers,
                session=session,
                use_vsicurl=True,
                metadata_rows=meta_rows,
                max_workers=layer_workers,
                stream_semaphore=stream_semaphore,
            )
            present_cols = [c for c in valid_layer_cols if c in sampled_df.columns]
            batch_valid = sampled_df.dropna(subset=present_cols)
            if not batch_valid.empty:
                valid_frames.append(batch_valid)
                collected_count += len(batch_valid)

        merged_valid = pd.concat(valid_frames, ignore_index=True) if valid_frames else pd.DataFrame()
        accepted_df = merged_valid.head(quota_k)
        g_elapsed = time.perf_counter() - g_t0
        with write_lock:
            granule_durations.append(g_elapsed)
        _log(
            f"  [{idx + 1}/{total}] {gid}: kept {len(accepted_df)}/{quota_k} samples ({g_elapsed:.2f}s)"
        )
        return accepted_df

    total_pending = len(pending)
    timings["cookie_warmup_s"] = 0.0
    t_extract = time.perf_counter()
    running_samples = 0

    effective_batch_size = max(1, batch_size)
    with logging_redirect_tqdm(), tqdm(
        total=total_pending,
        desc="Extracting COGs",
        unit="granule",
        disable=not verbose or total_pending == 0,
    ) as pbar:
        for batch_start in range(0, total_pending, effective_batch_size):
            batch_df_slice = pending.iloc[batch_start : batch_start + effective_batch_size]
            t_warm = time.perf_counter()
            _log(
                f"[5/6] Pre-warming GDAL /vsicurl/ Earthdata cookies "
                f"(granules {batch_start + 1}..{batch_start + len(batch_df_slice)} of {total_pending})"
            )
            with configure_gdal_earthdata_env(session=session, warmup_url=warmup_url):
                timings["cookie_warmup_s"] += time.perf_counter() - t_warm
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(
                            _process_granule,
                            row.to_dict(),
                            batch_start + local_idx,
                            total_pending,
                            random_state + batch_start + local_idx,
                        ): row["granule"]
                        for local_idx, (_, row) in enumerate(batch_df_slice.iterrows())
                    }
                    for future in as_completed(futures):
                        gid = futures[future]
                        result_df = future.result()
                        with write_lock:
                            if not result_df.empty:
                                part_counter += 1
                                part_stem = os.path.join(output_dir, f"dataset_part_{part_counter:04d}")
                                result_df.to_parquet(f"{part_stem}.parquet", index=False)
                                if export_csv:
                                    result_df.to_csv(f"{part_stem}.csv", index=False)
                                running_samples += len(result_df)
                            _append_completed_manifest(manifest_path, gid)
                        elapsed = max(1e-6, (time.perf_counter() - t_extract) - timings["cookie_warmup_s"])
                        pbar.set_postfix(
                            samples=f"{running_samples:,}",
                            rate=f"{running_samples / elapsed:.1f}/s",
                            refresh=False,
                        )
                        pbar.update(1)

    timings["extraction_s"] = max(0.0, (time.perf_counter() - t_extract) - timings["cookie_warmup_s"])

    t0 = time.perf_counter()
    _log("[6/6] Computing streaming Parquet coverage summary...")
    all_parts = sorted(Path(output_dir).glob("dataset_part_*.parquet"))
    coverage_summary = summarize_point_samples(all_parts, layers=layers)
    n_samples = int(coverage_summary["total_rows"].iloc[0]) if not coverage_summary.empty else 0
    timings["aggregation_s"] = time.perf_counter() - t0
    timings["total_s"] = time.perf_counter() - t_start

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
        f"[6/6] Done! {n_samples:,} samples in {timings['total_s']:.2f}s "
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
