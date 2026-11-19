from typing import Dict
import requests
import logging

from .constants import CMR_SEARCH_URL, COLLECTION_3_DOIS

logger = logging.getLogger(__name__)


def concept_ID_from_DOI(
        DOI: str,
        CMR_search_URL: str = CMR_SEARCH_URL) -> str:
    """
    Find the concept ID for a given DOI.

    Parameters:
    DOI (str): The DOI to search for.

    Returns:
    str: The concept ID for the given DOI.
    """
    URL = f"{CMR_search_URL}collections.json?doi={DOI}"
    response = requests.get(URL)

    if response.status_code != 200:
        raise ValueError(f"Error: {response.status_code} - {response.text}")

    try:
        concept_ID = response.json()['feed']['entry'][0]['id']
    except Exception as e:
        logger.exception(e)
        logger.error(response.text)
        raise ValueError(f"Error: Could not find concept ID for DOI: {DOI}")

    return concept_ID


def lookup_collection_3_concept_IDs(
        CMR_search_URL: str = CMR_SEARCH_URL) -> Dict[str, str]:
    """Query NASA CMR in bulk to verify or refresh all Collection 3 Concept IDs."""
    return {
        product: concept_ID_from_DOI(doi, CMR_search_URL=CMR_search_URL)
        for product, doi in COLLECTION_3_DOIS.items()
    }
