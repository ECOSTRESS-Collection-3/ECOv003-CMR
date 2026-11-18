"""Debug why LST sampling failed for a Collection 3 date."""
from ECOv003_CMR import setup_earthdata_session, ECOSTRESS_CMR_search

session = setup_earthdata_session()

# Search for LST on June 1, 2026
results = ECOSTRESS_CMR_search(
    product='L2T_LSTE',
    tile='52NHN',
    start_date='2026-06-01',
    end_date='2026-06-01'
)

print("June 1, 2026 LST granule:")
lst_files = results[results['variable'] == 'LST']
for _, row in lst_files.iterrows():
    print(f"  Granule: {row['granule']}")
    print(f"  URL: {row['URL']}")
    print(f"  Variable: {row['variable']}")

# Also check QC
qc_files = results[results['variable'] == 'QC']
print(f"\nQC files available: {len(qc_files)}")

print("\n" + "=" * 80)
print("If the LST file exists, but sampling returned NaN, possible reasons:")
print("  1. Pixel is masked (cloud, water, or quality flag)")
print("  2. Pixel value is nodata/fill value")
print("  3. Point falls outside valid data bounds")
print("  4. Pixel failed internal QC checks")
