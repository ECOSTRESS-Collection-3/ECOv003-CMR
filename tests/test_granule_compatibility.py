from datetime import datetime

import pytest
from ECOv003_granules import ECOSTRESSGranule

from ECOv003_CMR.granule_compatibility import open_ECOSTRESS_granule


@pytest.mark.parametrize(
    "granule_name,variable,orbit,scene,tile",
    [
        (
            "ECOv003_L1CT_RAD_44814_001_53NKG_20260601T000306_01",
            "radiance_1",
            44814,
            1,
            "53NKG",
        ),
        (
            "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02",
            "LST",
            44814,
            1,
            "52NHN",
        ),
        (
            "ECOv003_L2T_STARS_53PMK_20260601_01",
            "NDVI",
            None,
            None,
            "53PMK",
        ),
        (
            "ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01",
            "Ta",
            44814,
            1,
            "53NMH",
        ),
        (
            "ECOv003_L3T_JET_44814_001_53NMH_20260601T000306_01",
            "PTJPLSMinst",
            44814,
            1,
            "53NMH",
        ),
        (
            "ECOv003_L4T_ESI_44814_001_53NMH_20260601T000306_01",
            "ESI",
            44814,
            1,
            "53NMH",
        ),
        (
            "ECOv003_L4T_WUE_44814_001_53NMH_20260601T000306_01",
            "WUE",
            44814,
            1,
            "53NMH",
        ),
    ],
)
def test_open_collection3_granules_from_download_directories(
    tmp_path,
    granule_name,
    variable,
    orbit,
    scene,
    tile,
):
    granule_directory = tmp_path / granule_name
    granule_directory.mkdir()
    layer_file = granule_directory / f"{granule_name}_{variable}.tif"
    layer_file.touch()

    granule = open_ECOSTRESS_granule(str(granule_directory))

    assert isinstance(granule, ECOSTRESSGranule)
    assert granule.granule_name == granule_name
    assert granule.product == "_".join(granule_name.split("_")[1:3])
    assert granule.orbit == orbit
    assert granule.scene == scene
    assert granule.tile == tile
    expected_time = datetime(2026, 6, 1, 0, 3, 6) if orbit is not None else datetime(2026, 6, 1)
    assert granule.time_UTC == expected_time
    assert variable in granule.variables
    assert granule.layer_URI(variable) == str(layer_file)
    assert layer_file.name in granule.filenames
