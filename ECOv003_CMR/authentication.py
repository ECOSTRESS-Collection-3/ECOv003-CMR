"""
NASA Earthdata authentication utilities.

This module provides functions for setting up authenticated sessions and GDAL
/vsicurl/ environments to access NASA Earthdata services.
"""

import os
from pathlib import Path
import tempfile
from typing import Optional
import requests
import rasterio
import logging

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


def configure_gdal_earthdata_env(
    session: Optional[requests.Session] = None,
    cookie_file: Optional[str] = None,
    warmup_url: Optional[str] = None,
) -> rasterio.Env:
    """
    Create a process-wide rasterio.Env configured for authenticated /vsicurl/
    HTTP byte-range requests against LP DAAC Earthdata Cloud COGs without
    forwarding Authorization headers to AWS S3 presigned redirects.
    """
    if session is None:
        session = setup_earthdata_session(require_auth=False)

    if cookie_file is None:
        fd, cookie_file = tempfile.mkstemp(prefix="earthdata_gdal_", suffix=".cookies")
        os.close(fd)

    if warmup_url is not None:
        try:
            with session.get(warmup_url, stream=True, allow_redirects=True, timeout=30) as resp:
                resp.raise_for_status()
        except Exception as exc:
            logger.warning(f"Earthdata cookie pre-warm failed: {exc}")

    gdal_options = {
        "GDAL_HTTP_NETRC": "YES",
        "GDAL_HTTP_COOKIEFILE": cookie_file,
        "GDAL_HTTP_COOKIEJAR": cookie_file,
        "GDAL_HTTP_UNSAFESSL": "NO",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF",
        "CPL_VSIL_CURL_USE_HEAD": "NO",
        "VSI_CACHE": "TRUE",
        "VSI_CACHE_SIZE": "50000000",
    }
    return rasterio.Env(**gdal_options)
