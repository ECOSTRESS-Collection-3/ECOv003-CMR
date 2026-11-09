from posixpath import basename

from .granule_ID_from_filename import granule_ID_from_filename

def variable_from_filename(filename):
    """Extracts the variable name from an ECOSTRESS granule filename.

    Args:
        filename (str): The filename of the ECOSTRESS granule.

    Returns:
        str: The variable name extracted from the filename.
    """
    filename_base = basename(filename).split(".", 1)[0]
    granule_ID = str(granule_ID_from_filename(filename))

    if filename_base == granule_ID:
        return ""
    if not filename_base.startswith(f"{granule_ID}_"):
        raise ValueError(f"Filename does not start with the parsed granule ID: {filename}")

    return filename_base[len(granule_ID) + 1:]
