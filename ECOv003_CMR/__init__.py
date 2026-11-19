from .ECOv003_CMR import *
from .version import __version__
from .authentication import setup_earthdata_session, configure_gdal_earthdata_env
from .point_sampling import (
    sample_point_from_url,
    sample_points_from_granule,
    sample_points_from_geodataframe,
    sample_points_over_date_range,
    summarize_point_samples,
    find_sentinel2_tile,
)
from .tile_catalog import list_ecostress_land_tiles
from .stratified_sampling import (
    find_clear_sky_et_granules,
    select_stratified_granules,
    compute_per_granule_quota,
    extract_valid_swath_mask,
    sample_granule_coordinates,
)
from .stratified_dataset_builder import build_stratified_dataset, DEFAULT_STRATIFIED_LAYERS, UQ_LAYERS

__author__ = "Gregory H. Halverson"
