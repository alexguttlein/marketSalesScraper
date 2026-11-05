"""Arma el informe diario de promos a partir del texto scrapeado.

Uso:
    python build_report.py            # usa Gemini si hay GEMINI_API_KEY
    python build_report.py --no-llm   # modo sin IA (lista simple de líneas con %)

Variables de entorno:
    GEMINI_API_KEY        clave gratuita de Google AI Studio
    GEMINI_MODEL          opcional (por defecto gemini-2.5-flash)
    TELEGRAM_BOT_TOKEN    opcional, para recibir el informe por Telegram
    TELEGRAM_CHAT_ID      opcional
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MAX_CHARS = 60000  # tope de texto enviado al modelo

PROMPT = """Sos un asistente que extrae promociones de supermercado de textos de una web.
Hoy es {dia} {fecha} (Argentina).

Del TEXTO de abajo, extraé TODAS las promociones de descuento/beneficio que aparezcan.
Reglas estrictas:
- Usá SOLO información presente en el texto. Si un dato no está, poné null. No inventes nada.
- "dias" es la lista de días de la semana en que aplica (minúsculas, con tilde: lunes, martes, miércoles, jueves, viernes, sábado, domingo). Si aplica todos los días, listá los 7. Si no se indica, poné [].
- "aplica_hoy" es true solo si hoy ({dia}) está en "dias" y la vigencia no está claramente vencida.
- "descuento_pct" es el porcentaje numérico principal (ej. 20) o null si no es un porcentaje (ej. cuotas, 2x1).
- "evidencia" debe ser un fragmento COPIADO TEXTUALMENTE del texto (máx. 200 caracteres) que respalde la promo.

Respondé únicamente con JSON con esta forma:
{{"promos": [{{"medio_de_pago": str|null, "descuento": str, "descuento_pct": number|null, "dias": [str], "tope": str|null, "aplica_en": str|null, "exclusiones": str|null, "acumulable": bool|null, "vigencia": str|null, "aplica_hoy": bool, "evidencia": str}}]}}

TEXTO:
{texto}
"""


def load_latest_raw() -> dict:
    files = sorted(Path("data/raw").glob("*.json"))
    if not files:
        sys.exit("No hay datos en data/raw. Ejecutá primero scrape_carrefour.py")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def call_gemini(prompt: str) -> dict:
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    last_err = None
    for attempt in range(4):
        r = requests.post(url, headers={"x-goog-api-key": key}, json=body, timeout=120)
        if r.status_code in (429, 500, 503):
            last_err = f"HTTP {r.status_code}: {r.text[:200]}"
            time.sleep(15 * (attempt + 1))
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    raise RuntimeError(f"Gemini no respondió tras varios intentos ({last_err})")


def extract_promos(raw: dict, now: datetime) -> list[dict]:
    chunks = []
    for s in raw["sources"]:
        if s.get("text"):
            chunks.append(f"### FUENTE: {s['name']} ({s['url']})\n{s['text']}")
    texto = "\n\n".join(chunks)[:MAX_CHARS]
    prompt = PROMPT.format(dia=DIAS[now.weekday()], fecha=now.strftime("%d/%m/%Y"), texto=texto)
    data = call_gemini(prompt)
    promos = data.get("promos", [])

    # Verificación anti-alucinación: la evidencia debe existir en el texto original.
    haystack = norm(texto)
    for p in promos:
        ev = norm(p.get("evidencia") or "")
        p["verificada"] = bool(ev) and ev in haystack
    return promos


def fallback_promos(raw: dict) -> list[str]:
    """Modo sin IA: devuelve líneas que parecen promociones."""
    out = []
    for s in raw["sources"]:
        for ln in s.get("text", "").splitlines():
            if "%" in ln and 15 <= len(ln) <= 300:
                out.append(ln)
    return list(dict.fromkeys(out))[:40]


def fmt_promo(p: dict) -> str:
    partes = [f"**{p.get('descuento', '?')}**"]
    if p.get("medio_de_pago"):
        partes.append(f"con {p['medio_de_pago']}")
    if p.get("aplica_en"):
        partes.append(f"· {p['aplica_en']}")
    linea = " ".join(partes)
    extra = []
    extra.append(f"tope: {p['tope']}" if p.get("tope") else "sin tope indicado")
    if p.get("acumulable") is False:
        extra.append("no acumulable")
    if p.get("exclusiones"):
        extra.append(f"excluye: {p['exclusiones']}")
    if p.get("vigencia"):
        extra.append(f"vigencia: {p['vigencia']}")
    linea += "\n  - " + " | ".join(extra)
    if not p.get("verificada"):
        linea += "\n  - ⚠️ No pude verificar esta promo contra el texto original; confirmala en la fuente."
    return linea


def render_report(promos: list[dict], raw: dict, now: datetime) -> str:
    dia = DIAS[now.weekday()]
    hoy = [p for p in promos if p.get("aplica_hoy") and p.get("verificada")]
    hoy.sort(key=lambda p: (p.get("descuento_pct") or 0), reverse=True)
    resto = [p for p in promos if not p.get("aplica_hoy") and p.get("verificada")]
    dudosas = [p for p in promos if not p.get("verificada")]

    L = [f"# Promos Carrefour – {dia} {now.strftime('%d/%m/%Y')}", ""]
    if hoy:
        L.append("## Lo más destacado de hoy")
        for p in hoy[:5]:
            L.append(f"- {fmt_promo(p)}")
        if len(hoy) > 5:
            L += ["", "## Otras promos que aplican hoy"]
            for p in hoy[5:]:
                L.append(f"- {fmt_promo(p)}")
    else:
        L.append("No encontré promos que apliquen hoy en las fuentes consultadas.")
    if resto:
        L += ["", "## Próximos días / otras promos"]
        for p in resto:
            dias = ", ".join(p.get("dias") or []) or "días no indicados"
            L.append(f"- {p.get('descuento', '?')} con {p.get('medio_de_pago') or 'medio no indicado'} ({dias})")
    if dudosas:
        L += ["", "## ⚠️ A confirmar en la fuente (no pude verificarlas contra el texto original)"]
        for p in dudosas:
            L.append(f"- {p.get('descuento', '?')} con {p.get('medio_de_pago') or 'medio no indicado'}")
    L += ["", "---", "Fuentes:"]
    for s in raw["sources"]:
        L.append(f"- [{s['name']}]({s['url']})")
    L.append("_Generado automáticamente: verificá condiciones y topes en la fuente antes de comprar._")
    return "\n".join(L)


def render_fallback(lines: list[str], raw: dict, now: datetime) -> str:
    L = [f"# Promos Carrefour (modo sin IA) – {DIAS[now.weekday()]} {now.strftime('%d/%m/%Y')}", ""]
    L += [f"- {ln}" for ln in lines] or ["No se encontraron líneas con descuentos."]
    L += ["", "Fuentes:"] + [f"- {s['url']}" for s in raw["sources"]]
    return "\n".join(L)


def send_telegram(text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    plain = re.sub(r"[*_#]", "", text)
    for i in range(0, len(plain), 3800):
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": plain[i : i + 3800], "disable_web_page_preview": True},
            timeout=30,
        ).raise_for_status()


def main() -> int:
    now = datetime.now(TZ)
    raw = load_latest_raw()
    use_llm = "--no-llm" not in sys.argv and os.environ.get("GEMINI_API_KEY")

    if use_llm:
        report = render_report(extract_promos(raw, now), raw, now)
    else:
        print("Sin GEMINI_API_KEY o con --no-llm: usando modo simple.", file=sys.stderr)
        report = render_fallback(fallback_promos(raw), raw, now)

    out = Path("reports")
    out.mkdir(exist_ok=True)
    path = out / f"{now.date().isoformat()}.md"
    path.write_text(report, encoding="utf-8")
    print(report)
    send_telegram(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
