# Pinned TLS intermediates

Agency hosts that omit intermediate certificates from their TLS chain.
The ETL never disables verification (CLAUDE.md rule 9); it adds these
to the standard CA bundle instead (docs/decisions.md D11).

| File | Host | SHA-256 (DER) |
|---|---|---|
| `SectigoPublicServerAuthenticationCADVR36.crt` | deminimis.fm.gov.lv (D1 E1) | `8c54c334b66ba4e426772af4a3f9136c19a1aec729fdb28c535c07a5a4ef22e0` |

Source (AIA): `http://crt.sectigo.com/SectigoPublicServerAuthenticationCADVR36.crt`.
The PEM sibling is derived from the DER and used by OpenSSL/httpx.
