import importlib
from datetime import date
from unittest.mock import Mock

import pandas as pd
import pytest
from ECOv003_granules import ECOSTRESSGranule


download_module = importlib.import_module(
    "ECOv003_CMR.download_ECOSTRESS_granule"
)
download_files_module = importlib.import_module(
    "ECOv003_CMR.download_ECOSTRESS_granule_files"
)
download_batch_module = importlib.import_module(
    "ECOv003_CMR.download_ECOSTRESS"
)
download_file_module = importlib.import_module(
    "ECOv003_CMR.download_file"
)


class MisparsedGranule(ECOSTRESSGranule):
    @property
    def product(self):
        return "L2T_LSTE_44814"


def _mock_download_directory(monkeypatch):
    monkeypatch.setattr(
        download_module,
        "download_ECOSTRESS_granule_files",
        lambda **kwargs: (
            "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02"
        ),
    )


def test_download_raises_when_granule_package_does_not_recognize_product(
    monkeypatch,
):
    _mock_download_directory(monkeypatch)
    monkeypatch.setattr(
        download_module,
        "open_ECOSTRESS_granule",
        lambda directory: None,
    )

    with pytest.raises(RuntimeError, match="could not open Collection 3 granule"):
        download_module.download_ECOSTRESS_granule(
            product="L2T_LSTE",
            tile="52NHN",
            acquisition_date="2026-06-01",
        )


def test_download_raises_when_granule_package_misparses_product(monkeypatch):
    _mock_download_directory(monkeypatch)
    monkeypatch.setattr(
        download_module,
        "open_ECOSTRESS_granule",
        lambda directory: MisparsedGranule(directory),
    )

    with pytest.raises(RuntimeError, match="expected 'L2T_LSTE'"):
        download_module.download_ECOSTRESS_granule(
            product="L2T_LSTE",
            tile="52NHN",
            acquisition_date="2026-06-01",
        )


@pytest.mark.parametrize(
    "product,granule_name,variable,tile",
    [
        (
            "L1CT_RAD",
            "ECOv003_L1CT_RAD_44814_001_53NKG_20260601T000306_01",
            "radiance_1",
            "53NKG",
        ),
        (
            "L2T_STARS",
            "ECOv003_L2T_STARS_53PMK_20260601_01",
            "NDVI",
            "53PMK",
        ),
        (
            "L3T_ETAUX",
            "ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01",
            "Ta",
            "53NMH",
        ),
    ],
)
def test_download_opens_collection3_granules(
    monkeypatch,
    tmp_path,
    product,
    granule_name,
    variable,
    tile,
):
    granule_directory = tmp_path / granule_name
    granule_directory.mkdir()
    (granule_directory / f"{granule_name}_{variable}.tif").touch()
    monkeypatch.setattr(
        download_module,
        "download_ECOSTRESS_granule_files",
        lambda **kwargs: str(granule_directory),
    )

    granule = download_module.download_ECOSTRESS_granule(
        product=product,
        tile=tile,
        acquisition_date="2026-06-01",
    )

    assert granule.product == product
    assert granule.tile == tile
    assert granule.granule_name == granule_name


def test_download_granule_accepts_legacy_aquisition_date_alias_with_warning(monkeypatch, tmp_path):
    granule_name = "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02"
    granule_directory = tmp_path / granule_name
    granule_directory.mkdir()
    (granule_directory / f"{granule_name}_LST.tif").touch()
    recorded = {}

    def mock_download_files(**kwargs):
        recorded.update(kwargs)
        return str(granule_directory)

    monkeypatch.setattr(
        download_module,
        "download_ECOSTRESS_granule_files",
        mock_download_files,
    )

    with pytest.warns(DeprecationWarning, match="aquisition_date"):
        granule = download_module.download_ECOSTRESS_granule(
            product="L2T_LSTE",
            tile="52NHN",
            aquisition_date="2026-06-01",
        )

    assert recorded["acquisition_date"] == "2026-06-01"
    assert granule.granule_name == granule_name


def test_download_granule_files_propagates_session(monkeypatch, tmp_path):
    granule_name = "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02"
    listing = pd.DataFrame([
        {
            "granule": granule_name,
            "URL": f"https://example.test/{granule_name}_LST.tif",
        }
    ])
    mock_session = Mock()
    seen_sessions = []

    def mock_download_file(URL, filename, session=None):
        seen_sessions.append(session)
        return filename

    monkeypatch.setattr(download_files_module, "download_file", mock_download_file)

    download_files_module.download_ECOSTRESS_granule_files(
        product="L2T_LSTE",
        tile="52NHN",
        acquisition_date="2026-06-01",
        parent_directory=str(tmp_path),
        CMR_file_listing_df=listing,
        session=mock_session,
    )

    assert seen_sessions == [mock_session]


def test_get_granule_from_listing_raises_file_not_found_when_empty():
    with pytest.raises(FileNotFoundError, match="No matching ECOSTRESS granules"):
        download_files_module.get_granule_from_listing(pd.DataFrame())


def test_get_granule_from_listing_selects_latest_build_and_filters_urls(monkeypatch, tmp_path):
    stem = "ECOv003_L3T_ETAUX_44841_001_11SPS_20260602T180012"
    listing = pd.DataFrame([
        {"granule": f"{stem}_01", "URL": f"https://example.test/{stem}_01_Ta.tif"},
        {"granule": f"{stem}_03", "URL": f"https://example.test/{stem}_03_Ta.tif"},
        {"granule": f"{stem}_02", "URL": f"https://example.test/{stem}_02_Ta.tif"},
    ])

    gid = download_files_module.get_granule_from_listing(listing)
    assert str(gid) == f"{stem}_03"

    downloaded_urls = []

    def mock_download_file(URL, filename, session=None):
        downloaded_urls.append(URL)
        return filename

    monkeypatch.setattr(download_files_module, "download_file", mock_download_file)

    directory = download_files_module.download_ECOSTRESS_granule_files(
        product="L3T_ETAUX",
        tile="11SPS",
        acquisition_date="2026-06-02",
        parent_directory=str(tmp_path),
        CMR_file_listing_df=listing,
        session=Mock(),
    )

    assert directory.endswith(f"{stem}_03")
    assert downloaded_urls == [f"https://example.test/{stem}_03_Ta.tif"]


def test_get_granule_from_listing_rejects_distinct_granule_stems():
    listing = pd.DataFrame([
        {"granule": "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02"},
        {"granule": "ECOv003_L2T_LSTE_44860_002_52NHN_20260601T120000_02"},
    ])
    with pytest.raises(ValueError, match="distinct granules"):
        download_files_module.get_granule_from_listing(listing)


def test_download_file_retries_on_midstream_timeout_and_cleans_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(download_file_module.time, "sleep", lambda _: None)
    target = tmp_path / "ECOv003_L3T_ETAUX_44841_001_11SPS_20260602T180012_02_Rg.tif"
    partial = tmp_path / f"{target.name}.download"

    class StallThenSucceedSession:
        def __init__(self):
            self.calls = 0

        def get(self, url, stream=True, allow_redirects=True, timeout=None):
            assert timeout == (15.0, 90.0)
            self.calls += 1
            attempt = self.calls

            class FakeResponse:
                status_code = 200
                headers = {"content-length": "8"}

                def raise_for_status(self):
                    pass

                def iter_content(self, chunk_size=1024):
                    yield b"part"
                    if attempt == 1:
                        raise TimeoutError(60, "Operation timed out")
                    yield b"data"

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            return FakeResponse()

    session = StallThenSucceedSession()
    result = download_file_module.download_file(
        "https://example.test/Rg.tif",
        filename=str(target),
        session=session,
        max_retries=3,
    )

    assert session.calls == 2
    assert result == str(target)
    assert target.read_bytes() == b"partdata"
    assert not partial.exists()


def test_download_ecostress_extracts_per_granule_acquisition_date(monkeypatch):
    g1 = "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02"
    g2 = "ECOv003_L2T_LSTE_44860_002_52NHN_20260604T120000_02"
    listing = pd.DataFrame([
        {"granule": g1, "URL": f"https://example.test/{g1}_LST.tif"},
        {"granule": g2, "URL": f"https://example.test/{g2}_LST.tif"},
    ])
    seen_dates = []

    def mock_download_granule(**kwargs):
        seen_dates.append(kwargs["acquisition_date"])
        return kwargs["CMR_file_listing_df"]["granule"].iloc[0]

    monkeypatch.setattr(
        download_batch_module,
        "download_ECOSTRESS_granule",
        mock_download_granule,
    )

    results = download_batch_module.download_ECOSTRESS(
        product="L2T_LSTE",
        tile="52NHN",
        start_date="2026-06-01",
        end_date="2026-06-07",
        CMR_file_listing_df=listing,
        session=Mock(),
    )

    assert results == [g1, g2]
    assert seen_dates == [date(2026, 6, 1), date(2026, 6, 4)]


def test_download_cli_handles_errors_cleanly(monkeypatch, caplog):
    monkeypatch.setattr(
        download_batch_module,
        "download_ECOSTRESS",
        Mock(side_effect=RuntimeError("simulated network failure")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "ECOv003-download",
            "--product",
            "L2T_LSTE",
            "--tile",
            "52NHN",
            "--start-date",
            "2026-06-01",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        download_batch_module.main()

    assert exc_info.value.code == 1
    assert "Error: simulated network failure" in caplog.text
