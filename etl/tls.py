"""TLS helpers: pin missing intermediate certificates (CLAUDE.md rule 9, D11).

`deminimis.fm.gov.lv` does not send its intermediate. Verification stays on;
the pinned DER is SHA-256-checked and loaded into the default SSL context.
"""

from __future__ import annotations

import hashlib
import ssl
from functools import lru_cache
from pathlib import Path

CERTS = Path(__file__).resolve().parents[1] / "infra" / "certs"
SECTIGO_DV_R36 = CERTS / "SectigoPublicServerAuthenticationCADVR36.crt"
SECTIGO_DV_R36_SHA256 = "8c54c334b66ba4e426772af4a3f9136c19a1aec729fdb28c535c07a5a4ef22e0"
SECTIGO_DV_R36_PEM = CERTS / "SectigoPublicServerAuthenticationCADVR36.pem"


def _check_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise RuntimeError(
            f"{path.name}: SHA-256 {digest} != pinned {expected}; refuse to trust it"
        )


def _pem_text() -> str:
    if not SECTIGO_DV_R36.is_file():
        raise FileNotFoundError(
            f"missing pinned intermediate {SECTIGO_DV_R36}; see infra/certs/README.md"
        )
    _check_sha256(SECTIGO_DV_R36, SECTIGO_DV_R36_SHA256)
    if SECTIGO_DV_R36_PEM.is_file():
        return SECTIGO_DV_R36_PEM.read_text(encoding="ascii")
    import base64

    b64 = base64.encodebytes(SECTIGO_DV_R36.read_bytes()).decode("ascii")
    return "-----BEGIN CERTIFICATE-----\n" + b64 + "-----END CERTIFICATE-----\n"


@lru_cache(maxsize=1)
def ssl_context_with_sectigo() -> ssl.SSLContext:
    """Default CA store plus the pinned Sectigo intermediate (D11)."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=_pem_text())
    return ctx
