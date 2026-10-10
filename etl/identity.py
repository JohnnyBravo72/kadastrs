"""Version identity (rule E7; docs/data-sources.md §5.4).

Every fetched file becomes a FileRecord. The version checksum covers the file
contents only (never run dates or CKAN metadata), so the same data always
maps to the same dataset_version.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime


def canonical_sha256(obj) -> str:
    data = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass
class MemberRecord:
    name: str
    crc32: int
    size: int
    sha256: str
    path: str | None = None  # relative to the version's raw dir


@dataclass
class FileRecord:
    role: str
    resource_id: str
    url: str
    last_modified: str | None
    size: int | None
    sha256: str | None = None  # whole files
    path: str | None = None  # relative to the version's raw dir
    members: list[MemberRecord] = field(default_factory=list)  # Range-fetched zips
    central_directory_sha256: str | None = None
    range_supported: bool | None = None
    # National files cut to the pilot (BIS): SHA-256 of the canonical pilot rows.
    # It is the version identity, so a change elsewhere in Latvia makes no version.
    pilot_sha256: str | None = None

    def content_identity(self) -> dict:
        if self.pilot_sha256 is not None:
            return {"role": self.role, "pilot_sha256": self.pilot_sha256}
        if self.sha256 is not None:
            return {"role": self.role, "sha256": self.sha256}
        return {
            "role": self.role,
            "resource_id": self.resource_id,
            "members": sorted(
                [
                    {"name": m.name, "crc32": m.crc32, "size": m.size, "sha256": m.sha256}
                    for m in self.members
                ],
                key=lambda x: x["name"],
            ),
        }

    def remote_fingerprint(self) -> dict | None:
        """Only for Range-fetched zips: what can be known without fetching members."""
        if self.central_directory_sha256 is None:
            return None
        return {
            "resource_id": self.resource_id,
            "central_directory_sha256": self.central_directory_sha256,
            "last_modified": self.last_modified,
            "size": self.size,
        }

    def to_json(self) -> dict:
        return asdict(self)


def version_checksum(files: list[FileRecord]) -> str:
    return "sha256:" + canonical_sha256(
        sorted((f.content_identity() for f in files), key=lambda x: x["role"])
    )


def fingerprints(files: list[FileRecord]) -> list[dict] | None:
    fps = [f.remote_fingerprint() for f in files]
    if any(fp is None for fp in fps):
        return None
    return sorted(fps, key=lambda x: x["resource_id"])


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
