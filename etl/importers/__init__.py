"""Importers by registry id, in the order `import all` runs them.

flood_10y needs the live admin_boundaries version (pilot city extents). The
Phase 2c sources need none at import time; their links to the cadastre are SQL
functions of versions (ref.bis_links, ref.encumbrance_frozen_status)."""

from etl.importers.admin import AdminBoundaries
from etl.importers.bis import BisCases
from etl.importers.cadastre_spatial import CadastreSpatial
from etl.importers.cadastre_text import CadastreText
from etl.importers.encumbrances import AtisClassifier, CadastreEncumbrances, EncumbrancesFrozen
from etl.importers.flood import Flood10y
from etl.importers.nature import (
    NatureHabitats,
    NatureMicroreserves,
    NatureMonuments,
    NatureProtectedAreas,
)
from etl.importers.ownership import CadastreOwnership
from etl.importers.phase8b import (
    Deminimis,
    EisProcurement,
    EuProjects,
    FidFrozenProperty,
    VidRating,
)
from etl.importers.ur import FidSanctions, UrCompanies, UrInsolvency, UrSanctions
from etl.importers.varis import VarisAddresses

IMPORTERS = {
    "admin_boundaries": AdminBoundaries,
    "varis_addresses": VarisAddresses,
    "cadastre_spatial": CadastreSpatial,
    "cadastre_text": CadastreText,
    "flood_10y": Flood10y,
    "nature_protected_areas": NatureProtectedAreas,
    "nature_microreserves": NatureMicroreserves,
    "nature_monuments": NatureMonuments,
    "nature_habitats": NatureHabitats,
    "atis_classifier": AtisClassifier,
    "cadastre_encumbrances": CadastreEncumbrances,
    "encumbrances_frozen": EncumbrancesFrozen,
    "bis_cases": BisCases,
    "ur_companies": UrCompanies,
    "ur_insolvency": UrInsolvency,
    "ur_sanctions": UrSanctions,
    "fid_sanctions": FidSanctions,
    "cadastre_ownership": CadastreOwnership,
    "vid_rating": VidRating,
    "deminimis": Deminimis,
    "eu_projects": EuProjects,
    "eis_procurement": EisProcurement,
    "fid_frozen_property": FidFrozenProperty,
}
