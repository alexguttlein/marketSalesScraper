# Informe diario de promos de Carrefour Argentina

Scrapea la página de promociones de Carrefour, usa la IA gratuita de Google (Gemini) para extraer
y ordenar las promos que aplican hoy, y arma un informe en Markdown (opcionalmente lo manda por Telegram).
Corre solo todos los días con GitHub Actions (gratis).

## Archivos

- `scrape_carrefour.py`: descarga la página (requests; si hace falta, Playwright) y guarda el texto en `data/raw/`.
- `build_report.py`: extrae las promos con Gemini, verifica cada una contra el texto original y genera `reports/AAAA-MM-DD.md`.
- `.github/workflows/daily.yml`: ejecución diaria a las 07:00 (hora Argentina).

## Puesta en marcha

1. **Clave de Gemini (gratis):** entrá a https://aistudio.google.com/apikey y creá una API key.
   No hace falta tarjeta. Los límites del plan gratuito cambian con el tiempo; revisalos en AI Studio.
   Para un informe diario alcanza de sobra (1–2 llamadas por día).
2. **Repo en GitHub:** subí esta carpeta a un repositorio nuevo.
3. **Secretos:** en el repo, `Settings > Secrets and variables > Actions > New repository secret`:
   - `GEMINI_API_KEY` (obligatorio)
   - `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (opcionales, para recibir el informe en Telegram;
     el bot se crea hablando con @BotFather)
4. **Probalo:** pestaña `Actions > Informe diario de promos > Run workflow`. El resultado queda en `reports/`.

## Probarlo en tu computadora

```bash
pip install -r requirements.txt
python -m playwright install chromium
python scrape_carrefour.py
GEMINI_API_KEY=tu_clave python build_report.py      # o: python build_report.py --no-llm
```

## Antes de confiar en el informe

- **Verificá la URL de la fuente.** En `scrape_carrefour.py` (`DEFAULT_SOURCES`) está la página de
  promociones bancarias de Carrefour, pero confirmá en tu navegador que sigue vigente y que muestra
  las promos como texto (no solo como imágenes). Podés sumar más URLs, por ejemplo la del sitio de
  beneficios de Carrefour Banco, o pasarlas con la variable `CARREFOUR_URLS="url1,url2"`.
- Si el scraper devuelve poco texto, el workflow falla y GitHub te avisa por mail: es la alerta de que el sitio cambió o bloqueó la consulta.
- Si las promos están en imágenes, hay que pasarlas por un modelo con visión (Gemini también lo soporta); es una mejora para una segunda etapa.
- El informe marca con ⚠️ cualquier promo cuya evidencia no se encuentre en el texto original.
- Respetá los términos de uso del sitio: el prototipo hace una sola consulta por día.

## Próximos pasos

Agregar otros supermercados es sumar una fuente en `DEFAULT_SOURCES` (o un scraper propio si el sitio
lo requiere) y el mismo `build_report.py` sigue sirviendo.
