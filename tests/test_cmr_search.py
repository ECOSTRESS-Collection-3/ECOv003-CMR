import importlib

import pytest

from ECOv003_CMR.ECOSTRESS_CMR_search_links import ECOSTRESS_CMR_search_links
from ECOv003_CMR.interpret_ECOSTRESS_URLs import interpret_ECOSTRESS_URLs


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
    responses = [
        MockCMRResponse(
            [{"links": [{"href": "https://example.test/granule-1.tif"}]}],
            {"CMR-Search-After": search_after},
        ),
        MockCMRResponse(
            [{"links": [{"href": "https://example.test/granule-2.tif"}]}]
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
        end_date="2026-06-01",
    )

    assert urls == [
        "https://example.test/granule-1.tif",
        "https://example.test/granule-2.tif",
    ]
    assert calls[0]["headers"] == {}
    assert calls[1]["headers"] == {"CMR-Search-After": search_after}
    assert all(call["params"]["page_size"] == 2000 for call in calls)


def test_search_links_rejects_repeated_search_after_token(monkeypatch):
    search_after = '["provider", 123, 456]'
    response = MockCMRResponse(
        [{"links": [{"href": "https://example.test/granule.tif"}]}],
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
