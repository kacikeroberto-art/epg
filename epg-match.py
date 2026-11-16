#!/usr/bin/env python3
"""
epg-match.py - Empareja los canales de una lista M3U con una guia XMLTV
y reescribe los tvg-id para que la EPG se enganche.

Criterio: solo acepta coincidencias de alta confianza (mismas palabras
significativas). Todo lo demas queda sin tvg-id y se lista como candidato
en el informe, para asignarlo a mano. Un EPG equivocado es peor que ninguno.

Uso:
  python epg-match.py --m3u cl-grupos.m3u \
      --epg https://epgshare01.online/epgshare01/epg_ripper_CL1.xml.gz

  # varias guias (LatAm): separadas por coma
  python epg-match.py --m3u latam.m3u --epg URL_CL,URL_AR,URL_MX

  # ademas deja la guia unida en un XML local
  python epg-match.py --m3u cl-grupos.m3u --epg URL_CL --write-xmltv epg-cl.xml
"""

import argparse
import difflib
import time
import gzip
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# palabras que no distinguen un canal de otro
ALIAS = {('chv',): ('chilevision',)}

STOP = {
    "canal", "de", "del", "la", "el", "los", "las", "y", "en", "tv", "hd", "sd",
    "chile", "latinoamerica", "latam", "internacional", "senal", "hd2", "television",
}


def fetch(url: str) -> bytes:
    """descarga (con reintentos) o lee un archivo local .xml / .xml.gz"""
    if not url.lower().startswith(("http://", "https://")):
        data = Path(url).read_bytes()
    else:
        last = None
        for intento in range(3):
            try:
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = r.read()
                break
            except Exception as exc:          # red inestable, cortes a medias
                last = exc
                print(f"  reintento {intento + 1}/3: {exc}")
                time.sleep(2 * (intento + 1))
        else:
            raise SystemExit(f"No pude descargar {url}: {last}")
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def tokens(text: str) -> frozenset:
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("+", " plus ")
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"\([^)]*\)", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    words = [w for w in t.split() if w and w not in STOP]
    # el proveedor mete marcadores sueltos de una letra: "H TV PERU", "13 C"
    words = [w for w in words if len(w) > 1]
    base = frozenset(words)
    return frozenset(ALIAS.get(tuple(sorted(base)), sorted(base)))


class Guide:
    def __init__(self, url):
        self.url = url
        self.root = None
        self.entries = []          # (id, display)
        self.index = {}            # token -> set(ids)
        self.by_tokens = {}        # frozenset -> id

    def load(self):
        self.root = ET.fromstring(fetch(self.url))
        # solo canales que realmente traen programas: una guia puede listar
        # un canal sin horarios (PE1 lo hace con 136 de 164) y si lo dejamos
        # indexado le gana el turno a otra guia que si tiene datos
        con_datos = set()
        for pr in self.root.findall("programme"):
            con_datos.add(pr.get("channel"))
        for ch in self.root.findall("channel"):
            cid = ch.get("id") or ""
            if cid not in con_datos:
                continue
            names = [d.text or "" for d in ch.findall("display-name")] or [cid]
            self.entries.append((cid, names[0]))
            for n in names:
                tk = tokens(n)
                if tk:
                    self.by_tokens.setdefault(tk, cid)
                    for w in tk:
                        self.index.setdefault(w, set()).add(cid)
        return self


def candidates(name, guides):
    """ids que comparten al menos una palabra significativa"""
    tk = tokens(name)
    out = []
    for g in guides:
        ids = set()
        for w in tk:
            ids |= g.index.get(w, set())
        for cid in ids:
            out.append((cid, g))
    return out


def resolve(name, guides):
    """(id, guia, metodo, score) si hay alta confianza, si no None"""
    tk = tokens(name)
    if not tk:
        # nombres que quedan vacios al quitar palabras genericas ("TV Chile"):
        # se comparan completos, sin quitar nada, y solo si son identicos
        full = re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize(
            "NFKD", name).encode("ascii", "ignore").decode().lower()).strip()
        for g in guides:
            for cid, disp in g.entries:
                other = re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize(
                    "NFKD", disp).encode("ascii", "ignore").decode().lower()).strip()
                if other == full:
                    return cid, g, "exacto-completo", 1.0
        return None

    # 1. mismas palabras exactas
    for g in guides:
        if tk in g.by_tokens:
            return g.by_tokens[tk], g, "exacto", 1.0

    # 2. alta similitud de palabras (Jaccard)
    best = None
    for cid, g in candidates(name, guides):
        for other_tk, other_id in g.by_tokens.items():
            if other_id != cid:
                continue
            inter = len(tk & other_tk)
            if not inter:
                continue
            jac = inter / len(tk | other_tk)
            if jac >= 0.85 and not any(t.isdigit() for t in (tk ^ other_tk)) and (best is None or jac > best[3]):
                best = (cid, g, "jaccard", jac)
    if best:
        return best

    # 3. parecido de texto, pero solo si comparten la primera palabra
    first = sorted(tk)[0]
    best = None
    for cid, g in candidates(name, guides):
        for disp_id, disp in g.entries:
            if disp_id != cid:
                continue
            dt = tokens(disp)
            shared = {w for w in (tk & dt) if len(w) >= 4}
            if not dt or not shared:
                continue
            r = difflib.SequenceMatcher(None, " ".join(sorted(tk)), " ".join(sorted(dt))).ratio()
            if r >= 0.92 and (best is None or r > best[3]):
                best = (cid, g, "parecido", r)
    return best


def suggestion(name, guides):
    """mejor candidato dudoso, para el informe"""
    tk = tokens(name)
    best = None
    for cid, g in candidates(name, guides):
        for disp_id, disp in g.entries:
            if disp_id != cid:
                continue
            dt = tokens(disp)
            if not dt:
                continue
            jac = len(tk & dt) / len(tk | dt) if (tk | dt) else 0
            r = difflib.SequenceMatcher(None, " ".join(sorted(tk)), " ".join(sorted(dt))).ratio()
            score = max(jac, r)
            if best is None or score > best[2]:
                best = (cid, disp, score)
    return best


def read_m3u(path):
    entries, header, cur = [], None, None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#EXTM3U"):
            header = s
            continue
        if s.startswith("#EXTINF"):
            m = re.match(r"#EXTINF:[^,]*,\s*(.*)$", s)
            cur = {"raw": s, "name": m.group(1).strip() if m else "", "opts": [], "url": ""}
            continue
        if s.startswith("#EXTVLCOPT") and cur is not None:
            cur["opts"].append(s)
            continue
        if s.startswith("#"):
            continue
        if cur is not None:
            cur["url"] = s
            entries.append(cur)
            cur = None
    return header or "#EXTM3U", entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--m3u", required=True)
    ap.add_argument("--epg", required=True)
    ap.add_argument("--out")
    ap.add_argument("--report")
    ap.add_argument("--write-xmltv")
    args = ap.parse_args()

    src = Path(args.m3u)
    out = Path(args.out or src.with_name(src.stem + "-epg.m3u"))
    rep = Path(args.report or src.with_name(src.stem + "-epg.csv"))

    urls = [u.strip() for u in args.epg.split(",") if u.strip()]
    guides = []
    for u in urls:
        print(f"Descargando guia: {u}")
        g = Guide(u).load()
        print(f"  {len(g.entries)} canales, {len(g.by_tokens)} nombres unicos")
        guides.append(g)

    header, entries = read_m3u(src)
    print(f"\nLista: {len(entries)} canales")

    hits, misses = [], []
    for e in entries:
        m = resolve(e["name"], guides)
        (hits if m else misses).append((e, m) if m else e)

    ids = {id(e): m[0] for e, m in hits}

    x = re.search(r'x-tvg-url="([^"]+)"', header)
    header = (header.replace(x.group(0), f'x-tvg-url="{urls[0]}"') if x
              else header + f' x-tvg-url="{urls[0]}"')

    lines = [header]
    for e in entries:
        raw = e["raw"]
        cid = ids.get(id(e))
        if cid:
            raw = (re.sub(r'tvg-id="[^"]*"', f'tvg-id="{cid}"', raw)
                   if 'tvg-id="' in raw else raw.replace("#EXTINF:-1", f'#EXTINF:-1 tvg-id="{cid}"', 1))
        else:
            raw = re.sub(r'\s*tvg-id="[^"]*"', "", raw)
        lines.append(raw)
        lines.extend(e["opts"])
        lines.append(e["url"])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with rep.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("canal;grupo;estado;tvg_id;guia;metodo;score;sugerencia\n")
        for e, m in hits:
            cid, g, method, score = m
            grp = re.search(r'group-title="([^"]*)"', e["raw"])
            f.write(f'{e["name"]};{grp.group(1) if grp else ""};OK;{cid};{g.url};{method};{score:.2f};\n')
        for e in misses:
            grp = re.search(r'group-title="([^"]*)"', e["raw"])
            s = suggestion(e["name"], guides)
            sug = f"{s[1]} [{s[0]}] ({s[2]:.2f})" if s and s[2] >= 0.75 else ""
            f.write(f'{e["name"]};{grp.group(1) if grp else ""};SIN EPG;;;sin coincidencia;;{sug}\n')

    if args.write_xmltv:
        tv = ET.Element("tv")
        for g in guides:
            tv.extend(g.root.findall("channel"))
            tv.extend(g.root.findall("programme"))
        ET.ElementTree(tv).write(args.write_xmltv, encoding="utf-8", xml_declaration=True)
        print(f"Guia unida: {args.write_xmltv}")

    por_grupo = Counter()
    for e, m in hits:
        grp = re.search(r'group-title="([^"]*)"', e["raw"])
        por_grupo[grp.group(1) if grp else "(sin grupo)"] += 1

    print(f"\nCON EPG (alta confianza): {len(hits)} de {len(entries)}")
    for g, c in sorted(por_grupo.items()):
        print(f"  {g:38} {c}")
    print(f"Sin EPG: {len(misses)}")
    print(f"\nLista : {out}")
    print(f"Informe: {rep}")
    print("\nCoincidencias:")
    for e, m in hits:
        print(f"  {e['name']:26} -> {m[0]}  ({m[2]} {m[3]:.2f})")


if __name__ == "__main__":
    main()




