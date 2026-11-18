"""
Point sampling from ECOSTRESS Collection 3 data.

This module provides functions for sampling ECOSTRESS raster data at specific
geographic points, supporting both single-point queries and batch processing
of GeoDataFrames.
"""

from datetime import date, datetime
from typing import Optional, Union, List, Dict, Tuple, Any
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

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
    'ST_C': ('L2T_LSTE', 'LST'),           # Surface Temperature in Celsius (converted from Kelvin)
    'LST': ('L2T_LSTE', 'LST'),            # Land Surface Temperature (Kelvin)
    'LST_err': ('L2T_LSTE', 'LST_err'),    # LST uncertainty
    'QC': ('L2T_LSTE', 'QC'),              # Quality control
    'emissivity': ('L2T_LSTE', 'EmisWB'),  # Wideband emissivity (alias for EmisWB)
    'EmisWB': ('L2T_LSTE', 'EmisWB'),      # Wideband emissivity
    'NDVI': ('L2T_STARS', 'NDVI'),         # Normalized Difference Vegetation Index
    'albedo': ('L2T_STARS', 'albedo'),     # Surface albedo
    'Ta_C': ('L3T_ETAUX', 'Ta'),            # Air temperature in Celsius
    'Ta': ('L3T_ETAUX', 'Ta'),              # Alias for Ta_C
    'RH': ('L3T_ETAUX', 'RH'),              # Relative humidity ratio (0-1)
    'SM': ('L3T_ETAUX', 'SM'),              # Soil moisture ratio (0-1)
    'Rg': ('L3T_ETAUX', 'Rg'),              # Global radiation (W/m2)
    'Rn': ('L3T_ETAUX', 'Rn'),              # Net radiation (W/m2)
    'cloud': ('L3T_ETAUX', 'cloud'),        # Cloud mask
    'water': ('L3T_ETAUX', 'water'),        # Water mask
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


def _search_cmr_for_tile_product(
    tile: str,
    product: str,
    variables: List[str],
    start_date: date,
    end_date: date,
    verbose: bool = False
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    Search CMR for a specific tile-product combination. Helper for parallel execution.
    """
    tile_product_files = {}

    try:
        search_results = ECOSTRESS_CMR_search(
            product=product,
            tile=tile,
            start_date=start_date,
            end_date=end_date
        )

        if search_results.empty:
            if verbose:
                logger.info(f"  [{tile}/{product}] No granules found")
            return tile_product_files

        # Filter to desired variables
        for variable in variables:
            var_files = search_results[
                (search_results['type'] == 'GeoTIFF Data') &
                (search_results['variable'] == variable)
            ]

            if not var_files.empty:
                if verbose:
                    logger.info(f"  [{tile}/{product}] Found {len(var_files)} {variable} files")

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
    daily_granules: Dict
) -> Optional[Dict[str, Any]]:
    """
    Sample a single point-granule combination. Helper function for parallel execution.
    """
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

    # Copy metadata from original input
    granule_data.update(metadata)

    has_data = False

    # Determine product type and date from granule name
    parts = granule.split('_')
    product = "_".join(parts[1:3]) if len(parts) > 2 else None

    if product == 'L2T_LSTE':
        # LST granule - sample LST variables
        for variable in products.get('L2T_LSTE', []):
            key = (granule, variable)
            if key not in tile_files:
                continue

            file_info = tile_files[key]
            value, meta = sample_point_from_url(
                session,
                file_info['url'],
                lon,
                lat
            )

            if value is not None:
                has_data = True
                granule_data[variable] = value

        # Match with STARS and L3T data for this date
        if timestamp and len(timestamp) >= 8:
            date_str = timestamp[:8]

            # Look for STARS granule for this date
            stars_granule = None
            for test_granule in [k[0] for k in tile_files.keys() if 'L2T_STARS' in k[0]]:
                test_parts = test_granule.split('_')
                if len(test_parts) > 4 and test_parts[4] == date_str:
                    stars_granule = test_granule
                    break

            if stars_granule:
                for variable in products.get('L2T_STARS', []):
                    key = (stars_granule, variable)
                    if key not in tile_files:
                        continue

                    file_info = tile_files[key]
                    value, meta = sample_point_from_url(
                        session,
                        file_info['url'],
                        lon,
                        lat
                    )

                    if value is not None:
                        has_data = True
                        granule_data[variable] = value

            # Sample L3T/L4T products for this date
            for prod, date_granules in daily_granules.items():
                if date_str in date_granules:
                    product_granule = date_granules[date_str]
                    for variable in products.get(prod, []):
                        key = (product_granule, variable)
                        if key not in tile_files:
                            continue

                        file_info = tile_files[key]
                        value, meta = sample_point_from_url(
                            session,
                            file_info['url'],
                            lon,
                            lat
                        )

                        if value is not None:
                            has_data = True
                            granule_data[variable] = value

    elif product == 'L2T_STARS':
        # STARS-only granule
        for variable in products.get('L2T_STARS', []):
            key = (granule, variable)
            if key not in tile_files:
                continue

            file_info = tile_files[key]
            value, meta = sample_point_from_url(
                session,
                file_info['url'],
                lon,
                lat
            )

            if value is not None:
                has_data = True
                granule_data[variable] = value

        # Match with L3T data for this date
        if len(parts) > 4:
            date_str = parts[4]
            for prod, date_granules in daily_granules.items():
                if date_str in date_granules:
                    product_granule = date_granules[date_str]
                    for variable in products.get(prod, []):
                        key = (product_granule, variable)
                        if key not in tile_files:
                            continue

                        file_info = tile_files[key]
                        value, meta = sample_point_from_url(
                            session,
                            file_info['url'],
                            lon,
                            lat
                        )

                        if value is not None:
                            has_data = True
                            granule_data[variable] = value

    elif product and (product.startswith('L3T_') or product.startswith('L4T_')):
        for variable in products.get(product, []):
            key = (granule, variable)
            if key not in tile_files:
                continue

            file_info = tile_files[key]
            value, meta = sample_point_from_url(
                session,
                file_info['url'],
                lon,
                lat
            )

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
    """
    Sample a single point from a raster file accessed via URL.
    """
    for attempt in range(max_retries):
        try:
            response = session.get(url, allow_redirects=True, timeout=timeout)
            response.raise_for_status()

            with MemoryFile(response.content) as memfile:
                with memfile.open() as src:
                    # Transform bounds to WGS84 for comparison with input lon/lat
                    bounds_wgs84 = transform_bounds(
                        src.crs,
                        CRS.from_epsg(4326),
                        src.bounds.left,
                        src.bounds.bottom,
                        src.bounds.right,
                        src.bounds.top
                    )

                    # Check if point is within bounds (both in WGS84)
                    if not (bounds_wgs84[0] <= lon <= bounds_wgs84[2] and
                            bounds_wgs84[1] <= lat <= bounds_wgs84[3]):
                        return None, "outside_bounds"

                    # Transform point from WGS84 to raster CRS for pixel indexing
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

                    # Get pixel coordinates using transformed coordinates
                    try:
                        py, px = src.index(x_proj, y_proj)
                    except Exception as e:
                        return None, f"coordinate_error: {e}"

                    # Verify pixel is within image
                    if not (0 <= py < src.height and 0 <= px < src.width):
                        return None, "outside_image"

                    # Read pixel value
                    window = Window(px, py, 1, 1)
                    value = src.read(1, window=window, masked=True)[0, 0]

                    # Respect nodata values and internal raster masks, including NaN fill.
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
    """
    Find which Sentinel-2 tile contains the given coordinate.
    """
    try:
        point = Point(lon, lat)
        tile_name = sentinel_tiles.nearest(point)
        return tile_name
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
    """
    Sample ECOSTRESS data at multiple points for all available acquisitions in a date range.
    """
    # Set default layers if not provided
    if layers is None:
        layers = DEFAULT_LAYERS.copy()

    # Convert geometry input to standardized format
    points_data = []  # List of (index, point, metadata_dict)

    if isinstance(geometry, gpd.GeoDataFrame):
        if geometry.crs is None:
            raise ValueError("GeoDataFrame must have a defined CRS")
        if not geometry.crs.equals(CRS.from_epsg(4326)):
            if verbose:
                logger.info(f"Reprojecting GeoDataFrame from {geometry.crs} to EPSG:4326")
            geometry = geometry.to_crs('EPSG:4326')

        for idx, row in geometry.iterrows():
            point = row.get('geometry') or row.get(geometry.index.name)
            if not isinstance(point, Point):
                logger.warning(f"Row {idx}: geometry is not a Point, skipping")
                continue
            metadata = {col: row[col] for col in geometry.columns if col != 'geometry'}
            points_data.append((idx, point, metadata))

    elif isinstance(geometry, gpd.GeoSeries):
        if geometry.crs is None:
            raise ValueError("GeoSeries must have a defined CRS")
        if not geometry.crs.equals(CRS.from_epsg(4326)):
            if verbose:
                logger.info(f"Reprojecting GeoSeries from {geometry.crs} to EPSG:4326")
            geometry = geometry.to_crs('EPSG:4326')

        for idx, point in geometry.items():
            if not isinstance(point, Point):
                logger.warning(f"Index {idx}: geometry is not a Point, skipping")
                continue
            points_data.append((idx, point, {}))

    elif isinstance(geometry, pd.Series):
        if 'geometry' not in geometry:
            raise ValueError("Series must have a 'geometry' key")

        point = geometry['geometry']
        if not isinstance(point, Point):
            raise ValueError(f"Series geometry is not a Point: {type(point)}")

        if isinstance(geometry, gpd.GeoSeries) and geometry.crs is not None:
            if not geometry.crs.equals(CRS.from_epsg(4326)):
                if verbose:
                    logger.info(f"Reprojecting point from {geometry.crs} to EPSG:4326")
                geometry = geometry.to_crs('EPSG:4326')
                point = geometry['geometry']

        metadata = {key: geometry[key] for key in geometry.index if key != 'geometry'}
        points_data.append((0, point, metadata))

    elif isinstance(geometry, list):
        for idx, point in enumerate(geometry):
            if not isinstance(point, Point):
                logger.warning(f"Index {idx}: not a Point object, skipping")
                continue
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

    # Map layer names to products/variables
    products = {}
    for layer in layers:
        product, variable = LAYER_MAPPING[layer]
        if product not in products:
            products[product] = []
        if variable not in products[product]:
            products[product].append(variable)

    # Parse dates
    if isinstance(start_date, str):
        start_date = pd.to_datetime(start_date).date()
    if isinstance(end_date, str):
        end_date = pd.to_datetime(end_date).date()

    # Set up authentication
    if session is None:
        if verbose:
            logger.info("Setting up NASA Earthdata authentication...")
        session = setup_earthdata_session()

    # Determine tiles for each point
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
            lon, lat = point.x, point.y
            determined_tile = find_sentinel2_tile(lon, lat)
            if not determined_tile:
                logger.warning(f"Point {idx}: could not determine Sentinel-2 tile, skipping")
                continue
            point_tiles[idx] = determined_tile

    tiles_to_search = set(point_tiles.values())

    if not tiles_to_search:
        logger.warning("No valid tiles found for any points")
        return pd.DataFrame()

    if verbose:
        logger.info(f"Searching {len(tiles_to_search)} tile(s): {', '.join(sorted(tiles_to_search))}")
        logger.info(f"Date range: {start_date} to {end_date}")

    # Search CMR for all granules across all tiles and products
    all_granule_files = {}

    search_combinations = [
        (tile, product, variables if isinstance(variables, list) else [variables])
        for tile in tiles_to_search
        for product, variables in products.items()
    ]

    if max_workers > 1 and len(search_combinations) > 1:
        if verbose:
            logger.info(f"Searching {len(search_combinations)} tile/product combinations in parallel...")

        with ThreadPoolExecutor(max_workers=min(max_workers, len(search_combinations))) as executor:
            future_to_search = {
                executor.submit(
                    _search_cmr_for_tile_product,
                    tile, product, vars_list, start_date, end_date, False
                ): (tile, product) for tile, product, vars_list in search_combinations
            }

            futures_iter = as_completed(future_to_search)
            if HAS_TQDM and verbose:
                futures_iter = tqdm(
                    futures_iter,
                    total=len(future_to_search),
                    desc="CMR searches",
                    unit="search"
                )

            for future in futures_iter:
                tile, product = future_to_search[future]
                try:
                    tile_product_files = future.result()
                    if tile not in all_granule_files:
                        all_granule_files[tile] = {}
                    all_granule_files[tile].update(tile_product_files)

                    if verbose and HAS_TQDM:
                        num_files = len(tile_product_files)
                        if num_files > 0:
                            tqdm.write(f"  [{tile}/{product}] Found {num_files} files")
                except Exception as e:
                    logger.error(f"Error processing search results for {tile}/{product}: {e}")
    else:
        for tile in tiles_to_search:
            if verbose:
                logger.info(f"\nSearching tile {tile}...")

            tile_files = {}
            for product, variables in products.items():
                if not isinstance(variables, list):
                    variables = [variables]
                tile_product_files = _search_cmr_for_tile_product(
                    tile, product, variables, start_date, end_date, verbose
                )
                tile_files.update(tile_product_files)

            all_granule_files[tile] = tile_files

    # Get unique granules per tile
    granules_by_tile = {}
    for tile, tile_files in all_granule_files.items():
        granules = list(set(granule for granule, _ in tile_files.keys()))
        granules_by_tile[tile] = granules
        if verbose:
            logger.info(f"\nTile {tile}: {len(granules)} unique granules to sample")

    if verbose:
        logger.info("\nSampling all point-granule combinations...")

    if max_workers > 1:
        sampling_tasks = []

        for idx, point, metadata in points_data:
            if idx not in point_tiles:
                continue

            lon, lat = point.x, point.y
            point_tile = point_tiles[idx]
            tile_files = all_granule_files.get(point_tile, {})
            granules = granules_by_tile.get(point_tile, [])

            if not granules:
                if verbose:
                    logger.info(f"  Point {idx}: No granules available")
                continue

            if verbose:
                logger.info(f"  Point {idx} ({lat:.4f}, {lon:.4f}): Sampling {len(granules)} granule(s)")

            daily_granules = {}
            primary_dates = set()
            for granule in granules:
                parts = granule.split('_')
                product = "_".join(parts[1:3]) if len(parts) > 2 else None

                if product == 'L2T_LSTE' and len(parts) > 6:
                    primary_dates.add(parts[6][:8])
                elif product == 'L2T_STARS' and len(parts) > 4:
                    primary_dates.add(parts[4])
                elif product and (product.startswith('L3T_') or product.startswith('L4T_')):
                    if len(parts) > 6:
                        timestamp = parts[6]
                        date_str = timestamp[:8]
                        if product not in daily_granules:
                            daily_granules[product] = {}
                        daily_granules[product][date_str] = granule

            for granule in granules:
                parts = granule.split('_')
                product = "_".join(parts[1:3]) if len(parts) > 2 else None

                if product == 'L2T_LSTE':
                    if len(parts) > 6:
                        timestamp = parts[6]
                        orbit = parts[3] if len(parts) > 3 else None
                        scene = parts[4] if len(parts) > 4 else None
                        sampling_tasks.append((
                            idx, point, metadata, lon, lat, point_tile,
                            granule, timestamp, orbit, scene,
                            tile_files, products, daily_granules
                        ))

                elif product == 'L2T_STARS':
                    if len(parts) > 4:
                        date_str = parts[4]
                        sampling_tasks.append((
                            idx, point, metadata, lon, lat, point_tile,
                            granule, date_str, None, None,
                            tile_files, products, daily_granules
                        ))

            for date_granules in daily_granules.values():
                for date_str, granule in date_granules.items():
                    if date_str in primary_dates:
                        continue

                    parts = granule.split('_')
                    timestamp = parts[6] if len(parts) > 6 else date_str
                    orbit = parts[3] if len(parts) > 3 else None
                    scene = parts[4] if len(parts) > 4 else None
                    sampling_tasks.append((
                        idx, point, metadata, lon, lat, point_tile,
                        granule, timestamp, orbit, scene,
                        tile_files, products, daily_granules
                    ))

        all_results = []
        if verbose:
            logger.info(f"Executing {len(sampling_tasks)} sampling tasks with {max_workers} workers...")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(
                    _sample_single_point_granule,
                    session, *task
                ): task for task in sampling_tasks
            }

            futures_iter = as_completed(future_to_task)
            if HAS_TQDM and verbose:
                futures_iter = tqdm(
                    futures_iter,
                    total=len(future_to_task),
                    desc="Sampling points",
                    unit="granule",
                    smoothing=0.1
                )

            for future in futures_iter:
                try:
                    result = future.result()
                    if result is not None:
                        all_results.append(result)
                except Exception as e:
                    task = future_to_task[future]
                    error_msg = f"Error sampling point {task[0]}, granule {task[6]}: {e}"
                    if verbose and HAS_TQDM:
                        tqdm.write(error_msg)
                    else:
                        logger.error(error_msg)

    else:
        # Sequential execution (for debugging or when max_workers=1)
        all_results = []

        for idx, point, metadata in points_data:
            if idx not in point_tiles:
                continue

            lon, lat = point.x, point.y
            point_tile = point_tiles[idx]
            tile_files = all_granule_files.get(point_tile, {})
            granules = granules_by_tile.get(point_tile, [])

            if not granules:
                if verbose:
                    logger.info(f"  Point {idx}: No granules available")
                continue

            if verbose:
                logger.info(f"  Point {idx} ({lat:.4f}, {lon:.4f}): Sampling {len(granules)} granule(s)")

            lst_granules = {}
            stars_granules = {}
            daily_granules = {}

            for granule in granules:
                parts = granule.split('_')
                product = "_".join(parts[1:3]) if len(parts) > 2 else None

                if product == 'L2T_STARS':
                    if len(parts) > 4:
                        date_str = parts[4]
                        stars_granules[date_str] = granule
                elif product == 'L2T_LSTE':
                    if len(parts) > 6:
                        timestamp = parts[6]
                        date_str = timestamp[:8]
                        orbit = parts[3] if len(parts) > 3 else None
                        scene = parts[4] if len(parts) > 4 else None

                        if date_str not in lst_granules:
                            lst_granules[date_str] = []
                        lst_granules[date_str].append((granule, timestamp, orbit, scene))
                elif product and (product.startswith('L3T_') or product.startswith('L4T_')):
                    if len(parts) > 6:
                        timestamp = parts[6]
                        date_str = timestamp[:8]

                        if product not in daily_granules:
                            daily_granules[product] = {}
                        daily_granules[product][date_str] = granule

            # Process LST granules and match with STARS data by date
            for date_str, lst_list in lst_granules.items():
                stars_granule = stars_granules.get(date_str)

                for granule, timestamp, orbit, scene in lst_list:
                    granule_data = {
                        'point_index': idx,
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

                    for variable in products.get('L2T_LSTE', []):
                        key = (granule, variable)
                        if key not in tile_files:
                            continue

                        file_info = tile_files[key]
                        value, meta = sample_point_from_url(
                            session,
                            file_info['url'],
                            lon,
                            lat
                        )

                        if value is not None:
                            has_data = True
                            granule_data[variable] = value

                    if stars_granule:
                        for variable in products.get('L2T_STARS', []):
                            key = (stars_granule, variable)
                            if key not in tile_files:
                                continue

                            file_info = tile_files[key]
                            value, meta = sample_point_from_url(
                                session,
                                file_info['url'],
                                lon,
                                lat
                            )

                            if value is not None:
                                has_data = True
                                granule_data[variable] = value

                    for product, date_granules in daily_granules.items():
                        if date_str in date_granules:
                            product_granule = date_granules[date_str]
                            for variable in products.get(product, []):
                                key = (product_granule, variable)
                                if key not in tile_files:
                                    continue

                                file_info = tile_files[key]
                                value, meta = sample_point_from_url(
                                    session,
                                    file_info['url'],
                                    lon,
                                    lat
                                )

                                if value is not None:
                                    has_data = True
                                    granule_data[variable] = value

                    if has_data:
                        all_results.append(granule_data)

            # Process STARS-only granules (dates with STARS but no LST) for this point
            stars_only_dates = set(stars_granules.keys()) - set(lst_granules.keys())
            for date_str in stars_only_dates:
                stars_granule = stars_granules[date_str]

                granule_data = {
                    'point_index': idx,
                    'granule': stars_granule,
                    'lon': lon,
                    'lat': lat,
                    'tile': point_tile,
                    'timestamp': date_str,
                    'orbit': None,
                    'scene': None
                }
                granule_data.update(metadata)

                has_data = False

                for variable in products.get('L2T_STARS', []):
                    key = (stars_granule, variable)
                    if key not in tile_files:
                        continue

                    file_info = tile_files[key]
                    value, meta = sample_point_from_url(
                        session,
                        file_info['url'],
                        lon,
                        lat
                    )

                    if value is not None:
                        has_data = True
                        granule_data[variable] = value

                for product, date_granules in daily_granules.items():
                    if date_str in date_granules:
                        product_granule = date_granules[date_str]
                        for variable in products.get(product, []):
                            key = (product_granule, variable)
                            if key not in tile_files:
                                continue

                            file_info = tile_files[key]
                            value, meta = sample_point_from_url(
                                session,
                                file_info['url'],
                                lon,
                                lat
                            )

                            if value is not None:
                                has_data = True
                                granule_data[variable] = value

                if has_data:
                    all_results.append(granule_data)

            # Process standalone L3T/L4T granules for this point
            primary_dates = set(lst_granules) | set(stars_granules)
            for product, date_granules in daily_granules.items():
                for date_str, granule in date_granules.items():
                    if date_str in primary_dates:
                        continue

                    parts = granule.split('_')
                    timestamp = parts[6] if len(parts) > 6 else date_str
                    granule_data = {
                        'point_index': idx,
                        'granule': granule,
                        'lon': lon,
                        'lat': lat,
                        'tile': point_tile,
                        'timestamp': timestamp,
                        'orbit': parts[3] if len(parts) > 3 else None,
                        'scene': parts[4] if len(parts) > 4 else None
                    }
                    granule_data.update(metadata)

                    has_data = False
                    for variable in products.get(product, []):
                        key = (granule, variable)
                        if key not in tile_files:
                            continue

                        file_info = tile_files[key]
                        value, meta = sample_point_from_url(
                            session,
                            file_info['url'],
                            lon,
                            lat
                        )

                        if value is not None:
                            has_data = True
                            granule_data[variable] = value

                    if has_data:
                        all_results.append(granule_data)

    if not all_results:
        logger.warning("No data sampled from any point-granule combinations")
        return pd.DataFrame()

    results_df = pd.DataFrame(all_results)
    results_df = _apply_layer_names(results_df, layers)

    if drop_na and len(results_df) > 0:
        sampled_cols = [col for col in results_df.columns if col in layers]
        if sampled_cols:
            initial_len = len(results_df)
            results_df = results_df[results_df[sampled_cols].notna().all(axis=1)]
            if verbose and initial_len > len(results_df):
                logger.info(f"  Dropped {initial_len - len(results_df)} rows with missing data")

    if verbose:
        logger.info(f"\nSampled {len(results_df)} observations from {len(points_data)} input points")
        logger.info(f"  Unique granules sampled: {results_df['granule'].nunique()}")
        logger.info(f"  Points with data: {results_df['point_index'].nunique()}")

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
    """
    Sample ECOSTRESS data at multiple points with known acquisition times.
    """
    if layers is None:
        layers = DEFAULT_LAYERS

    if isinstance(geometry, list):
        gdf = gpd.GeoDataFrame({'geometry': geometry}, crs='EPSG:4326')
    elif isinstance(geometry, gpd.GeoSeries):
        gdf = gpd.GeoDataFrame({'geometry': geometry}, crs=geometry.crs)
    elif isinstance(geometry, gpd.GeoDataFrame):
        gdf = geometry
    else:
        raise TypeError(
            f"geometry must be GeoDataFrame, GeoSeries, or list of Point, got {type(geometry)}"
        )

    if gdf.crs is None:
        raise ValueError("GeoDataFrame must have a defined CRS")

    if not gdf.crs.equals(CRS.from_epsg(4326)):
        logger.info(f"Reprojecting GeoDataFrame from {gdf.crs} to EPSG:4326")
        gdf = gdf.to_crs('EPSG:4326')

    geometry_col = gdf.geometry.name
    if datetime_col not in gdf.columns:
        raise ValueError(f"Datetime column '{datetime_col}' not found in GeoDataFrame")

    _validate_layers(layers)

    products = {}
    for layer in layers:
        product, variable = LAYER_MAPPING[layer]
        if product not in products:
            products[product] = []
        if isinstance(products[product], str):
            products[product] = [products[product]]
        if variable not in products[product]:
            products[product].append(variable)

    for product in products:
        if len(products[product]) == 1:
            products[product] = products[product][0]

    if session is None:
        if verbose:
            logger.info("Setting up NASA Earthdata authentication...")
        session = setup_earthdata_session()

    all_results = []

    for idx, row in gdf.iterrows():
        point = row['geometry']
        dt = row[datetime_col]

        if not isinstance(point, Point):
            logger.warning(f"Row {idx}: geometry is not a Point, skipping")
            continue

        lon, lat = point.x, point.y

        if isinstance(dt, datetime):
            search_date = dt.date()
        elif isinstance(dt, date):
            search_date = dt
        else:
            try:
                search_date = pd.to_datetime(dt).date()
            except Exception:
                logger.warning(f"Row {idx}: cannot parse datetime '{dt}', skipping")
                continue

        if tile_col and tile_col in row:
            tile = row[tile_col]
        else:
            tile = find_sentinel2_tile(lon, lat)
            if not tile:
                logger.warning(f"Row {idx}: could not determine Sentinel-2 tile, skipping")
                continue

        if verbose:
            logger.info(f"Processing row {idx}: ({lat:.4f}, {lon:.4f}) on {search_date} in tile {tile}")

        from datetime import timedelta
        start_date = search_date - timedelta(days=date_buffer_days)
        end_date = search_date + timedelta(days=date_buffer_days)

        point_files = {}

        for product, variables in products.items():
            if not isinstance(variables, list):
                variables = [variables]

            try:
                search_results = ECOSTRESS_CMR_search(
                    product=product,
                    tile=tile,
                    start_date=start_date,
                    end_date=end_date
                )

                if search_results.empty:
                    if verbose:
                        logger.info(f"  No {product} granules found")
                    continue

                for variable in variables:
                    var_files = search_results[
                        (search_results['type'] == 'GeoTIFF Data') &
                        (search_results['variable'] == variable)
                    ]

                    for _, file_row in var_files.iterrows():
                        key = (file_row['granule'], variable)
                        point_files[key] = {
                            'url': file_row['URL'],
                            'orbit': file_row.get('orbit'),
                            'scene': file_row.get('scene'),
                            'product': product
                        }

            except Exception as e:
                logger.error(f"  Error searching {product}: {e}")
                continue

        if not point_files:
            if verbose:
                logger.info("  No granules found for this point")
            continue

        unique_granules = list(set(granule for granule, _ in point_files.keys()))

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

            for variable in [v for vars in products.values() for v in (vars if isinstance(vars, list) else [vars])]:
                key = (granule, variable)
                if key not in point_files:
                    continue

                file_info = point_files[key]
                value, meta = sample_point_from_url(
                    session,
                    file_info['url'],
                    lon,
                    lat
                )

                if value is not None:
                    has_data = True
                    granule_data[variable] = value
                    if verbose:
                        logger.info(f"    {variable}: {value:.4f}")
                else:
                    if verbose and meta not in ["outside_bounds", "nodata"]:
                        logger.info(f"    {variable}: {meta}")

            if has_data:
                all_results.append(granule_data)

    if not all_results:
        logger.warning("No data sampled from any points")
        return pd.DataFrame()

    results_df = pd.DataFrame(all_results)
    results_df = _apply_layer_names(results_df, layers)

    if verbose:
        logger.info(f"\nSampled {len(results_df)} observations from {len(gdf)} input points")

    return results_df
