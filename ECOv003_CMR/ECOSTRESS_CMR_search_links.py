from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
import io
import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from dateutil import parser
import pandas as pd
import requests
from sentinel_tiles import sentinel_tiles
from tqdm.auto import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

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
    params: Union[Dict[str, Any], List[Tuple[str, Any]]],
    headers: Dict[str, str],
    session: Optional[requests.Session] = None,
    max_retries: int = 5,
    backoff_base: float = 1.5,
    timeout: Tuple[float, float] = (15.0, 90.0),
    method: str = "GET",
) -> requests.Response:
    """
    Execute a CMR GET request with explicit (connect, read) socket timeouts and
    jittered exponential retry backoff on transient HTTP errors, timeouts, and
    dropped connections so worker threads never hang indefinitely on stalled sockets.
    """
    use_plain_get = (
        method == "GET"
        and session is None
        and getattr(requests.get, "__module__", "") != "requests.api"
    )
    sess = _get_cmr_session(session)

    for attempt in range(max_retries):
        try:
            if use_plain_get:
                response = requests.get(url, params=params, headers=headers)
            elif method == "POST":
                response = sess.post(url, data=params, headers=headers, timeout=timeout)
            else:
                response = sess.get(url, params=params, headers=headers, timeout=timeout)
            status = getattr(response, "status_code", 200)
            if status in _TRANSIENT_CMR_STATUS and attempt < max_retries - 1:
                retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
                delay = float(retry_after) if retry_after else (backoff_base ** (attempt + 1) + random.uniform(0, 0.5))
                logger.warning(
                    f"CMR transient HTTP {status} (attempt {attempt + 1}/{max_retries}); retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt >= max_retries - 1:
                raise
            delay = backoff_base ** (attempt + 1) + random.uniform(0, 0.5)
            logger.warning(
                f"CMR request timeout/connection reset ({exc}); retrying in {delay:.1f}s (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(delay)
    raise RuntimeError(f"CMR request failed after {max_retries} retries: {url}")


def _split_date_chunks(
    start_date: date,
    end_date: date,
    chunk_days: Optional[int],
) -> List[Tuple[date, date]]:
    if chunk_days is None or chunk_days <= 0:
        return [(start_date, end_date)]
    chunks: List[Tuple[date, date]] = []
    cursor = start_date
    while cursor <= end_date:
        c_end = min(end_date, cursor + timedelta(days=chunk_days - 1))
        chunks.append((cursor, c_end))
        cursor = c_end + timedelta(days=1)
    return chunks


def _parse_granule_ur_row(
    granule_ur: str,
    time_start: Optional[str] = None,
    cloud_cover: Optional[float] = None,
    target_tiles: Optional[Set[str]] = None,
) -> Optional[Dict[str, Any]]:
    if not granule_ur:
        return None
    parts = granule_ur.split("_")
    product = "_".join(parts[1:3]) if len(parts) > 2 else None
    if product == "L2T_STARS":
        if len(parts) <= 4:
            return None
        orbit = None
        scene = None
        tile = parts[3]
        ts = parts[4]
    else:
        if len(parts) <= 6:
            return None
        orbit = int(parts[3]) if parts[3].isdigit() else None
        scene = int(parts[4]) if parts[4].isdigit() else None
        tile = parts[5]
        ts = parts[6]

    if target_tiles is not None and tile not in target_tiles:
        return None

    return {
        "granule": granule_ur,
        "product": product,
        "orbit": orbit,
        "scene": scene,
        "tile": tile,
        "timestamp": ts,
        "date_str": ts[:8],
        "time_start": time_start,
        "cloud_cover": cloud_cover,
    }


def search_granule_catalog_csv(
    concept_ID: str,
    start_date: Union[date, str],
    end_date: Union[date, str],
    allowed_tiles: Optional[Set[str]] = None,
    chunk_days: Optional[int] = 5,
    max_workers: int = 6,
    CMR_search_URL: str = CMR_SEARCH_URL,
    session: Optional[requests.Session] = None,
    desc: Optional[str] = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Enumerate Collection 3 granule metadata via NASA CMR's flat granules.csv
    endpoint (~97% smaller payloads than UMM-JSON/JSON, with zero polygons or
    asset link arrays) across parallel temporal windows.

    Note: NASA CMR leaves Cloud Cover null on all ECOSTRESS Collection 3
    granules; do not pass cloud_cover filters to CMR. Scene cloud cover is
    stored in per-granule .json sidecars (ProductMetadata.QAPercentCloudCover).
    """
    if isinstance(start_date, str):
        start_date = parser.parse(start_date).date()
    if end_date is None:
        end_date = start_date
    elif isinstance(end_date, str):
        end_date = parser.parse(end_date).date()

    csv_url = f"{CMR_search_URL}granules.csv"
    chunks = _split_date_chunks(start_date, end_date, chunk_days)
    target_tiles = set(allowed_tiles) if allowed_tiles is not None else None

    def _fetch_window(window: Tuple[date, date]) -> List[Dict[str, Any]]:
        w_start, w_end = window
        params: Dict[str, Any] = {
            "concept_id": concept_ID,
            "temporal": f"{w_start}T00:00:00Z,{w_end}T23:59:59Z",
            "page_size": 2000,
        }

        rows: List[Dict[str, Any]] = []
        headers: Dict[str, str] = {}
        previous_search_after: Optional[str] = None

        while True:
            response = _request_with_backoff(
                csv_url, params=params, headers=headers, session=session
            )
            text = (response.text or "").strip()
            if not text:
                break
            df_page = pd.read_csv(io.StringIO(text))
            if df_page.empty or "Granule UR" not in df_page.columns:
                break

            start_col = df_page["Start Time"] if "Start Time" in df_page.columns else [None] * len(df_page)
            cc_series = pd.to_numeric(df_page["Cloud Cover"], errors="coerce") if "Cloud Cover" in df_page.columns else [None] * len(df_page)

            for granule_ur, t_start, raw_cc in zip(df_page["Granule UR"], start_col, cc_series):
                cc_val = float(raw_cc) if raw_cc is not None and pd.notna(raw_cc) else None
                parsed = _parse_granule_ur_row(
                    str(granule_ur),
                    time_start=str(t_start) if pd.notna(t_start) else None,
                    cloud_cover=cc_val,
                    target_tiles=target_tiles,
                )
                if parsed is not None:
                    rows.append(parsed)

            search_after = response.headers.get("CMR-Search-After")
            if not search_after:
                break
            if search_after == previous_search_after:
                raise RuntimeError("CMR repeated a Search-After token; stopping pagination")
            previous_search_after = search_after
            headers = {"CMR-Search-After": search_after}

        return rows

    all_rows: List[Dict[str, Any]] = []
    if max_workers > 1 and len(chunks) > 1:
        with logging_redirect_tqdm(), ThreadPoolExecutor(
            max_workers=min(max_workers, len(chunks))
        ) as executor:
            futures = [executor.submit(_fetch_window, w) for w in chunks]
            with tqdm(
                total=len(chunks),
                desc=desc or f"CMR CSV ({concept_ID})",
                unit="win",
                dynamic_ncols=True,
                disable=not verbose,
            ) as pbar:
                for future in as_completed(futures):
                    chunk_rows = future.result()
                    all_rows.extend(chunk_rows)
                    pbar.set_postfix(granules=f"{len(all_rows):,}", refresh=False)
                    pbar.update(1)
    else:
        for w in chunks:
            all_rows.extend(_fetch_window(w))

    columns = [
        "granule",
        "product",
        "orbit",
        "scene",
        "tile",
        "timestamp",
        "date_str",
        "time_start",
        "cloud_cover",
    ]
    if not all_rows:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(all_rows, columns=columns)
    return df.drop_duplicates(subset=["granule"]).reset_index(drop=True)


def search_granule_catalog_umm(
    concept_ID: str,
    start_date: Union[date, str],
    end_date: Union[date, str],
    max_cloud_cover: Optional[float] = None,
    allowed_tiles: Optional[Set[str]] = None,
    chunk_days: Optional[int] = 5,
    max_workers: int = 6,
    CMR_search_URL: str = CMR_SEARCH_URL,
    session: Optional[requests.Session] = None,
    desc: Optional[str] = None,
    verbose: bool = False,
) -> pd.DataFrame:
    """Backward-compatible wrapper delegating global catalog enumeration to search_granule_catalog_csv()."""
    return search_granule_catalog_csv(
        concept_ID=concept_ID,
        start_date=start_date,
        end_date=end_date,
        allowed_tiles=allowed_tiles,
        chunk_days=chunk_days,
        max_workers=max_workers,
        CMR_search_URL=CMR_search_URL,
        session=session,
        desc=desc,
        verbose=verbose,
    )


def _extract_matching_links(
    entries: List[Dict[str, Any]],
    max_cloud_cover: Optional[float] = None,
    target_tiles: Optional[Set[str]] = None,
    tif_only: bool = False,
    allowed_suffixes: Optional[Tuple[str, ...]] = None,
) -> List[Dict[str, Any]]:
    if allowed_suffixes is None:
        allowed_suffixes = (".tif",) if tif_only else (".tif", ".json", ".aux.xml", ".jpeg")
    records: List[Dict[str, Any]] = []
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
            if not (href and href.startswith("https") and href.endswith(allowed_suffixes)):
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
    return records


def search_granules_by_name_patterns(
    concept_ID: str,
    granule_patterns: Sequence[str],
    max_cloud_cover: Optional[float] = None,
    tif_only: bool = True,
    allowed_suffixes: Optional[Tuple[str, ...]] = None,
    CMR_search_URL: str = CMR_SEARCH_URL,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """
    Query CMR granules.json for an exact batch of wildcard readable_granule_name[]
    patterns (e.g. 'ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_*'), avoiding
    broad spatial sweeps and deep Search-After pagination when companion granules
    are already known from a primary product search.
    """
    if not granule_patterns:
        return []

    granule_search_URL = f"{CMR_search_URL}granules.json"
    params: List[Tuple[str, Any]] = [
        ("concept_id", concept_ID),
        ("options[readable_granule_name][pattern]", "true"),
        ("page_size", 2000),
    ]
    for pattern in granule_patterns:
        params.append(("readable_granule_name[]", pattern))

    records: List[Dict[str, Any]] = []
    headers: Dict[str, str] = {}
    previous_search_after = None

    while True:
        response = _request_with_backoff(
            granule_search_URL, params=params, headers=headers, session=session, method="POST"
        )
        entries = response.json().get("feed", {}).get("entry", [])
        records.extend(
            _extract_matching_links(
                entries=entries,
                max_cloud_cover=max_cloud_cover,
                target_tiles=None,
                tif_only=tif_only,
                allowed_suffixes=allowed_suffixes,
            )
        )
        search_after = response.headers.get("CMR-Search-After")
        if not search_after or not entries:
            break
        if search_after == previous_search_after:
            raise RuntimeError("CMR repeated a Search-After token; stopping pagination")
        previous_search_after = search_after
        headers = {"CMR-Search-After": search_after}

    return records


def ECOSTRESS_CMR_search_entries(
    concept_ID: str,
    tile: Optional[str] = None,
    bounding_box: Optional[Tuple[float, float, float, float]] = None,
    start_date: Union[date, str] = None,
    end_date: Union[date, str] = None,
    use_tile_bounds: bool = True,
    max_cloud_cover: Optional[float] = None,
    allowed_tiles: Optional[Set[str]] = None,
    tif_only: bool = False,
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
        records.extend(
            _extract_matching_links(
                entries=entries,
                max_cloud_cover=max_cloud_cover,
                target_tiles=target_tiles,
                tif_only=tif_only,
            )
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
