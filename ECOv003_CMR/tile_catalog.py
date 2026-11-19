import logging
import os
from pathlib import Path
from typing import List, Optional

import geopandas as gpd
from shapely.geometry import box
from sentinel_tiles import sentinel_tiles

logger = logging.getLogger(__name__)

NATURAL_EARTH_110M_LAND_URL = (
    "https://naciscdn.org/naturalearth/110m/physical/ne_110m_land.zip"
)


def _load_landmass_geometry(cache_dir: Optional[str] = None):
    """Load and cache lightweight Natural Earth 110m land polygons."""
    if cache_dir is None:
        cache_dir = os.path.join(Path.home(), ".cache", "ECOv003_CMR")
    os.makedirs(cache_dir, exist_ok=True)
    cached_geojson = os.path.join(cache_dir, "ne_110m_land.geojson")

    if os.path.exists(cached_geojson):
        land_gdf = gpd.read_file(cached_geojson)
    else:
        land_gdf = gpd.read_file(NATURAL_EARTH_110M_LAND_URL)
        land_gdf.to_file(cached_geojson, driver="GeoJSON")

    return land_gdf.geometry.union_all()


def list_ecostress_land_tiles(
    min_lat: float = -54.0,
    max_lat: float = 54.0,
    land_geometry=None,
    cache_dir: Optional[str] = None,
) -> List[str]:
    """
    Enumerate all Sentinel-2 MGRS tiles intersecting global landmasses within
    ECOSTRESS orbital coverage ([min_lat, max_lat]).
    """
    if land_geometry is None:
        land_geometry = _load_landmass_geometry(cache_dir=cache_dir)

    orbital_band = box(-180.0, min_lat, 180.0, max_lat)
    clipped_land = land_geometry.intersection(orbital_band)

    if hasattr(sentinel_tiles, "grid_df"):
        tiles_df = sentinel_tiles.grid_df
        lat_filtered = tiles_df.cx[-180:180, min_lat:max_lat]
        intersecting = lat_filtered[lat_filtered.geometry.intersects(clipped_land)]
        tile_col = "tile" if "tile" in intersecting.columns else intersecting.index.name
        tiles = (
            intersecting[tile_col].tolist()
            if tile_col
            else intersecting.index.tolist()
        )
        return sorted(set(str(t) for t in tiles))

    mgrs_bands = "FGHJKLMNPQRSTU"
    squares_col = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    squares_row = "ABCDEFGHJKLMNPQRSTUV"
    valid_tiles = []

    for zone in range(1, 61):
        for band in mgrs_bands:
            for col_char in squares_col:
                for row_char in squares_row:
                    tile_id = f"{zone:02d}{band}{col_char}{row_char}"
                    try:
                        geom = sentinel_tiles.grid(tile_id)
                        bounds = geom.bounds
                        if bounds[3] < min_lat or bounds[1] > max_lat:
                            continue
                        if geom.intersects(clipped_land):
                            valid_tiles.append(tile_id)
                    except Exception:
                        continue

    return sorted(set(valid_tiles))
