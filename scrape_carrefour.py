"""Descarga las páginas de promociones de Carrefour Argentina y guarda su texto visible.

Uso:
    python scrape_carrefour.py

Salida:
    data/raw/AAAA-MM-DD.json  (una entrada por fuente, con el texto extraído)

Estrategia: primero intenta con requests (rápido y liviano). Si la página casi no
trae texto (señal de que carga con JavaScript), reintenta con Playwright.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

TZ = ZoneInfo("America/Argentina/Buenos_Aires")

# IMPORTANTE: verificá estas URLs en tu navegador y ajustalas si cambiaron.
# También podés pasarlas por variable de entorno: CARREFOUR_URLS="url1,url2"
DEFAULT_SOURCES = [
    {
        "name": "Carrefour - Promociones bancarias",
        "url": "https://www.carrefour.com.ar/promociones-bancarias",
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9",
}
MIN_TEXT_CHARS = 1500  # por debajo de esto asumimos que falta contenido dinámico


def get_sources():
    env = os.environ.get("CARREFOUR_URLS", "").strip()
    if env:
        return [{"name": f"Fuente {i + 1}", "url": u.strip()} for i, u in enumerate(env.split(",")) if u.strip()]
    return DEFAULT_SOURCES


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def fetch_static(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return visible_text(r.text)


def fetch_browser(url: str) -> str:
    from playwright.sync_api import sync_playwright

    debug_dir = Path("data/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent=HEADERS["User-Agent"], locale="es-AR", viewport={"width": 1366, "height": 900}
        )
        try:
            # "networkidle" casi nunca se alcanza en sitios con tracking: esperamos solo el DOM.
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(6000)
            for _ in range(4):  # scroll para disparar contenido que carga al bajar
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(800)
            html = page.content()
            page.screenshot(path=str(debug_dir / "ultima_pagina.png"), full_page=True)
            (debug_dir / "ultima_pagina.html").write_text(html, encoding="utf-8")
        finally:
            browser.close()
    return visible_text(html)


def scrape_source(src: dict) -> dict:
    result = {"name": src["name"], "url": src["url"], "method": None, "text": "", "error": None}
    text = ""
    try:
        text = fetch_static(src["url"])
        result["method"] = "requests"
    except Exception as e:  # noqa: BLE001
        result["error"] = f"requests: {e}"

    if len(text) < MIN_TEXT_CHARS:
        try:
            text = fetch_browser(src["url"])
            result["method"] = "playwright"
            result["error"] = None
        except Exception as e:  # noqa: BLE001
            prev = result["error"] + " | " if result["error"] else ""
            result["error"] = f"{prev}playwright: {e}"

    result["text"] = text
    return result


def main() -> int:
    now = datetime.now(TZ)
    out_dir = Path("data/raw")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = [scrape_source(s) for s in get_sources()]
    payload = {"date": now.date().isoformat(), "fetched_at": now.isoformat(), "sources": results}
    out_path = out_dir / f"{now.date().isoformat()}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = [r for r in results if len(r["text"]) >= MIN_TEXT_CHARS]
    for r in results:
        print(f"- {r['name']}: {len(r['text'])} caracteres via {r['method']} {'(ERROR: ' + r['error'] + ')' if r['error'] else ''}")
    if not ok:
        print("ALERTA: ninguna fuente devolvió contenido suficiente. Revisá las URLs o si el sitio bloqueó la consulta.", file=sys.stderr)
        return 1
    print(f"Guardado en {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
