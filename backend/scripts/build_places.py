"""Build app/normalization/places.tsv.gz, the place index used to tell where a card payment took place.

Source: GeoNames "cities15000" (every town with at least 15,000 inhabitants) and "countryInfo",
https://download.geonames.org/export/dump/ — licensed CC BY 4.0, https://www.geonames.org.

    python scripts/build_places.py cities15000.txt countryInfo.txt

Output: one line per town, most likely first, "COUNTRY<TAB>Name<TAB>KEY<TAB>KEY...". The keys are the
normalized spellings a statement may print (see app.normalization.location.place_key). A key listed
by an earlier line wins; the order prefers official names over alternate names, then towns in
Germany, then the rest of Europe, then population.
"""
from __future__ import annotations

import gzip
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.normalization.location import place_key  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[1] / "app" / "normalization" / "places.tsv.gz"
# German names for the few German-speaking towns GeoNames lists under their English name.
GERMAN_NAMES = {"Munich": "München", "Nuremberg": "Nürnberg", "Vienna": "Wien", "Cologne": "Köln"}
# Alternate names only in a Latin script; transcriptions from other scripts don't appear on statements.
_LATIN_NAME = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ' .\-]{3,40}")


def build(cities: Path, country_info: Path) -> list[str]:
    europe = set()
    for line in country_info.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if not line.startswith("#") and len(parts) > 8 and parts[8] == "EU":
            europe.add(parts[0])
    towns = []
    for line in cities.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        name, ascii_name, alternates, feature, country, population = f[1], f[2], f[3], f[7], f[8], int(f[14] or 0)
        if feature == "PPLX":  # a district of a city ("Mitte", "Centro"): statements print the city
            continue
        bias = 1000 if country == "DE" else 50 if country in europe else 1
        own = {place_key(name), place_key(ascii_name)} - {""}
        other = {place_key(a) for a in alternates.split(",") if _LATIN_NAME.fullmatch(a)} - own - {""}
        towns.append((population * bias, country, GERMAN_NAMES.get(name, name), own, other))
    towns.sort(key=lambda t: -t[0])
    seen: set[str] = set()
    lines = []
    # Official names of all towns first, then their alternate names, so that an alternate name
    # ("Monaco" for Munich in Italian) never shadows another town's own name.
    rows: dict[int, list[str]] = {i: [] for i in range(len(towns))}
    for tier in (3, 4):
        for i, town in enumerate(towns):
            for key in sorted(town[tier]):
                if key not in seen and re.search(r"[A-Z]", key) and len(key) >= 3:
                    seen.add(key)
                    rows[i].append(key)
    for i, (_weight, country, name, _own, _other) in enumerate(towns):
        if rows[i]:
            lines.append("\t".join([country, name, *rows[i]]))
    return lines


def main() -> None:
    cities, country_info = (Path(a) for a in sys.argv[1:3])
    lines = build(cities, country_info)
    with gzip.GzipFile(OUTPUT, "wb", mtime=0) as raw:  # mtime 0: identical input, identical file
        raw.write(("\n".join(lines) + "\n").encode("utf-8"))
    print(f"{len(lines)} towns -> {OUTPUT}")


if __name__ == "__main__":
    main()
