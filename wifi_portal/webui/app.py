"""FastAPI application providing a captive Wi-Fi configuration portal."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..wifi_manager import WifiCommandError, WifiManager


def create_app(manager: Optional[WifiManager] = None) -> FastAPI:
    """Factory that builds the FastAPI application."""

    if manager is None:
        config_path = os.getenv("WPA_SUPPLICANT_CONF", "/etc/wpa_supplicant/wpa_supplicant.conf")
        interface = os.getenv("WIFI_INTERFACE", "wlan0")
        manager = WifiManager(config_path=config_path, interface=interface)

    app = FastAPI(title="Raspberry Pi Wi-Fi Setup Portal")

    base_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    static_dir = base_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ------------------------------------------------------------------
    # UI routes
    # ------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, result: str | None = None, error: str | None = None) -> HTMLResponse:
        configured_error: str | None = None
        scan_error: str | None = None
        status_error: str | None = None

        try:
            configured = manager.list_configured_networks()
        except Exception as exc:  # pragma: no cover - defensive fallback
            configured = []
            configured_error = str(exc)

        try:
            scan_results = manager.scan_networks()
        except WifiCommandError as exc:
            scan_results = []
            scan_error = str(exc)

        try:
            connection = manager.current_connection()
        except WifiCommandError as exc:
            connection = {}
            status_error = str(exc)

        context = {
            "request": request,
            "configured": configured,
            "scan_results": scan_results,
            "connection": connection,
            "configured_error": configured_error,
            "scan_error": scan_error,
            "status_error": status_error,
            "result": result,
            "error": error,
        }
        return templates.TemplateResponse("index.html", context)

    @app.post("/configure")
    async def configure_wifi(
        request: Request,
        ssid: str = Form(...),
        password: str = Form(...),
        hidden: Optional[str] = Form(None),
    ):
        if not ssid:
            return RedirectResponse(
                request.url_for("index") + "?error=SSID%20is%20required",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        hidden_flag = hidden in {"on", "true", "1", "yes"}

        try:
            manager.add_network(ssid=ssid, psk=password, hidden=hidden_flag)
            manager.reconfigure()
        except (ValueError, WifiCommandError) as exc:
            return RedirectResponse(
                request.url_for("index") + f"?error={str(exc)}",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        return RedirectResponse(
            request.url_for("index") + "?result=Saved",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # ------------------------------------------------------------------
    # JSON APIs for frontend polling or future automation
    # ------------------------------------------------------------------
    @app.get("/api/configured")
    async def api_configured() -> JSONResponse:
        try:
            networks = manager.list_configured_networks()
        except Exception as exc:  # pragma: no cover - defensive fallback
            return JSONResponse(status_code=500, content={"error": str(exc)})
        return JSONResponse({"networks": networks})

    @app.get("/api/scan")
    async def api_scan() -> JSONResponse:
        try:
            networks = manager.scan_networks()
        except WifiCommandError as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})
        return JSONResponse({"networks": networks})

    @app.get("/api/status")
    async def api_status() -> JSONResponse:
        try:
            info = manager.current_connection()
        except WifiCommandError as exc:
            return JSONResponse(status_code=500, content={"error": str(exc)})
        return JSONResponse(info)

    return app


app = create_app()
