import os
import pytest
from ECOv003_CMR import ECOSTRESS_CMR_search, setup_earthdata_session


@pytest.mark.integration
def test_live_cmr_search_and_auth():
    if not (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")):
        pytest.skip("Earthdata credentials not set")
    session = setup_earthdata_session(require_auth=True)
    assert session.auth is not None
    df = ECOSTRESS_CMR_search(product="L2T_LSTE", tile="52NHN", start_date="2026-06-01", end_date="2026-06-02")
    assert not df.empty
