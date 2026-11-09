import importlib

import pytest
from ECOv003_granules import ECOSTRESSGranule


download_module = importlib.import_module(
    "ECOv003_CMR.download_ECOSTRESS_granule"
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
            aquisition_date="2026-06-01",
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
            aquisition_date="2026-06-01",
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
        aquisition_date="2026-06-01",
    )

    assert granule.product == product
    assert granule.tile == tile
    assert granule.granule_name == granule_name
