"""The results view (web/, Vite + React, PLAN.md §8.2) served at / from the same
origin as /api. The build is made in the image's `web` stage (api/Dockerfile) and
found through KADASTRS_WEB_DIST; the URL keeps the state (?run=…&target=…), so
every page path answers with index.html."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

NOT_BUILT = (
    "<!doctype html><html lang='lv'><meta charset='utf-8'><title>Kadastra pārbaude</title>"
    "<body style='font-family:system-ui;margin:3rem'><h1>Kadastra pārbaude</h1>"
    "<p>Lietotne nav uzbūvēta šajā attēlā. Palaidiet <code>docker compose up -d --build</code>.</p>"
    "</body></html>"
)


def dist_dir() -> Path:
    return Path(
        os.environ.get("KADASTRS_WEB_DIST", Path(__file__).resolve().parents[1] / "web/dist")
    )


def mount(app: FastAPI) -> None:
    dist = dist_dir()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False, response_model=None)
    def index() -> FileResponse | HTMLResponse:
        page = dist / "index.html"
        if not page.is_file():
            return HTMLResponse(NOT_BUILT, status_code=503)
        # never cached: a new build must show at once (assets have hashed names)
        return FileResponse(page, headers={"Cache-Control": "no-cache"})
