import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from ECOv003_CMR import sample_points_over_date_range

sites_df = gpd.GeoDataFrame(
    {
        "site_id": ["downtown_la", "lax_airport", "pasadena"],
        "site_name": ["Downtown LA", "LAX Airport", "Pasadena"],
        "geometry": [
            Point(-118.2437, 34.0522),
            Point(-118.4085, 33.9416),
            Point(-118.1445, 34.1478),
        ],
    },
    crs="EPSG:4326",
)

print(f"Loaded {len(sites_df)} sites")
print(f"Site columns: {sites_df.columns.tolist()}\n")

print("=" * 60)
print("Testing: Multi-site Collection 3 point sampling")
print("=" * 60)
result = sample_points_over_date_range(
    geometry=sites_df,
    start_date="2026-06-01",
    end_date="2026-06-07",
    layers=['ST_C', 'emissivity', 'NDVI', 'albedo', 'Ta_C', 'RH', 'SM']
)

print(f"\nResult shape: {result.shape}")
print(f"Available columns: {result.columns.tolist()}")
if not result.empty:
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    pd.set_option('display.precision', 4)

    result_display = result.copy()
    if 'timestamp' in result_display.columns:
        result_display['date'] = result_display['timestamp'].str[:8]
        cols = ['timestamp', 'date'] + [c for c in result_display.columns if c not in ['timestamp', 'date']]
        result_display = result_display[cols]
    print(result_display.to_string(index=False))
