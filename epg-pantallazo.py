#!/usr/bin/env python3
"""
epg-pantallazo.py - Genera un XMLTV con la programacion de pantallazo.cl

Cada canal lista sus programas con data-start / data-end en epoch, asi que no
hay que calcular zonas horarias. Algunos canales solo publican bloques
genericos (el nombre del canal repetido): esos se descartan.
"""
import argparse
import gzip
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
BASE = "https://pantallazo.cl/programacion-tv/"

CANALES = {
    "13c": "13C",
    "13rec": "13Rec",
    "24-horas": "Canal 24 Horas",
    "artv": "AR TV",
    "bio-bio-tv": "Bio Bio TV",
    "canal-13": "Canal 13",
    "canal-9": "Canal 9",
    "canal-isb": "Canal ISB",
    "cddtv": "Camara de Diputados",
    "cdo": "CDO",
    "cdo-2": "CDO 2",
    "chv": "CHV",
    "chv-contigo": "CHV Contigo",
    "chv-de-culto": "CHV de Culto",
    "chv-noticias": "CHV Noticias",
    "docu": "Docu",
    "etc": "ETC",
    "knino": "KNINO",
    "mega": "Mega",
    "mega-2": "Mega 2",
    "mega-ficcion": "Mega Ficcion",
    "ntv": "NTV",
    "puranoticia": "PuraNoticia",
    "t13-en-vivo": "T13 En Vivo",
    "tv-chile": "TV Chile",
    "tv-mas": "TV+",
    "tv-senado": "TV Senado",
    "tvn": "TVN",
    "tvn-3": "TVN3",
    "tvr": "TVR",
    "uchile-tv": "U Chile TV",
    "ucv-tv": "UCV TV",
    "via-x": "Via X",
    "via-x-esports": "Via X Esports",
    "zona-latina": "Zona Latina",
}

BLOQUE = re.compile(r'data-start="(\d+)"\s+data-end="(\d+)"(.*?)(?=data-start="|\Z)', re.S)
NOMBRE = re.compile(r'class="program-name">(.*?)</div>', re.S)
DESC = re.compile(r'class="program-desc">(.*?)</p>', re.S)
GENERO = re.compile(r'class="tag-genre">(.*?)</span>', re.S)


def a_xmltv(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def limpiar(texto: str) -> str:
    t = re.sub(r"<[^>]+>", "", texto or "")
    return html.unescape(t).strip()


def bajar(url: str) -> str:
    for intento in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        except Exception as exc:
            if intento == 2:
                print(f"  ! {url}: {exc}")
                return ""
    return ""



def cubre_ahora(raiz):
    """True si algun programa de la guia incluye el momento actual."""
    ahora = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for p in raiz.findall("programme"):
        if (p.get("start") or "")[:14] <= ahora < (p.get("stop") or "")[:14]:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="epg-pantallazo.xml")
    args = ap.parse_args()

    tv = ET.Element("tv", {"generator-info-name": "pantallazo.cl"})
    total, utiles, genericos = 0, 0, []

    for slug, nombre in CANALES.items():
        pagina = bajar(BASE + slug + "/")
        if not pagina:
            continue

        programas = []
        for m in BLOQUE.finditer(pagina):
            start, end, resto = m.group(1), m.group(2), m.group(3)
            titulo = limpiar(NOMBRE.search(resto).group(1)) if NOMBRE.search(resto) else ""
            if not titulo:
                continue
            desc = limpiar(DESC.search(resto).group(1)) if DESC.search(resto) else ""
            gen = limpiar(GENERO.search(resto).group(1)) if GENERO.search(resto) else ""
            programas.append((start, end, titulo, desc, gen))

        if not programas:
            print(f"  {nombre:22} sin parrilla")
            continue

        # si todos los titulos son iguales, es un bloque generico sin informacion
        titulos = {p[2].lower().replace(" ", "") for p in programas}
        if len(titulos) == 1:
            genericos.append(nombre)
            print(f"  {nombre:22} solo bloque generico ({programas[0][2]})")
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
        print(f"  {nombre:22} {len(vistos):4} programas")

    ET.ElementTree(tv).write(args.out, encoding="utf-8", xml_declaration=True)
    gz = Path(args.out + ".gz")
    with open(args.out, "rb") as fi, gzip.open(gz, "wb", compresslevel=9) as fo:
        fo.write(fi.read())

    print(f"\ncanales utiles: {utiles} | programas: {total}")
    if genericos:
        print(f"descartados por bloque generico: {', '.join(genericos)}")
    if not cubre_ahora(tv):
        print("\nAVISO: la parrilla NO cubre el momento actual "
              "(pantallazo todavia no cambio de dia).")
        raise SystemExit(2)

    print(f"{args.out}: {Path(args.out).stat().st_size/1024:.0f} KB | "
          f"{gz.name}: {gz.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
