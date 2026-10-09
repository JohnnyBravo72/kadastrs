"""Downloads: whole files, and single members of remote zips via HTTP Range.

Range-fetched members are identified as documented in docs/data-sources.md §5.4.
If the server ignores Range (answers 200), the whole zip is downloaded and the
same members are read locally; `range_supported` is then False and the
importer records `range_unsupported` in import_log.
"""

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

import httpx

CHUNK = 1 << 20


@dataclass(frozen=True)
class FileInfo:
    path: Path
    size: int
    sha256: str


def download(client: httpx.Client, url: str, dest: Path) -> FileInfo:
    """Stream `url` to `dest`, returning its size and SHA-256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    h, n = hashlib.sha256(), 0
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(CHUNK):
                f.write(chunk)
                h.update(chunk)
                n += len(chunk)
    return FileInfo(dest, n, h.hexdigest())


@dataclass(frozen=True)
class Member:
    name: str
    method: int  # 0 stored, 8 deflate
    crc32: int
    csize: int
    usize: int
    local_offset: int


class ZipFormatError(ValueError):
    pass


def parse_central_directory(cd: bytes) -> list[Member]:
    members, i = [], 0
    while i < len(cd):
        if cd[i : i + 4] != b"PK\x01\x02":
            raise ZipFormatError(f"bad central directory entry at {i}")
        method = struct.unpack("<H", cd[i + 10 : i + 12])[0]
        crc, csize, usize = struct.unpack("<III", cd[i + 16 : i + 28])
        n, m, k = struct.unpack("<HHH", cd[i + 28 : i + 34])
        local = struct.unpack("<I", cd[i + 42 : i + 46])[0]
        if 0xFFFFFFFF in (csize, usize, local):
            raise ZipFormatError("zip64 entries are not supported (none expected, §5.3)")
        name = cd[i + 46 : i + 46 + n].decode("utf-8")
        members.append(Member(name, method, crc, csize, usize, local))
        i += 46 + n + m + k
    return members


def _eocd(tail: bytes) -> tuple[int, int]:
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0:
        raise ZipFormatError("end of central directory not found")
    cd_size, cd_offset = struct.unpack("<II", tail[pos + 12 : pos + 20])
    return cd_size, cd_offset


class RemoteZip:
    """A zip on a web server, read member by member."""

    TAIL = 65536

    def __init__(self, client: httpx.Client, url: str, workdir: Path):
        self.client = client
        self.url = url
        self.workdir = workdir
        self.local_copy: Path | None = None  # set when Range is not supported
        self.range_supported = True
        self.total_size: int | None = None
        self.central_directory: bytes = b""
        self.members: list[Member] = []

    # -- byte access ---------------------------------------------------------

    def _range(self, start: int, end: int) -> bytes:
        if self.local_copy is not None:
            with open(self.local_copy, "rb") as f:
                f.seek(start)
                return f.read(end - start + 1)
        resp = self.client.get(self.url, headers={"Range": f"bytes={start}-{end}"})
        resp.raise_for_status()
        if resp.status_code != 206:
            raise ZipFormatError(f"expected 206 for a range request, got {resp.status_code}")
        return resp.content

    def _stream_range(self, start: int, end: int):
        if self.local_copy is not None:
            with open(self.local_copy, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk
            return
        with self.client.stream("GET", self.url, headers={"Range": f"bytes={start}-{end}"}) as r:
            r.raise_for_status()
            if r.status_code != 206:
                raise ZipFormatError(f"expected 206 for a range request, got {r.status_code}")
            yield from r.iter_bytes(CHUNK)

    # -- open ------------------------------------------------------------------

    def open(self) -> RemoteZip:
        with self.client.stream("GET", self.url, headers={"Range": f"bytes=-{self.TAIL}"}) as r:
            r.raise_for_status()
            if r.status_code == 206:
                tail = r.read()
                self.total_size = int(r.headers["Content-Range"].rsplit("/", 1)[1])
            else:
                # Server ignored Range: keep the full download and read locally.
                self.range_supported = False
                self.workdir.mkdir(parents=True, exist_ok=True)
                self.local_copy = self.workdir / ("full_" + Path(httpx.URL(self.url).path).name)
                with open(self.local_copy, "wb") as f:
                    for chunk in r.iter_bytes(CHUNK):
                        f.write(chunk)
                self.total_size = self.local_copy.stat().st_size
                tail = self._range(max(0, self.total_size - self.TAIL), self.total_size - 1)
        cd_size, cd_offset = _eocd(tail)
        self.central_directory = self._range(cd_offset, cd_offset + cd_size - 1)
        self.members = parse_central_directory(self.central_directory)
        return self

    @property
    def central_directory_sha256(self) -> str:
        return hashlib.sha256(self.central_directory).hexdigest()

    # -- members ---------------------------------------------------------------

    def extract(self, m: Member, dest: Path) -> str:
        """Decompress member `m` to `dest`; verify CRC-32 and size; return SHA-256."""
        header = self._range(m.local_offset, m.local_offset + 29)
        if header[:4] != b"PK\x03\x04":
            raise ZipFormatError(f"bad local header for {m.name}")
        n, k = struct.unpack("<HH", header[26:30])
        start = m.local_offset + 30 + n + k
        if m.method not in (0, 8):
            raise ZipFormatError(f"{m.name}: compression method {m.method} not supported")
        dec = zlib.decompressobj(-15) if m.method == 8 else None
        crc, size, h = 0, 0, hashlib.sha256()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            if m.csize:
                for chunk in self._stream_range(start, start + m.csize - 1):
                    data = dec.decompress(chunk) if dec else chunk
                    f.write(data)
                    crc, size = zlib.crc32(data, crc), size + len(data)
                    h.update(data)
            if dec:
                data = dec.flush()
                f.write(data)
                crc, size = zlib.crc32(data, crc), size + len(data)
                h.update(data)
        if crc != m.crc32 or size != m.usize:
            raise ZipFormatError(f"{m.name}: CRC/size mismatch after download")
        return h.hexdigest()
