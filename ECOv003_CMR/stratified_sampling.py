from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform
import requests
from tqdm.auto import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from .ECOSTRESS_CMR_search import ECOSTRESS_CMR_search
from .ECOSTRESS_CMR_search_links import (
    search_granule_catalog_umm,
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


def _batched(items: Sequence[Any], batch_size: int) -> List[Sequence[Any]]:
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def resolve_granule_asset_urls(
    granules_df: pd.DataFrame,
    extra_products: Optional[List[str]] = None,
    max_cloud_cover: Optional[float] = 20.0,
    CMR_search_URL: str = CMR_SEARCH_URL,
    session: Optional[requests.Session] = None,
    cmr_workers: int = 8,
    pattern_batch_size: int = 150,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Resolve GeoTIFF asset URLs across L3T_JET, L2T_LSTE, L3T_ETAUX, L2T_STARS
    (and any extra_products) strictly for the supplied candidate/selected rows
    using exact wildcard readable_granule_name[] batches.
    """
    if granules_df.empty:
        return granules_df.copy()

    if "variable_urls" in granules_df.columns and granules_df["variable_urls"].apply(
        lambda d: isinstance(d, dict) and len(d) > 0
    ).all():
        return granules_df.copy()

    companion_products = ["L2T_LSTE", "L3T_ETAUX", "L2T_STARS"]
    if extra_products:
        for prod in extra_products:
            if prod != "L3T_JET" and prod not in companion_products:
                companion_products.append(prod)
    all_products = ["L3T_JET"] + companion_products

    overpass_stems = sorted(
        {
            f"{int(r.orbit):05d}_{int(r.scene):03d}_{r.tile}_{r.timestamp}"
            for r in granules_df.itertuples()
        }
    )
    stars_stems = sorted({f"{r.tile}_{str(r.date_str)[:8]}" for r in granules_df.itertuples()})

    tasks: List[Tuple[str, List[str]]] = []
    for prod in all_products:
        if prod == "L2T_STARS":
            patterns = [f"ECOv003_L2T_STARS_{stem}_*" for stem in stars_stems]
        else:
            patterns = [f"ECOv003_{prod}_{stem}_*" for stem in overpass_stems]
        for batch in _batched(patterns, pattern_batch_size):
            tasks.append((prod, list(batch)))

    if verbose:
        logger.info(
            f"Resolving GeoTIFF asset URLs for {len(granules_df):,} granules across "
            f"{len(all_products)} products ({len(tasks)} pattern batches, workers={min(cmr_workers, max(1, len(tasks)))})..."
        )

    def _run_batch(task: Tuple[str, List[str]]) -> pd.DataFrame:
        prod, patterns = task
        # CloudCover in CMR is populated on L2T_LSTE (null on L3T_JET/L3T_ETAUX/L2T_STARS)
        cc_filter = max_cloud_cover if prod == "L2T_LSTE" else None
        entries = search_granules_by_name_patterns(
            concept_ID=CONCEPT_IDS[prod],
            granule_patterns=patterns,
            max_cloud_cover=cc_filter,
            tif_only=True,
            CMR_search_URL=CMR_search_URL,
            session=session,
        )
        if not entries:
            return pd.DataFrame()
        return interpret_ECOSTRESS_URLs(
            URLs=[e["URL"] for e in entries],
            entry_metadata=entries,
        )

    frames: List[pd.DataFrame] = []
    with logging_redirect_tqdm(), ThreadPoolExecutor(
        max_workers=max(1, min(cmr_workers, max(1, len(tasks))))
    ) as executor:
        futures = [executor.submit(_run_batch, t) for t in tasks]
        with tqdm(
            total=len(tasks),
            desc="Resolving asset URLs",
            unit="batch",
            dynamic_ncols=True,
            disable=not verbose,
        ) as pbar:
            for future in as_completed(futures):
                df_part = future.result()
                if not df_part.empty:
                    frames.append(df_part)
                pbar.update(1)

    if not frames:
        return pd.DataFrame()

    tifs = pd.concat(frames, ignore_index=True)
    instantaneous_keys: Dict[str, Set[Tuple[int, int, str, str]]] = {
        prod: set() for prod in all_products if prod != "L2T_STARS"
    }
    stars_keys: Set[Tuple[str, str]] = set()
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

    required_inst = [p for p in all_products if p != "L2T_STARS"]
    resolved_rows: List[Dict[str, Any]] = []
    for _, row in granules_df.iterrows():
        key = (int(row["orbit"]), int(row["scene"]), str(row["tile"]), str(row["timestamp"]))
        s_key = (str(row["tile"]), str(row["date_str"])[:8])
        if s_key in stars_keys and all(key in instantaneous_keys[p] for p in required_inst):
            merged_urls = dict(stars_urls.get(s_key, {}))
            merged_urls.update(overpass_urls.get(key, {}))
            rec = row.to_dict()
            rec["variable_urls"] = merged_urls
            resolved_rows.append(rec)

    return pd.DataFrame(resolved_rows)


def find_clear_sky_et_granules(
    tiles: List[str],
    start_date: Union[date, str],
    end_date: Union[date, str],
    max_cloud_cover: Optional[float] = 20.0,
    extra_products: Optional[List[str]] = None,
    min_granules_floor: int = 1,
    resolve_urls: bool = True,
    CMR_search_URL: str = CMR_SEARCH_URL,
    session: Optional[requests.Session] = None,
    regional_batch_threshold: int = 25,
    cmr_workers: int = 8,
    cmr_cache_dir: Optional[str] = None,
    pattern_batch_size: int = 150,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Fast ET-first discovery for complete multi-product ECOSTRESS overpasses:
      - For small tile subsets (<= regional_batch_threshold): queries CMR directly
        per tile and resolves full GeoTIFF URLs.
      - For large/global tile sets (> regional_batch_threshold): uses NASA CMR's
        lightweight UMM-JSON endpoint (granules.umm_json) across global temporal
        chunks to index L3T_JET and server-side cloud-filtered L2T_LSTE in seconds
        with zero spatial-overlap duplicates, prunes tiles below min_granules_floor,
        and resolves GeoTIFF URLs via wildcard readable_granule_name[] batches only
        when resolve_urls=True.
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

        return pd.DataFrame(complete_rows)

    # --- Large / Global UMM-JSON Fast Path ---
    allowed_tile_set = set(unique_tiles)
    if verbose:
        logger.info(
            f"UMM-JSON Pass 1/2 [L3T_JET]: indexing global ET granules across "
            f"{len(allowed_tile_set):,} target tiles ({start_date} to {end_date})..."
        )
    jet_df = search_granule_catalog_umm(
        concept_ID=CONCEPT_IDS["L3T_JET"],
        start_date=start_date,
        end_date=end_date,
        max_cloud_cover=None,  # CloudCover is null on L3T_JET in CMR; filtered via L2T_LSTE below
        allowed_tiles=allowed_tile_set,
        chunk_days=31,
        max_workers=cmr_workers,
        CMR_search_URL=CMR_search_URL,
        session=session,
        desc="UMM Pass 1/2 (L3T_JET)",
        verbose=verbose,
    )
    if jet_df.empty:
        return pd.DataFrame()

    # Prune tiles below min_granules_floor before querying L2T_LSTE
    jet_counts = jet_df.groupby("tile").size()
    eligible_tiles = set(jet_counts[jet_counts >= max(1, min_granules_floor)].index.tolist())
    if not eligible_tiles:
        return pd.DataFrame()
    jet_df = jet_df[jet_df["tile"].isin(eligible_tiles)].copy()

    if verbose:
        logger.info(
            f"UMM-JSON Pass 2/2 [L2T_LSTE]: indexing clear-sky LSTE granules "
            f"(max_cloud_cover={max_cloud_cover}) across {len(eligible_tiles):,} eligible tiles..."
        )
    lste_df = search_granule_catalog_umm(
        concept_ID=CONCEPT_IDS["L2T_LSTE"],
        start_date=start_date,
        end_date=end_date,
        max_cloud_cover=max_cloud_cover,
        allowed_tiles=eligible_tiles,
        chunk_days=31,
        max_workers=cmr_workers,
        CMR_search_URL=CMR_search_URL,
        session=session,
        desc="UMM Pass 2/2 (L2T_LSTE)",
        verbose=verbose,
    )
    if lste_df.empty:
        return pd.DataFrame()

    lste_keys = lste_df[["orbit", "scene", "tile", "timestamp", "cloud_cover"]].drop_duplicates(
        subset=["orbit", "scene", "tile", "timestamp"]
    )
    joined = jet_df.drop(columns=["cloud_cover"]).merge(
        lste_keys,
        on=["orbit", "scene", "tile", "timestamp"],
        how="inner",
    )
    if joined.empty:
        return pd.DataFrame()

    post_counts = joined.groupby("tile").size()
    final_tiles = set(post_counts[post_counts >= max(1, min_granules_floor)].index.tolist())
    if not final_tiles:
        return pd.DataFrame()

    joined = joined[joined["tile"].isin(final_tiles)].copy()
    joined["quarter"] = joined["date_str"].str[4:6].astype(int).sub(1).floordiv(3).add(1)
    joined = joined.sort_values(["tile", "timestamp"], kind="mergesort").reset_index(drop=True)

    if not resolve_urls:
        return joined

    return resolve_granule_asset_urls(
        granules_df=joined,
        extra_products=extra_products,
        max_cloud_cover=max_cloud_cover,
        CMR_search_URL=CMR_search_URL,
        session=session,
        cmr_workers=cmr_workers,
        pattern_batch_size=pattern_batch_size,
        verbose=verbose,
    )


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
