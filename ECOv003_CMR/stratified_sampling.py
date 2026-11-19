from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import hashlib
import logging
import math
import os
import shutil
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform
import requests
from sentinel_tiles import sentinel_tiles
from tqdm.auto import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from .ECOSTRESS_CMR_search import ECOSTRESS_CMR_search
from .ECOSTRESS_CMR_search_links import (
    ECOSTRESS_CMR_search_entries,
    search_granules_by_name_patterns,
)
from .constants import CMR_SEARCH_URL, CONCEPT_IDS
from .interpret_ECOSTRESS_URLs import interpret_ECOSTRESS_URLs

logger = logging.getLogger(__name__)


def _extract_granule_join_keys(granule: str) -> Tuple[str, Optional[int], Optional[int], str, str]:
    """Return (product, orbit, scene, tile, timestamp_or_date) for a Collection 3 granule."""
    parts = granule.split("_")
    product = "_".join(parts[1:3])
    if product == "L2T_STARS":
        return product, None, None, parts[3], parts[4]
    return product, int(parts[3]), int(parts[4]), parts[5], parts[6]


def _tile_bounds_wgs84(tile: str) -> Tuple[float, float, float, float]:
    """Return (minx, miny, maxx, maxy) WGS84 bounds for a Sentinel-2 MGRS tile."""
    if hasattr(sentinel_tiles, "footprint"):
        return sentinel_tiles.footprint(tile).bounds
    grid_obj = sentinel_tiles.grid(tile)
    if hasattr(grid_obj, "boundary_latlon"):
        return grid_obj.boundary_latlon.bounds
    if hasattr(grid_obj, "bounds"):
        return grid_obj.bounds
    centroid = grid_obj.centroid_latlon
    return (centroid.x - 0.5, centroid.y - 0.5, centroid.x + 0.5, centroid.y + 0.5)


def _cluster_tiles_to_regional_boxes(
    tiles: Sequence[str],
    deg_step: float = 15.0,
) -> List[Tuple[Tuple[float, float, float, float], Set[str]]]:
    """
    Group MGRS tiles into compact WGS84 regional bounding boxes (default 15 deg)
    so each CMR spatial query stays shallow (1-2 pages) with fast response times.
    """
    buckets: Dict[Tuple[int, int], List[Tuple[str, Tuple[float, float, float, float]]]] = {}
    for tile in tiles:
        minx, miny, maxx, maxy = _tile_bounds_wgs84(tile)
        cx = 0.5 * (minx + maxx)
        cy = 0.5 * (miny + maxy)
        bx = int(math.floor((cx + 180.0) / deg_step))
        by = int(math.floor((cy + 90.0) / deg_step))
        buckets.setdefault((bx, by), []).append((tile, (minx, miny, maxx, maxy)))

    regions: List[Tuple[Tuple[float, float, float, float], Set[str]]] = []
    for items in buckets.values():
        region_tiles = {t for t, _ in items}
        minx = max(-180.0, min(b[0] for _, b in items))
        miny = max(-90.0, min(b[1] for _, b in items))
        maxx = min(180.0, max(b[2] for _, b in items))
        maxy = min(90.0, max(b[3] for _, b in items))
        regions.append(((minx, miny, maxx, maxy), region_tiles))
    return regions


def _iter_temporal_chunks(
    start_date: Union[date, str],
    end_date: Union[date, str],
    chunk_days: int = 31,
) -> List[Tuple[date, date]]:
    s_date = pd.to_datetime(start_date).date()
    e_date = pd.to_datetime(end_date).date()
    chunks: List[Tuple[date, date]] = []
    cursor = s_date
    while cursor <= e_date:
        chunk_end = min(e_date, cursor + timedelta(days=chunk_days - 1))
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _cmr_task_cache_path(cache_dir: str, prefix: str, key_material: str) -> str:
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:24]
    return os.path.join(cache_dir, f"{prefix}_{digest}.parquet")


def _batched(items: Sequence[Any], batch_size: int) -> List[Sequence[Any]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def find_clear_sky_et_granules(
    tiles: List[str],
    start_date: Union[date, str],
    end_date: Union[date, str],
    max_cloud_cover: Optional[float] = 20.0,
    extra_products: Optional[List[str]] = None,
    min_granules_floor: int = 1,
    CMR_search_URL: str = CMR_SEARCH_URL,
    session: Optional[requests.Session] = None,
    regional_batch_threshold: int = 25,
    cmr_workers: int = 8,
    cmr_cache_dir: Optional[str] = None,
    pattern_batch_size: int = 150,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Two-pass ET-first discovery for complete multi-product ECOSTRESS overpasses:
      Pass 1: Sweep L3T_JET across compact (15 deg x 31-day) regional boxes to
              identify daytime clear-sky scenes where an ET retrieval succeeded,
              and prune tiles below min_granules_floor early.
      Pass 2: Resolve companion products (L2T_LSTE, L3T_ETAUX, L2T_STARS, plus any
              extra_products) strictly for the surviving L3T_JET overpasses and
              (tile, YYYYMMDD) dates using exact wildcard readable_granule_name[]
              batches—eliminating blind spatial sweeps for non-ET scenes.
    """
    companion_products = ["L2T_LSTE", "L3T_ETAUX", "L2T_STARS"]
    if extra_products:
        for prod in extra_products:
            if prod != "L3T_JET" and prod not in companion_products:
                companion_products.append(prod)
    required_products = ["L3T_JET"] + companion_products

    unique_tiles = list(dict.fromkeys(tiles))
    if not unique_tiles:
        return pd.DataFrame()

    if len(unique_tiles) <= regional_batch_threshold:
        listing = ECOSTRESS_CMR_search(
            product=required_products,
            tile=unique_tiles,
            start_date=start_date,
            end_date=end_date,
            max_cloud_cover=max_cloud_cover,
            CMR_search_URL=CMR_search_URL,
            session=session,
        )
        tifs = listing[listing["type"] == "GeoTIFF Data"].copy() if not listing.empty else pd.DataFrame()
    else:
        if cmr_cache_dir:
            os.makedirs(cmr_cache_dir, exist_ok=True)

        # --- Pass 1: Discover L3T_JET overpasses across compact (15 deg x 31-day) buckets ---
        regions = _cluster_tiles_to_regional_boxes(unique_tiles, deg_step=15.0)
        temporal_chunks = _iter_temporal_chunks(start_date, end_date, chunk_days=31)
        jet_tasks = [
            (bbox, region_tiles, c_start, c_end)
            for bbox, region_tiles in regions
            for c_start, c_end in temporal_chunks
        ]

        if verbose:
            logger.info(
                f"Pass 1/2 [L3T_JET]: querying {len(regions)} boxes x {len(temporal_chunks)} monthly chunks "
                f"({len(jet_tasks)} requests, workers={min(cmr_workers, len(jet_tasks))})..."
            )

        def _query_jet_chunk(task):
            bbox, region_tiles, c_start, c_end = task
            task_file = (
                _cmr_task_cache_path(
                    cmr_cache_dir,
                    f"pass1_L3T_JET_{c_start}_{c_end}",
                    f"{bbox}|{c_start}|{c_end}|{max_cloud_cover}|{','.join(sorted(region_tiles))}",
                )
                if cmr_cache_dir
                else None
            )
            if task_file and os.path.exists(task_file):
                try:
                    return pd.read_parquet(task_file), True
                except Exception:
                    pass

            entries = ECOSTRESS_CMR_search_entries(
                concept_ID=CONCEPT_IDS["L3T_JET"],
                bounding_box=bbox,
                start_date=c_start,
                end_date=c_end,
                max_cloud_cover=max_cloud_cover,
                allowed_tiles=region_tiles,
                tif_only=True,
                CMR_search_URL=CMR_search_URL,
                session=session,
            )
            df_chunk = (
                interpret_ECOSTRESS_URLs(
                    URLs=[e["URL"] for e in entries],
                    entry_metadata=entries,
                )
                if entries
                else pd.DataFrame()
            )
            if task_file:
                tmp_file = f"{task_file}.tmp.{os.getpid()}"
                df_chunk.to_parquet(tmp_file, index=False)
                os.replace(tmp_file, task_file)
            return df_chunk, False

        jet_frames: List[pd.DataFrame] = []
        jet_assets = 0
        cached_hits = 0
        milestone_step = max(1, len(jet_tasks) // 10)

        with logging_redirect_tqdm(), ThreadPoolExecutor(
            max_workers=max(1, min(cmr_workers, len(jet_tasks)))
        ) as executor:
            futures = [executor.submit(_query_jet_chunk, t) for t in jet_tasks]
            with tqdm(
                total=len(jet_tasks),
                desc="Pass 1/2 (L3T_JET)",
                unit="req",
                dynamic_ncols=True,
                disable=not verbose,
            ) as pbar:
                for completed_idx, future in enumerate(as_completed(futures), start=1):
                    df_chunk, from_cache = future.result()
                    if from_cache:
                        cached_hits += 1
                    if not df_chunk.empty:
                        jet_frames.append(df_chunk)
                        jet_assets += len(df_chunk)
                    pbar.set_postfix(
                        jet_tifs=f"{jet_assets:,}",
                        cached=cached_hits,
                        refresh=False,
                    )
                    pbar.update(1)
                    if verbose and (completed_idx % milestone_step == 0 or completed_idx == len(jet_tasks)):
                        logger.info(
                            f"  Pass 1/2 [L3T_JET] progress: {completed_idx}/{len(jet_tasks)} requests "
                            f"({100.0 * completed_idx / len(jet_tasks):.0f}%), {jet_assets:,} GeoTIFF assets"
                        )

        jet_df = pd.concat(jet_frames, ignore_index=True) if jet_frames else pd.DataFrame()
        if jet_df.empty:
            if cmr_cache_dir and os.path.isdir(cmr_cache_dir):
                shutil.rmtree(cmr_cache_dir, ignore_errors=True)
            return pd.DataFrame()

        # Prune tiles with fewer than min_granules_floor L3T_JET overpasses before Pass 2
        jet_unique = jet_df.drop_duplicates(subset=["granule"])
        tile_jet_counts = jet_unique.groupby("tile").size()
        eligible_tiles = set(tile_jet_counts[tile_jet_counts >= max(1, min_granules_floor)].index.tolist())
        if not eligible_tiles:
            if cmr_cache_dir and os.path.isdir(cmr_cache_dir):
                shutil.rmtree(cmr_cache_dir, ignore_errors=True)
            return pd.DataFrame()

        jet_df = jet_df[jet_df["tile"].isin(eligible_tiles)].copy()
        jet_unique = jet_unique[jet_unique["tile"].isin(eligible_tiles)].copy()

        overpass_stems = sorted(
            {
                f"{int(r.orbit):05d}_{int(r.scene):03d}_{r.tile}_{r.granule.split('_')[6]}"
                for r in jet_unique.itertuples()
            }
        )
        stars_stems = sorted(
            {
                f"{r.tile}_{r.granule.split('_')[6][:8]}"
                for r in jet_unique.itertuples()
            }
        )

        # --- Pass 2: Targeted companion lookup via wildcard readable_granule_name[] batches ---
        companion_tasks: List[Tuple[str, List[str]]] = []
        for prod in companion_products:
            if prod == "L2T_STARS":
                patterns = [f"ECOv003_L2T_STARS_{stem}_*" for stem in stars_stems]
            else:
                patterns = [f"ECOv003_{prod}_{stem}_*" for stem in overpass_stems]
            for batch in _batched(patterns, pattern_batch_size):
                companion_tasks.append((prod, list(batch)))

        if verbose:
            logger.info(
                f"Pass 2/2 [Companions]: resolving {len(overpass_stems):,} L3T_JET overpasses & "
                f"{len(stars_stems):,} tile-dates across {len(eligible_tiles):,} eligible tiles "
                f"({len(companion_tasks)} batch requests, workers={min(cmr_workers, max(1, len(companion_tasks)))})..."
            )

        def _query_companion_batch(task):
            prod, patterns = task
            task_file = (
                _cmr_task_cache_path(
                    cmr_cache_dir,
                    f"pass2_{prod}",
                    f"{prod}|{max_cloud_cover}|{','.join(patterns)}",
                )
                if cmr_cache_dir
                else None
            )
            if task_file and os.path.exists(task_file):
                try:
                    return pd.read_parquet(task_file), True
                except Exception:
                    pass

            entries = search_granules_by_name_patterns(
                concept_ID=CONCEPT_IDS[prod],
                granule_patterns=patterns,
                max_cloud_cover=max_cloud_cover,
                tif_only=True,
                CMR_search_URL=CMR_search_URL,
                session=session,
            )
            df_chunk = (
                interpret_ECOSTRESS_URLs(
                    URLs=[e["URL"] for e in entries],
                    entry_metadata=entries,
                )
                if entries
                else pd.DataFrame()
            )
            if task_file:
                tmp_file = f"{task_file}.tmp.{os.getpid()}"
                df_chunk.to_parquet(tmp_file, index=False)
                os.replace(tmp_file, task_file)
            return df_chunk, False

        comp_frames: List[pd.DataFrame] = [jet_df]
        comp_assets = 0
        comp_cached = 0
        comp_milestone = max(1, len(companion_tasks) // 10)

        with logging_redirect_tqdm(), ThreadPoolExecutor(
            max_workers=max(1, min(cmr_workers, max(1, len(companion_tasks))))
        ) as executor:
            futures = [executor.submit(_query_companion_batch, t) for t in companion_tasks]
            with tqdm(
                total=len(companion_tasks),
                desc="Pass 2/2 (Companions)",
                unit="batch",
                dynamic_ncols=True,
                disable=not verbose,
            ) as pbar:
                for completed_idx, future in enumerate(as_completed(futures), start=1):
                    df_chunk, from_cache = future.result()
                    if from_cache:
                        comp_cached += 1
                    if not df_chunk.empty:
                        comp_frames.append(df_chunk)
                        comp_assets += len(df_chunk)
                    pbar.set_postfix(
                        comp_tifs=f"{comp_assets:,}",
                        cached=comp_cached,
                        refresh=False,
                    )
                    pbar.update(1)
                    if verbose and (
                        completed_idx % comp_milestone == 0 or completed_idx == len(companion_tasks)
                    ):
                        logger.info(
                            f"  Pass 2/2 [Companions] progress: {completed_idx}/{len(companion_tasks)} batches "
                            f"({100.0 * completed_idx / len(companion_tasks):.0f}%), {comp_assets:,} companion GeoTIFFs"
                        )

        tifs = pd.concat(comp_frames, ignore_index=True)

    if tifs.empty:
        return pd.DataFrame()

    instantaneous_keys: Dict[str, set] = {
        prod: set() for prod in required_products if prod != "L2T_STARS"
    }
    stars_keys: set = set()
    jet_granule_meta: Dict[Tuple[int, int, str, str], Dict[str, Any]] = {}
    overpass_urls: Dict[Tuple[int, int, str, str], Dict[str, str]] = {}
    stars_urls: Dict[Tuple[str, str], Dict[str, str]] = {}

    for _, row in tifs.iterrows():
        granule = row["granule"]
        variable = row["variable"]
        url = row["URL"]
        prod, orbit, scene, tile, ts = _extract_granule_join_keys(granule)
        if prod == "L2T_STARS":
            s_key = (tile, ts[:8])
            stars_keys.add(s_key)
            stars_urls.setdefault(s_key, {})[variable] = url
        else:
            key = (orbit, scene, tile, ts)
            overpass_urls.setdefault(key, {})[variable] = url
            if prod in instantaneous_keys:
                instantaneous_keys[prod].add(key)
            if prod == "L3T_JET" and key not in jet_granule_meta:
                jet_granule_meta[key] = {
                    "granule": granule,
                    "orbit": orbit,
                    "scene": scene,
                    "tile": tile,
                    "timestamp": ts,
                    "date_str": ts[:8],
                    "cloud_cover": row.get("cloud_cover"),
                }

    complete_rows = []
    required_inst_products = [p for p in required_products if p not in ("L3T_JET", "L2T_STARS")]
    for key, meta in jet_granule_meta.items():
        _, _, tile, ts = key
        date_str = ts[:8]
        s_key = (tile, date_str)
        if s_key in stars_keys and all(key in instantaneous_keys[p] for p in required_inst_products):
            month = int(date_str[4:6])
            meta["quarter"] = (month - 1) // 3 + 1
            merged_urls = dict(stars_urls.get(s_key, {}))
            merged_urls.update(overpass_urls.get(key, {}))
            meta["variable_urls"] = merged_urls
            complete_rows.append(meta)

    result_df = pd.DataFrame(complete_rows)
    if cmr_cache_dir and os.path.isdir(cmr_cache_dir):
        shutil.rmtree(cmr_cache_dir, ignore_errors=True)
    return result_df


def select_stratified_granules(
    granules_df: pd.DataFrame,
    min_granules_floor: int = 4,
    seasonal_balance: bool = True,
    random_state: Optional[int] = None,
) -> Tuple[pd.DataFrame, int]:
    """
    Cap per-tile clear-sky granule counts at N_cap = min_{t in EligibleTiles} N_t
    (filtering out sparse tiles below min_granules_floor) and sample N_cap
    granules per tile balanced across calendar quarters.
    """
    if granules_df.empty:
        return pd.DataFrame(), 0

    rng = np.random.default_rng(random_state)
    df = granules_df.copy()
    if "quarter" not in df.columns:
        df["quarter"] = df["date_str"].str[4:6].astype(int).sub(1).floordiv(3).add(1)

    counts = df.groupby("tile").size()
    eligible_tiles = counts[counts >= min_granules_floor].index.tolist()
    if not eligible_tiles:
        return pd.DataFrame(), 0

    df = df[df["tile"].isin(eligible_tiles)]
    n_cap = int(counts.loc[eligible_tiles].min())

    selected_frames = []
    for tile, group in df.groupby("tile", sort=True):
        if len(group) == n_cap:
            selected_frames.append(group)
            continue

        if not seasonal_balance:
            idx = rng.choice(group.index.to_numpy(), size=n_cap, replace=False)
            selected_frames.append(group.loc[idx])
            continue

        quarter_pools = {
            q: list(rng.permutation(q_df.index.to_numpy()))
            for q, q_df in group.groupby("quarter")
        }
        chosen_indices: List[int] = []
        quarters = sorted(quarter_pools.keys())
        while len(chosen_indices) < n_cap:
            progressed = False
            for q in quarters:
                if quarter_pools[q] and len(chosen_indices) < n_cap:
                    chosen_indices.append(quarter_pools[q].pop())
                    progressed = True
            if not progressed:
                break
        selected_frames.append(group.loc[chosen_indices])

    return pd.concat(selected_frames, ignore_index=True), n_cap


def compute_per_granule_quota(
    num_selected_granules: int,
    target_total_samples: int = 1_000_000,
    oversample_factor: float = 1.2,
) -> Tuple[int, int]:
    """Return (accepted_quota_K, candidate_draw_count) per granule."""
    if num_selected_granules <= 0:
        raise ValueError("num_selected_granules must be positive")
    quota_k = math.ceil(target_total_samples / num_selected_granules)
    candidate_n = math.ceil(quota_k * oversample_factor)
    return quota_k, candidate_n


def extract_valid_swath_mask(
    cloud_url: Optional[str] = None,
    water_url: Optional[str] = None,
    primary_data_url: Optional[str] = None,
    overview_level: Optional[int] = None,
) -> Tuple[np.ndarray, rasterio.Affine, CRS]:
    """
    Identify valid clear-sky land pixels inside the swath footprint using a single
    pre-masked primary retrieval raster (e.g., L3T_JET PTJPLSMinst) when provided,
    or explicit cloud/water mask COGs.
    """
    target_url = primary_data_url or cloud_url
    if not target_url:
        raise ValueError("Either 'primary_data_url' or 'cloud_url' must be provided")

    with rasterio.open(target_url) as src:
        overviews = src.overviews(1)
        if overview_level is not None and overviews:
            scale = overviews[min(overview_level, len(overviews) - 1)]
            out_shape = (
                max(1, src.height // scale),
                max(1, src.width // scale),
            )
            arr = src.read(1, out_shape=out_shape, masked=True)
            affine = src.transform * rasterio.Affine.scale(
                src.width / out_shape[1],
                src.height / out_shape[0],
            )
        else:
            arr = src.read(1, masked=True)
            affine = src.transform
        crs = src.crs

    if primary_data_url is not None:
        filled = np.ma.filled(arr, np.nan)
        valid_mask = (~np.ma.getmaskarray(arr)) & np.isfinite(filled)
        return valid_mask, affine, crs

    valid_mask = (~np.ma.getmaskarray(arr)) & (np.ma.filled(arr, 1) == 0)
    if water_url is not None:
        with rasterio.open(water_url) as water_src:
            water_arr = water_src.read(1, out_shape=valid_mask.shape, masked=True)
        valid_mask &= (~np.ma.getmaskarray(water_arr)) & (np.ma.filled(water_arr, 1) == 0)

    return valid_mask, affine, crs


def _draw_dispersed_indices(
    candidate_indices: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    draw_count: int,
    shape: Tuple[int, int],
    strategy: str,
    grid_divisions: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if draw_count <= 0 or len(candidate_indices) == 0:
        return np.array([], dtype=int)
    draw_count = min(draw_count, len(candidate_indices))
    if strategy == "uniform":
        return rng.choice(candidate_indices, size=draw_count, replace=False)

    height, width = shape
    block_h = max(1, math.ceil(height / grid_divisions))
    block_w = max(1, math.ceil(width / grid_divisions))
    sub_rows = rows[candidate_indices]
    sub_cols = cols[candidate_indices]
    block_ids = (sub_rows // block_h) * grid_divisions + (sub_cols // block_w)

    block_pools: Dict[int, List[int]] = {}
    for orig_idx, b_id in zip(candidate_indices, block_ids):
        block_pools.setdefault(int(b_id), []).append(int(orig_idx))
    for b_id in block_pools:
        block_pools[b_id] = list(rng.permutation(block_pools[b_id]))

    chosen_list: List[int] = []
    blocks = list(rng.permutation(list(block_pools.keys())))
    while len(chosen_list) < draw_count:
        progressed = False
        for b_id in blocks:
            if block_pools[b_id] and len(chosen_list) < draw_count:
                chosen_list.append(block_pools[b_id].pop())
                progressed = True
        if not progressed:
            break
    return np.array(chosen_list, dtype=int)


def sample_granule_coordinates(
    granule_mask: np.ndarray,
    affine: rasterio.Affine,
    crs: CRS,
    n_samples: int,
    strategy: str = "stratified_grid",
    grid_divisions: int = 6,
    cropland_mask: Optional[np.ndarray] = None,
    cropland_fraction_target: Optional[float] = None,
    random_state: Optional[int] = None,
) -> List[Tuple[float, float]]:
    """
    Independently randomize n_samples clear-sky land coordinates ('rolling the dice')
    within a granule footprint using 'uniform' or 'stratified_grid' dispersion and
    optional agricultural vs. natural land weighting.
    """
    if strategy not in ("uniform", "stratified_grid"):
        raise ValueError(f"Unknown dispersion strategy: {strategy!r}")

    rng = np.random.default_rng(random_state)
    valid_rows, valid_cols = np.where(granule_mask)
    total_valid = len(valid_rows)
    if total_valid == 0 or n_samples <= 0:
        return []

    draw_count = min(n_samples, total_valid)

    if cropland_mask is not None and cropland_fraction_target is not None:
        is_crop = cropland_mask[valid_rows, valid_cols].astype(bool)
        crop_idx = np.where(is_crop)[0]
        nat_idx = np.where(~is_crop)[0]
        n_crop_target = int(round(draw_count * cropland_fraction_target))
        n_crop = min(n_crop_target, len(crop_idx))
        n_nat = min(draw_count - n_crop, len(nat_idx))
        if n_crop + n_nat < draw_count:
            rem = draw_count - (n_crop + n_nat)
            if len(crop_idx) - n_crop >= rem:
                n_crop += rem
            elif len(nat_idx) - n_nat >= rem:
                n_nat += rem

        chosen_crop = _draw_dispersed_indices(
            crop_idx, valid_rows, valid_cols, n_crop, granule_mask.shape, strategy, grid_divisions, rng
        )
        chosen_nat = _draw_dispersed_indices(
            nat_idx, valid_rows, valid_cols, n_nat, granule_mask.shape, strategy, grid_divisions, rng
        )
        chosen = np.concatenate([chosen_crop, chosen_nat])
        rng.shuffle(chosen)
        sel_rows, sel_cols = valid_rows[chosen], valid_cols[chosen]
    else:
        all_idx = np.arange(total_valid, dtype=int)
        chosen = _draw_dispersed_indices(
            all_idx, valid_rows, valid_cols, draw_count, granule_mask.shape, strategy, grid_divisions, rng
        )
        sel_rows, sel_cols = valid_rows[chosen], valid_cols[chosen]

    xs, ys = rasterio.transform.xy(affine, sel_rows, sel_cols, offset="center")
    lons, lats = transform(crs, CRS.from_epsg(4326), xs, ys)
    return list(zip(lons, lats))
