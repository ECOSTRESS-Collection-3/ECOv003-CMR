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
    monkeypatch.setattr(download_module, "open_granule", lambda directory: None)

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
        "open_granule",
        lambda directory: MisparsedGranule(directory),
    )

    with pytest.raises(RuntimeError, match="expected 'L2T_LSTE'"):
        download_module.download_ECOSTRESS_granule(
            product="L2T_LSTE",
            tile="52NHN",
            aquisition_date="2026-06-01",
        )
