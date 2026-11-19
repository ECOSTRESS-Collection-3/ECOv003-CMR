from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import logging
import math
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
from .ECOSTRESS_CMR_search_links import ECOSTRESS_CMR_search_entries
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
    deg_step: float = 30.0,
) -> List[Tuple[Tuple[float, float, float, float], Set[str]]]:
    """
    Group MGRS tiles into coarse WGS84 regional bounding boxes so global CMR
    discovery issues hundreds of bulk regional queries instead of tens of thousands
    of per-tile requests.
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
    chunk_days: int = 92,
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


def find_clear_sky_et_granules(
    tiles: List[str],
    start_date: Union[date, str],
    end_date: Union[date, str],
    max_cloud_cover: Optional[float] = 20.0,
    extra_products: Optional[List[str]] = None,
    CMR_search_URL: str = CMR_SEARCH_URL,
    session: Optional[requests.Session] = None,
    regional_batch_threshold: int = 25,
    cmr_workers: int = 8,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Verify candidate daytime clear-sky L3T_JET overpasses that have matching
    (orbit, scene, tile, timestamp) L2T_LSTE and L3T_ETAUX granules plus a
    same-date (tile, YYYYMMDD) L2T_STARS granule, caching all variable GeoTIFF URLs.
    Automatically switches to concurrent regional WGS84 bounding-box + temporal-chunked
    CMR queries with live progress logging and tqdm progress bars when
    len(tiles) > regional_batch_threshold.
    """
    required_products = ["L3T_JET", "L2T_LSTE", "L3T_ETAUX", "L2T_STARS"]
    if extra_products:
        required_products = list(dict.fromkeys(required_products + list(extra_products)))

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
    else:
        regions = _cluster_tiles_to_regional_boxes(unique_tiles)
        temporal_chunks = _iter_temporal_chunks(start_date, end_date, chunk_days=92)
        tasks = [
            (prod, CONCEPT_IDS[prod], bbox, region_tiles, c_start, c_end)
            for prod in required_products
            for bbox, region_tiles in regions
            for c_start, c_end in temporal_chunks
        ]

        if verbose:
            logger.info(
                f"Querying CMR across {len(regions)} regional boxes x "
                f"{len(temporal_chunks)} temporal chunks x {len(required_products)} products "
                f"({len(tasks)} total requests, workers={min(cmr_workers, len(tasks))})..."
            )

        def _query_chunk(task):
            prod, concept_id, bbox, region_tiles, c_start, c_end = task
            entries = ECOSTRESS_CMR_search_entries(
                concept_ID=concept_id,
                bounding_box=bbox,
                start_date=c_start,
                end_date=c_end,
                max_cloud_cover=max_cloud_cover,
                allowed_tiles=region_tiles,
                CMR_search_URL=CMR_search_URL,
                session=session,
            )
            if not entries:
                return prod, pd.DataFrame()
            df_chunk = interpret_ECOSTRESS_URLs(
                URLs=[e["URL"] for e in entries],
                entry_metadata=entries,
            )
            return prod, df_chunk

        frames: List[pd.DataFrame] = []
        total_assets = 0
        milestone_step = max(1, len(tasks) // 10)

        with logging_redirect_tqdm(), ThreadPoolExecutor(
            max_workers=max(1, min(cmr_workers, len(tasks)))
        ) as executor:
            futures = [executor.submit(_query_chunk, t) for t in tasks]
            with tqdm(
                total=len(tasks),
                desc="CMR regional search",
                unit="req",
                disable=not verbose,
            ) as pbar:
                for completed_idx, future in enumerate(as_completed(futures), start=1):
                    _, df_chunk = future.result()
                    if not df_chunk.empty:
                        frames.append(df_chunk)
                        total_assets += len(df_chunk)
                    pbar.set_postfix(assets=f"{total_assets:,}", refresh=False)
                    pbar.update(1)
                    if verbose and (completed_idx % milestone_step == 0 or completed_idx == len(tasks)):
                        logger.info(
                            f"  CMR discovery progress: {completed_idx}/{len(tasks)} requests "
                            f"({100.0 * completed_idx / len(tasks):.0f}%), {total_assets:,} matching asset URLs"
                        )

        listing = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    if listing.empty:
        return pd.DataFrame()

    tifs = listing[listing["type"] == "GeoTIFF Data"].copy()
    if tifs.empty:
        return pd.DataFrame()

    instantaneous_keys: Dict[str, set] = {"L3T_JET": set(), "L2T_LSTE": set(), "L3T_ETAUX": set()}
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
    for key, meta in jet_granule_meta.items():
        _, _, tile, ts = key
        date_str = ts[:8]
        s_key = (tile, date_str)
        if (
            key in instantaneous_keys["L2T_LSTE"]
            and key in instantaneous_keys["L3T_ETAUX"]
            and s_key in stars_keys
        ):
            month = int(date_str[4:6])
            meta["quarter"] = (month - 1) // 3 + 1
            merged_urls = dict(stars_urls.get(s_key, {}))
            merged_urls.update(overpass_urls.get(key, {}))
            meta["variable_urls"] = merged_urls
            complete_rows.append(meta)

    return pd.DataFrame(complete_rows)


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
