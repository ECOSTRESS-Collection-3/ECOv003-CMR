from typing import Optional, Union
from os.path import join
from datetime import date
import posixpath
import warnings
import pandas as pd
import requests

from .authentication import setup_earthdata_session
from .constants import *
from .granule_ID import GranuleID
from .download_file import download_file
from .ECOSTRESS_CMR_search import ECOSTRESS_CMR_search


def get_granule_from_listing(listing: pd.DataFrame) -> GranuleID:
    """
    Extracts the granule ID from a listing DataFrame.
    """
    granule_IDs = list(listing.granule.unique())

    if len(granule_IDs) != 1:
        raise ValueError(f"there are {len(granule_IDs)} found in listing")

    return GranuleID(granule_IDs[0])


def download_ECOSTRESS_granule_files(
        product: str,
        tile: str,
        acquisition_date: Union[date, str] = None,
        orbit: int = None,
        scene: int = None,
        parent_directory: str = ".",
        CMR_file_listing_df: pd.DataFrame = None,
        CMR_search_URL: str = CMR_SEARCH_URL,
        session: Optional[requests.Session] = None,
        aquisition_date: Union[date, str] = None) -> str:
    """
    Downloads ECOSTRESS granule files based on the provided parameters.
    """
    if aquisition_date is not None:
        warnings.warn(
            "'aquisition_date' is deprecated and will be removed in a future release; "
            "use 'acquisition_date' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if acquisition_date is None:
            acquisition_date = aquisition_date

    if acquisition_date is None and CMR_file_listing_df is None:
        raise ValueError("acquisition_date must be provided when CMR_file_listing_df is None")

    if CMR_file_listing_df is None:
        CMR_file_listing_df = ECOSTRESS_CMR_search(
            product=product,
            orbit=orbit,
            scene=scene,
            tile=tile,
            start_date=acquisition_date,
            end_date=acquisition_date,
            CMR_search_URL=CMR_search_URL,
            session=session,
        )

    granule_ID = get_granule_from_listing(CMR_file_listing_df)

    if orbit is not None and orbit != granule_ID.orbit:
        raise ValueError(f"given orbit {orbit} does not match listed orbit {granule_ID.orbit}")

    if scene is not None and scene != granule_ID.scene:
        raise ValueError(f"given scene {scene} does not match listed scene {granule_ID.scene}")

    if tile != granule_ID.tile:
        raise ValueError(f"given tile {tile} does not match listed tile {granule_ID.tile}")

    if session is None:
        session = setup_earthdata_session()

    directory = join(parent_directory, str(granule_ID))

    for URL in list(CMR_file_listing_df.URL):
        filename = join(directory, posixpath.basename(URL))
        download_file(URL, filename, session=session)

    return directory
