"""data.gov.lv CKAN API. Resource URLs are resolved from package_show on every
run (rule E1): filenames carry export dates, so URLs are never stored."""

from dataclasses import dataclass
from datetime import datetime

import httpx

USER_AGENT = "kadastrs-etl/0.1 (+https://github.com/JohnnyBravo72/kadastrs)"


def http_client(**kwargs) -> httpx.Client:
    """TLS verification stays on (CLAUDE.md rule 9)."""
    kwargs.setdefault("timeout", httpx.Timeout(60.0, read=600.0))
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, **kwargs)


@dataclass(frozen=True)
class Resource:
    dataset: str  # CKAN package id or name as configured
    dataset_id: str  # CKAN package uuid
    id: str
    name: str
    url: str
    last_modified: datetime | None
    size: int | None
    licence: str | None


class Ckan:
    def __init__(self, client: httpx.Client, api: str):
        self.client = client
        self.api = api.rstrip("/") + "/"
        self._packages: dict[str, dict] = {}

    def package(self, dataset: str) -> dict:
        if dataset not in self._packages:
            resp = self.client.get(self.api + "package_show", params={"id": dataset})
            resp.raise_for_status()
            body = resp.json()
            if not body.get("success"):
                raise RuntimeError(f"package_show {dataset}: {body.get('error')}")
            self._packages[dataset] = body["result"]
        return self._packages[dataset]

    def resource(self, dataset: str, resource_id: str) -> Resource:
        pkg = self.package(dataset)
        for res in pkg["resources"]:
            if res["id"] == resource_id:
                lm = res.get("last_modified") or res.get("metadata_modified")
                return Resource(
                    dataset=dataset,
                    dataset_id=pkg["id"],
                    id=res["id"],
                    name=res.get("name") or "",
                    url=res["url"],
                    last_modified=datetime.fromisoformat(lm) if lm else None,
                    size=int(res["size"]) if res.get("size") not in (None, "") else None,
                    licence=pkg.get("license_id"),
                )
        raise LookupError(
            f"resource {resource_id} not in {dataset}: re-verify (docs/data-sources.md, rule 2)"
        )

    def find_resource(self, datasets: list[str], resource_id: str) -> Resource:
        """The resource in whichever of the source's datasets lists it (BIS spans two)."""
        for dataset in datasets:
            pkg = self.package(dataset)
            if any(r["id"] == resource_id for r in pkg["resources"]):
                return self.resource(dataset, resource_id)
        raise LookupError(
            f"resource {resource_id} not in {datasets}: re-verify (docs/data-sources.md, rule 2)"
        )
