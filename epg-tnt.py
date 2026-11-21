#!/usr/bin/env python3
"""
epg-tnt.py - EPG oficial de TNT Sports Chile.

Usa la misma API que la pagina de programacion de tntsports.cl:
  https://epg.tapkit.warnermedia.com/cloud-epg-schedule/schedule-sports
      ?feed=CDFB_CL&from=AAAA-MM-DD&to=AAAA-MM-DD

Feeds:
  CDFB_CL -> TNT Sports (basico)
  CDFP_CL -> TNT Sports Premium

  python epg-tnt.py --out epg-tnt.xml --dias 4
"""
import argparse
import gzip
import json
import re
import subprocess
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
BASE = "https://epg.tapkit.warnermedia.com/cloud-epg-schedule/schedule-sports"
FEEDS = {
    "CDFB_CL": "TNT Sports",
    "CDFP_CL": "TNT Sports Premium",
}


def bajar(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        return urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")
    except Exception:
        # respaldo: curl del sistema (urllib falla en algunos TLS)
        salida = subprocess.run(["curl", "-s", "-L", "-m", "60", "-A", UA, url],
                                capture_output=True).stdout
        return salida.decode("utf-8", "replace")


def a_utc(local, offset):
    """'2026-11-21T00:00:00' con offset '-03:00' -> '20261121030000 +0000'."""
    dt = datetime.strptime(local[:19], "%Y-%m-%dT%H:%M:%S")
    signo = 1 if offset.startswith("+") else -1
    hh, mm = int(offset[1:3]), int(offset[4:6])
    dt = dt - signo * timedelta(hours=hh, minutes=mm)
    return dt.strftime("%Y%m%d%H%M%S +0000")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="epg-tnt.xml")
    ap.add_argument("--dias", type=int, default=4)
    args = ap.parse_args()

    hoy = datetime.now().date()
    dias = [hoy + timedelta(days=d) for d in range(-1, args.dias - 1)]

    tv = ET.Element("tv", {"generator-info-name": "tntsports.cl"})
    total = 0

    for codigo, nombre in FEEDS.items():
        bolsa = {}
        for dia in dias:
            f = dia.isoformat()
            crudo = bajar(f"{BASE}?feed={codigo}&from={f}&to={f}")
            try:
                j = json.loads(crudo)
                dto = j["com.turner.dmtla.schedule.dto.ScheduleDTO"]
            except Exception:
                print(f"  {nombre:22} {f}: sin datos")
                continue
            offset = dto.get("offset") or "-03:00"
            for feed in dto.get("feeds", []):
                for s in feed.get("shows", []):
                    inicio, fin = s.get("begin"), s.get("end")
                    titulo = (s.get("originalTitle") or s.get("title") or "").strip()
                    if not inicio or not fin or not titulo:
                        continue
                    bolsa[(a_utc(inicio, offset), titulo)] = (a_utc(fin, offset),
                                                              (s.get("summary") or "").strip())

        if not bolsa:
            print(f"  {nombre:22} SIN PROGRAMAS")
            continue

        cid = f"tnt.{codigo}"
        ch = ET.SubElement(tv, "channel", {"id": cid})
        ET.SubElement(ch, "display-name").text = nombre
        for (start, titulo), (stop, resumen) in sorted(bolsa.items()):
            pr = ET.SubElement(tv, "programme", {
                "start": start, "stop": stop, "channel": cid})
            ET.SubElement(pr, "title", {"lang": "es"}).text = titulo
            if resumen:
                ET.SubElement(pr, "desc", {"lang": "es"}).text = resumen[:400]
        total += len(bolsa)
        print(f"  {nombre:22} {len(bolsa):4} programas")

    ET.ElementTree(tv).write(args.out, encoding="utf-8", xml_declaration=True)
    gz = Path(args.out + ".gz")
    with open(args.out, "rb") as fi, gzip.open(gz, "wb", compresslevel=9) as fo:
        fo.write(fi.read())

    if total == 0:
        raise SystemExit("No se obtuvo ningun programa de TNT Sports")

    print(f"\ntotal: {total} programas")
    print(f"{args.out}: {Path(args.out).stat().st_size/1024:.0f} KB | "
          f"{gz.name}: {gz.stat().st_size/1024:.0f} KB")


if __name__ == "__main__":
    main()
