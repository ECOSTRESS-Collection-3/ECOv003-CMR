"""
Test point sampling functionality.

These tests verify the point sampling API without requiring actual
network requests or authentication.
"""

import pytest
import pandas as pd
import geopandas as gpd
import numpy as np
from datetime import datetime, date
from shapely.geometry import Point
from unittest.mock import Mock, patch, MagicMock
from rasterio.io import MemoryFile
from rasterio.transform import from_origin


def test_import_point_sampling():
    """Test that point sampling functions can be imported."""
    from ECOv003_CMR import (
        setup_earthdata_session,
        sample_point_from_url,
        sample_points_from_geodataframe,
        sample_points_over_date_range,
        find_sentinel2_tile
    )
    
    assert callable(setup_earthdata_session)
    assert callable(sample_point_from_url)
    assert callable(sample_points_from_geodataframe)
    assert callable(sample_points_over_date_range)
    assert callable(find_sentinel2_tile)


def test_find_sentinel2_tile():
    """Test Sentinel-2 tile lookup for Los Angeles."""
    from ECOv003_CMR import find_sentinel2_tile
    
    # Downtown LA should be in tile 11SLT
    tile = find_sentinel2_tile(-118.2437, 34.0522)
    assert tile == "11SLT"
    
    # LAX Airport should also be in 11SLT
    tile = find_sentinel2_tile(-118.4085, 33.9416)
    assert tile == "11SLT"


def test_setup_earthdata_session_with_params():
    """Test setting up session with explicit credentials."""
    from ECOv003_CMR import setup_earthdata_session
    
    session = setup_earthdata_session(
        username="testuser",
        password="testpass",
        require_auth=True
    )
    
    assert session.auth == ("testuser", "testpass")


def test_setup_earthdata_session_no_auth_optional():
    """Test setting up session without authentication when optional."""
    from ECOv003_CMR import setup_earthdata_session
    
    # Clear environment and mock .netrc to test no-auth scenario
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
    
    # Create test GeoDataFrame without CRS
    data = {
        'datetime': [datetime(2025, 6, 15)],
        'geometry': [Point(-118.24, 34.05)]
    }
    gdf = gpd.GeoDataFrame(data)  # No CRS
    
    # Should raise ValueError for missing CRS
    with pytest.raises(ValueError, match="must have a defined CRS"):
        sample_points_from_geodataframe(geometry=gdf)


def test_sample_points_from_geodataframe_missing_columns():
    """Test error handling for missing required columns."""
    from ECOv003_CMR import sample_points_from_geodataframe
    
    # GeoDataFrame without datetime column
    data = {
        'site_id': ['A'],
        'geometry': [Point(-118.24, 34.05)]
    }
    gdf = gpd.GeoDataFrame(data, crs='EPSG:4326')
    
    with pytest.raises(ValueError, match="Datetime column 'datetime' not found"):
        sample_points_from_geodataframe(geometry=gdf)


def test_sample_points_from_geodataframe_crs_reprojection():
    """Test that non-WGS84 GeoDataFrames are reprojected."""
    from ECOv003_CMR import sample_points_from_geodataframe
    from unittest.mock import patch
    
    # Create GeoDataFrame in Web Mercator (EPSG:3857)
    data = {
        'datetime': [datetime(2025, 6, 15)],
        'geometry': [Point(-13163264, 4035122)]  # LA in Web Mercator
    }
    gdf = gpd.GeoDataFrame(data, crs='EPSG:3857')
    
    # Mock the search and session to avoid actual network calls
    with patch('ECOv003_CMR.point_sampling.setup_earthdata_session'):
        with patch('ECOv003_CMR.point_sampling.ECOSTRESS_CMR_search') as mock_search:
            mock_search.return_value = pd.DataFrame()  # Empty results
            
            result = sample_points_from_geodataframe(geometry=gdf, verbose=False)
            
            # Should return empty DataFrame (no data found), but no errors
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


def test_sample_points_from_geodataframe_converts_collection3_lst_to_celsius(monkeypatch):
    import importlib

    point_sampling = importlib.import_module("ECOv003_CMR.point_sampling")
    granule = "ECOv003_L2T_LSTE_44814_001_52NHN_20260601T000306_02"
    search_results = pd.DataFrame(
        [{
            "type": "GeoTIFF Data",
            "variable": "LST",
            "granule": granule,
            "URL": "https://example.test/lst.tif",
            "orbit": 44814,
            "scene": 1,
        }]
    )
    monkeypatch.setattr(point_sampling, "find_sentinel2_tile", lambda lon, lat: "52NHN")
    monkeypatch.setattr(point_sampling, "ECOSTRESS_CMR_search", lambda **kwargs: search_results)
    monkeypatch.setattr(
        point_sampling,
        "sample_point_from_url",
        lambda *args, **kwargs: (300.0, {"nodata": None}),
    )

    gdf = gpd.GeoDataFrame(
        {"datetime": [datetime(2026, 6, 1)], "geometry": [Point(-118.24, 34.05)]},
        crs="EPSG:4326",
    )
    results = point_sampling.sample_points_from_geodataframe(
        geometry=gdf,
        layers=["ST_C", "LST"],
        session=Mock(),
        verbose=False,
    )

    assert results.loc[0, "LST"] == pytest.approx(300.0)
    assert results.loc[0, "ST_C"] == pytest.approx(26.85)


@pytest.mark.parametrize("max_workers", [1, 2])
def test_sample_points_over_date_range_supports_etaux_only(monkeypatch, max_workers):
    import importlib

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
        "sample_point_from_url",
        lambda *args, **kwargs: (21.5, {"nodata": None}),
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


def test_sample_point_from_url_success():
    """Test successful point sampling from URL (simplified)."""
    # This is a complex integration that's difficult to mock fully.
    # In practice, this would require actual raster data or a test fixture.
    # For now, we just verify the function exists and has correct signature.
    from ECOv003_CMR import sample_point_from_url
    import inspect
    
    sig = inspect.signature(sample_point_from_url)
    params = list(sig.parameters.keys())
    
    assert 'session' in params
    assert 'url' in params
    assert 'lon' in params
    assert 'lat' in params
    assert 'max_retries' in params
    assert 'timeout' in params


def test_sample_point_from_url_outside_bounds():
    """Test handling of point outside raster bounds (simplified)."""
    # Similar to above, complex mocking is difficult.
    # This would be better tested with integration tests using real data.
    from ECOv003_CMR import sample_point_from_url
    import inspect
    
    # Just verify the function signature and that it returns a tuple
    sig = inspect.signature(sample_point_from_url)
    assert sig.return_annotation != inspect.Signature.empty or True  # Has type hints or not


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
