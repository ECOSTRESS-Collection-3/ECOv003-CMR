import os
from os import makedirs
from os.path import exists, getsize, dirname, abspath, expanduser, join
import logging
import posixpath
import random
import time
from typing import Optional, Tuple
import requests
from tqdm.auto import tqdm

import colored_logging as cl

from .authentication import setup_earthdata_session
from .exceptions import *

logger = logging.getLogger(__name__)

_TRANSIENT_DOWNLOAD_STATUS = {429, 500, 502, 503, 504}


def expand_filename(filename: str) -> str:
    """
    Expands the given filename to an absolute path.

    Args:
        filename (str): The filename to expand.

    Returns:
        str: The expanded absolute path of the filename.
    """
    return abspath(expanduser(filename))


def download_file(
        URL: str,
        filename: str = None,
        granule_directory: str = None,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        timeout: Tuple[float, float] = (15.0, 90.0)) -> str:
    """
    Downloads a file from the given URL to the specified filename using an
    authenticated NASA Earthdata session with explicit socket timeouts and
    jittered exponential retry backoff.

    Args:
        URL (str): The URL of the file to download.
        filename (str, optional): The local filename to save the downloaded file. Defaults to None.
        granule_directory (str, optional): The directory to save the file if filename is not provided. Defaults to None.
        session (requests.Session, optional): Authenticated session for NASA Earthdata. Defaults to setup_earthdata_session().
        max_retries (int, optional): Maximum download attempts. Defaults to 3.
        backoff_base (float, optional): Base seconds for exponential retry backoff. Defaults to 2.0.
        timeout (Tuple[float, float], optional): (connect, read) socket timeout in seconds. Defaults to (15.0, 90.0).

    Returns:
        str: The path to the downloaded file.

    Raises:
        ECOSTRESSDownloadFailed: If the download fails.
    """
    if filename is None:
        if granule_directory is None:
            raise ValueError("Either filename or granule_directory must be provided")
        filename = join(granule_directory, posixpath.basename(URL))

    abs_filename = expand_filename(filename)

    if exists(abs_filename) and getsize(abs_filename) == 0:
        logger.warning(f"removing zero-size corrupted ECOSTRESS file: {filename}")
        os.remove(abs_filename)

    if exists(abs_filename):
        logger.info(f"file already downloaded: {cl.file(filename)}")
        return filename

    if session is None:
        session = setup_earthdata_session()

    directory = dirname(abs_filename)
    makedirs(directory, exist_ok=True)
    partial_filename = f"{abs_filename}.download"

    last_error = None
    for attempt in range(1, max_retries + 1):
        if exists(partial_filename):
            os.remove(partial_filename)

        logger.info(f"downloading (attempt {attempt}/{max_retries}): {cl.URL(URL)} -> {cl.file(filename)}")
        try:
            with session.get(URL, stream=True, allow_redirects=True, timeout=timeout) as r:
                status = getattr(r, "status_code", 200)
                if status in _TRANSIENT_DOWNLOAD_STATUS and attempt < max_retries:
                    retry_after = r.headers.get("Retry-After") if hasattr(r, "headers") else None
                    delay = float(retry_after) if retry_after else (backoff_base ** attempt + random.uniform(0, 0.5))
                    logger.warning(
                        f"transient HTTP {status} downloading {URL}; retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    continue

                r.raise_for_status()
                total = int(r.headers.get('content-length', 0))
                with open(partial_filename, 'wb') as f, tqdm(
                    desc=posixpath.basename(filename),
                    total=total,
                    unit='iB',
                    unit_scale=True,
                    unit_divisor=1024,
                    leave=True
                ) as bar:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            bar.update(len(chunk))

            last_error = None
            break
        except (requests.exceptions.RequestException, TimeoutError, OSError) as e:
            last_error = e
            if exists(partial_filename):
                os.remove(partial_filename)
            if attempt < max_retries:
                delay = backoff_base ** attempt + random.uniform(0, 0.5)
                logger.warning(
                    f"download attempt {attempt}/{max_retries} failed for {URL} ({e}); "
                    f"retrying in {delay:.1f}s..."
                )
                time.sleep(delay)

    if last_error is not None:
        raise ECOSTRESSDownloadFailed(f"unable to download URL: {URL}\n{last_error}")

    if not exists(partial_filename) or getsize(partial_filename) == 0:
        if exists(partial_filename):
            os.remove(partial_filename)
        raise ECOSTRESSDownloadFailed(f"unable to download URL: {URL}")

    os.replace(partial_filename, abs_filename)

    if not exists(abs_filename):
        raise ECOSTRESSDownloadFailed(f"failed to download file: {filename}")

    logger.info(f"completed download: {cl.file(filename)}")
    return filename
