"""
Test point sampling functionality.

These tests verify the point sampling API without requiring actual
network requests or authentication.
"""

from datetime import datetime
import importlib
from unittest.mock import Mock, patch

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import Point


def test_import_point_sampling():
    """Test that point sampling functions can be imported."""
    from ECOv003_CMR import (
        setup_earthdata_session,
        sample_point_from_url,
        sample_points_from_geodataframe,
        sample_points_over_date_range,
        find_sentinel2_tile,
    )

    assert callable(setup_earthdata_session)
    assert callable(sample_point_from_url)
    assert callable(sample_points_from_geodataframe)
    assert callable(sample_points_over_date_range)
    assert callable(find_sentinel2_tile)


def test_find_sentinel2_tile():
    """Test Sentinel-2 tile containment lookup and open-ocean None behavior."""
    from ECOv003_CMR import find_sentinel2_tile

    tile = find_sentinel2_tile(-118.2437, 34.0522)
    assert tile == "11SLT"

    all_tiles = find_sentinel2_tile(-118.2437, 34.0522, return_all=True)
    assert "11SLT" in all_tiles

    ocean_tile = find_sentinel2_tile(-140.0, 0.0)
    assert ocean_tile is None
    assert find_sentinel2_tile(-140.0, 0.0, return_all=True) == []


def test_setup_earthdata_session_with_params():
    """Test setting up session with explicit credentials."""
    from ECOv003_CMR import setup_earthdata_session

    session = setup_earthdata_session(
        username="testuser",
        password="testpass",
        require_auth=True,
    )

    assert session.auth == ("testuser", "testpass")


def test_setup_earthdata_session_no_auth_optional():
    """Test setting up session without authentication when optional."""
    from ECOv003_CMR import setup_earthdata_session

    with patch.dict('os.environ', {}, clear=True):
        with patch('pathlib.Path.exists', return_value=False):
            session = setup_earthdata_session(require_auth=False)
            assert session.auth is None


def test_setup_earthdata_session_no_auth_required():
    """Test that missing auth raises error when required."""
    from ECOv003_CMR import setup_earthdata_session

    with patch.dict('os.environ', {}, clear=True):
        with patch('pathlib.Path.exists', return_value=False):
            with pytest.raises(RuntimeError, match="authentication required"):
                setup_earthdata_session(require_auth=True)


def test_sample_points_from_geodataframe_validation():
    """Test input validation for GeoDataFrame sampling."""
    from ECOv003_CMR import sample_points_from_geodataframe

    data = {
        'datetime': [datetime(2025, 6, 15)],
        'geometry': [Point(-118.24, 34.05)],
    }
    gdf = gpd.GeoDataFrame(data)

    with pytest.raises(ValueError, match="must have a defined CRS"):
        sample_points_from_geodataframe(geometry=gdf)


def test_sample_points_from_geodataframe_missing_columns():
    """Test error handling for missing required columns."""
    from ECOv003_CMR import sample_points_from_geodataframe

    data = {
        'site_id': ['A'],
        'geometry': [Point(-118.24, 34.05)],
    }
    gdf = gpd.GeoDataFrame(data, crs='EPSG:4326')

    with pytest.raises(ValueError, match="Datetime column 'datetime' not found"):
        sample_points_from_geodataframe(geometry=gdf)


def test_sample_points_from_geodataframe_crs_reprojection():
    """Test that non-WGS84 GeoDataFrames are reprojected."""
    from ECOv003_CMR import sample_points_from_geodataframe

    data = {
        'datetime': [datetime(2025, 6, 15)],
        'geometry': [Point(-13163264, 4035122)],
    }
    gdf = gpd.GeoDataFrame(data, crs='EPSG:3857')

    with patch('ECOv003_CMR.point_sampling.setup_earthdata_session'):
        with patch('ECOv003_CMR.point_sampling.ECOSTRESS_CMR_search') as mock_search:
            mock_search.return_value = pd.DataFrame()
            result = sample_points_from_geodataframe(geometry=gdf, verbose=False)
            assert isinstance(result, pd.DataFrame)


def test_collection3_layer_mapping_uses_supported_products_and_variables():
    from ECOv003_CMR.constants import CONCEPT_IDS
    from ECOv003_CMR.point_sampling import LAYER_MAPPING

    assert {product for product, _ in LAYER_MAPPING.values()} <= set(CONCEPT_IDS)
    assert LAYER_MAPPING["Ta_C"] == ("L3T_ETAUX", "Ta")
    assert LAYER_MAPPING["RH"] == ("L3T_ETAUX", "RH")
    assert LAYER_MAPPING["SM"] == ("L3T_ETAUX", "SM")
    assert LAYER_MAPPING["Rg"] == ("L3T_ETAUX", "Rg")
    assert LAYER_MAPPING["Rn"] == ("L3T_ETAUX", "Rn")
    assert "EVI" not in LAYER_MAPPING
    assert "SAVI" not in LAYER_MAPPING
    assert not {"L3T_MET", "L3T_SM", "L3T_SEB"} & {
        product for product, _ in LAYER_MAPPING.values()
    }


@pytest.mark.parametrize("sampling_function", ["date_range", "geodataframe"])
def test_removed_collection2_layers_are_rejected(sampling_function):
    from ECOv003_CMR import sample_points_from_geodataframe, sample_points_over_date_range

    if sampling_function == "date_range":
        with pytest.raises(ValueError, match="EVI"):
            sample_points_over_date_range(
                geometry=Point(-118.24, 34.05),
                start_date="2026-06-01",
                end_date="2026-06-01",
                layers=["EVI"],
                session=Mock(),
                verbose=False,
            )
    else:
        gdf = gpd.GeoDataFrame(
            {"datetime": [datetime(2026, 6, 1)], "geometry": [Point(-118.24, 34.05)]},
            crs="EPSG:4326",
        )
        with pytest.raises(ValueError, match="EVI"):
            sample_points_from_geodataframe(
                geometry=gdf,
                layers=["EVI"],
                session=Mock(),
                verbose=False,
            )


def test_sample_point_from_url_reads_values_and_nan_nodata():
    from ECOv003_CMR import sample_point_from_url

    def geotiff_bytes(value, nodata):
        with MemoryFile() as memfile:
            with memfile.open(
                driver="GTiff",
                height=1,
                width=1,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(-120, 40, 1, 1),
                nodata=nodata,
            ) as dataset:
                dataset.write(np.array([[value]], dtype="float32"), 1)
            return memfile.read()

    session = Mock()
    session.get.return_value.content = geotiff_bytes(298.15, np.nan)
    value, _ = sample_point_from_url(session, "https://example.test/lst.tif", -119.5, 39.5)
    assert value == pytest.approx(298.15)

    session.get.return_value.content = geotiff_bytes(np.nan, np.nan)
    value, reason = sample_point_from_url(session, "https://example.test/lst.tif", -119.5, 39.5)
    assert value is None
    assert reason == "nodata"


def test_sample_points_from_geodataframe_joins_stars_and_converts_lst_to_celsius(monkeypatch):
    point_sampling = importlib.import_module("ECOv003_CMR.point_sampling")
    lste_granule = "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02"
    stars_granule = "ECOv003_L2T_STARS_52NHN_20260601_01"

    def mock_search(product, tile, **kwargs):
        if product == "L2T_LSTE":
            return pd.DataFrame([
                {
                    "type": "GeoTIFF Data",
                    "variable": "LST",
                    "granule": lste_granule,
                    "URL": "https://example.test/lst.tif",
                    "orbit": 44814,
                    "scene": 1,
                }
            ])
        if product == "L2T_STARS":
            return pd.DataFrame([
                {
                    "type": "GeoTIFF Data",
                    "variable": "NDVI",
                    "granule": stars_granule,
                    "URL": "https://example.test/ndvi.tif",
                    "orbit": None,
                    "scene": None,
                }
            ])
        return pd.DataFrame()

    def mock_sample_var(variable, url, lons, lats, session, use_vsicurl, stream_semaphore=None):
        val = 300.0 if variable == "LST" else 0.55
        return variable, [val for _ in lons]

    monkeypatch.setattr(point_sampling, "find_sentinel2_tile", lambda lon, lat: "52NHN")
    monkeypatch.setattr(point_sampling, "ECOSTRESS_CMR_search", mock_search)
    monkeypatch.setattr(point_sampling, "_sample_single_variable_url", mock_sample_var)

    gdf = gpd.GeoDataFrame(
        {"datetime": [datetime(2026, 6, 1)], "geometry": [Point(-118.24, 34.05)]},
        crs="EPSG:4326",
    )
    results = point_sampling.sample_points_from_geodataframe(
        geometry=gdf,
        layers=["ST_C", "LST", "NDVI"],
        session=Mock(),
        verbose=False,
    )

    assert len(results) == 1
    assert results.loc[0, "LST"] == pytest.approx(300.0)
    assert results.loc[0, "ST_C"] == pytest.approx(26.85)
    assert results.loc[0, "NDVI"] == pytest.approx(0.55)


@pytest.mark.parametrize("max_workers", [1, 2])
def test_sample_points_over_date_range_supports_etaux_only(monkeypatch, max_workers):
    point_sampling = importlib.import_module("ECOv003_CMR.point_sampling")
    granule = "ECOv003_L3T_ETAUX_44814_001_53NMH_20260601T000306_01"
    search_results = pd.DataFrame(
        [{
            "type": "GeoTIFF Data",
            "variable": "Ta",
            "granule": granule,
            "URL": "https://example.test/ta.tif",
            "orbit": 44814,
            "scene": 1,
        }]
    )
    monkeypatch.setattr(point_sampling, "find_sentinel2_tile", lambda lon, lat: "53NMH")
    monkeypatch.setattr(point_sampling, "ECOSTRESS_CMR_search", lambda **kwargs: search_results)
    monkeypatch.setattr(
        point_sampling,
        "_sample_single_variable_url",
        lambda variable, url, lons, lats, *args, **kwargs: (variable, [21.5 for _ in lons]),
    )

    results = point_sampling.sample_points_over_date_range(
        geometry=Point(-118.24, 34.05),
        start_date="2026-06-01",
        end_date="2026-06-01",
        layers=["Ta_C"],
        session=Mock(),
        max_workers=max_workers,
        verbose=False,
    )

    assert len(results) == 1
    assert results.loc[0, "Ta_C"] == pytest.approx(21.5)


@pytest.mark.parametrize("max_workers", [1, 2])
def test_sample_points_over_date_range_multi_point_stars_and_empty_tile(monkeypatch, max_workers):
    point_sampling = importlib.import_module("ECOv003_CMR.point_sampling")
    stars_granule = "ECOv003_L2T_STARS_11SLT_20260601_01"

    def mock_search(product, tile, **kwargs):
        if tile == "11SLT" and product == "L2T_STARS":
            return pd.DataFrame([
                {
                    "type": "GeoTIFF Data",
                    "variable": "NDVI",
                    "granule": stars_granule,
                    "URL": "https://example.test/ndvi.tif",
                    "orbit": None,
                    "scene": None,
                }
            ])
        return pd.DataFrame()

    monkeypatch.setattr(point_sampling, "ECOSTRESS_CMR_search", mock_search)
    monkeypatch.setattr(
        point_sampling,
        "_sample_single_variable_url",
        lambda variable, url, lons, lats, *args, **kwargs: (variable, [0.42 for _ in lons]),
    )

    gdf = gpd.GeoDataFrame(
        {
            "site_id": ["site_a", "site_b", "site_empty"],
            "geometry": [
                Point(-118.24, 34.05),
                Point(-118.40, 33.94),
                Point(-120.00, 36.00),
            ],
        },
        crs="EPSG:4326",
    )

    results = point_sampling.sample_points_over_date_range(
        geometry=gdf,
        start_date="2026-06-01",
        end_date="2026-06-01",
        layers=["NDVI"],
        tile=["11SLT", "11SLT", "10SGF"],
        session=Mock(),
        max_workers=max_workers,
        verbose=False,
    )

    assert sorted(results["site_id"].tolist()) == ["site_a", "site_b"]
    assert np.allclose(results["NDVI"], 0.42)


def test_summarize_point_samples_from_parquet_files(tmp_path):
    from ECOv003_CMR.point_sampling import summarize_point_samples

    p1 = tmp_path / "part_1.parquet"
    p2 = tmp_path / "part_2.parquet"
    pd.DataFrame({"ST_C": [25.0, np.nan], "NDVI": [0.4, 0.5]}).to_parquet(p1, index=False)
    pd.DataFrame({"ST_C": [27.0, 28.0], "NDVI": [np.nan, 0.6]}).to_parquet(p2, index=False)

    summary = summarize_point_samples([p1, p2], layers=["ST_C", "NDVI"]).set_index("layer")
    assert summary.loc["ST_C", "total_rows"] == 4
    assert summary.loc["ST_C", "valid_count"] == 3
    assert summary.loc["ST_C", "completeness_pct"] == 75.0
    assert summary.loc["NDVI", "valid_count"] == 3
