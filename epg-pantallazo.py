#!/usr/bin/env python3
"""
epg-pantallazo.py - Genera un XMLTV con la programacion de pantallazo.cl

Cada canal lista sus programas con data-start / data-end en epoch, asi que no
hay que calcular zonas horarias.

El sitio usa cache de WordPress y a veces sirve paginas de dias anteriores.
Por eso cada canal se valida: si su parrilla no cubre el momento actual se
reintenta con un parametro anti-cache y, si sigue vieja, se descarta.

  python epg-pantallazo.py --out epg-pantallazo.xml
"""
import argparse
import gzip
import html
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
BASE = "https://pantallazo.cl/programacion-tv/"
INTENTOS = 3

CANALES = {
    "13c": "13C", "13rec": "13Rec", "24-horas": "Canal 24 Horas", "artv": "AR TV",
    "bio-bio-tv": "Bio Bio TV", "canal-13": "Canal 13", "canal-9": "Canal 9",
    "canal-isb": "Canal ISB", "cddtv": "Camara de Diputados", "cdo": "CDO",
    "cdo-2": "CDO 2", "chv": "CHV", "chv-contigo": "CHV Contigo",
    "chv-de-culto": "CHV de Culto", "chv-noticias": "CHV Noticias", "docu": "Docu",
    "etc": "ETC", "knino": "KNINO", "mega": "Mega", "mega-2": "Mega 2",
    "mega-ficcion": "Mega Ficcion", "ntv": "NTV", "puranoticia": "PuraNoticia",
    "t13-en-vivo": "T13 En Vivo", "tv-chile": "TV Chile", "tv-mas": "TV+",
    "tv-senado": "TV Senado", "tvn": "TVN", "tvn-3": "TVN3", "tvr": "TVR",
    "uchile-tv": "U Chile TV", "ucv-tv": "UCV TV", "via-x": "Via X",
    "via-x-esports": "Via X Esports", "zona-latina": "Zona Latina",
}

BLOQUE = re.compile(r'data-start="(\d+)"\s+data-end="(\d+)"(.*?)(?=data-start="|\Z)', re.S)
NOMBRE = re.compile(r'class="program-name">(.*?)</div>', re.S)
DESC = re.compile(r'class="program-desc">(.*?)</p>', re.S)
GENERO = re.compile(r'class="tag-genre">(.*?)</span>', re.S)


def a_xmltv(ms):
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def limpiar(texto):
    t = re.sub(r"<[^>]+>", "", texto or "")
    return html.unescape(t).strip()


def bajar(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    except Exception:
        return ""


def parsear(pagina):
    programas = []
    for m in BLOQUE.finditer(pagina):
        start, end, resto = m.group(1), m.group(2), m.group(3)
        n = NOMBRE.search(resto)
        if not n:
            continue
        titulo = limpiar(n.group(1))
        if not titulo:
            continue
        d = DESC.search(resto)
        g = GENERO.search(resto)
        programas.append((start, end, titulo,
                          limpiar(d.group(1)) if d else "",
                          limpiar(g.group(1)) if g else ""))
    return programas


def cubre(programas, ahora_ms):
    return any(int(s) <= ahora_ms < int(e) for s, e, *_ in programas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="epg-pantallazo.xml")
    ap.add_argument("--pausa", type=float, default=0.4)
    args = ap.parse_args()

    ahora_ms = time.time() * 1000
    marca = int(time.time())

    tv = ET.Element("tv", {"generator-info-name": "pantallazo.cl"})
    total, utiles, genericos, descartados = 0, 0, [], []

    for slug, nombre in CANALES.items():
        programas, origen = [], ""
        for intento in range(INTENTOS):
            url = BASE + slug + "/"
            if intento:
                url += f"?v={marca}-{intento}"
            pagina = bajar(url)
            time.sleep(args.pausa)
            if not pagina:
                continue
            programas = parsear(pagina)
            if not programas:
                continue
            if cubre(programas, ahora_ms):
                origen = "fresco" if intento == 0 else f"reintento {intento}"
                break

        if not programas:
            print(f"  {nombre:22} sin parrilla")
            continue

        titulos = {p[2].lower().replace(" ", "") for p in programas}
        if len(titulos) == 1:
            genericos.append(nombre)
            continue

        if not cubre(programas, ahora_ms):
            descartados.append(nombre)
            rango = f"{programas[0][0][:8]} -> {programas[-1][1][:8]}"
            print(f"  {nombre:22} DESCARTADO: parrilla vieja ({rango})")
            continue

        cid = f"pantallazo.{slug}"
        ch = ET.SubElement(tv, "channel", {"id": cid})
        ET.SubElement(ch, "display-name").text = nombre

        vistos = set()
        for start, end, titulo, desc, gen in programas:
            clave = (start, end, titulo)
            if clave in vistos:
                continue
            vistos.add(clave)
            pr = ET.SubElement(tv, "programme", {
                "start": a_xmltv(start), "stop": a_xmltv(end), "channel": cid})
            ET.SubElement(pr, "title", {"lang": "es"}).text = titulo
            if desc:
                ET.SubElement(pr, "desc", {"lang": "es"}).text = desc
            if gen:
                ET.SubElement(pr, "category", {"lang": "es"}).text = gen

        utiles += 1
        total += len(vistos)
        print(f"  {nombre:22} {len(vistos):4} programas  ({origen})")

    ET.ElementTree(tv).write(args.out, encoding="utf-8", xml_declaration=True)
    gz = Path(args.out + ".gz")
    with open(args.out, "rb") as fi, gzip.open(gz, "wb", compresslevel=9) as fo:
        fo.write(fi.read())

    print(f"\ncanales utiles: {utiles} | programas: {total}")
    if genericos:
        print(f"descartados por bloque generico: {', '.join(genericos)}")
    if descartados:
        print(f"descartados por parrilla vieja : {', '.join(descartados)}")

    if utiles == 0:
        raise SystemExit("Ningun canal con parrilla fresca: no se publica nada")

    print(f"{args.out}: {Path(args.out).stat().st_size/1024:.0f} KB | "
          f"{gz.name}: {gz.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
