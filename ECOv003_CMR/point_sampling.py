"""
Point sampling from ECOSTRESS Collection 3 data.

This module provides functions for sampling ECOSTRESS raster data at specific
geographic points, supporting single-point queries, granule-grouped /vsicurl/
COG batch reads, streaming Parquet diagnostics, and GeoDataFrame workflows.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
import logging
from pathlib import Path
import random
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import rasterio
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.warp import transform, transform_bounds
from rasterio.windows import Window
import requests
from sentinel_tiles import sentinel_tiles
from shapely.geometry import Point

from .ECOSTRESS_CMR_search import ECOSTRESS_CMR_search
from .authentication import setup_earthdata_session

logger = logging.getLogger(__name__)

# Layer name to (Collection 3 product, variable) mapping
LAYER_MAPPING = {
    # L2T_LSTE
    'ST_C': ('L2T_LSTE', 'LST'),
    'LST': ('L2T_LSTE', 'LST'),
    'LST_err': ('L2T_LSTE', 'LST_err'),
    'QC': ('L2T_LSTE', 'QC'),
    'emissivity': ('L2T_LSTE', 'EmisWB'),
    'EmisWB': ('L2T_LSTE', 'EmisWB'),
    'Emis1': ('L2T_LSTE', 'Emis1'),
    'Emis2': ('L2T_LSTE', 'Emis2'),
    'Emis3': ('L2T_LSTE', 'Emis3'),
    'Emis4': ('L2T_LSTE', 'Emis4'),
    'Emis5': ('L2T_LSTE', 'Emis5'),
    'Emis1_err': ('L2T_LSTE', 'Emis1_err'),
    'Emis2_err': ('L2T_LSTE', 'Emis2_err'),
    'Emis3_err': ('L2T_LSTE', 'Emis3_err'),
    'Emis4_err': ('L2T_LSTE', 'Emis4_err'),
    'Emis5_err': ('L2T_LSTE', 'Emis5_err'),
    'view_zenith': ('L2T_LSTE', 'view_zenith'),
    'height': ('L2T_LSTE', 'height'),
    # L2T_STARS
    'NDVI': ('L2T_STARS', 'NDVI'),
    'NDVI-UQ': ('L2T_STARS', 'NDVI-UQ'),
    'albedo': ('L2T_STARS', 'albedo'),
    'albedo-UQ': ('L2T_STARS', 'albedo-UQ'),
    # L3T_ETAUX
    'Ta_C': ('L3T_ETAUX', 'Ta'),
    'Ta': ('L3T_ETAUX', 'Ta'),
    'RH': ('L3T_ETAUX', 'RH'),
    'SM': ('L3T_ETAUX', 'SM'),
    'Rg': ('L3T_ETAUX', 'Rg'),
    'Rn': ('L3T_ETAUX', 'Rn'),
    'cloud': ('L3T_ETAUX', 'cloud'),
    'water': ('L3T_ETAUX', 'water'),
    # L3T_JET (Evapotranspiration & Ensemble Partitioning)
    'PTJPLSMinst': ('L3T_JET', 'PTJPLSMinst'),
    'PTJPLSMdaily': ('L3T_JET', 'PTJPLSMdaily'),
    'PTJPLSMcanopy': ('L3T_JET', 'PTJPLSMcanopy'),
    'PTJPLSMsoil': ('L3T_JET', 'PTJPLSMsoil'),
    'PTJPLSMinterception': ('L3T_JET', 'PTJPLSMinterception'),
    'ETdaily': ('L3T_JET', 'ETdaily'),
    'ETuncertainty': ('L3T_JET', 'ETuncertainty'),
    'ETinstUncertainty': ('L3T_JET', 'ETuncertainty'),
    'STICJPLinst': ('L3T_JET', 'STICJPLinst'),
    'STICJPLdaily': ('L3T_JET', 'STICJPLdaily'),
    'STICJPLcanopy': ('L3T_JET', 'STICJPLcanopy'),
    'BESSJPLdaily': ('L3T_JET', 'BESSJPLdaily'),
    'PMJPLdaily': ('L3T_JET', 'PMJPLdaily'),
    # L4T Products
    'ESI': ('L4T_ESI', 'ESI'),
    'WUE': ('L4T_WUE', 'WUE'),
}

DEFAULT_LAYERS = ['ST_C', 'NDVI', 'albedo']
_TRANSIENT_HTTP_STATUS = {429, 502, 503, 504}


def _validate_layers(layers: List[str]) -> None:
    unknown_layers = [layer for layer in layers if layer not in LAYER_MAPPING]
    if unknown_layers:
        raise ValueError(
            f"Unknown layer(s): {', '.join(unknown_layers)}. "
            f"Available Collection 3 layers: {', '.join(LAYER_MAPPING)}"
        )
    if not layers:
        raise ValueError("At least one sampling layer must be requested")


def _apply_layer_names(results: pd.DataFrame, layers: List[str]) -> pd.DataFrame:
    source_variables = set()
    for layer in layers:
        _, variable = LAYER_MAPPING[layer]
        source_variables.add(variable)
        if layer == 'ST_C':
            if variable in results:
                results[layer] = results[variable] - 273.15
        elif layer != variable and variable in results:
            results[layer] = results[variable]

    unrequested_sources = [
        variable for variable in source_variables
        if variable not in layers and variable in results.columns
    ]
    return results.drop(columns=unrequested_sources)


def _overpass_key(granule: str) -> Optional[Tuple[str, str, str, str]]:
    """Return (orbit, scene, tile, timestamp) for instantaneous Collection 3 granules."""
    parts = granule.split('_')
    product = "_".join(parts[1:3]) if len(parts) > 2 else None
    if product and product != 'L2T_STARS' and len(parts) > 6:
        return (parts[3], parts[4], parts[5], parts[6])
    return None


def _http_get_with_jittered_backoff(
    session: requests.Session,
    url: str,
    timeout: int = 90,
    max_retries: int = 4,
    base_delay: float = 1.0,
) -> requests.Response:
    for attempt in range(max_retries):
        try:
            resp = session.get(url, allow_redirects=True, timeout=timeout)
            status = getattr(resp, "status_code", 200)
            if status in _TRANSIENT_HTTP_STATUS and attempt < max_retries - 1:
                retry_after = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
                delay = float(retry_after) if retry_after else (base_delay * (2 ** attempt) + random.uniform(0, 0.5))
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException:
            if attempt >= max_retries - 1:
                raise
            time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.5))
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} retries")


def _sample_from_dataset(
    src: rasterio.DatasetReader,
    lons: List[float],
    lats: List[float],
) -> List[Optional[float]]:
    bounds_wgs84 = transform_bounds(
        src.crs,
        CRS.from_epsg(4326),
        src.bounds.left,
        src.bounds.bottom,
        src.bounds.right,
        src.bounds.top,
    )
    in_bounds_indices = [
        i for i, (lon, lat) in enumerate(zip(lons, lats))
        if bounds_wgs84[0] <= lon <= bounds_wgs84[2] and bounds_wgs84[1] <= lat <= bounds_wgs84[3]
    ]
    extracted: List[Optional[float]] = [None] * len(lons)
    if not in_bounds_indices:
        return extracted

    sub_lons = [lons[i] for i in in_bounds_indices]
    sub_lats = [lats[i] for i in in_bounds_indices]
    xs, ys = transform(CRS.from_epsg(4326), src.crs, sub_lons, sub_lats)
    sampled = list(src.sample(zip(xs, ys), masked=True))
    for idx, val in zip(in_bounds_indices, sampled):
        scalar = val[0]
        if np.ma.is_masked(scalar) or np.isnan(float(scalar)):
            extracted[idx] = None
        else:
            extracted[idx] = float(scalar)
    return extracted


def _sample_single_variable_url(
    variable: str,
    url: str,
    lons: List[float],
    lats: List[float],
    session: Optional[requests.Session],
    use_vsicurl: bool,
    stream_semaphore: Optional[threading.Semaphore] = None,
) -> Tuple[str, List[Optional[float]]]:
    extracted: Optional[List[Optional[float]]] = None

    def _run_read() -> Optional[List[Optional[float]]]:
        nonlocal session
        local_extracted: Optional[List[Optional[float]]] = None
        if use_vsicurl:
            try:
                with rasterio.open(url) as src:
                    local_extracted = _sample_from_dataset(src, lons, lats)
            except Exception as exc:
                logger.debug(f"/vsicurl/ read failed for {url}, falling back to MemoryFile: {exc}")

        if local_extracted is None:
            if session is None:
                session = setup_earthdata_session()
            resp = _http_get_with_jittered_backoff(session, url, timeout=90)
            with MemoryFile(resp.content) as memfile, memfile.open() as src:
                local_extracted = _sample_from_dataset(src, lons, lats)
        return local_extracted

    if stream_semaphore is not None:
        with stream_semaphore:
            extracted = _run_read()
    else:
        extracted = _run_read()

    return variable, extracted if extracted is not None else [None] * len(lons)


def sample_points_from_granule(
    variable_urls: Dict[str, str],
    coords: List[Tuple[float, float]],
    layers: Optional[List[str]] = None,
    session: Optional[requests.Session] = None,
    use_vsicurl: bool = True,
    metadata_rows: Optional[List[Dict[str, Any]]] = None,
    max_workers: int = 8,
    stream_semaphore: Optional[threading.Semaphore] = None,
) -> pd.DataFrame:
    """
    Open each variable GeoTIFF once (concurrently across variables, optionally bounded
    by stream_semaphore) and extract all K coordinates in a single vectorized
    src.sample() call over /vsicurl/ (falling back to MemoryFile if needed).
    """
    if not coords:
        return pd.DataFrame()
    if layers is None:
        layers = DEFAULT_LAYERS.copy()
    _validate_layers(layers)

    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]

    records = []
    for i, (lon, lat) in enumerate(coords):
        rec: Dict[str, Any] = {"point_index": i, "lon": lon, "lat": lat}
        if metadata_rows and i < len(metadata_rows):
            rec.update(metadata_rows[i])
        records.append(rec)

    requested_vars = [
        v for v in dict.fromkeys(LAYER_MAPPING[layer][1] for layer in layers)
        if variable_urls.get(v)
    ]

    if max_workers > 1 and len(requested_vars) > 1:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(requested_vars))) as executor:
            futures = [
                executor.submit(
                    _sample_single_variable_url,
                    var,
                    variable_urls[var],
                    lons,
                    lats,
                    session,
                    use_vsicurl,
                    stream_semaphore,
                )
                for var in requested_vars
            ]
            for future in as_completed(futures):
                variable, extracted = future.result()
                for i, val in enumerate(extracted):
                    records[i][variable] = val
    else:
        for var in requested_vars:
            variable, extracted = _sample_single_variable_url(
                var,
                variable_urls[var],
                lons,
                lats,
                session,
                use_vsicurl,
                stream_semaphore,
            )
            for i, val in enumerate(extracted):
                records[i][variable] = val

    df = pd.DataFrame(records)
    return _apply_layer_names(df, layers)


def summarize_point_samples(
    results_or_paths: Union[pd.DataFrame, Sequence[Union[str, Path]]],
    layers: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Summarize valid observation counts and completeness percentages per layer.
    Accepts either an in-memory DataFrame or a sequence of Parquet file paths
    (computed via pyarrow metadata/batches in O(1) memory).
    """
    if isinstance(results_or_paths, pd.DataFrame):
        results_df = results_or_paths
        if layers is None:
            layers = [col for col in results_df.columns if col in LAYER_MAPPING]

        total = len(results_df)
        summary_rows = []
        for layer in layers:
            valid = int(results_df[layer].notna().sum()) if layer in results_df.columns else 0
            missing = total - valid
            pct = (100.0 * valid / total) if total > 0 else 0.0
            summary_rows.append(
                {
                    "layer": layer,
                    "total_rows": total,
                    "valid_count": valid,
                    "missing_count": missing,
                    "completeness_pct": round(pct, 2),
                }
            )
        return pd.DataFrame(summary_rows)

    parquet_paths = [Path(p) for p in results_or_paths if Path(p).exists()]
    if not parquet_paths:
        target_layers = layers or []
        return pd.DataFrame(
            [
                {
                    "layer": layer,
                    "total_rows": 0,
                    "valid_count": 0,
                    "missing_count": 0,
                    "completeness_pct": 0.0,
                }
                for layer in target_layers
            ]
        )

    first_pf = pq.ParquetFile(parquet_paths[0])
    schema_names = set(first_pf.schema_arrow.names)
    if layers is None:
        layers = [col for col in first_pf.schema_arrow.names if col in LAYER_MAPPING]

    total_rows = 0
    null_counts: Dict[str, int] = {layer: 0 for layer in layers}
    missing_cols = {layer for layer in layers if layer not in schema_names}

    for path in parquet_paths:
        pf = pq.ParquetFile(path)
        meta = pf.metadata
        file_rows = meta.num_rows
        total_rows += file_rows
        file_schema_names = pf.schema_arrow.names
        col_idx_map = {name: idx for idx, name in enumerate(file_schema_names)}

        for layer in layers:
            if layer not in col_idx_map:
                null_counts[layer] += file_rows
                continue
            col_idx = col_idx_map[layer]
            stats_available = True
            file_nulls = 0
            for rg in range(meta.num_row_groups):
                col_meta = meta.row_group(rg).column(col_idx)
                if col_meta.is_stats_set and col_meta.statistics.has_null_count:
                    file_nulls += col_meta.statistics.null_count
                else:
                    stats_available = False
                    break
            if stats_available:
                null_counts[layer] += file_nulls
            else:
                for batch in pf.iter_batches(columns=[layer]):
                    arr = batch.column(0)
                    null_counts[layer] += arr.null_count

    summary_rows = []
    for layer in layers:
        missing = null_counts[layer] if layer not in missing_cols else total_rows
        valid = max(0, total_rows - missing)
        pct = (100.0 * valid / total_rows) if total_rows > 0 else 0.0
        summary_rows.append(
            {
                "layer": layer,
                "total_rows": total_rows,
                "valid_count": valid,
                "missing_count": missing,
                "completeness_pct": round(pct, 2),
            }
        )
    return pd.DataFrame(summary_rows)


def _search_cmr_for_tile_product(
    tile: str,
    product: str,
    variables: List[str],
    start_date: date,
    end_date: date,
    session: Optional[requests.Session] = None,
    verbose: bool = False,
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    tile_product_files = {}

    try:
        search_results = ECOSTRESS_CMR_search(
            product=product,
            tile=tile,
            start_date=start_date,
            end_date=end_date,
            session=session,
        )

        if search_results.empty:
            return tile_product_files

        for variable in variables:
            var_files = search_results[
                (search_results['type'] == 'GeoTIFF Data') &
                (search_results['variable'] == variable)
            ]

            for _, file_row in var_files.iterrows():
                key = (file_row['granule'], variable)
                tile_product_files[key] = {
                    'url': file_row['URL'],
                    'orbit': file_row.get('orbit'),
                    'scene': file_row.get('scene'),
                    'product': product,
                }

    except Exception as e:
        logger.error(f"  [{tile}/{product}] Error searching: {e}")

    return tile_product_files


def sample_point_from_url(
    session: requests.Session,
    url: str,
    lon: float,
    lat: float,
    max_retries: int = 2,
    timeout: int = 90
) -> Tuple[Optional[float], Union[Dict[str, Any], str]]:
    """Sample a single point from a raster file accessed via URL."""
    for attempt in range(max_retries):
        try:
            response = session.get(url, allow_redirects=True, timeout=timeout)
            response.raise_for_status()

            with MemoryFile(response.content) as memfile:
                with memfile.open() as src:
                    bounds_wgs84 = transform_bounds(
                        src.crs,
                        CRS.from_epsg(4326),
                        src.bounds.left,
                        src.bounds.bottom,
                        src.bounds.right,
                        src.bounds.top
                    )

                    if not (bounds_wgs84[0] <= lon <= bounds_wgs84[2] and
                            bounds_wgs84[1] <= lat <= bounds_wgs84[3]):
                        return None, "outside_bounds"

                    try:
                        xs, ys = transform(
                            CRS.from_epsg(4326),
                            src.crs,
                            [lon],
                            [lat]
                        )
                        x_proj, y_proj = xs[0], ys[0]
                    except Exception as e:
                        return None, f"coordinate_transform_error: {e}"

                    try:
                        py, px = src.index(x_proj, y_proj)
                    except Exception as e:
                        return None, f"coordinate_error: {e}"

                    if not (0 <= py < src.height and 0 <= px < src.width):
                        return None, "outside_image"

                    window = Window(px, py, 1, 1)
                    value = src.read(1, window=window, masked=True)[0, 0]

                    nodata = src.nodata
                    if np.ma.is_masked(value):
                        return None, "nodata"

                    return float(value), {
                        'bounds': bounds_wgs84,
                        'crs': str(src.crs),
                        'nodata': nodata
                    }

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                logger.warning(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}")
                continue
            return None, f"network_error: {str(e)}"
        except Exception as e:
            return None, f"error: {str(e)}"

    return None, "failed_after_retries"


def find_sentinel2_tile(
    lon: float,
    lat: float,
    return_all: bool = False,
    land_only: bool = True,
) -> Union[Optional[str], List[str]]:
    """
    Find Sentinel-2 MGRS tile(s) containing the given WGS84 coordinate using true
    polygon intersection via sentinel_tiles.tiles(Point(lon, lat)) and optional
    land-tile filtering via sentinel_tiles.land(tile).
    """
    try:
        point = Point(lon, lat)
        raw_tiles = sorted(str(t) for t in sentinel_tiles.tiles(point))
        matching_tiles = [t for t in raw_tiles if sentinel_tiles.land(t)] if land_only else raw_tiles

        if return_all:
            return matching_tiles
        return matching_tiles[0] if matching_tiles else None
    except Exception as e:
        logger.error(f"Failed to find Sentinel-2 tile: {e}")
        return [] if return_all else None


def _build_granule_sampling_batches(
    points_data: List[Tuple[Any, Point, Dict[str, Any]]],
    point_tiles: Dict[Any, str],
    all_granule_files: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Group point observations by (tile, overpass/granule) so each remote COG variable
    is opened once per granule batch across all co-located points.
    """
    points_by_tile: Dict[str, List[Tuple[Any, Point, Dict[str, Any]]]] = {}
    for item in points_data:
        idx = item[0]
        if idx in point_tiles:
            points_by_tile.setdefault(point_tiles[idx], []).append(item)

    batches: List[Dict[str, Any]] = []
    for tile, tile_points in points_by_tile.items():
        tile_files = all_granule_files.get(tile, {})
        if not tile_files:
            continue

        granules = list(dict.fromkeys(g for g, _ in tile_files.keys()))
        urls_by_granule: Dict[str, Dict[str, str]] = {}
        for (g, var), info in tile_files.items():
            urls_by_granule.setdefault(g, {})[var] = info["url"]

        overpass_granules: Dict[str, Dict[Tuple[str, str, str, str], str]] = {}
        stars_by_date: Dict[str, str] = {}
        lste_dates: set = set()
        primary_overpasses = set()
        primary_dates = set()

        for granule in granules:
            parts = granule.split('_')
            product = "_".join(parts[1:3]) if len(parts) > 2 else None
            ovp_key = _overpass_key(granule)
            if product == 'L2T_LSTE' and ovp_key:
                primary_overpasses.add(ovp_key)
                lste_dates.add(ovp_key[3][:8])
                primary_dates.add(ovp_key[3][:8])
            elif product == 'L2T_STARS' and len(parts) > 4:
                stars_by_date[parts[4]] = granule
                primary_dates.add(parts[4])
            elif product and (product.startswith('L3T_') or product.startswith('L4T_')) and ovp_key:
                overpass_granules.setdefault(product, {})[ovp_key] = granule

        anchor_entries: List[Tuple[str, Optional[str], Optional[str], Optional[str], Dict[str, str]]] = []
        for granule in granules:
            parts = granule.split('_')
            product = "_".join(parts[1:3]) if len(parts) > 2 else None
            ovp_key = _overpass_key(granule)

            if product == 'L2T_LSTE' and len(parts) > 6:
                ts = parts[6]
                merged_urls = dict(urls_by_granule.get(granule, {}))
                stars_g = stars_by_date.get(ts[:8])
                if stars_g:
                    merged_urls.update(urls_by_granule.get(stars_g, {}))
                if ovp_key:
                    for ovp_map in overpass_granules.values():
                        matched_g = ovp_map.get(ovp_key)
                        if matched_g:
                            merged_urls.update(urls_by_granule.get(matched_g, {}))
                anchor_entries.append((granule, ts, parts[3], parts[4], merged_urls))
            elif product == 'L2T_STARS' and len(parts) > 4:
                date_str = parts[4]
                if date_str in lste_dates:
                    continue
                merged_urls = dict(urls_by_granule.get(granule, {}))
                for ovp_map in overpass_granules.values():
                    for k, matched_g in ovp_map.items():
                        if k[3].startswith(date_str):
                            merged_urls.update(urls_by_granule.get(matched_g, {}))
                            break
                anchor_entries.append((granule, date_str, None, None, merged_urls))

        for ovp_map in overpass_granules.values():
            for ovp_key, granule in ovp_map.items():
                if ovp_key in primary_overpasses or ovp_key[3][:8] in primary_dates:
                    continue
                anchor_entries.append(
                    (granule, ovp_key[3], ovp_key[0], ovp_key[1], dict(urls_by_granule.get(granule, {})))
                )

        coords = [(pt.x, pt.y) for _, pt, _ in tile_points]
        for granule, ts, orbit, scene, merged_urls in anchor_entries:
            meta_rows = []
            for idx, _, metadata in tile_points:
                row_meta = {
                    "point_index": idx,
                    "granule": granule,
                    "tile": tile,
                    "timestamp": ts,
                    "orbit": orbit,
                    "scene": scene,
                }
                row_meta.update(metadata)
                meta_rows.append(row_meta)
            batches.append(
                {
                    "variable_urls": merged_urls,
                    "coords": coords,
                    "metadata_rows": meta_rows,
                }
            )

    return batches


def sample_points_over_date_range(
    geometry: Union[gpd.GeoDataFrame, gpd.GeoSeries, pd.Series, List[Point], Point],
    start_date: Union[date, str],
    end_date: Union[date, str],
    layers: Optional[List[str]] = None,
    tile: Optional[Union[str, List[str]]] = None,
    session: Optional[requests.Session] = None,
    max_workers: int = 10,
    drop_na: bool = True,
    use_vsicurl: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """Sample ECOSTRESS data at multiple points for all available acquisitions in a date range."""
    if layers is None:
        layers = DEFAULT_LAYERS.copy()

    points_data = []

    if isinstance(geometry, gpd.GeoDataFrame):
        if geometry.crs is None:
            raise ValueError("GeoDataFrame must have a defined CRS")
        if not geometry.crs.equals(CRS.from_epsg(4326)):
            geometry = geometry.to_crs('EPSG:4326')

        for idx, row in geometry.iterrows():
            point = row.get('geometry') or row.get(geometry.index.name)
            if not isinstance(point, Point):
                continue
            metadata = {col: row[col] for col in geometry.columns if col != 'geometry'}
            points_data.append((idx, point, metadata))

    elif isinstance(geometry, gpd.GeoSeries):
        if geometry.crs is None:
            raise ValueError("GeoSeries must have a defined CRS")
        if not geometry.crs.equals(CRS.from_epsg(4326)):
            geometry = geometry.to_crs('EPSG:4326')

        for idx, point in geometry.items():
            if isinstance(point, Point):
                points_data.append((idx, point, {}))

    elif isinstance(geometry, pd.Series):
        if 'geometry' not in geometry:
            raise ValueError("Series must have a 'geometry' key")
        point = geometry['geometry']
        if not isinstance(point, Point):
            raise ValueError(f"Series geometry is not a Point: {type(point)}")
        metadata = {key: geometry[key] for key in geometry.index if key != 'geometry'}
        points_data.append((0, point, metadata))

    elif isinstance(geometry, list):
        for idx, point in enumerate(geometry):
            if isinstance(point, Point):
                points_data.append((idx, point, {}))

    elif isinstance(geometry, Point):
        points_data.append((0, geometry, {}))

    else:
        raise ValueError(
            "geometry must be a GeoDataFrame, GeoSeries, Series (single row), list of Point objects, or a single Point"
        )

    if not points_data:
        raise ValueError("No valid point geometries found in input")

    _validate_layers(layers)

    products: Dict[str, List[str]] = {}
    for layer in layers:
        product, variable = LAYER_MAPPING[layer]
        products.setdefault(product, [])
        if variable not in products[product]:
            products[product].append(variable)

    if isinstance(start_date, str):
        start_date = pd.to_datetime(start_date).date()
    if isinstance(end_date, str):
        end_date = pd.to_datetime(end_date).date()

    if session is None:
        session = setup_earthdata_session()

    point_tiles = {}
    if isinstance(tile, str):
        for idx, _, _ in points_data:
            point_tiles[idx] = tile
    elif isinstance(tile, list):
        if len(tile) != len(points_data):
            raise ValueError(f"tile list length ({len(tile)}) must match number of points ({len(points_data)})")
        for (idx, _, _), t in zip(points_data, tile):
            point_tiles[idx] = t
    else:
        for idx, point, _ in points_data:
            determined_tile = find_sentinel2_tile(point.x, point.y)
            if determined_tile:
                point_tiles[idx] = determined_tile

    tiles_to_search = set(point_tiles.values())
    if not tiles_to_search:
        return pd.DataFrame()

    all_granule_files: Dict[str, Dict] = {}
    search_combinations = [
        (t, prod, vars_list)
        for t in tiles_to_search
        for prod, vars_list in products.items()
    ]

    if max_workers > 1 and len(search_combinations) > 1:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(search_combinations))) as executor:
            future_to_search = {
                executor.submit(
                    _search_cmr_for_tile_product,
                    t, prod, vars_list, start_date, end_date, session, False
                ): (t, prod) for t, prod, vars_list in search_combinations
            }
            for future in as_completed(future_to_search):
                t, _ = future_to_search[future]
                all_granule_files.setdefault(t, {}).update(future.result())
    else:
        for t in tiles_to_search:
            tile_files = {}
            for prod, vars_list in products.items():
                tile_files.update(
                    _search_cmr_for_tile_product(t, prod, vars_list, start_date, end_date, session, verbose)
                )
            all_granule_files[t] = tile_files

    batches = _build_granule_sampling_batches(points_data, point_tiles, all_granule_files)
    if not batches:
        return pd.DataFrame()

    stream_semaphore = threading.Semaphore(max(1, max_workers * 2))
    batch_frames: List[pd.DataFrame] = []

    def _run_batch(batch: Dict[str, Any]) -> pd.DataFrame:
        return sample_points_from_granule(
            variable_urls=batch["variable_urls"],
            coords=batch["coords"],
            layers=layers,
            session=session,
            use_vsicurl=use_vsicurl,
            metadata_rows=batch["metadata_rows"],
            max_workers=max_workers,
            stream_semaphore=stream_semaphore,
        )

    if max_workers > 1 and len(batches) > 1:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(batches))) as executor:
            for future in as_completed([executor.submit(_run_batch, b) for b in batches]):
                df_part = future.result()
                if not df_part.empty:
                    batch_frames.append(df_part)
    else:
        for b in batches:
            df_part = _run_batch(b)
            if not df_part.empty:
                batch_frames.append(df_part)

    if not batch_frames:
        return pd.DataFrame()

    results_df = pd.concat(batch_frames, ignore_index=True)
    sampled_cols = [col for col in results_df.columns if col in layers]
    if sampled_cols:
        if drop_na:
            results_df = results_df[results_df[sampled_cols].notna().all(axis=1)]
        else:
            results_df = results_df[results_df[sampled_cols].notna().any(axis=1)]

    return results_df.reset_index(drop=True)


def sample_points_from_geodataframe(
    geometry: Union[gpd.GeoDataFrame, gpd.GeoSeries, List[Point]],
    layers: Optional[List[str]] = None,
    datetime_col: str = 'datetime',
    tile_col: Optional[str] = None,
    session: Optional[requests.Session] = None,
    date_buffer_days: int = 0,
    max_workers: int = 10,
    use_vsicurl: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Sample ECOSTRESS data at multiple points with known acquisition times,
    grouping CMR searches by (tile, date_window) and joining L2T_STARS priors by date.
    """
    if layers is None:
        layers = DEFAULT_LAYERS.copy()

    if isinstance(geometry, list):
        gdf = gpd.GeoDataFrame({'geometry': geometry}, crs='EPSG:4326')
    elif isinstance(geometry, gpd.GeoSeries):
        gdf = gpd.GeoDataFrame({'geometry': geometry}, crs=geometry.crs)
    elif isinstance(geometry, gpd.GeoDataFrame):
        gdf = geometry
    else:
        raise TypeError(f"geometry must be GeoDataFrame, GeoSeries, or list of Point, got {type(geometry)}")

    if gdf.crs is None:
        raise ValueError("GeoDataFrame must have a defined CRS")

    if not gdf.crs.equals(CRS.from_epsg(4326)):
        gdf = gdf.to_crs('EPSG:4326')

    geometry_col = gdf.geometry.name
    if datetime_col not in gdf.columns:
        raise ValueError(f"Datetime column '{datetime_col}' not found in GeoDataFrame")

    _validate_layers(layers)

    products: Dict[str, List[str]] = {}
    for layer in layers:
        product, variable = LAYER_MAPPING[layer]
        products.setdefault(product, [])
        if variable not in products[product]:
            products[product].append(variable)

    if session is None:
        session = setup_earthdata_session()

    grouped_rows: Dict[Tuple[str, date, date], List[Tuple[Any, Point, Dict[str, Any]]]] = {}
    for idx, row in gdf.iterrows():
        point = row[geometry_col]
        dt = row[datetime_col]
        if not isinstance(point, Point):
            continue

        lon, lat = point.x, point.y
        search_date = (
            dt.date()
            if isinstance(dt, datetime)
            else (dt if isinstance(dt, date) else pd.to_datetime(dt).date())
        )
        tile = row[tile_col] if (tile_col and tile_col in row and pd.notna(row[tile_col])) else find_sentinel2_tile(lon, lat)
        if not tile:
            continue

        start_date = search_date - timedelta(days=date_buffer_days)
        end_date = search_date + timedelta(days=date_buffer_days)
        meta = {col: row[col] for col in gdf.columns if col != geometry_col}
        meta["search_date"] = search_date
        grouped_rows.setdefault((tile, start_date, end_date), []).append((idx, point, meta))

    if not grouped_rows:
        return pd.DataFrame()

    all_frames: List[pd.DataFrame] = []
    for (tile, start_date, end_date), group_points in grouped_rows.items():
        tile_files: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for prod, vars_list in products.items():
            tile_files.update(
                _search_cmr_for_tile_product(tile, prod, vars_list, start_date, end_date, session, verbose)
            )
        if not tile_files:
            continue

        point_tiles = {idx: tile for idx, _, _ in group_points}
        batches = _build_granule_sampling_batches(group_points, point_tiles, {tile: tile_files})
        for batch in batches:
            for meta in batch["metadata_rows"]:
                meta["gdf_index"] = meta.pop("point_index")
            df_part = sample_points_from_granule(
                variable_urls=batch["variable_urls"],
                coords=batch["coords"],
                layers=layers,
                session=session,
                use_vsicurl=use_vsicurl,
                metadata_rows=batch["metadata_rows"],
                max_workers=max_workers,
            )
            if not df_part.empty:
                all_frames.append(df_part)

    if not all_frames:
        return pd.DataFrame()

    results_df = pd.concat(all_frames, ignore_index=True)
    sampled_cols = [col for col in results_df.columns if col in layers]
    if sampled_cols:
        results_df = results_df[results_df[sampled_cols].notna().any(axis=1)]
    return results_df.reset_index(drop=True)