# ECOSTRESS Collection 3 CMR Concept IDs

## How Concept IDs Were Obtained

NASA Common Metadata Repository (CMR) Collection Concept IDs uniquely identify each ECOSTRESS Collection 3 product dataset in the LP DAAC archive (`LPCLOUD`). They were resolved programmatically using each product's Digital Object Identifier (DOI) via the following process:

1. **Map Collection 3 DOIs:** Each active ECOSTRESS Collection 3 (`.003`) product code was paired with its official NASA LP DAAC DOI (for example, `10.5067/ECOSTRESS/ECO_L2T_LSTE.003`). Separate Collection 2 meteorological, soil moisture, and surface energy balance products (`L3T_MET`, `L3T_SM`, and `L3T_SEB`) were excluded because they were discontinued in Collection 3 and consolidated into `L3T_ETAUX`.
2. **Query the NASA CMR Collections API:** Using `concept_IDs.py` (and `ECOv003_CMR.concept_ID_from_DOI()`), an HTTP `GET` request was issued for each DOI against the CMR Collections endpoint:
   ```text
   https://cmr.earthdata.nasa.gov/search/collections.json?doi=<DOI>
   ```
3. **Extract the Concept ID:** From the JSON response payload (`feed.entry[0].id`), each collection's `-LPCLOUD` identifier was extracted, verified for a `SUCCESS` status, and exported to `ecostress_collection3_concept_ids.csv`.
4. **Codify in Package Constants:** The verified Concept IDs were recorded in `ECOv003_CMR/constants.py` under `CONCEPT_IDS` so CMR search and download functions resolve product codes offline without extra collection-lookup round trips.

## ECOSTRESS Collection 3 Concept ID Table

| Product | Level | Collection | DOI | CMR Concept ID | Status / Notes |
|---|---|---|---|---|---|
| `L1CT_RAD` | Level 1 | 3 | `10.5067/ECOSTRESS/ECO_L1CT_RAD.003` | `C4142244484-LPCLOUD` | Active (calibrated at-sensor radiance) |
| `L2T_LSTE` | Level 2 | 3 | `10.5067/ECOSTRESS/ECO_L2T_LSTE.003` | `C3998139651-LPCLOUD` | Active (land surface temperature & emissivity) |
| `L2T_STARS` | Level 2 | 3 | `10.5067/ECOSTRESS/ECO_L2T_STARS.003` | `C3998139658-LPCLOUD` | Active (NDVI & surface albedo priors) |
| `L3T_ETAUX` | Level 3 | 3 | `10.5067/ECOSTRESS/ECO_L3T_ETAUX.003` | `C4057520953-LPCLOUD` | New in C3 (replaces `L3T_MET`, `L3T_SM`, `L3T_SEB`) |
| `L3T_JET` | Level 3 | 3 | `10.5067/ECOSTRESS/ECO_L3T_JET.003` | `C4057232489-LPCLOUD` | Active (JPL evapotranspiration product) |
| `L4T_ESI` | Level 4 | 3 | `10.5067/ECOSTRESS/ECO_L4T_ESI.003` | `C4057232495-LPCLOUD` | Active (Evaporative Stress Index) |
| `L4T_WUE` | Level 4 | 3 | `10.5067/ECOSTRESS/ECO_L4T_WUE.003` | `C4057232498-LPCLOUD` | Active (Water Use Efficiency) |