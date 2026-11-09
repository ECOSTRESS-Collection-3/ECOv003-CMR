import csv
import logging
import requests
from typing import Dict, Tuple

# Base URL for NASA Common Metadata Repository (CMR) Search API
CMR_SEARCH_URL = "https://cmr.earthdata.nasa.gov/search/"

# Configure logging format and level
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s %(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ECOSTRESS Collection 3 Product DOIs (.003)
# Discontinued in C3: L3T_MET, L3T_SM, L3T_SEB
# New in C3: L3T_ETAUX
COLLECTION_3_DOIS: Dict[str, str] = {
    "L1CT_RAD": "10.5067/ECOSTRESS/ECO_L1CT_RAD.003",
    "L2T_LSTE": "10.5067/ECOSTRESS/ECO_L2T_LSTE.003",
    "L2T_STARS": "10.5067/ECOSTRESS/ECO_L2T_STARS.003",
    "L3T_ETAUX": "10.5067/ECOSTRESS/ECO_L3T_ETAUX.003",
    "L3T_JET": "10.5067/ECOSTRESS/ECO_L3T_JET.003",
    "L4T_ESI": "10.5067/ECOSTRESS/ECO_L4T_ESI.003",
    "L4T_WUE": "10.5067/ECOSTRESS/ECO_L4T_WUE.003"
}


def query_concept_id_from_doi(
    doi: str,
    cmr_search_url: str = CMR_SEARCH_URL,
    timeout: int = 10
) -> Tuple[str, str]:
    """
    Queries the NASA CMR API to obtain the Concept ID for a given DOI.

    Parameters:
        doi (str): Digital Object Identifier to search.
        cmr_search_url (str): Base CMR search endpoint URL.
        timeout (int): Request timeout in seconds.

    Returns:
        Tuple[str, str]: A tuple of (concept_id, status) where status indicates success or error.
    """
    url = f"{cmr_search_url}collections.json?doi={doi}"
    try:
        response = requests.get(url, timeout=timeout)

        if response.status_code != 200:
            logger.warning(f"HTTP Error {response.status_code} for DOI: {doi}")
            return "", f"HTTP_{response.status_code}"

        json_data = response.json()
        entries = json_data.get("feed", {}).get("entry", [])

        if not entries:
            logger.warning(f"No collection entries found for DOI: {doi}")
            return "", "NOT_FOUND"

        concept_id = entries[0].get("id", "")
        if concept_id:
            logger.info(f"Successfully retrieved Concept ID '{concept_id}' for DOI: {doi}")
            return concept_id, "SUCCESS"
        else:
            logger.warning(f"Concept ID field missing in response for DOI: {doi}")
            return "", "MISSING_CONCEPT_ID"

    except requests.exceptions.RequestException as req_err:
        logger.error(f"Network error querying CMR for DOI {doi}: {req_err}")
        return "", "REQUEST_FAILED"
    except Exception as err:
        logger.error(f"Unexpected error parsing response for DOI {doi}: {err}")
        return "", "PARSING_ERROR"


def export_ecostress_c3_concept_ids(
    output_filename: str = "ecostress_collection3_concept_ids.csv"
) -> None:
    """
    Queries Concept IDs for all ECOSTRESS Collection 3 products and exports results to CSV.
    """
    logger.info("Starting CMR search for ECOSTRESS Collection 3 products...")

    results = []

    for product_code, doi in COLLECTION_3_DOIS.items():
        logger.info(f"Querying product '{product_code}' (DOI: {doi})...")
        concept_id, status = query_concept_id_from_doi(doi)

        results.append({
            "product": product_code,
            "collection": 3,
            "doi": doi,
            "concept_id": concept_id,
            "status": status
        })

    # Write output to CSV file
    fieldnames = ["product", "collection", "doi", "concept_id", "status"]

    try:
        with open(output_filename, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

        logger.info(f"Export complete. Results written to '{output_filename}'.")
    except IOError as io_err:
        logger.error(f"Failed to write CSV file '{output_filename}': {io_err}")


if __name__ == "__main__":
    export_ecostress_c3_concept_ids()