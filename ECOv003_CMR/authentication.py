"""
NASA Earthdata authentication utilities.

This module provides functions for setting up authenticated sessions and GDAL
/vsicurl/ environments to access NASA Earthdata services.
"""

from contextlib import contextmanager
import http.cookiejar
import logging
import os
from pathlib import Path
import tempfile
from typing import Iterator, Optional
import rasterio
import requests

logger = logging.getLogger(__name__)


def setup_earthdata_session(
    username: Optional[str] = None,
    password: Optional[str] = None,
    require_auth: bool = True
) -> requests.Session:
    """
    Set up NASA Earthdata authenticated session.

    Credentials are sourced from (in order of priority):
    1. Parameters passed directly to this function
    2. Environment variables (EARTHDATA_USERNAME, EARTHDATA_PASSWORD)
    3. ~/.netrc file
    """
    if not (username and password):
        username = username or os.environ.get("EARTHDATA_USERNAME")
        password = password or os.environ.get("EARTHDATA_PASSWORD")

    if not (username and password):
        netrc_path = Path.home() / ".netrc"
        if netrc_path.exists():
            try:
                import netrc
                netrc_auth = netrc.netrc(str(netrc_path))
                auth = netrc_auth.authenticators("urs.earthdata.nasa.gov")
                if auth:
                    username, _, password = auth
                    logger.info("Credentials loaded from ~/.netrc")
            except Exception as e:
                logger.warning(f"Failed to read .netrc: {e}")

    session = requests.Session()

    if username and password:
        session.auth = (username, password)
        logger.info("NASA Earthdata authentication configured")
    elif require_auth:
        raise RuntimeError(
            "NASA Earthdata authentication required!\n\n"
            "Option 1: Create ~/.netrc with:\n"
            "    machine urs.earthdata.nasa.gov\n"
            "        login YOUR_USERNAME\n"
            "        password YOUR_PASSWORD\n\n"
            "Option 2: Set environment variables:\n"
            "    export EARTHDATA_USERNAME=YOUR_USERNAME\n"
            "    export EARTHDATA_PASSWORD=YOUR_PASSWORD\n\n"
            "Option 3: Pass credentials directly:\n"
            "    setup_earthdata_session(username='...', password='...')"
        )
    else:
        logger.warning("No NASA Earthdata credentials found, session is unauthenticated")

    return session


def _export_session_cookies_to_netscape(session: requests.Session, cookie_file: str) -> None:
    """Persist requests.Session cookies into a Netscape-format cookie jar for GDAL/libcurl."""
    jar = http.cookiejar.MozillaCookieJar(cookie_file)
    for cookie in session.cookies:
        jar.set_cookie(cookie)
    jar.save(ignore_discard=True, ignore_expires=True)


@contextmanager
def configure_gdal_earthdata_env(
    session: Optional[requests.Session] = None,
    cookie_file: Optional[str] = None,
    warmup_url: Optional[str] = None,
) -> Iterator[rasterio.Env]:
    """
    Context manager providing a process-wide rasterio.Env configured for authenticated
    /vsicurl/ HTTP byte-range requests against LP DAAC Earthdata Cloud COGs, exporting
    pre-warmed URS cookies to Netscape format and cleaning up temporary cookie files
    on exit.
    """
    if session is None:
        session = setup_earthdata_session(require_auth=False)

    created_temp_cookie = False
    if cookie_file is None:
        fd, cookie_file = tempfile.mkstemp(prefix="earthdata_gdal_", suffix=".cookies")
        os.close(fd)
        created_temp_cookie = True

    if warmup_url is not None:
        try:
            with session.get(warmup_url, stream=True, allow_redirects=True, timeout=30) as resp:
                resp.raise_for_status()
        except Exception as exc:
            logger.warning(f"Earthdata cookie pre-warm failed: {exc}")

    try:
        _export_session_cookies_to_netscape(session, cookie_file)
    except Exception as exc:
        logger.debug(f"Could not export session cookies to Netscape jar: {exc}")

    gdal_options = {
        "GDAL_HTTP_NETRC": "YES",
        "GDAL_HTTP_COOKIEFILE": cookie_file,
        "GDAL_HTTP_COOKIEJAR": cookie_file,
        "GDAL_HTTP_UNSAFESSL": "NO",
        "GDAL_HTTP_MAX_RETRY": "3",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "GDAL_HTTP_RETRY_CODES": "429,502,503,504",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
        "CPL_VSIL_CURL_USE_HEAD": "NO",
        "VSI_CACHE": "TRUE",
        "VSI_CACHE_SIZE": "50000000",
    }
    try:
        with rasterio.Env(**gdal_options) as env:
            yield env
    finally:
        if created_temp_cookie and cookie_file and os.path.exists(cookie_file):
            try:
                os.remove(cookie_file)
            except OSError:
                pass
