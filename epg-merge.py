#!/usr/bin/env python3
"""
epg-merge.py - Une varias guias XMLTV en un solo archivo, dejando solo los
canales que aparecen en una lista M3U. Sirve para tener UNA sola URL de EPG.

  python epg-merge.py --m3u cliente-epg.m3u \
      --epg URL_PE,URL_CL,URL_AR,URL_MX,URL_ES,URL_CO,URL_UY \
      --out epg-cliente.xml
"""
import argparse
import gzip
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch(url: str) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        data = Path(url).read_bytes()
    else:
        for intento in range(3):
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = r.read()
                break
            except Exception as exc:
                print(f"  reintento {intento+1}/3: {exc}")
                time.sleep(2 * (intento + 1))
        else:
            raise SystemExit(f"No pude descargar {url}")
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def used_ids(m3u: Path) -> set:
    txt = m3u.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r'tvg-id="([^"]+)"', txt))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--m3u", help="lista con los tvg-id")
    ap.add_argument("--ids-file", help="archivo de texto con un id por linea "
                                      "(permite generar el EPG sin subir la lista)")
    ap.add_argument("--epg", required=True)
    ap.add_argument("--out", default="epg-cliente.xml")
    ap.add_argument("--days", type=int, default=0, help="solo N dias (0 = todo)")
    ap.add_argument("--keep-all", action="store_true", help="no filtrar por la lista")
    args = ap.parse_args()

    if args.keep_all:
        ids = set()
    elif args.ids_file:
        ids = {l.strip() for l in Path(args.ids_file).read_text(encoding="utf-8").splitlines()
               if l.strip() and not l.startswith("#")}
    elif args.m3u:
        ids = used_ids(Path(args.m3u))
    else:
        raise SystemExit("Falta --m3u o --ids-file")
    print(f"Canales pedidos: {len(ids)}")

    out = ET.Element("tv", {"generator-info-name": "epg-merge"})
    found = set()
    programas = 0
    con_datos = set()

    # limite de dias: una guia de 11 MB hace que algunos reproductores carguen
    # solo una parte. Con --days 3 el archivo baja casi a la mitad
    limite = ""
    if args.days:
        limite = (datetime.now(timezone.utc)
                  + timedelta(days=args.days)).strftime("%Y%m%d%H%M%S")

    for url in [u.strip() for u in args.epg.split(",") if u.strip()]:
        print(f"Guia: {url.split('epg_ripper_')[-1]}")
        root = ET.fromstring(fetch(url))
        for ch in root.findall("channel"):
            cid = ch.get("id")
            if cid in ids and cid not in found:
                out.append(ch)
                found.add(cid)
        for pr in root.findall("programme"):
            if pr.get("channel") not in ids:
                continue
            if limite and (pr.get("start") or "")[:14] > limite:
                continue
            out.append(pr)
            programas += 1
            con_datos.add(pr.get("channel"))

    # no publicar canales que quedaron sin un solo programa: en el reproductor
    # se ven como "sin informacion" y ensucian la guia
    for ch in list(out.findall("channel")):
        if ch.get("id") not in con_datos:
            out.remove(ch)
            found.discard(ch.get("id"))

    ET.ElementTree(out).write(args.out, encoding="utf-8", xml_declaration=True)
    raw = Path(args.out).stat().st_size
    gz_path = Path(args.out + ".gz")
    with open(args.out, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=9) as f_out:
        f_out.write(f_in.read())

    print(f"\nCanales incluidos : {len(found)} de {len(ids)}")
    print(f"Programas         : {programas}")
    print(f"XML               : {args.out}  ({raw/1024:.0f} KB)")
    print(f"XML comprimido    : {gz_path}  ({gz_path.stat().st_size/1024:.0f} KB)")

    faltan = ids - found
    if faltan:
        print(f"Sin datos en las guias: {len(faltan)}")


if __name__ == "__main__":
    main()

