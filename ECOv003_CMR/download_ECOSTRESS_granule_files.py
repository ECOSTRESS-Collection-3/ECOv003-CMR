from typing import Optional, Union
from os.path import join
from datetime import date
import posixpath
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

    Args:
        listing (pd.DataFrame): DataFrame containing granule information.

    Returns:
        GranuleID: The granule ID extracted from the listing.

    Raises:
        ValueError: If there are not exactly one unique granule ID in the listing.
    """
    # Extract unique granule IDs from the listing DataFrame
    granule_IDs = list(listing.granule.unique())

    # Ensure there is exactly one unique granule ID
    if len(granule_IDs) != 1:
        raise ValueError(f"there are {len(granule_IDs)} found in listing")

    # Create a GranuleID object from the unique granule ID
    granule_ID = GranuleID(granule_IDs[0])

    return granule_ID


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

    Args:
        product (str): The product type.
        tile (str): The tile identifier.
        acquisition_date (Union[date, str], optional): The acquisition date.
        orbit (int, optional): The orbit number. Defaults to None.
        scene (int, optional): The scene number. Defaults to None.
        parent_directory (str, optional): The parent directory to save files. Defaults to ".".
        CMR_file_listing_df (pd.DataFrame, optional): DataFrame containing file listings. Defaults to None.
        CMR_search_URL (str, optional): The URL for CMR search. Defaults to CMR_SEARCH_URL.
        session (requests.Session, optional): Authenticated NASA Earthdata session. Defaults to None.
        aquisition_date (Union[date, str], optional): Deprecated spelling alias for acquisition_date.

    Returns:
        str: The directory where the files are downloaded.

    Raises:
        ValueError: If acquisition_date is missing or provided orbit, scene, or tile does not match the granule ID.
    """
    if acquisition_date is None:
        acquisition_date = aquisition_date

    if acquisition_date is None and CMR_file_listing_df is None:
        raise ValueError("acquisition_date must be provided when CMR_file_listing_df is None")

    # Run CMR search to list all files in ECOSTRESS granule if no listing DataFrame is provided
    if CMR_file_listing_df is None:
        CMR_file_listing_df = ECOSTRESS_CMR_search(
            product=product,
            orbit=orbit,
            scene=scene,
            tile=tile,
            start_date=acquisition_date,
            end_date=acquisition_date,
            CMR_search_URL=CMR_search_URL
        )

    # Check that there is exactly one granule listed and get granule ID
    granule_ID = get_granule_from_listing(CMR_file_listing_df)

    # Validate orbit only when a specific orbit was requested
    if orbit is not None and orbit != granule_ID.orbit:
        raise ValueError(f"given orbit {orbit} does not match listed orbit {granule_ID.orbit}")

    # Validate scene only when a specific scene was requested
    if scene is not None and scene != granule_ID.scene:
        raise ValueError(f"given scene {scene} does not match listed scene {granule_ID.scene}")

    # Validate that the provided tile matches the granule ID's tile
    if tile != granule_ID.tile:
        raise ValueError(f"given tile {tile} does not match listed tile {granule_ID.tile}")

    if session is None:
        session = setup_earthdata_session()

    # Construct granule directory path
    directory = join(parent_directory, str(granule_ID))

    # Download each file listed in the CMR file listing DataFrame
    for URL in list(CMR_file_listing_df.URL):
        filename = join(directory, posixpath.basename(URL))
        download_file(URL, filename, session=session)

    return directory
