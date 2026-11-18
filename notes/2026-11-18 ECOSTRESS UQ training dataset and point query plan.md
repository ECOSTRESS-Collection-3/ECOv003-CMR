# ECOSTRESS UQ Training Dataset & Point Query Plan

## Executive Overview
To improve uncertainty quantification (UQ), spatial downscaling of relative humidity, and temporal upscaling of evapotranspiration (ET) for transport map models—particularly in support of the Biosphere proposal—a comprehensive sampling plan has been designed to generate a large, non-tower ECOSTRESS training dataset.  

The plan transitions from the initial limited Collection 2 calibration/validation (cal/val) dataset to a globally representative, multi-temporal dataset of approximately **1,000,000 point samples** extracted across the life-of-mission record.

---

## Objectives & Motivation

- **Overcoming Dataset Constraints:** The original transport map exploration relied on arbitrary input UQ values derived from a small set of tower cal/val sites. Expanding to a non-tower point-query dataset across full ECOSTRESS acquisitions enables training on realistic, globally distributed input UQ values.
- **Proposal Integration:** The dataset supports broader ROSES Biosphere goals, specifically:
  - Enhancing spatial downscaling of relative humidity.
  - Improving temporal upscaling of ET and surface energy balance estimates.
  - Rigorously quantifying ET uncertainties.

---

## Dataset Scale & Coverage Targets

- **Sample Size:** Approximately 1,000,000 individual pixel point extractions.
- **Spatial & Climate Uniformity:** Equal representation across global biomes and climate zones achieved via UTM tile-based spatial normalization.
- **Temporal & Seasonal Balance:** Sampling distributed throughout the year to capture full seasonal variability across the ECOSTRESS mission duration.

---

## Stratified Sampling Methodology

The agreed-upon workflow for building the dataset follows a multi-stage stratified sampling pipeline:

``` 
[Full Clear-Sky ET Granules] 
             │
             ▼
[Group Granules by UTM Tile] ───► [Cap Selection to Minimum Clear-Sky Tile Count]
             │
             ▼
[Uniform Random Granule Selection per Tile]
             │
             ▼
[Calculate Per-Tile Pixel Sample Allocation] (Target 1M / Total Granules)
             │
             ▼
[Dynamic Random Pixel Sampling per Granule]
             │
             ▼
[Extract Output/Input Variables at Selected Coordinates] 
```

### 1. Granule Filtering & Tile Uniformity
1. **Clear-Sky Selection:** Filter the entire ECOSTRESS life-of-mission record for all clear-sky granules that include valid ET retrievals.
2. **UTM Tile Capping:** Tally available clear-sky granules per UTM tile. Set the maximum per-tile granule selection limit to the **minimum tile count** across all tiles. This ensures every arbitrary square on Earth carries equal weight, enforcing spatial and biome uniformity.

### 2. Granule & Pixel Distribution
1. **Uniform Granule Subsampling:** Take a random selection of granules for each UTM tile up to the established tile limit.
2. **Per-Tile Pixel Allocation:** Divide the overall target sample size (~1M) by the final count of selected granules to determine the required pixel sample size per granule.
3. **Intra-Granule Pixel Randomization:** Perform a spatially dispersed random sample of pixels within each selected granule scene.

> **Key Decision:** Pixel sampling locations are randomized independently for each acquisition ("rolling the dice" per scene) rather than using fixed, static pixel coordinates across repeated passes over the same tile.

### 3. Feature Extraction
1. **Point Query Extraction:** Extract all target output variables, input parameters, and surface energy balance estimates at each selected pixel point across the time series.

---

## Decision Timeline & Key Milestones

| Date | Forum | Key Outcome / Decision |
| :---: | :---: | :--- |
| **Apr 14, 2026** | UQ Meeting | Identified cal/val dataset size limitations; proposed synthetic/real UQ sampling across full life-of-mission products. |
| **Sep 16, 2026** | Maggie Meeting & Slack | Established non-tower target of **1M samples**; agreed on UTM tile coverage, seasonal distribution, and dynamic per-acquisition pixel randomization. |
| **Oct 1, 2026** | UQ Meeting | Formalized draft step-by-step sampling procedure and tile capping logic to enforce spatial/biome uniformity. |
| **Oct 9, 2026** | Maggie Meeting | Highlighted need to balance **agricultural vs. non-managed land** representation; set target completion for UQ meeting review. |

---

## Open Technical Questions

> - **Intra-Tile Sampling Algorithm:** Finalizing the specific randomized spatial dispersion method inside selected clear-sky scenes (evaluating uniform random vs. spatially constrained dispersion algorithms).
> - **Land Cover Balance:** Explicitly weighting or stratifying the pixel extraction to maintain proper proportion between managed agricultural land and natural/non-managed ecosystems.