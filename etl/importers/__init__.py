"""Importers by registry id, in the order `import all` runs them.

flood_10y needs the live admin_boundaries version (pilot city extents)."""

from etl.importers.admin import AdminBoundaries
from etl.importers.bis import BisCases
from etl.importers.cadastre_spatial import CadastreSpatial
from etl.importers.cadastre_text import CadastreText
from etl.importers.flood import Flood10y
from etl.importers.nature import (
    NatureHabitats,
    NatureMicroreserves,
    NatureMonuments,
    NatureProtectedAreas,
)
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
    "bis_cases": BisCases,
}
