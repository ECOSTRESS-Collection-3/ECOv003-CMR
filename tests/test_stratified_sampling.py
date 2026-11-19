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
    # Tile A has 8 granules (2 per quarter); Tile B has 4 granules; Tile C has 1 (below floor)
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
        mask, affine, crs, n_samples=20, cropland_mask=cropland, cropland_fraction_target=0.5, random_state=42
    )
    assert len(coords_crop) == 20
    crop_count = sum(1 for _, lat in coords_crop if lat > 39.88)
    assert crop_count == 10


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
