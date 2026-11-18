import time
from typing import Any, Dict, List, Optional, Tuple, Union
import requests
from datetime import date
from dateutil import parser

from sentinel_tiles import sentinel_tiles

from .constants import CMR_SEARCH_URL
from .granule_ID_from_filename import granule_ID_from_filename


def _request_with_backoff(
    url: str,
    params: Dict[str, Any],
    headers: Dict[str, str],
    session: Optional[requests.Session] = None,
    max_retries: int = 4,
    backoff_base: float = 1.5,
) -> requests.Response:
    requester = session.get if session is not None else requests.get
    for attempt in range(max_retries):
        response = requester(url, params=params, headers=headers)
        if getattr(response, "status_code", 200) in (429, 503) and attempt < max_retries - 1:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else backoff_base ** (attempt + 1)
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response
    response.raise_for_status()
    return response


def ECOSTRESS_CMR_search_entries(
    concept_ID: str,
    tile: Optional[str] = None,
    bounding_box: Optional[Tuple[float, float, float, float]] = None,
    start_date: Union[date, str] = None,
    end_date: Union[date, str] = None,
    use_tile_bounds: bool = True,
    max_cloud_cover: Optional[float] = None,
    CMR_search_URL: str = CMR_SEARCH_URL,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """Query CMR granules.json using tile WGS84 bounds or regional bounding boxes."""
    if isinstance(start_date, str):
        start_date = parser.parse(start_date).date()
    if end_date is None:
        end_date = start_date
    elif isinstance(end_date, str):
        end_date = parser.parse(end_date).date()

    if bounding_box is not None:
        bbox_str = f"{bounding_box[0]},{bounding_box[1]},{bounding_box[2]},{bounding_box[3]}"
    elif tile is not None:
        geometry = sentinel_tiles.grid(tile)
        if use_tile_bounds and hasattr(geometry, "bounds"):
            minx, miny, maxx, maxy = geometry.bounds
            bbox_str = f"{minx},{miny},{maxx},{maxy}"
        else:
            centroid = geometry.centroid_latlon
            bbox_str = f"{centroid.x},{centroid.y},{centroid.x},{centroid.y}"
    else:
        raise ValueError("Either 'tile' or 'bounding_box' must be provided")

    granule_search_URL = f"{CMR_search_URL}granules.json"
    params = {
        "concept_id": concept_ID,
        "bounding_box": bbox_str,
        "temporal": f"{start_date}T00:00:00Z,{end_date}T23:59:59Z",
        "page_size": 2000,
    }

    records: List[Dict[str, Any]] = []
    headers: Dict[str, str] = {}
    previous_search_after = None

    while True:
        response = _request_with_backoff(
            granule_search_URL, params=params, headers=headers, session=session
        )
        entries = response.json().get("feed", {}).get("entry", [])
        for entry in entries:
            raw_cc = entry.get("cloud_cover")
            cloud_cover = float(raw_cc) if raw_cc is not None else None
            if (
                max_cloud_cover is not None
                and cloud_cover is not None
                and cloud_cover > max_cloud_cover
            ):
                continue

            time_start = entry.get("time_start")
            for link in entry.get("links", []):
                href = link.get("href")
                if not (
                    href
                    and href.startswith("https")
                    and href.endswith((".tif", ".json", ".aux.xml", ".jpeg"))
                ):
                    continue
                if tile is not None:
                    try:
                        gid = granule_ID_from_filename(href)
                        if gid.tile != tile:
                            continue
                    except Exception:
                        pass
                records.append(
                    {
                        "URL": href,
                        "cloud_cover": cloud_cover,
                        "acquisition_datetime": time_start,
                    }
                )

        search_after = response.headers.get("CMR-Search-After")
        if not search_after or not entries:
            break
        if search_after == previous_search_after:
            raise RuntimeError("CMR repeated a Search-After token; stopping pagination")
        previous_search_after = search_after
        headers = {"CMR-Search-After": search_after}

    return records


def ECOSTRESS_CMR_search_links(
        concept_ID: str,
        tile: str,
        start_date: Union[date, str],
        end_date: Union[date, str],
        use_tile_bounds: bool = True,
        max_cloud_cover: Optional[float] = None,
        CMR_search_URL: str = CMR_SEARCH_URL,
        session: Optional[requests.Session] = None) -> List[str]:
    """Search CMR for matching Collection 3 granules and extract file URLs."""
    entries = ECOSTRESS_CMR_search_entries(
        concept_ID=concept_ID,
        tile=tile,
        start_date=start_date,
        end_date=end_date,
        use_tile_bounds=use_tile_bounds,
        max_cloud_cover=max_cloud_cover,
        CMR_search_URL=CMR_search_URL,
        session=session,
    )
    return [entry["URL"] for entry in entries]
