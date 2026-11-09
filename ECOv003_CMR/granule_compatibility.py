from glob import glob
from os.path import basename, join, normpath
from typing import List, Optional
from zipfile import ZipFile

from ECOv003_granules import ECOSTRESSGranule
from ECOv003_granules import open_granule as open_granule_from_library
from ECOv003_granules.L1CTRAD import L1CTRAD
from ECOv003_granules.L2TLSTE import L2TLSTE
from ECOv003_granules.L2TSTARS import L2TSTARS
from ECOv003_granules.L3TJET import L3TJET
from ECOv003_granules.L4TESI import L4TESI
from ECOv003_granules.L4TWUE import L4TWUE
from ECOv003_granules.tiled_granule import ECOSTRESSTiledGranule


class _Collection3GranuleMixin:
    @property
    def product(self) -> str:
        return self._PRODUCT_NAME

    @property
    def filenames(self) -> List[str]:
        if self.is_zip:
            with ZipFile(self.product_filename) as zip_file:
                return zip_file.namelist()

        return [basename(filename) for filename in glob(join(self.product_location, "*.tif"))]


class _L1CTRAD(_Collection3GranuleMixin, L1CTRAD):
    pass


class _L2TLSTE(_Collection3GranuleMixin, L2TLSTE):
    pass


class _L2TSTARS(_Collection3GranuleMixin, L2TSTARS):
    pass


class _L3TETAUX(_Collection3GranuleMixin, ECOSTRESSTiledGranule):
    _PRODUCT_NAME = "L3T_ETAUX"
    _PRIMARY_VARIABLE = "Ta"


class _L3TJET(_Collection3GranuleMixin, L3TJET):
    pass


class _L4TESI(_Collection3GranuleMixin, L4TESI):
    pass


class _L4TWUE(_Collection3GranuleMixin, L4TWUE):
    pass


COLLECTION_3_GRANULE_CLASSES = {
    "ECOv003_L1CT_RAD_": _L1CTRAD,
    "ECOv003_L2T_LSTE_": _L2TLSTE,
    "ECOv003_L2T_STARS_": _L2TSTARS,
    "ECOv003_L3T_ETAUX_": _L3TETAUX,
    "ECOv003_L3T_JET_": _L3TJET,
    "ECOv003_L4T_ESI_": _L4TESI,
    "ECOv003_L4T_WUE_": _L4TWUE,
}


def open_ECOSTRESS_granule(
        filename: str,
        **kwargs) -> Optional[ECOSTRESSGranule]:
    """Open Collection 3 granules with corrected filename and directory handling."""
    filename = normpath(filename)
    filename_base = basename(filename)
    for prefix, granule_class in COLLECTION_3_GRANULE_CLASSES.items():
        if filename_base.startswith(prefix):
            return granule_class(product_location=filename, **kwargs)

    return open_granule_from_library(filename, **kwargs)
