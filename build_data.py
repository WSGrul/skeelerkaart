#!/usr/bin/env python3
"""Maakt compacte kaartdata (fietspaden met ondergrond en kwaliteit) uit Geofabrik-extracten.

Regio's staan in de omgevingsvariabele REGIONS (spatie-gescheiden Geofabrik-paden),
bijvoorbeeld: "europe/netherlands/zuid-holland" of "europe/netherlands".
"""
import datetime, json, math, os, shutil, subprocess, sys, time, urllib.request

REGIONS = os.environ.get("REGIONS", "europe/netherlands/zuid-holland").split()
DY, DX = 0.1, 0.15            # blokgrootte in graden (ca. 11 x 10 km)
OUT, TMP = "data", "tmp"
HW = {"cycleway": "c", "path": "p", "footway": "f"}
# Gedeelde wegen waar je kunt skeeleren (geen snelwegen of drukke provinciale wegen).
ROADS = ("residential", "living_street", "unclassified", "tertiary", "secondary")

def run(cmd):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)

def download(region):
    url = f"https://download.geofabrik.de/{region}-latest.osm.pbf"
    dest = os.path.join(TMP, region.replace("/", "_") + ".osm.pbf")
    for _ in range(3):
        try:
            print("Downloaden", url, flush=True)
            req = urllib.request.Request(url, headers={"User-Agent": "skeelerkaart-build"})
            with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            return dest
        except Exception as e:
            print("  mislukt:", e, flush=True)
            time.sleep(15)
    sys.exit("Download mislukt: " + url)

def features(pbf):
    filt, gj = pbf + ".filtered.pbf", pbf + ".geojsonseq"
    run(["osmium", "tags-filter", "--overwrite", "-o", filt, pbf,
         "w/highway=cycleway", "w/highway=path", "w/highway=footway"]
        + ["w/highway=" + r for r in ROADS])
    run(["osmium", "export", "--overwrite", "-f", "geojsonseq",
         "--geometry-types=linestring", "-u", "type_id", "-o", gj, filt])
    with open(gj, encoding="utf-8") as f:
        for line in f:
            line = line.strip("\x1e \n")
            if line:
                yield json.loads(line)

def main():
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(os.path.join(OUT, "r"))
    os.makedirs(TMP, exist_ok=True)
    chunks, rchunks = {}, {}
    for region in REGIONS:
        pbf = download(region)
        for ft in features(pbf):
            p = ft.get("properties") or {}
            hw = p.get("highway")
            # Fietspaden, plus paden/voetpaden die expliciet voor fietsers zijn aangewezen.
            if hw == "cycleway" or (hw in ("path", "footway") and p.get("bicycle") == "designated"):
                target, code = chunks, HW[hw]
            elif (hw in ROADS and p.get("access") not in ("no", "private")
                  and p.get("bicycle") != "no" and p.get("motorroad") != "yes"):
                target, code = rchunks, hw
            else:
                continue
            try:
                wid = int(str(ft["id"]).lstrip("w"))
                coords = ft["geometry"]["coordinates"]
            except (KeyError, ValueError):
                continue
            flat = []
            for lon, lat in coords:
                flat += [round(lat, 5), round(lon, 5)]
            if len(flat) < 4:
                continue
            rec = [wid, code, p.get("surface", ""), p.get("smoothness", ""), p.get("name", ""), flat]
            if target is rchunks:
                rec.append(p.get("maxspeed", ""))
            for c in {(math.floor(flat[i] / DY), math.floor(flat[i + 1] / DX)) for i in range(0, len(flat), 2)}:
                target.setdefault(c, {})[wid] = rec
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP)

    index = {"updated": datetime.date.today().isoformat(), "regions": REGIONS, "dy": DY, "dx": DX,
             "chunks": {}, "rchunks": {}}
    uniq, runiq = {}, {}
    for src, sub, key_index, allw in ((chunks, "", "chunks", uniq), (rchunks, "r", "rchunks", runiq)):
        for (y, x), d in src.items():
            key = f"{y}_{x}"
            with open(os.path.join(OUT, sub, key + ".json"), "w", encoding="utf-8") as f:
                json.dump({"w": list(d.values())}, f, separators=(",", ":"), ensure_ascii=False)
            index[key_index][key] = len(d)
            allw.update(d)
    asph = [r for r in uniq.values() if r[2] == "asphalt"]
    rasph = [r for r in runiq.values() if r[2] == "asphalt"]
    index["stats"] = {"ways": len(uniq), "asphalt": len(asph), "asphalt_quality": sum(1 for r in asph if r[3]),
                      "roads": len(runiq), "roads_asphalt": len(rasph)}
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, separators=(",", ":"))
    shutil.rmtree(TMP, ignore_errors=True)
    print("Klaar:", index["stats"], len(chunks), "+", len(rchunks), "blokken")

if __name__ == "__main__":
    main()
