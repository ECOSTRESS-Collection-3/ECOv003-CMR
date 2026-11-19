import logging
from typing import List, Optional

from sentinel_tiles import sentinel_tiles

logger = logging.getLogger(__name__)


def list_ecostress_land_tiles(
    min_lat: float = -54.0,
    max_lat: float = 54.0,
    land_geometry=None,
    cache_dir: Optional[str] = None,
) -> List[str]:
    """
    Enumerate all land-intersecting Sentinel-2 MGRS tiles within ECOSTRESS
    orbital coverage ([min_lat, max_lat]) directly from sentinel_tiles.sentinel_polygons.
    """
    polygons = sentinel_tiles.sentinel_polygons
    land_tiles = polygons[polygons["Land"].astype(bool)]
    if land_geometry is not None:
        in_scope = land_tiles[land_tiles.geometry.intersects(land_geometry)]
    else:
        in_scope = land_tiles.cx[-180.0:180.0, min_lat:max_lat]
    return sorted(set(str(t) for t in in_scope["Name"].tolist()))
