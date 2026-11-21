#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Legge i bollettini nivometrici della Valle d'Aosta (Centro Funzionale VdA)
e produce neve-vda.json con l'altezza neve al suolo piu' recente per stazione.

Fonte: https://cf.regione.vda.it/allegati/bollettini/dettaglio/nivometri_Zona_{A,B,C,D}.pdf
I PDF sono testuali: estraggo il testo e lo analizzo con regex tolleranti,
cosi' se cambia l'impaginazione grafica il parsing regge comunque.

Uso:
    python3 parse_vda.py            # scarica i PDF e scrive neve-vda.json
    python3 parse_vda.py --self-test  # esegue il test interno sul campione
"""

import io
import json
import re
import sys
import datetime
import urllib.request

ZONE = ["A", "B", "C", "D"]
URL = "https://cf.regione.vda.it/allegati/bollettini/dettaglio/nivometri_Zona_{}.pdf"

# Un blocco stazione inizia con il nome (riga di testo), seguito entro poche
# righe da "Quota: NNN m" e "Coordinate WGS84: latitudine LAT; longitudine LON".
# Poi una tabella di righe "GG - HH:MM  T  H" (H = altezza neve in cm, puo' mancare).

RE_QUOTA = re.compile(r"Quota\s*:?\s*([0-9]{3,4})\s*m", re.I)
RE_COORD = re.compile(
    r"latitudine\s+([0-9]+\.[0-9]+)\s*;\s*longitudine\s+([0-9]+\.[0-9]+)", re.I
)
# riga tabella: "13 - 15:00 1.3 47.0"  oppure solo temp "13 - 15:00 2.3"
RE_ROW = re.compile(
    r"^\s*([0-9]{1,2})\s*-\s*([0-9]{1,2}):([0-9]{2})\s+"
    r"(-?[0-9]+(?:\.[0-9]+)?)"          # temperatura
    r"(?:\s+(-?[0-9]+(?:\.[0-9]+)?))?"  # altezza neve (opzionale)
    r"\s*$"
)
# nome stazione: "Luogo - Localita'" con una lettera maiuscola iniziale,
# non deve essere una riga di intestazione/legenda.
RE_NOME = re.compile(r"^[A-ZÀ-Ý][A-Za-zÀ-ÿ'’\.\s]+-\s+[A-ZÀ-Ý][A-Za-zÀ-ÿ'’\.\s0-9]+$")
SKIP = re.compile(
    r"dettaglio|indice|zona|centro funzionale|ultime|giorno|torna|coordinate|"
    r"grafico|tabella|quota|wgs84|s\.l\.m|pagina|ora locale",
    re.I,
)


def estrai_testo(pdf_bytes):
    """Testo lineare del PDF. Prova pdfplumber, poi pypdf come ripiego."""
    try:
        import pdfplumber
        out = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for pg in pdf.pages:
                t = pg.extract_text() or ""
                out.append(t)
        return "\n".join(out)
    except Exception:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join((p.extract_text() or "") for p in r.pages)


def parse_testo(testo):
    """Ritorna una lista di stazioni {nome, quota, lat, lon, neve, ora}."""
    righe = [r.rstrip() for r in testo.splitlines()]
    staz = []
    cur = None

    def chiudi(c):
        if c and c.get("neve") is not None and c.get("lat") is not None:
            staz.append(c)

    for i, r in enumerate(righe):
        s = r.strip()
        if not s:
            continue

        mrow = RE_ROW.match(s)
        if mrow and cur is not None:
            h = mrow.group(5)
            if h is not None:
                gg, hh, mm = mrow.group(1), mrow.group(2), mrow.group(3)
                cur["neve"] = float(h)        # l'ultima riga con H vince
                cur["_gg"] = int(gg)
                cur["_hh"] = f"{int(hh):02d}:{mm}"
            continue

        mq = RE_QUOTA.search(s)
        if mq and cur is not None and cur.get("quota") is None:
            cur["quota"] = int(mq.group(1))
            continue

        mc = RE_COORD.search(s)
        if mc and cur is not None and cur.get("lat") is None:
            cur["lat"] = float(mc.group(1))
            cur["lon"] = float(mc.group(2))
            continue

        # possibile nome stazione -> apre un nuovo blocco
        if RE_NOME.match(s) and not SKIP.search(s) and len(s) <= 60:
            chiudi(cur)
            cur = {"nome": re.sub(r"\s+", " ", s), "quota": None,
                   "lat": None, "lon": None, "neve": None}
            continue

    chiudi(cur)
    return staz


def main():
    oggi = datetime.date.today()
    tutte = []
    errori = []
    for z in ZONE:
        url = URL.format(z)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "meteo-limone/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            testo = estrai_testo(data)
            st = parse_testo(testo)
            for s in st:
                s["zona"] = z
            tutte.extend(st)
            print(f"Zona {z}: {len(st)} stazioni con neve", file=sys.stderr)
        except Exception as e:
            errori.append(f"Zona {z}: {e}")
            print(f"Zona {z}: ERRORE {e}", file=sys.stderr)

    # deduplica per nome (tiene la quota piu' alta / prima occorrenza)
    visti = {}
    for s in tutte:
        k = s["nome"].lower()
        if k not in visti:
            visti[k] = s
    stazioni = sorted(visti.values(), key=lambda x: x["nome"])

    out = {
        "aggiornato": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "fonte": "Centro Funzionale Valle d'Aosta - bollettini nivometrici",
        "stazioni": [
            {
                "nome": s["nome"],
                "quota": s.get("quota"),
                "lat": s["lat"],
                "lon": s["lon"],
                "neve": s["neve"],
            }
            for s in stazioni
        ],
    }
    if errori:
        out["errori"] = errori

    with open("neve-vda.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"Scritte {len(out['stazioni'])} stazioni in neve-vda.json", file=sys.stderr)
    # exit !=0 solo se non ho preso NIENTE (cosi' l'Action non committa il vuoto)
    return 0 if out["stazioni"] else 1


# ---------------------------------------------------------------------------
CAMPIONE = """DETTAGLIO DATI STAZIONI ULTIME ORE
13 gennaio 2026 - 15:18

La Thuile - Villaret

Quota: 1488 m s.l.m.
Coordinate WGS84: latitudine 45.7095; longitudine 6.95609.

Ultime 24 ore (ora locale)

Giorno-Ora T(C) H(cm)

13 - 09:00 -0.5 48.0
13 - 10:00 0.2 47.0
13 - 14:00 1.0 45.0
13 - 15:00 1.3 47.0

Torna all'indice

DETTAGLIO DATI STAZIONI ULTIME ORE
13 gennaio 2026 - 15:18

Bionaz - Place Moulin

Quota: 1979 m s.l.m.
Coordinate WGS84: latitudine 45.8997; longitudine 7.49137.

12 - 16:00 0.8 68.0
13 - 15:00 0.0 64.0

Torna all'indice

Valtournenche - Maen

Quota: 1310 m s.l.m.
Coordinate WGS84: latitudine 45.8626; longitudine 7.61112.

13 - 14:00 2.3
13 - 15:00 2.2

Torna all'indice
"""


def self_test():
    st = parse_testo(CAMPIONE)
    by = {s["nome"]: s for s in st}
    assert "La Thuile - Villaret" in by, "manca La Thuile"
    assert abs(by["La Thuile - Villaret"]["neve"] - 47.0) < 1e-6, by["La Thuile - Villaret"]
    assert by["La Thuile - Villaret"]["quota"] == 1488
    assert abs(by["La Thuile - Villaret"]["lat"] - 45.7095) < 1e-6
    assert "Bionaz - Place Moulin" in by
    assert abs(by["Bionaz - Place Moulin"]["neve"] - 64.0) < 1e-6
    # Valtournenche - Maen ha solo temperatura, niente H -> va scartata
    assert "Valtournenche - Maen" not in by, "Maen non doveva avere neve"
    print("SELF-TEST OK:", {k: v["neve"] for k, v in by.items()})


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        sys.exit(main())
