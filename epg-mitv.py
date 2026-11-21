#!/usr/bin/env python3
"""
epg-mitv.py - Genera un XMLTV con la programacion de mi.tv (Chile).

mi.tv entrega la parrilla renderizada solo a buscadores, asi que se pide con el
user-agent de Googlebot. Cada canal tiene hoy, manana y los dias por nombre,
con sinopsis incluida.

  python epg-mitv.py --mapa mitv-slugs.json --dias 3 --out epg-mitv.xml
"""
import argparse
import gzip
import html
import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BASE = "https://mi.tv/cl/canales/"
DIAS_ES = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

ITEM = re.compile(
    r'<li\s*>\s*<a href="(?P<href>/cl/programas/[^"]+)" class="program-link">(?P<cuerpo>.*?)</li>',
    re.S)
HORA = re.compile(r'class="time">\s*([0-9]{2}):([0-9]{2})')
TITULO = re.compile(r"<h2>\s*(.*?)\s*</h2>", re.S)
DESC = re.compile(r"<p[^>]*>(.*?)</p>", re.S)


def limpiar(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    return html.unescape(re.sub(r"\s+", " ", t)).strip()


def bajar(url, intentos=3):
    for i in range(intentos):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "es-CL,es;q=0.9"})
            return urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")
        except Exception:
            if i == intentos - 1:
                return ""
            time.sleep(1.5 * (i + 1))
    return ""


def desfase_horas(fecha):
    try:
        from zoneinfo import ZoneInfo
        return int(fecha.replace(tzinfo=ZoneInfo("America/Santiago")).utcoffset().total_seconds() // 3600)
    except Exception:
        return -3 if fecha.month in (9, 10, 11, 12, 1, 2, 3, 4) else -4


def utc(base, hora, minuto, desfase):
    local = base.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    return (local - timedelta(hours=desfase)).strftime("%Y%m%d%H%M%S +0000")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapa", default="mitv-slugs.json")
    ap.add_argument("--out", default="epg-mitv.xml")
    ap.add_argument("--dias", type=int, default=3)
    ap.add_argument("--pausa", type=float, default=0.3)
    args = ap.parse_args()

    mapa = json.loads(Path(args.mapa).read_text(encoding="utf-8"))
    hoy = datetime.now()
    desfase = desfase_horas(hoy)

    rutas = [("ayer", hoy - timedelta(days=1)), ("", hoy), ("manana", hoy + timedelta(days=1))]
    for i in range(2, args.dias):
        f = hoy + timedelta(days=i)
        rutas.append((DIAS_ES[f.weekday()], f))

    bolsas = {}      # cid -> {(start, titulo): (stop, desc)}
    nombres = {}
    fallos = []

    for n, (canal, slug) in enumerate(sorted(mapa.items()), 1):
        cid = f"mitv.{slug}"
        nombres[cid] = canal
        for ruta, fecha in rutas:
            url = BASE + slug + "/" + (ruta + "/" if ruta else "")
            pagina = bajar(url)
            time.sleep(args.pausa)
            if not pagina:
                continue

            programas = []
            for m in ITEM.finditer(pagina):
                cuerpo = m.group("cuerpo")
                h = HORA.search(cuerpo)
                t = TITULO.search(cuerpo)
                if not h or not t:
                    continue
                titulo = limpiar(t.group(1))
                if not titulo:
                    continue
                d = DESC.search(cuerpo)
                programas.append((int(h.group(1)), int(h.group(2)), titulo,
                                  limpiar(d.group(1)) if d else ""))

            bolsa = bolsas.setdefault(cid, {})
            for i, (hora, minuto, titulo, desc) in enumerate(programas):
                if i + 1 < len(programas):
                    nh, nm = programas[i + 1][0], programas[i + 1][1]
                    extra = 1 if nh * 60 + nm <= hora * 60 + minuto else 0
                    fin = fecha + timedelta(days=extra)
                    fin = fin.replace(hour=nh, minute=nm)
                else:
                    fin = fecha.replace(hour=hora, minute=minuto) + timedelta(hours=1)
                bolsas[cid][(utc(fecha, hora, minuto, desfase), titulo)] = (
                    (fin - timedelta(hours=desfase)).strftime("%Y%m%d%H%M%S +0000"), desc)

        cuantos = len(bolsas[cid])
        if cuantos == 0:
            fallos.append(canal)
        if n % 10 == 0 or cuantos == 0:
            print(f"  {n:3}/{len(mapa)} {canal:24} {cuantos:4} programas")

    tv = ET.Element("tv", {"generator-info-name": "mi.tv"})
    total = 0
    for cid, bolsa in sorted(bolsas.items()):
        if not bolsa:
            continue
        ch = ET.SubElement(tv, "channel", {"id": cid})
        ET.SubElement(ch, "display-name").text = nombres[cid]
        for (start, titulo), (stop, desc) in sorted(bolsa.items()):
            pr = ET.SubElement(tv, "programme", {"start": start, "stop": stop, "channel": cid})
            ET.SubElement(pr, "title", {"lang": "es"}).text = titulo
            if desc:
                ET.SubElement(pr, "desc", {"lang": "es"}).text = desc
        total += len(bolsa)

    ET.ElementTree(tv).write(args.out, encoding="utf-8", xml_declaration=True)
    with open(args.out, "rb") as fi, gzip.open(args.out + ".gz", "wb", compresslevel=9) as fo:
        fo.write(fi.read())

    con_datos = sum(1 for b in bolsas.values() if b)
    print(f"\ncanales con datos: {con_datos} de {len(mapa)} | programas: {total}")
    if fallos:
        print("sin datos:", ", ".join(fallos[:20]), f"... ({len(fallos)})" if len(fallos) > 20 else "")
    print(f"{args.out}: {Path(args.out).stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
