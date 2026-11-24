from datetime import date
import os
import pytest
from shapely.geometry import Point
from ECOv003_CMR import (
    ECOSTRESS_CMR_search,
    download_ECOSTRESS_granule,
    sample_points_over_date_range,
    setup_earthdata_session,
)


@pytest.mark.integration
def test_live_cmr_search_and_auth():
    if not (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")):
        pytest.skip("Earthdata credentials not set")
    session = setup_earthdata_session(require_auth=True)
    assert session.auth is not None
    df = ECOSTRESS_CMR_search(product="L2T_LSTE", tile="52NHN", start_date="2026-06-01", end_date="2026-06-02")
    assert not df.empty


@pytest.mark.integration
def test_live_download_and_point_sampling(tmp_path):
    if not (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")):
        pytest.skip("Earthdata credentials not set")
    session = setup_earthdata_session(require_auth=True)
    granule = download_ECOSTRESS_granule(
        product="L3T_ETAUX",
        tile="11SPS",
        orbit=44841,
        scene=1,
        acquisition_date=date(2026, 6, 2),
        parent_directory=str(tmp_path),
        session=session,
    )
    assert granule.product == "L3T_ETAUX"
    samples = sample_points_over_date_range(
        geometry=Point(-118.2437, 34.0522),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 7),
        layers=["ST_C", "NDVI", "albedo"],
        session=session,
        verbose=False,
    )
    assert not samples.empty
