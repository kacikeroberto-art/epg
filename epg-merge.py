#!/usr/bin/env python3
"""
epg-merge.py - Une varias guias XMLTV en un archivo, dejando solo los canales
que interesan. Dos modos:

  # a partir de una lista M3U (saca los tvg-id de ahi)
  python epg-merge.py --m3u cliente-epg.m3u --epg URL_PE,URL_CL --out epg.xml

  # a partir de un archivo de ids (para correr sin la lista, sin credenciales)
  python epg-merge.py --ids-file ids.txt --epg URL_PE,URL_CL --out epg.xml
"""
import argparse
import gzip
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch(url: str) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        data = Path(url).read_bytes()
    else:
        for intento in range(4):
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=240) as r:
                    data = r.read()
                break
            except Exception as exc:
                print(f"  reintento {intento+1}/4: {exc}")
                time.sleep(3 * (intento + 1))
        else:
            raise SystemExit(f"No pude descargar {url}")
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def ids_desde_m3u(path: Path) -> set:
    txt = path.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r'tvg-id="([^"]+)"', txt))


def ids_desde_txt(path: Path) -> set:
    return {l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--m3u")
    ap.add_argument("--ids-file")
    ap.add_argument("--epg", required=True, help="URLs separadas por coma")
    ap.add_argument("--out", default="epg.xml")
    ap.add_argument("--keep-all", action="store_true")
    args = ap.parse_args()

    if args.keep_all:
        ids = set()
    elif args.ids_file:
        ids = ids_desde_txt(Path(args.ids_file))
    elif args.m3u:
        ids = ids_desde_m3u(Path(args.m3u))
    else:
        raise SystemExit("Falta --m3u o --ids-file")

    print(f"Canales pedidos: {len(ids)}")
    out = ET.Element("tv", {"generator-info-name": "epg-merge"})
    found, programas = set(), 0

    for url in [u.strip() for u in args.epg.split(",") if u.strip()]:
        print(f"Guia: {url.rsplit('_', 1)[-1]}")
        root = ET.fromstring(fetch(url))
        for ch in root.findall("channel"):
            cid = ch.get("id")
            if (not ids or cid in ids) and cid not in found:
                out.append(ch)
                found.add(cid)
        for pr in root.findall("programme"):
            if not ids or pr.get("channel") in ids:
                out.append(pr)
                programas += 1

    ET.ElementTree(out).write(args.out, encoding="utf-8", xml_declaration=True)
    gz = Path(args.out + ".gz")
    with open(args.out, "rb") as fi, gzip.open(gz, "wb", compresslevel=9) as fo:
        fo.write(fi.read())

    print(f"\nCanales incluidos: {len(found)}")
    print(f"Programas        : {programas}")
    print(f"{args.out}: {Path(args.out).stat().st_size/1024:.0f} KB  |  "
          f"{gz.name}: {gz.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
