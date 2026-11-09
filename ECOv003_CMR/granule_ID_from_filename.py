from posixpath import basename

from .product_name_from_filename import product_name_from_filename
from .granule_ID import GranuleID

def granule_ID_from_filename(filename: str) -> GranuleID:
    """
    Extracts the granule name from an ECOSTRESS filename.

    Args:
        filename: The name of the ECOSTRESS granule file.

    Returns:
        The granule name extracted from the filename.
    """
    product = product_name_from_filename(filename)
    filename_base = basename(filename).split(".", 1)[0]
    filename_parts = filename_base.split("_")
    is_collection_3 = filename_parts[0] == "ECOv003"

    if product == "L2T_STARS":
        granule_ID_length = 6 if is_collection_3 else 7
    else:
        granule_ID_length = 8 if is_collection_3 else 9
    granule_ID = "_".join(filename_parts[:granule_ID_length])

    return GranuleID(granule_ID)
