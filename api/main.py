"""FastAPI app: health check (Phase 1), input resolution (Phase 3, api/resolve.py),
check runs (Phase 4, api/runs.py), batch runs with the Excel report (Phase 5,
api/batch.py), map data (Phase 6, api/map.py) and the results
view at / (api/web.py)."""

import platform
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from api.batch import router as batch_router
from api.db import create_pool
from api.map import router as map_router
from api.resolve import router as resolve_router
from api.runs import router as runs_router
from api.web import mount as mount_web

# Minimum PROJ for EPSG:10306 and EPSG:10838 (decision D9).
MIN_PROJ = (9, 8)

# EPSG sample point Odukalns projected to EPSG:3059; used to prove the grid works.
_GRID_PROBE_SQL = (
    "SELECT ST_X(g), ST_Y(g) FROM lks92_to_lks2020("
    "ST_SetSRID(ST_MakePoint(516646.2934, 298317.1952), 3059)) AS g"
)


class DbHealth(BaseModel):
    ok: bool
    error: str | None = None
    postgres: str | None = None
    postgis: str | None = None
    proj: str | None = None
    proj_ok: bool = False
    srid_10306: bool = False
    lks_grid: bool = False
    migration: str | None = None


class Health(BaseModel):
    status: str  # "ok" | "error"
    python: str
    db: DbHealth


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = create_pool()
    pool.open(wait=False)
    app.state.pool = pool
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="Kadastra pārbaude", version="0.1.0", lifespan=lifespan)
app.include_router(resolve_router)
app.include_router(runs_router)
app.include_router(map_router)
app.include_router(batch_router)
mount_web(app)


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.split(".") if p.isdigit())


def _check_db(pool) -> DbHealth:
    try:
        with pool.connection(timeout=3) as conn:
            row = conn.execute(
                "SELECT current_setting('server_version'),"
                " postgis_lib_version(),"
                " split_part(postgis_proj_version(), ' ', 1),"
                " EXISTS (SELECT 1 FROM spatial_ref_sys WHERE srid = 10306),"
                " (SELECT max(version) FROM schema_migrations)"
            ).fetchone()
            postgres, postgis, proj, srid_10306, migration = row
            health = DbHealth(
                ok=True,
                postgres=postgres,
                postgis=postgis,
                proj=proj,
                proj_ok=_version_tuple(proj)[:2] >= MIN_PROJ,
                srid_10306=srid_10306,
                migration=migration,
            )
            try:
                with conn.transaction():
                    conn.execute(_GRID_PROBE_SQL).fetchone()
                health.lks_grid = True
            except Exception as exc:  # grid missing or function absent
                health.error = f"lks_grid: {exc}".strip()
            return health
    except Exception as exc:
        return DbHealth(ok=False, error=f"{type(exc).__name__}: {exc}".strip())


@app.get("/health", response_model=Health)
def health(request: Request, response: Response) -> Health:
    db = _check_db(request.app.state.pool)
    good = db.ok and db.proj_ok and db.srid_10306 and db.lks_grid and db.migration is not None
    if not good:
        response.status_code = 503
    return Health(status="ok" if good else "error", python=platform.python_version(), db=db)
