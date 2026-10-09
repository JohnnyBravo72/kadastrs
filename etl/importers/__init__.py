"""Importers by registry id, in the order `import all` runs them."""

from etl.importers.admin import AdminBoundaries
from etl.importers.cadastre_spatial import CadastreSpatial
from etl.importers.cadastre_text import CadastreText
from etl.importers.varis import VarisAddresses

IMPORTERS = {
    "admin_boundaries": AdminBoundaries,
    "varis_addresses": VarisAddresses,
    "cadastre_spatial": CadastreSpatial,
    "cadastre_text": CadastreText,
}
