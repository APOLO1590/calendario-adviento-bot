"""Monitor de calendarios de adviento en maquillajetrendyshop.com (tienda VTEX).

Vigila dos fuentes:
  1. API de búsqueda de VTEX (productos + disponibilidad)
  2. sitemap de productos (detecta URLs nuevas antes de que se indexen en la búsqueda)

Avisa por Telegram (variables TELEGRAM_TOKEN y TELEGRAM_CHAT_ID) o por consola.
Uso:  python monitor.py          -> una revisión (para cron / GitHub Actions)
      python monitor.py --loop   -> revisa cada INTERVALO segundos
      python monitor.py --test   -> manda un mensaje de prueba
"""
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://www.maquillajetrendyshop.com"
KEYWORDS = ["adviento", "advent", "calendario"]
URL_PATTERN = re.compile(r"adviento|advent|calendario", re.I)
STATE_FILE = Path(__file__).with_name("state.json")
INTERVALO = 180  # segundos entre revisiones en modo --loop

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def notify(text):
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    print(text)
    if token and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text}, timeout=15)
        except requests.RequestException as e:
            print("No se pudo enviar a Telegram:", e)


def search_products():
    """Devuelve {link: {name, available, price}} para todas las palabras clave."""
    found = {}
    for kw in KEYWORDS:
        r = requests.get(f"{BASE}/api/io/_v/api/intelligent-search/product_search/",
                         params={"query": kw, "count": 40, "page": 1}, headers=HEADERS, timeout=20)
        r.raise_for_status()
        for p in r.json().get("products", []):
            name = p["productName"]
            if not URL_PATTERN.search(name + " " + p.get("link", "")):
                continue
            offers = [s["commertialOffer"] for i in p["items"] for s in i["sellers"]]
            found[BASE + p["link"]] = {
                "name": name,
                "available": any(o["AvailableQuantity"] > 0 for o in offers),
                "price": min((o["Price"] for o in offers), default=0),
            }
    return found


def sitemap_urls():
    r = requests.get(f"{BASE}/sitemap/product-0.xml", headers=HEADERS, timeout=20)
    r.raise_for_status()
    return {u for u in re.findall(r"<loc>([^<]+)</loc>", r.text) if URL_PATTERN.search(u)}


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return None


def check():
    products, urls = search_products(), sitemap_urls()
    old = load_state()
    first_run = old is None
    old = old or {"products": {}, "urls": []}
    alerts = []

    for link, p in products.items():
        prev = old["products"].get(link)
        precio = f"${p['price']:,.0f}"
        if prev is None:
            estado = "DISPONIBLE" if p["available"] else "aún no disponible"
            alerts.append(f"🎁 NUEVO: {p['name']} ({precio}) - {estado}\n{link}")
        elif p["available"] and not prev["available"]:
            alerts.append(f"🛒 YA DISPONIBLE: {p['name']} ({precio})\n{link}")

    for u in sorted(urls - set(old["urls"])):
        if u not in products:
            alerts.append(f"👀 URL nueva en el sitemap:\n{u}")

    STATE_FILE.write_text(json.dumps({"products": products, "urls": sorted(urls)},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    if first_run:
        print(f"Primera ejecución: {len(products)} productos y {len(urls)} URLs guardados como base.")
        for a in alerts:
            print(a)
    else:
        for a in alerts:
            notify(a)
        if not alerts:
            print(time.strftime("%H:%M:%S"), "- sin novedades")


def main():
    if "--test" in sys.argv:
        notify("✅ Bot de calendario de adviento funcionando.")
        return
    if "--loop" in sys.argv:
        fallos = 0
        while True:
            try:
                check()
                fallos = 0
            except Exception as e:
                fallos += 1
                print("Error:", e)
                if fallos == 5:
                    notify(f"⚠️ El monitor lleva 5 fallos seguidos: {e}")
            time.sleep(INTERVALO + random.randint(0, 30))
    else:
        check()


if __name__ == "__main__":
    main()
