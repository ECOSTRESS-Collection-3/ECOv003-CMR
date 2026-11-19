import importlib
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from ECOv003_CMR.point_sampling import (
    LAYER_MAPPING,
    sample_points_from_granule,
    summarize_point_samples,
)
from ECOv003_CMR.stratified_sampling import (
    compute_per_granule_quota,
    find_clear_sky_et_granules,
    sample_granule_coordinates,
    select_stratified_granules,
)


def test_expanded_layer_mapping_includes_jet_and_uq_layers():
    assert LAYER_MAPPING["PTJPLSMinst"] == ("L3T_JET", "PTJPLSMinst")
    assert LAYER_MAPPING["ETdaily"] == ("L3T_JET", "ETdaily")
    assert LAYER_MAPPING["ETuncertainty"] == ("L3T_JET", "ETuncertainty")
    assert LAYER_MAPPING["PTJPLSMcanopy"] == ("L3T_JET", "PTJPLSMcanopy")
    assert LAYER_MAPPING["NDVI-UQ"] == ("L2T_STARS", "NDVI-UQ")
    assert LAYER_MAPPING["albedo-UQ"] == ("L2T_STARS", "albedo-UQ")
    assert LAYER_MAPPING["view_zenith"] == ("L2T_LSTE", "view_zenith")
    assert LAYER_MAPPING["ESI"] == ("L4T_ESI", "ESI")
    assert LAYER_MAPPING["WUE"] == ("L4T_WUE", "WUE")


def test_select_stratified_granules_caps_and_balances_seasons():
    rows = []
    for q in range(1, 5):
        month = f"{(q - 1) * 3 + 1:02d}"
        for i in range(2):
            rows.append({"granule": f"G_A_{q}_{i}", "tile": "11SLT", "date_str": f"2026{month}05", "quarter": q})
        rows.append({"granule": f"G_B_{q}_0", "tile": "11SPS", "date_str": f"2026{month}10", "quarter": q})
    rows.append({"granule": "G_C_1_0", "tile": "10SGF", "date_str": "20260115", "quarter": 1})

    df = pd.DataFrame(rows)
    selected, n_cap = select_stratified_granules(df, min_granules_floor=4, seasonal_balance=True, random_state=7)

    assert n_cap == 4
    assert set(selected["tile"].unique()) == {"11SLT", "11SPS"}
    assert len(selected[selected["tile"] == "11SLT"]) == 4
    assert set(selected[selected["tile"] == "11SLT"]["quarter"]) == {1, 2, 3, 4}


def test_compute_per_granule_quota():
    quota_k, candidate_n = compute_per_granule_quota(num_selected_granules=1000, target_total_samples=1_000_000, oversample_factor=1.2)
    assert quota_k == 1000
    assert candidate_n == 1200


def test_sample_granule_coordinates_dispersion_and_cropland_balance():
    mask = np.ones((24, 24), dtype=bool)
    cropland = np.zeros((24, 24), dtype=bool)
    cropland[:12, :] = True
    affine = from_origin(-120.0, 40.0, 0.01, 0.01)
    crs = CRS.from_epsg(4326)

    coords_grid = sample_granule_coordinates(mask, affine, crs, n_samples=36, strategy="stratified_grid", grid_divisions=6, random_state=42)
    assert len(coords_grid) == 36
    assert len(set(coords_grid)) == 36

    coords_crop = sample_granule_coordinates(
        mask,
        affine,
        crs,
        n_samples=20,
        strategy="stratified_grid",
        cropland_mask=cropland,
        cropland_fraction_target=0.5,
        random_state=42,
    )
    assert len(coords_crop) == 20
    crop_count = sum(1 for _, lat in coords_crop if lat > 39.88)
    assert crop_count == 10


def test_find_clear_sky_et_granules_uses_umm_join_and_lazy_pattern_resolution(monkeypatch):
    strat_mod = importlib.import_module("ECOv003_CMR.stratified_sampling")
    umm_calls = []
    pattern_calls = []

    def mock_umm(**kwargs):
        umm_calls.append(kwargs)
        cid = kwargs["concept_ID"]
        if cid == "C4057232489-LPCLOUD":  # L3T_JET
            assert kwargs["max_cloud_cover"] is None
            return pd.DataFrame(
                [
                    {
                        "granule": "ECOv003_L3T_JET_44814_001_11SLT_20260601T000306_01",
                        "product": "L3T_JET",
                        "orbit": 44814,
                        "scene": 1,
                        "tile": "11SLT",
                        "timestamp": "20260601T000306",
                        "date_str": "20260601",
                        "time_start": "2026-06-01T00:03:06Z",
                        "cloud_cover": None,
                    },
                    {
                        "granule": "ECOv003_L3T_JET_44900_002_52NHN_20260605T120000_01",
                        "product": "L3T_JET",
                        "orbit": 44900,
                        "scene": 2,
                        "tile": "52NHN",
                        "timestamp": "20260605T120000",
                        "date_str": "20260605",
                        "time_start": "2026-06-05T12:00:00Z",
                        "cloud_cover": None,
                    },
                ]
            )
        if cid == "C3998139651-LPCLOUD":  # L2T_LSTE (only 11SLT passes cloud_cover <= 20)
            assert kwargs["max_cloud_cover"] == 20.0
            return pd.DataFrame(
                [
                    {
                        "granule": "ECOv003_L2T_LSTE_44814_001_11SLT_20260601T000306_02",
                        "product": "L2T_LSTE",
                        "orbit": 44814,
                        "scene": 1,
                        "tile": "11SLT",
                        "timestamp": "20260601T000306",
                        "date_str": "20260601",
                        "time_start": "2026-06-01T00:03:06Z",
                        "cloud_cover": 7.5,
                    }
                ]
            )
        return pd.DataFrame()

    def mock_patterns(**kwargs):
        pattern_calls.append(kwargs)
        cid = kwargs["concept_ID"]
        prod_map = {
            "C4057232489-LPCLOUD": ("L3T_JET", "PTJPLSMinst"),
            "C3998139651-LPCLOUD": ("L2T_LSTE", "LST"),
            "C4057520953-LPCLOUD": ("L3T_ETAUX", "Ta"),
            "C3998139658-LPCLOUD": ("L2T_STARS", "NDVI"),
        }
        prod, var = prod_map[cid]
        if prod == "L2T_STARS":
            gid = "ECOv003_L2T_STARS_11SLT_20260601_01"
        else:
            gid = f"ECOv003_{prod}_44814_001_11SLT_20260601T000306_01"
        return [{"URL": f"https://example.test/{gid}_{var}.tif", "cloud_cover": 7.5}]

    monkeypatch.setattr(strat_mod, "search_granule_catalog_umm", mock_umm)
    monkeypatch.setattr(strat_mod, "search_granules_by_name_patterns", mock_patterns)

    tiles = ["11SLT", "11SPS", "52NHN"]
    # When resolve_urls=False, returns lightweight joined catalog with 0 pattern calls
    catalog_only = find_clear_sky_et_granules(
        tiles=tiles,
        start_date="2026-06-01",
        end_date="2026-06-06",
        max_cloud_cover=20.0,
        resolve_urls=False,
        regional_batch_threshold=2,
        verbose=False,
    )
    assert len(umm_calls) == 2
    assert len(pattern_calls) == 0
    assert len(catalog_only) == 1
    assert catalog_only.iloc[0]["tile"] == "11SLT"
    assert catalog_only.iloc[0]["cloud_cover"] == 7.5

    # When resolve_urls=True, resolves all 4 products via pattern batches
    full_df = find_clear_sky_et_granules(
        tiles=tiles,
        start_date="2026-06-01",
        end_date="2026-06-06",
        max_cloud_cover=20.0,
        resolve_urls=True,
        regional_batch_threshold=2,
        verbose=False,
    )
    assert len(pattern_calls) == 4
    assert len(full_df) == 1
    assert set(full_df.iloc[0]["variable_urls"].keys()) == {"PTJPLSMinst", "LST", "Ta", "NDVI"}


def test_build_stratified_dataset_catalog_cache_and_quota_refill(monkeypatch, tmp_path):
    builder_mod = importlib.import_module("ECOv003_CMR.stratified_dataset_builder")

    et_path = tmp_path / "et.tif"
    lst_path = tmp_path / "lst.tif"
    affine = from_origin(-120.0, 40.0, 0.01, 0.01)

    # Create a 20x20 grid where PTJPLSMinst is valid everywhere, but LST has NaNs in top half
    et_arr = np.full((20, 20), 350.0, dtype="float32")
    lst_arr = np.full((20, 20), 300.15, dtype="float32")
    lst_arr[:12, :] = np.nan

    for path, arr in [(et_path, et_arr), (lst_path, lst_arr)]:
        with MemoryFile() as mem:
            with mem.open(
                driver="GTiff",
                height=20,
                width=20,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=affine,
                nodata=np.nan,
            ) as ds:
                ds.write(arr, 1)
            path.write_bytes(mem.read())

    search_calls = []

    def mock_find_granules(**kwargs):
        search_calls.append(kwargs)
        return pd.DataFrame(
            [
                {
                    "granule": "ECOv003_L3T_JET_44814_001_11SLT_20260601T000306_01",
                    "orbit": 44814,
                    "scene": 1,
                    "tile": "11SLT",
                    "timestamp": "20260601T000306",
                    "date_str": "20260601",
                    "quarter": 2,
                    "cloud_cover": 2.0,
                    "variable_urls": {"PTJPLSMinst": str(et_path), "LST": str(lst_path)},
                }
            ]
        )

    monkeypatch.setattr(builder_mod, "find_clear_sky_et_granules", mock_find_granules)

    out1 = tmp_path / "run1"
    shared_catalog = str(tmp_path / "shared_catalog.parquet")
    summary1 = builder_mod.build_stratified_dataset(
        output_dir=str(out1),
        start_date="2026-06-01",
        end_date="2026-06-07",
        tiles=["11SLT"],
        target_total_samples=20,
        min_granules_floor=1,
        layers=["PTJPLSMinst", "ST_C"],
        catalog_path=shared_catalog,
        batch_size=1,
        max_concurrent_streams=4,
        session=Mock(),
        verbose=False,
    )
    assert len(search_calls) == 1
    assert summary1["total_samples"] == 20

    # Second run with refresh_catalog=False should hit cached catalog with 0 CMR searches
    out2 = tmp_path / "run2"
    summary2 = builder_mod.build_stratified_dataset(
        output_dir=str(out2),
        start_date="2026-06-01",
        end_date="2026-06-07",
        tiles=["11SLT"],
        target_total_samples=15,
        min_granules_floor=1,
        layers=["PTJPLSMinst", "ST_C"],
        catalog_path=shared_catalog,
        refresh_catalog=False,
        session=Mock(),
        verbose=False,
    )
    assert len(search_calls) == 1
    assert summary2["total_samples"] == 15


def test_sample_points_from_granule_vectorized_and_summary(tmp_path):
    lst_path = tmp_path / "lst.tif"
    et_path = tmp_path / "et.tif"

    for path, val in [(lst_path, 300.15), (et_path, 410.5)]:
        with MemoryFile() as mem:
            with mem.open(
                driver="GTiff", height=10, width=10, count=1, dtype="float32",
                crs="EPSG:4326", transform=from_origin(-120.0, 40.0, 0.1, 0.1)
            ) as ds:
                ds.write(np.full((10, 10), val, dtype="float32"), 1)
            path.write_bytes(mem.read())

    coords = [(-119.95, 39.95), (-119.55, 39.55)]
    df = sample_points_from_granule(
        variable_urls={"LST": str(lst_path), "PTJPLSMinst": str(et_path)},
        coords=coords,
        layers=["ST_C", "PTJPLSMinst"],
        use_vsicurl=True,
    )
    assert len(df) == 2
    assert np.allclose(df["ST_C"], 27.0)
    assert np.allclose(df["PTJPLSMinst"], 410.5)

    summary = summarize_point_samples(df, layers=["ST_C", "PTJPLSMinst"])
    assert (summary["completeness_pct"] == 100.0).all()
