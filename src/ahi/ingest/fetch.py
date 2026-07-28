"""Download every upstream source into `data/raw/` and record provenance.

Run with `python -m ahi.ingest.fetch` (add `--force` to re-download files that
are already present). Every file written is recorded in `data/raw/MANIFEST.json`
with its URL, byte size, SHA-256 and fetch timestamp, so a reader can tell
whether the numbers in the article came from the same bytes they are looking at.

World Bank series are pulled through the JSON API with `mrnev=1` ("most recent
non-empty value"), which returns the latest observation *and the year it is
from* for every economy. The vintage year matters: `ST.INT.ARVL` (tourist
arrivals) is stuck in 2019-2021 for most countries, and a pipeline that silently
mixes a 2019 tourism figure with a 2024 GDP figure should at least be able to
say so out loud. See `output/tables/data_vintages.csv`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from ..config import INDICATORS, RAW, SUPPORT_SERIES

USER_AGENT = "adjusted-henley-index/2.0 (research project; +https://github.com/spencerrjenkins/adjusted-henley-index)"
MANIFEST_PATH = RAW / "MANIFEST.json"

WB_ENDPOINT = ("https://api.worldbank.org/v2/country/all/indicator/{code}"
               "?format=json&per_page=500&mrnev=1")

OWID_SOURCES = {
    "owid_rule_of_law": "https://ourworldindata.org/grapher/rule-of-law-index.csv"
                        "?csvType=full&useColumnShortNames=true",
    "owid_electoral_democracy": "https://ourworldindata.org/grapher/electoral-democracy-index.csv"
                                "?csvType=full&useColumnShortNames=true",
}

OTHER_SOURCES = {
    "passport_index_matrix_iso3.csv": "https://raw.githubusercontent.com/imorte/passport-index-data/"
                                      "main/passport-index-matrix-iso3.csv",
    "passport_index_matrix_names.csv": "https://raw.githubusercontent.com/imorte/passport-index-data/"
                                       "main/passport-index-matrix.csv",
    "undp_hdi.csv": "https://hdr.undp.org/sites/default/files/2025_HDR/"
                    "HDR25_Composite_indices_complete_time_series.csv",
    "country_reference.json": "https://raw.githubusercontent.com/mledoze/countries/master/countries.json",
}


# ---------------------------------------------------------------------------
# HTTP + manifest plumbing
# ---------------------------------------------------------------------------
def _get(url: str, retries: int = 5, timeout: int = 90) -> bytes:
    """GET with exponential backoff.

    The World Bank API answers bursts with HTTP 400 or an XML error page rather
    than a 429, so transient throttling is indistinguishable from a bad request
    on the first try. Backing off and retrying is the only way to tell them
    apart; a genuinely bad indicator code still fails after the last attempt.
    """
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            time.sleep(3 * 2 ** attempt)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def _record(manifest: dict, name: str, url: str, payload: bytes, extra: dict | None = None) -> None:
    manifest[name] = {
        "url": url,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **(extra or {}),
    }


def _backfill(manifest: dict, path, url: str) -> None:
    """Manifest a file that was already on disk, so a cached run still yields a
    complete provenance record rather than one covering only what it re-fetched."""
    if path.name in manifest:
        return
    payload = path.read_bytes()
    _record(manifest, path.name, url, payload, {"fetched_at_note": "pre-existing file, hashed in place"})


# ---------------------------------------------------------------------------
# World Bank
# ---------------------------------------------------------------------------
def fetch_worldbank(manifest: dict, force: bool) -> None:
    """One tidy CSV per indicator: iso3, value, year, wb_name."""
    wanted = {ind.key: ind.code for ind in INDICATORS if ind.source == "worldbank"}
    wanted.update(SUPPORT_SERIES)

    for key, code in wanted.items():
        out = RAW / f"wb_{key}.csv"
        url = WB_ENDPOINT.format(code=code)
        if out.exists() and not force:
            _backfill(manifest, out, url)
            print(f"  skip   wb_{key} (cached)")
            continue

        payload = _get(url)
        try:
            body = json.loads(payload)
        except json.JSONDecodeError as exc:
            # The API intermittently answers with an XML error page under load.
            raise RuntimeError(f"World Bank returned non-JSON for {code}: "
                               f"{payload[:120]!r}") from exc
        if not isinstance(body, list) or len(body) < 2 or body[1] is None:
            raise RuntimeError(f"World Bank returned no data for {code}: {body[:1]}")

        rows = [
            {
                "iso3": rec["countryiso3code"],
                "value": rec["value"],
                "year": int(rec["date"]) if rec["date"] else None,
                "wb_name": rec["country"]["value"],
            }
            for rec in body[1]
            if rec.get("countryiso3code") and rec.get("value") is not None
        ]
        df = pd.DataFrame(rows).sort_values("iso3")
        df.to_csv(out, index=False)
        _record(manifest, out.name, url, payload,
                {"indicator_code": code, "rows": len(df),
                 "vintage_min": int(df["year"].min()), "vintage_max": int(df["year"].max()),
                 "vintage_median": int(df["year"].median())})
        print(f"  ok     wb_{key:<18} {len(df):>3} economies, "
              f"vintages {df['year'].min()}-{df['year'].max()}")
        time.sleep(0.7)  # the API rate-limits into XML error pages under bursts


# ---------------------------------------------------------------------------
# Everything else
# ---------------------------------------------------------------------------
def fetch_plain(manifest: dict, force: bool, sources: dict[str, str], suffix: str) -> None:
    for name, url in sources.items():
        out = RAW / f"{name}{suffix}"
        if out.exists() and not force:
            _backfill(manifest, out, url)
            print(f"  skip   {name} (cached)")
            continue
        payload = _get(url)
        out.write_bytes(payload)
        _record(manifest, out.name, url, payload)
        print(f"  ok     {name:<28} {len(payload) / 1024:>8.0f} KB")


WB_COUNTRY_META = "https://api.worldbank.org/v2/country?format=json&per_page=400"


def fetch_worldbank_metadata(manifest: dict, force: bool) -> None:
    """Region and income group per economy -- the grouping keys used to impute
    missing indicator values from peers rather than from the global median."""
    out = RAW / "wb_country_meta.csv"
    if out.exists() and not force:
        _backfill(manifest, out, WB_COUNTRY_META)
        print("  skip   wb_country_meta (cached)")
        return
    payload = _get(WB_COUNTRY_META)
    body = json.loads(payload)
    rows = [
        {
            "iso3": rec["id"],
            "wb_name": rec["name"],
            "region": (rec.get("region") or {}).get("value"),
            "income_group": (rec.get("incomeLevel") or {}).get("value"),
            "capital": rec.get("capitalCity"),
        }
        for rec in body[1]
        if (rec.get("region") or {}).get("value") not in (None, "Aggregates")
    ]
    df = pd.DataFrame(rows).sort_values("iso3")
    df.to_csv(out, index=False)
    _record(manifest, out.name, WB_COUNTRY_META, payload, {"rows": len(df)})
    print(f"  ok     wb_country_meta       {len(df)} economies")


def build_country_reference(manifest: dict) -> None:
    """Flatten mledoze/countries into the geography + language columns we use.

    Gives us centroids (for great-circle distance analysis), land area,
    landlockedness, land borders, UN region/subregion, and official languages --
    from which we derive the `english_official` flag used in the language-access
    discussion. None of this is available in a single World Bank series.
    """
    src = RAW / "country_reference.json"
    records = json.loads(src.read_text())
    rows = []
    for rec in records:
        latlng = rec.get("latlng") or [None, None]
        languages = rec.get("languages") or {}
        rows.append({
            "iso3": rec.get("cca3"),
            "country_name": (rec.get("name") or {}).get("common"),
            "lat": latlng[0] if len(latlng) > 0 else None,
            "lon": latlng[1] if len(latlng) > 1 else None,
            "land_area_km2": rec.get("area"),
            "landlocked": bool(rec.get("landlocked", False)),
            "n_land_borders": len(rec.get("borders") or []),
            "un_region": rec.get("region"),
            "un_subregion": rec.get("subregion"),
            "languages": "|".join(sorted(languages.values())),
            "english_official": any(v.lower() == "english" for v in languages.values()),
            "independent": bool(rec.get("independent", False)),
            "un_member": bool(rec.get("unMember", False)),
        })
    df = pd.DataFrame(rows).dropna(subset=["iso3"]).sort_values("iso3")
    out = RAW / "country_reference.csv"
    df.to_csv(out, index=False)
    manifest[out.name] = {
        "url": "derived from country_reference.json",
        "bytes": out.stat().st_size,
        "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rows": len(df),
    }
    print(f"  ok     country_reference.csv        {len(df)} countries")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download cached files")
    args = parser.parse_args()

    manifest = _load_manifest()
    print("World Bank indicators")
    fetch_worldbank(manifest, args.force)
    fetch_worldbank_metadata(manifest, args.force)
    print("Our World in Data series")
    fetch_plain(manifest, args.force, OWID_SOURCES, ".csv")
    print("Other sources")
    fetch_plain(manifest, args.force, OTHER_SOURCES, "")
    build_country_reference(manifest)

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"\nManifest: {MANIFEST_PATH.relative_to(RAW.parents[1])} "
          f"({len(manifest)} files)")


if __name__ == "__main__":
    main()
