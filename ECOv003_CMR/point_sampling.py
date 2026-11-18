"""
Point sampling from ECOSTRESS Collection 3 data.

This module provides functions for sampling ECOSTRESS raster data at specific
geographic points, supporting single-point queries, granule-grouped /vsicurl/
COG batch reads, and GeoDataFrame workflows.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Union, List, Dict, Tuple, Any
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    tqdm = None
import geopandas as gpd
import requests
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import Window
from rasterio.warp import transform, transform_bounds
from rasterio.crs import CRS
from shapely.geometry import Point
from sentinel_tiles import sentinel_tiles

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


def sample_points_from_granule(
    variable_urls: Dict[str, str],
    coords: List[Tuple[float, float]],
    layers: Optional[List[str]] = None,
    session: Optional[requests.Session] = None,
    use_vsicurl: bool = True,
    metadata_rows: Optional[List[Dict[str, Any]]] = None,
) -> pd.DataFrame:
    """
    Open each variable GeoTIFF once and extract all K coordinates in a single
    vectorized src.sample(proj_coords, masked=True) call over /vsicurl/
    (falling back to MemoryFile if needed).
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

    requested_vars = list(dict.fromkeys(LAYER_MAPPING[layer][1] for layer in layers))

    for variable in requested_vars:
        url = variable_urls.get(variable)
        if not url:
            continue

        extracted: Optional[List[Optional[float]]] = None
        if use_vsicurl:
            try:
                with rasterio.open(url) as src:
                    xs, ys = transform(CRS.from_epsg(4326), src.crs, lons, lats)
                    sampled = list(src.sample(zip(xs, ys), masked=True))
                    extracted = [
                        None if np.ma.is_masked(val[0]) or np.isnan(float(val[0])) else float(val[0])
                        for val in sampled
                    ]
            except Exception as exc:
                logger.debug(f"/vsicurl/ read failed for {url}, falling back to MemoryFile: {exc}")

        if extracted is None:
            if session is None:
                session = setup_earthdata_session()
            resp = session.get(url, allow_redirects=True, timeout=90)
            resp.raise_for_status()
            with MemoryFile(resp.content) as memfile, memfile.open() as src:
                xs, ys = transform(CRS.from_epsg(4326), src.crs, lons, lats)
                sampled = list(src.sample(zip(xs, ys), masked=True))
                extracted = [
                    None if np.ma.is_masked(val[0]) or np.isnan(float(val[0])) else float(val[0])
                    for val in sampled
                ]

        for i, val in enumerate(extracted):
            records[i][variable] = val

    df = pd.DataFrame(records)
    return _apply_layer_names(df, layers)


def summarize_point_samples(
    results_df: pd.DataFrame, layers: Optional[List[str]] = None
) -> pd.DataFrame:
    """Summarize valid observation counts and completeness percentages per layer."""
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


def _search_cmr_for_tile_product(
    tile: str,
    product: str,
    variables: List[str],
    start_date: date,
    end_date: date,
    verbose: bool = False
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    tile_product_files = {}

    try:
        search_results = ECOSTRESS_CMR_search(
            product=product,
            tile=tile,
            start_date=start_date,
            end_date=end_date
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
                    'product': product
                }

    except Exception as e:
        logger.error(f"  [{tile}/{product}] Error searching: {e}")

    return tile_product_files


def _sample_single_point_granule(
    session: requests.Session,
    point_idx: int,
    point: Point,
    metadata: dict,
    lon: float,
    lat: float,
    point_tile: str,
    granule: str,
    timestamp: Optional[str],
    orbit: Optional[str],
    scene: Optional[str],
    tile_files: Dict,
    products: Dict[str, List[str]],
    overpass_granules: Dict[str, Dict[Tuple[str, str, str, str], str]],
    stars_by_date: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    granule_data = {
        'point_index': point_idx,
        'granule': granule,
        'lon': lon,
        'lat': lat,
        'tile': point_tile,
        'timestamp': timestamp,
        'orbit': orbit,
        'scene': scene
    }
    granule_data.update(metadata)

    has_data = False
    parts = granule.split('_')
    product = "_".join(parts[1:3]) if len(parts) > 2 else None
    ovp_key = _overpass_key(granule)

    if product == 'L2T_LSTE':
        for variable in products.get('L2T_LSTE', []):
            key = (granule, variable)
            if key not in tile_files:
                continue
            value, _ = sample_point_from_url(session, tile_files[key]['url'], lon, lat)
            if value is not None:
                has_data = True
                granule_data[variable] = value

        if timestamp and len(timestamp) >= 8:
            date_str = timestamp[:8]
            stars_granule = stars_by_date.get(date_str)
            if stars_granule:
                for variable in products.get('L2T_STARS', []):
                    key = (stars_granule, variable)
                    if key not in tile_files:
                        continue
                    value, _ = sample_point_from_url(session, tile_files[key]['url'], lon, lat)
                    if value is not None:
                        has_data = True
                        granule_data[variable] = value

            if ovp_key:
                for prod, ovp_map in overpass_granules.items():
                    matched_granule = ovp_map.get(ovp_key)
                    if not matched_granule:
                        continue
                    for variable in products.get(prod, []):
                        key = (matched_granule, variable)
                        if key not in tile_files:
                            continue
                        value, _ = sample_point_from_url(session, tile_files[key]['url'], lon, lat)
                        if value is not None:
                            has_data = True
                            granule_data[variable] = value

    elif product == 'L2T_STARS':
        for variable in products.get('L2T_STARS', []):
            key = (granule, variable)
            if key not in tile_files:
                continue
            value, _ = sample_point_from_url(session, tile_files[key]['url'], lon, lat)
            if value is not None:
                has_data = True
                granule_data[variable] = value

        if len(parts) > 4:
            date_str = parts[4]
            for prod, ovp_map in overpass_granules.items():
                for k, matched_granule in ovp_map.items():
                    if k[3].startswith(date_str):
                        for variable in products.get(prod, []):
                            key = (matched_granule, variable)
                            if key not in tile_files:
                                continue
                            value, _ = sample_point_from_url(session, tile_files[key]['url'], lon, lat)
                            if value is not None:
                                has_data = True
                                granule_data[variable] = value
                        break

    elif product and (product.startswith('L3T_') or product.startswith('L4T_')):
        for variable in products.get(product, []):
            key = (granule, variable)
            if key not in tile_files:
                continue
            value, _ = sample_point_from_url(session, tile_files[key]['url'], lon, lat)
            if value is not None:
                has_data = True
                granule_data[variable] = value

    return granule_data if has_data else None


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


def find_sentinel2_tile(lon: float, lat: float) -> Optional[str]:
    """Find which Sentinel-2 tile contains the given coordinate."""
    try:
        point = Point(lon, lat)
        return sentinel_tiles.nearest(point)
    except Exception as e:
        logger.error(f"Failed to find Sentinel-2 tile: {e}")
        return None


def sample_points_over_date_range(
    geometry: Union[gpd.GeoDataFrame, gpd.GeoSeries, pd.Series, List[Point], Point],
    start_date: Union[date, str],
    end_date: Union[date, str],
    layers: Optional[List[str]] = None,
    tile: Optional[Union[str, List[str]]] = None,
    session: Optional[requests.Session] = None,
    max_workers: int = 10,
    drop_na: bool = True,
    verbose: bool = True
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
                    t, prod, vars_list, start_date, end_date, False
                ): (t, prod) for t, prod, vars_list in search_combinations
            }
            for future in as_completed(future_to_search):
                t, _ = future_to_search[future]
                all_granule_files.setdefault(t, {}).update(future.result())
    else:
        for t in tiles_to_search:
            tile_files = {}
            for prod, vars_list in products.items():
                tile_files.update(_search_cmr_for_tile_product(t, prod, vars_list, start_date, end_date, verbose))
            all_granule_files[t] = tile_files

    granules_by_tile = {
        t: list(dict.fromkeys(granule for granule, _ in tf.keys()))
        for t, tf in all_granule_files.items()
    }

    sampling_tasks = []
    for idx, point, metadata in points_data:
        if idx not in point_tiles:
            continue
        lon, lat = point.x, point.y
        point_tile = point_tiles[idx]
        tile_files = all_granule_files.get(point_tile, {})
        granules = granules_by_tile.get(point_tile, [])
        if not granules:
            continue

        overpass_granules: Dict[str, Dict[Tuple[str, str, str, str], str]] = {}
        stars_by_date: Dict[str, str] = {}
        primary_overpasses = set()
        primary_dates = set()

        for granule in granules:
            parts = granule.split('_')
            product = "_".join(parts[1:3]) if len(parts) > 2 else None
            ovp_key = _overpass_key(granule)

            if product == 'L2T_LSTE' and ovp_key:
                primary_overpasses.add(ovp_key)
                primary_dates.add(ovp_key[3][:8])
            elif product == 'L2T_STARS' and len(parts) > 4:
                stars_by_date[parts[4]] = granule
                primary_dates.add(parts[4])
            elif product and (product.startswith('L3T_') or product.startswith('L4T_')) and ovp_key:
                overpass_granules.setdefault(product, {})[ovp_key] = granule

        for granule in granules:
            parts = granule.split('_')
            product = "_".join(parts[1:3]) if len(parts) > 2 else None
            if product == 'L2T_LSTE' and len(parts) > 6:
                sampling_tasks.append((
                    idx, point, metadata, lon, lat, point_tile,
                    granule, parts[6], parts[3], parts[4],
                    tile_files, products, overpass_granules, stars_by_date
                ))
            elif product == 'L2T_STARS' and len(parts) > 4:
                sampling_tasks.append((
                    idx, point, metadata, lon, lat, point_tile,
                    granule, parts[4], None, None,
                    tile_files, products, overpass_granules, stars_by_date
                ))

        for ovp_map in overpass_granules.values():
            for ovp_key, granule in ovp_map.items():
                if ovp_key in primary_overpasses or ovp_key[3][:8] in primary_dates:
                    continue
                sampling_tasks.append((
                    idx, point, metadata, lon, lat, point_tile,
                    granule, ovp_key[3], ovp_key[0], ovp_key[1],
                    tile_files, products, overpass_granules, stars_by_date
                ))

    all_results = []
    if max_workers > 1 and sampling_tasks:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_sample_single_point_granule, session, *t) for t in sampling_tasks]
            for future in as_completed(futures):
                res = future.result()
                if res is not None:
                    all_results.append(res)
    else:
        for t in sampling_tasks:
            res = _sample_single_point_granule(session, *t)
            if res is not None:
                all_results.append(res)

    if not all_results:
        return pd.DataFrame()

    results_df = pd.DataFrame(all_results)
    results_df = _apply_layer_names(results_df, layers)

    if drop_na and len(results_df) > 0:
        sampled_cols = [col for col in results_df.columns if col in layers]
        if sampled_cols:
            results_df = results_df[results_df[sampled_cols].notna().all(axis=1)]

    return results_df


def sample_points_from_geodataframe(
    geometry: Union[gpd.GeoDataFrame, gpd.GeoSeries, List[Point]],
    layers: Optional[List[str]] = None,
    datetime_col: str = 'datetime',
    tile_col: Optional[str] = None,
    session: Optional[requests.Session] = None,
    date_buffer_days: int = 0,
    verbose: bool = True
) -> pd.DataFrame:
    """Sample ECOSTRESS data at multiple points with known acquisition times."""
    if layers is None:
        layers = DEFAULT_LAYERS

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

    all_results = []
    for idx, row in gdf.iterrows():
        point = row['geometry']
        dt = row[datetime_col]
        if not isinstance(point, Point):
            continue

        lon, lat = point.x, point.y
        search_date = dt.date() if isinstance(dt, datetime) else (dt if isinstance(dt, date) else pd.to_datetime(dt).date())
        tile = row[tile_col] if (tile_col and tile_col in row) else find_sentinel2_tile(lon, lat)
        if not tile:
            continue

        start_date = search_date - timedelta(days=date_buffer_days)
        end_date = search_date + timedelta(days=date_buffer_days)

        point_files = {}
        for product, variables in products.items():
            search_results = ECOSTRESS_CMR_search(
                product=product,
                tile=tile,
                start_date=start_date,
                end_date=end_date
            )
            if search_results.empty:
                continue
            for variable in variables:
                var_files = search_results[
                    (search_results['type'] == 'GeoTIFF Data') &
                    (search_results['variable'] == variable)
                ]
                for _, file_row in var_files.iterrows():
                    point_files[(file_row['granule'], variable)] = file_row['URL']

        if not point_files:
            continue

        unique_granules = list(dict.fromkeys(g for g, _ in point_files.keys()))
        for granule in unique_granules:
            granule_data = {
                'gdf_index': idx,
                'granule': granule,
                'lon': lon,
                'lat': lat,
                'tile': tile,
                'search_date': search_date
            }
            for col in gdf.columns:
                if col != geometry_col and col not in granule_data:
                    granule_data[col] = row[col]

            parts = granule.split('_')
            if len(parts) > 6:
                granule_data['timestamp'] = parts[6] if 'T' in parts[6] else parts[4]

            has_data = False
            for variable in [v for vars_list in products.values() for v in vars_list]:
                url = point_files.get((granule, variable))
                if not url:
                    continue
                value, _ = sample_point_from_url(session, url, lon, lat)
                if value is not None:
                    has_data = True
                    granule_data[variable] = value

            if has_data:
                all_results.append(granule_data)

    if not all_results:
        return pd.DataFrame()

    results_df = pd.DataFrame(all_results)
    return _apply_layer_names(results_df, layers)
