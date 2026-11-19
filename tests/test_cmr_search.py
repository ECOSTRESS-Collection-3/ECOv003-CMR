import importlib

import pytest

from ECOv003_CMR.ECOSTRESS_CMR_search_links import ECOSTRESS_CMR_search_links
from ECOv003_CMR.granule_ID_from_filename import granule_ID_from_filename
from ECOv003_CMR.interpret_ECOSTRESS_URLs import interpret_ECOSTRESS_URLs
from ECOv003_CMR.product_name_from_filename import product_name_from_filename
from ECOv003_CMR.variable_from_filename import variable_from_filename


class MockCMRResponse:
    def __init__(self, entries, headers=None):
        self.payload = {"feed": {"entry": entries}}
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_search_links_follows_search_after_pages(monkeypatch):
    search_after = '["provider", 123, 456]'
    url1 = "https://example.test/ECOv003_L2T_LSTE_44814_001_11SLT_20260601T000306_02_LST.tif"
    url2 = "https://example.test/ECOv003_L2T_LSTE_44860_002_11SLT_20260602T120000_02_LST.tif"
    responses = [
        MockCMRResponse(
            [{"links": [{"href": url1}]}],
            {"CMR-Search-After": search_after},
        ),
        MockCMRResponse(
            [{"links": [{"href": url2}]}]
        ),
    ]
    calls = []

    def mock_get(url, params, headers):
        calls.append({"url": url, "params": params, "headers": headers})
        return responses.pop(0)

    search_links_module = importlib.import_module(
        "ECOv003_CMR.ECOSTRESS_CMR_search_links"
    )
    monkeypatch.setattr(search_links_module.requests, "get", mock_get)

    urls = ECOSTRESS_CMR_search_links(
        concept_ID="C3998139651-LPCLOUD",
        tile="11SLT",
        start_date="2026-06-01",
        end_date="2026-06-02",
    )

    assert urls == [url1, url2]
    assert calls[0]["headers"] == {}
    assert calls[1]["headers"] == {"CMR-Search-After": search_after}
    assert all(call["params"]["page_size"] == 2000 for call in calls)


def test_search_links_rejects_repeated_search_after_token(monkeypatch):
    search_after = '["provider", 123, 456]'
    url1 = "https://example.test/ECOv003_L2T_LSTE_44814_001_11SLT_20260601T000306_02_LST.tif"
    response = MockCMRResponse(
        [{"links": [{"href": url1}]}],
        {"CMR-Search-After": search_after},
    )
    search_links_module = importlib.import_module(
        "ECOv003_CMR.ECOSTRESS_CMR_search_links"
    )

    def mock_get(url, params, headers):
        return response

    monkeypatch.setattr(search_links_module.requests, "get", mock_get)

    with pytest.raises(RuntimeError, match="repeated a Search-After token"):
        ECOSTRESS_CMR_search_links(
            concept_ID="C3998139651-LPCLOUD",
            tile="11SLT",
            start_date="2026-06-01",
            end_date="2026-06-01",
        )


def test_search_links_rejects_unparseable_urls_when_filtering_by_tile(monkeypatch):
    valid_url = "https://example.test/ECOv003_L2T_LSTE_44814_001_11SLT_20260601T000306_02_LST.tif"
    other_tile_url = "https://example.test/ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02_LST.tif"
    malformed_url = "https://example.test/bad.tif"
    response = MockCMRResponse(
        [
            {
                "links": [
                    {"href": valid_url},
                    {"href": other_tile_url},
                    {"href": malformed_url},
                ]
            }
        ]
    )
    search_links_module = importlib.import_module(
        "ECOv003_CMR.ECOSTRESS_CMR_search_links"
    )
    monkeypatch.setattr(search_links_module.requests, "get", lambda url, params, headers: response)

    urls = ECOSTRESS_CMR_search_links(
        concept_ID="C3998139651-LPCLOUD",
        tile="11SLT",
        start_date="2026-06-01",
        end_date="2026-06-01",
    )
    assert urls == [valid_url]


def test_cmr_search_propagates_session(monkeypatch):
    search_module = importlib.import_module("ECOv003_CMR.ECOSTRESS_CMR_search")
    seen_sessions = []

    def mock_search_links(**kwargs):
        seen_sessions.append(kwargs.get("session"))
        return []

    monkeypatch.setattr(search_module, "ECOSTRESS_CMR_search_links", mock_search_links)
    sentinel_session = object()
    search_module.ECOSTRESS_CMR_search(
        product="L2T_LSTE",
        tile="11SLT",
        start_date="2026-06-01",
        session=sentinel_session,
    )
    assert seen_sessions == [sentinel_session]


def test_interpret_collection_3_filenames():
    urls = [
        "https://example.test/"
        "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02_view_zenith.tif",
        "https://example.test/"
        "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02.json",
        "https://example.test/"
        "ECOv003_L2T_STARS_53PMK_20260601_01_NDVI.tif",
    ]

    results = interpret_ECOSTRESS_URLs(urls).set_index("filename")

    lst_granule = "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02"
    stars_granule = "ECOv003_L2T_STARS_53PMK_20260601_01"
    lst_row = results.loc[f"{lst_granule}_view_zenith.tif"]
    metadata_row = results.loc[f"{lst_granule}.json"]
    stars_row = results.loc[f"{stars_granule}_NDVI.tif"]

    assert lst_row["granule"] == lst_granule
    assert lst_row["variable"] == "view_zenith"
    assert lst_row["orbit"] == 44814
    assert lst_row["scene"] == 1
    assert lst_row["tile"] == "52NHN"
    assert metadata_row["granule"] == lst_granule
    assert metadata_row["type"] == "JSON Metadata"
    assert stars_row["granule"] == stars_granule
    assert stars_row["variable"] == "NDVI"
    assert stars_row["tile"] == "53PMK"


def test_collection_3_product_filenames_from_summer_2026():
    cases = [
        (
            "ECOv003_L1CT_RAD_44814_001_53NKG_20260601T000306_01_radiance_1.tif",
            "L1CT_RAD",
            "ECOv003_L1CT_RAD_44814_001_53NKG_20260601T000306_01",
            "radiance_1",
            44814,
            1,
            "53NKG",
        ),
        (
            "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02_Emis4_err.tif",
            "L2T_LSTE",
            "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02",
            "Emis4_err",
            44814,
            1,
            "52NHN",
        ),
        (
            "ECOv003_L2T_STARS_53PMK_20260601_01_NDVI-UQ.tif",
            "L2T_STARS",
            "ECOv003_L2T_STARS_53PMK_20260601_01",
            "NDVI-UQ",
            None,
            None,
            "53PMK",
        ),
        (
            "ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01_Ta.tif",
            "L3T_ETAUX",
            "ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01",
            "Ta",
            44814,
            1,
            "53NMH",
        ),
        (
            "ECOv003_L3T_JET_44814_001_53NMH_20260601T000306_01_PTJPLSMinst.tif",
            "L3T_JET",
            "ECOv003_L3T_JET_44814_001_53NMH_20260601T000306_01",
            "PTJPLSMinst",
            44814,
            1,
            "53NMH",
        ),
        (
            "ECOv003_L4T_ESI_44814_001_53NMH_20260601T000306_01_ESI.tif",
            "L4T_ESI",
            "ECOv003_L4T_ESI_44814_001_53NMH_20260601T000306_01",
            "ESI",
            44814,
            1,
            "53NMH",
        ),
        (
            "ECOv003_L4T_WUE_44814_001_53NMH_20260601T000306_01_WUE.tif",
            "L4T_WUE",
            "ECOv003_L4T_WUE_44814_001_53NMH_20260601T000306_01",
            "WUE",
            44814,
            1,
            "53NMH",
        ),
    ]

    for filename, product, granule_name, variable, orbit, scene, tile in cases:
        assert product_name_from_filename(filename) == product
        assert str(granule_ID_from_filename(filename)) == granule_name
        assert variable_from_filename(filename) == variable

        granule_ID = granule_ID_from_filename(filename)
        assert granule_ID.product == product
        assert granule_ID.orbit == orbit
        assert granule_ID.scene == scene
        assert granule_ID.tile == tile


def test_collection_2_filename_parsing_remains_compatible():
    filename = (
        "ECOv002_L2T_LSTE_35698_014_11SPS_"
        "20241022T183627_0713_01_LST.tif"
    )

    assert str(granule_ID_from_filename(filename)) == (
        "ECOv002_L2T_LSTE_35698_014_11SPS_"
        "20241022T183627_0713_01"
    )
    assert variable_from_filename(filename) == "LST"


def test_interpret_jpeg_auxiliary_xml_before_jpeg_preview():
    filename = (
        "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02_"
        "browse.jpeg.aux.xml"
    )
    result = interpret_ECOSTRESS_URLs([f"https://example.test/{filename}"])

    assert result.iloc[0]["type"] == "GeoJPEG Metadata"
    assert result.iloc[0]["variable"] == "browse"


def test_search_returns_empty_dataframe_when_no_granules(monkeypatch):
    search_module = importlib.import_module("ECOv003_CMR.ECOSTRESS_CMR_search")
    monkeypatch.setattr(
        search_module,
        "ECOSTRESS_CMR_search_links",
        lambda **kwargs: [],
    )

    results = search_module.ECOSTRESS_CMR_search(
        product="L2T_LSTE",
        tile="52NHN",
        start_date="2026-06-01",
    )

    assert results.empty
