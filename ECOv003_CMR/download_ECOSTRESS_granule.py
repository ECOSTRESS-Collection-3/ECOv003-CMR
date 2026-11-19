from typing import Optional, Union
from datetime import date
import posixpath
import warnings
import pandas as pd
import requests

from ECOv003_granules import ECOSTRESSGranule

from .constants import *
from .granule_ID import GranuleID
from .download_ECOSTRESS_granule_files import download_ECOSTRESS_granule_files
from .granule_compatibility import open_ECOSTRESS_granule


def download_ECOSTRESS_granule(
        product: str,
        tile: str,
        acquisition_date: Union[date, str] = None,
        orbit: int = None,
        scene: int = None,
        parent_directory: str = DOWNLOAD_DIRECTORY,
        CMR_file_listing_df: pd.DataFrame = None,
        CMR_search_URL: str = CMR_SEARCH_URL,
        session: Optional[requests.Session] = None,
        aquisition_date: Union[date, str] = None) -> ECOSTRESSGranule:
    """
    Downloads an ECOSTRESS granule based on the provided parameters and returns the granule object.
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

    directory = download_ECOSTRESS_granule_files(
        product=product,
        tile=tile,
        acquisition_date=acquisition_date,
        orbit=orbit,
        scene=scene,
        parent_directory=parent_directory,
        CMR_file_listing_df=CMR_file_listing_df,
        CMR_search_URL=CMR_search_URL,
        session=session,
    )

    granule = open_ECOSTRESS_granule(directory)
    if not isinstance(granule, ECOSTRESSGranule):
        raise RuntimeError(
            f"ECOv003-granules could not open Collection 3 granule: {directory}"
        )

    expected_product = GranuleID(posixpath.basename(directory)).product
    if granule.product != expected_product:
        raise RuntimeError(
            f"ECOv003-granules parsed product {granule.product!r} from {directory}, "
            f"expected {expected_product!r}; update ECOv003-granules for Collection 3 filenames"
        )

    return granule
