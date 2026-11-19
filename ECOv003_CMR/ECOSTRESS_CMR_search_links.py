import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import requests
from datetime import date
from dateutil import parser

from sentinel_tiles import sentinel_tiles

from .constants import CMR_SEARCH_URL
from .granule_ID_from_filename import granule_ID_from_filename

logger = logging.getLogger(__name__)

_TRANSIENT_CMR_STATUS = {429, 500, 502, 503, 504}
_THREAD_LOCAL = threading.local()


def _get_cmr_session(session: Optional[requests.Session] = None) -> requests.Session:
    """Return an unauthenticated per-thread requests.Session for public CMR search endpoints."""
    if session is not None and not getattr(session, "auth", None):
        return session
    local_sess = getattr(_THREAD_LOCAL, "cmr_session", None)
    if local_sess is None:
        local_sess = requests.Session()
        _THREAD_LOCAL.cmr_session = local_sess
    return local_sess


def _request_with_backoff(
    url: str,
    params: Dict[str, Any],
    headers: Dict[str, str],
    session: Optional[requests.Session] = None,
    max_retries: int = 5,
    backoff_base: float = 1.5,
    timeout: Tuple[float, float] = (15.0, 60.0),
) -> requests.Response:
    """
    Execute a CMR GET request with explicit (connect, read) socket timeouts and
    retry backoff on transient HTTP errors, timeouts, and dropped connections so
    worker threads never hang indefinitely on stalled sockets.
    """
    use_plain_get = (
        session is None
        and getattr(requests.get, "__module__", "") != "requests.api"
    )
    requester = requests.get if use_plain_get else _get_cmr_session(session).get

    for attempt in range(max_retries):
        try:
            if use_plain_get:
                response = requester(url, params=params, headers=headers)
            else:
                response = requester(url, params=params, headers=headers, timeout=timeout)
            status = getattr(response, "status_code", 200)
            if status in _TRANSIENT_CMR_STATUS and attempt < max_retries - 1:
                retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
                delay = float(retry_after) if retry_after else backoff_base ** (attempt + 1)
                logger.warning(f"CMR transient HTTP {status} (attempt {attempt + 1}/{max_retries}); retrying in {delay:.1f}s")
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt >= max_retries - 1:
                raise
            delay = backoff_base ** (attempt + 1)
            logger.warning(f"CMR request timeout/connection reset ({exc}); retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(delay)
    raise RuntimeError(f"CMR request failed after {max_retries} retries: {url}")


def ECOSTRESS_CMR_search_entries(
    concept_ID: str,
    tile: Optional[str] = None,
    bounding_box: Optional[Tuple[float, float, float, float]] = None,
    start_date: Union[date, str] = None,
    end_date: Union[date, str] = None,
    use_tile_bounds: bool = True,
    max_cloud_cover: Optional[float] = None,
    allowed_tiles: Optional[Set[str]] = None,
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
        if use_tile_bounds:
            minx, miny, maxx, maxy = sentinel_tiles.footprint(tile).bounds
            bbox_str = f"{minx},{miny},{maxx},{maxy}"
        else:
            centroid = sentinel_tiles.centroid(tile)
            bbox_str = f"{centroid.x},{centroid.y},{centroid.x},{centroid.y}"
    else:
        raise ValueError("Either 'tile' or 'bounding_box' must be provided")

    target_tiles = set(allowed_tiles) if allowed_tiles is not None else ({tile} if tile is not None else None)

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
                if target_tiles is not None:
                    try:
                        gid = granule_ID_from_filename(href)
                    except Exception as exc:
                        logger.debug(f"Skipping unparseable CMR asset URL {href}: {exc}")
                        continue
                    if gid.tile not in target_tiles:
                        continue
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
