# ECOSTRESS Collection 3 Examples

These scripts demonstrate using the `ECOv003-CMR` package to search or sample Collection 3 data. Install the package and configure NASA Earthdata authentication before running examples that fetch data:

```bash
python -m pip install ECOv003-CMR
```

See the top-level [README](../README.md#nasa-earthdata-authentication) for `.netrc` and environment-variable setup. The examples use June 2026 dates, when representative Collection 3 data is available.

## Point sampling

### `point_sampling_demo.py`

Samples `LST` from `L2T_LSTE` and `NDVI` / `albedo` from `L2T_STARS` at a single Los Angeles coordinate. It searches CMR for June 2026, samples each returned raster, and reports LST in both Kelvin and Celsius.

```bash
python examples/point_sampling_demo.py
```

### `geodataframe_sampling_demo.py`

Demonstrates the recommended date-range workflow with a GeoDataFrame of several points. It uses the default layers (`ST_C`, `NDVI`, and `albedo`) and reports results and summary statistics.

```bash
python examples/geodataframe_sampling_demo.py
```

### `csv_to_geodataframe_demo.py`

Demonstrates loading latitude/longitude and site metadata from a CSV, converting the rows into a GeoDataFrame, sampling all available acquisitions for the configured date range, and saving enriched results.

```bash
python examples/csv_to_geodataframe_demo.py
```

## Authentication

The examples access protected ECOSTRESS data and require NASA Earthdata credentials. Configure `~/.netrc` for `urs.earthdata.nasa.gov`, or set `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`. Ensure you have authorized the applicable LP DAAC applications.

## Sampling behavior

The examples call the public functions exported from `ECOv003_CMR`. `sample_points_over_date_range()` searches for available products in the requested period; `sample_points_from_geodataframe()` is for points with known datetimes. The supported sampling layer-to-product mapping is documented in the top-level [README](../README.md#available-sampling-layers).

Sampling reads raster responses into memory and extracts pixel values without creating local raster files. For downloads, use `ECOv003-download` or `download_ECOSTRESS_granule()`.
