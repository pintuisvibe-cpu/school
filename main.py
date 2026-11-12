"""School ID card + gate attendance app.

The whole application is static HTML/CSS/JS. Data lives in Supabase (Postgres)
and is reached through locked-down `security definer` RPC functions, so the
browser only ever holds the public anon/publishable key. Face descriptors are
computed in the browser and only the 128-number vector is stored.

Run locally / on Render:  uvicorn main:app --host 0.0.0.0 --port 8000
Static-only hosts (Netlify, GitHub Pages, Vercel) can serve these files directly.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="School ID Card & Attendance", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/css", StaticFiles(directory=BASE_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=BASE_DIR / "js"), name="js")

# page route -> html file
PAGES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/admin": "admin.html",
    "/admin.html": "admin.html",
    "/card": "card.html",
    "/card.html": "card.html",
    "/cards": "cards.html",
    "/cards.html": "cards.html",
    "/scanner": "scanner.html",
    "/scanner.html": "scanner.html",
}


def page(filename: str) -> FileResponse:
    return FileResponse(
        BASE_DIR / filename,
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "backend": "supabase", "version": "3.0.0"})


def _register(path: str) -> None:
    async def handler():  # pragma: no cover - trivial
        return page(PAGES[path])

    app.get(path)(handler)


for _path in PAGES:
    _register(_path)


@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse(
        {
            "name": "School ID Card & Attendance",
            "short_name": "School ID",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#f1f5fb",
            "theme_color": "#1d4ed8",
            "icons": [{"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
        }
    )
