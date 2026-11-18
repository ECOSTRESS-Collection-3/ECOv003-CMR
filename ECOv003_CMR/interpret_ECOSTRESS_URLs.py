from typing import Any, Dict, List, Optional
import posixpath

import pandas as pd
import requests

from .variable_from_filename import variable_from_filename
from .granule_ID_from_filename import granule_ID_from_filename


def fetch_granule_metadata(
    json_url: str,
    session: Optional[requests.Session] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """Inspect a per-granule .json metadata sidecar for cloud fraction and QA flags."""
    requester = session.get if session is not None else requests.get
    response = requester(json_url, allow_redirects=True, timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    product_meta = payload.get("ProductMetadata", payload.get("Product Metadata", {}))
    standard_meta = payload.get("StandardMetadata", payload.get("Standard Metadata", {}))

    cloud_fraction = (
        product_meta.get("QAPercentCloudCover")
        or product_meta.get("CloudCover")
        or standard_meta.get("CloudCover")
    )
    return {
        "cloud_cover": float(cloud_fraction) if cloud_fraction is not None else None,
        "product_metadata": product_meta,
        "standard_metadata": standard_meta,
    }


def interpret_ECOSTRESS_URLs(
        URLs: List[str],
        orbit: int = None,
        scene: int = None,
        entry_metadata: Optional[List[Dict[str, Any]]] = None) -> pd.DataFrame:
    """
    Parse and organize ECOSTRESS file URLs into a structured DataFrame.
    """
    meta_by_url = {}
    if entry_metadata:
        for item in entry_metadata:
            if "URL" in item:
                meta_by_url[item["URL"]] = item

    records = []

    for URL in URLs:
        filename = posixpath.basename(URL)
        variable = ""

        granule_ID = granule_ID_from_filename(filename)

        if filename.endswith(".json"):
            file_type = "JSON Metadata"
        elif filename.endswith(".tif"):
            file_type = "GeoTIFF Data"
        elif filename.endswith(".jpeg.aux.xml"):
            file_type = "GeoJPEG Metadata"
        elif filename.endswith(".jpeg"):
            file_type = "GeoJPEG Preview"
        else:
            raise ValueError(f"Unknown file type for {filename}")

        if filename.endswith((".tif", ".jpeg", ".jpeg.aux.xml")):
            variable = variable_from_filename(filename)

        extra = meta_by_url.get(URL, {})
        records.append({
            "product": granule_ID.product,
            "variable": variable,
            "orbit": granule_ID.orbit,
            "scene": granule_ID.scene,
            "tile": granule_ID.tile,
            "type": file_type,
            "granule": str(granule_ID),
            "filename": filename,
            "URL": URL,
            "cloud_cover": extra.get("cloud_cover"),
            "acquisition_datetime": extra.get("acquisition_datetime"),
        })

    df = pd.DataFrame(records, columns=[
        "product",
        "variable",
        "orbit",
        "scene",
        "tile",
        "type",
        "granule",
        "filename",
        "URL",
        "cloud_cover",
        "acquisition_datetime",
    ])

    if orbit is not None:
        df = df[df['orbit'] == orbit]

    if scene is not None:
        df = df[df['scene'] == scene]

    return df
