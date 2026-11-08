"""Haalt SolarEdge- en Frank Energie-data op en schrijft data/energie.json.

  python haal_data_op.py           data ophalen
  python haal_data_op.py --serve   dashboard op http://127.0.0.1:8000, met formulier om de API-key op te slaan
  python haal_data_op.py --test    korte zelftest

API-key en site-ID staan in .env (SOLAREDGE_API_KEY, SOLAREDGE_SITE_ID). Dat bestand gaat nooit naar git.
Alleen standaardbibliotheek, geen pip install nodig.
"""
import calendar
import json
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAP = Path(__file__).resolve().parent
ENV = MAP / ".env"
UIT = MAP / "data" / "energie.json"
H = 8760
POORT = 8000
FRANK = "https://graphql.frankenergie.nl"
FRANK_Q = ("query MarketPrices($date: String!, $resolution: PriceResolution!){ marketPrices(date:$date, resolution:$resolution){"
           " electricityPrices{ from marketPrice sourcingMarkupPrice energyTaxPrice } gasPrices{ from allInPrice } } }")
SE = "https://monitoringapi.solaredge.com"


def lees_env():
    if not ENV.exists():
        return {}
    regels = (r.split("=", 1) for r in ENV.read_text(encoding="utf-8").splitlines() if "=" in r and not r.startswith("#"))
    return {k.strip(): v.strip().strip('"') for k, v in regels}


def schrijf_env(key, site):
    ENV.write_text(f"SOLAREDGE_API_KEY={key}\nSOLAREDGE_SITE_ID={site}\n", encoding="utf-8")


def uur_index(t):
    """Plek van een lokaal uur in een jaar van 8760 uur (1 jan 00:00 = 0). 29 februari geeft None."""
    if t.month == 2 and t.day == 29:
        return None
    dag = t.timetuple().tm_yday - 1
    if calendar.isleap(t.year) and t.month > 2:
        dag -= 1
    return dag * 24 + t.hour


def get_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "Energiebalans"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def frank_dag(d):
    body = json.dumps({"operationName": "MarketPrices", "query": FRANK_Q,
                       "variables": {"date": d.isoformat(), "resolution": "PT60M"}}).encode()
    return get_json(FRANK, body)["data"]["marketPrices"]


def haal_frank(dagen):
    stroom, gas = [None] * H, []
    laatste = {}
    with ThreadPoolExecutor(8) as pool:
        for d, mp in zip(dagen, pool.map(frank_dag, dagen)):
            for p in mp["electricityPrices"]:
                # ponytail: UTC -> lokale tijd van deze pc (staat op NL). Andere tijdzone? Gebruik zoneinfo.
                i = uur_index(datetime.fromisoformat(p["from"].replace("Z", "+00:00")).astimezone())
                if i is not None:
                    stroom[i] = p["marketPrice"]
                laatste = p
            gas += [p["allInPrice"] for p in mp["gasPrices"]]
    return {"prijs_stroom": stroom,
            "energiebelasting": laatste.get("energyTaxPrice"),
            "inkoopkosten": laatste.get("sourcingMarkupPrice"),
            "gasprijs": round(sum(gas) / len(gas), 4) if gas else None}


def se(pad, key, **params):
    return get_json(f"{SE}{pad}?" + urllib.parse.urlencode({**params, "api_key": key}))


def haal_solaredge(key, site, start, eind):
    uit = {"opbrengst_kwh": [None] * H, "verbruik_kwh": [None] * H}
    soort = {"Production": "opbrengst_kwh", "Consumption": "verbruik_kwh"}
    m = start.replace(day=1)
    while m <= eind:  # uurdata: max. één maand per verzoek
        volgende = (m + timedelta(days=32)).replace(day=1)
        van, tot = max(m, start), min(volgende - timedelta(days=1), eind)
        r = se(f"/site/{site}/energyDetails", key, meters="Production,Consumption", timeUnit="HOUR",
               startTime=f"{van} 00:00:00", endTime=f"{tot} 23:59:59")
        for meter in r["energyDetails"]["meters"]:
            reeks = uit.get(soort.get(meter["type"]))
            if reeks is None:
                continue
            for v in meter["values"]:
                i = uur_index(datetime.strptime(v["date"], "%Y-%m-%d %H:%M:%S"))
                if i is not None and v.get("value") is not None:
                    reeks[i] = round(v["value"] / 1000, 4)  # Wh -> kWh
        m = volgende
    try:
        uit["kwp"] = se(f"/site/{site}/details", key)["details"]["peakPower"]
    except Exception:
        uit["kwp"] = None
    return uit


def haal_op():
    eind = date.today() - timedelta(days=1)
    start = eind - timedelta(days=365)  # 366 dagen: elke kalenderdag zit erin, ook als er een 29 februari tussen zit
    dagen = [start + timedelta(days=n) for n in range(366)]
    print(f"Frank Energie prijzen {start} t/m {eind} ...")
    data = {"gemaakt": datetime.now().isoformat(timespec="seconds"), "van": str(start), "tot": str(eind), **haal_frank(dagen)}
    env = lees_env()
    key, site = env.get("SOLAREDGE_API_KEY"), env.get("SOLAREDGE_SITE_ID")
    if key and site:
        print("SolarEdge opbrengst en verbruik ...")
        data.update(haal_solaredge(key, site, start, eind))
    else:
        print("Geen SolarEdge-gegevens in .env, alleen prijzen opgehaald.")
    UIT.parent.mkdir(exist_ok=True)
    UIT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"Geschreven: {UIT}")
    return data


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(MAP), **k)

    def eigen_herkomst(self):
        # Alleen verzoeken van deze pagina zelf (geen andere websites, geen DNS-rebinding).
        goed = {f"127.0.0.1:{POORT}", f"localhost:{POORT}"}
        herkomst = urllib.parse.urlparse(self.headers.get("Origin", "")).netloc
        return self.headers.get("Host") in goed and herkomst in goed

    def antwoord(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        pad = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
        if any(deel.startswith(".") for deel in re.split(r"[/\\]", pad)):  # nooit .env of .git uitserveren
            return self.send_error(404)
        if pad == "/api/status":
            env = lees_env()
            return self.antwoord(200, {"lokaal": True, "gekoppeld": bool(env.get("SOLAREDGE_API_KEY") and env.get("SOLAREDGE_SITE_ID"))})
        super().do_GET()

    do_HEAD = do_GET

    def do_POST(self):
        if self.path != "/api/koppel" or not self.eigen_herkomst():
            return self.send_error(403)
        try:
            v = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4096)) or b"{}")
            key, site = str(v.get("key", "")).strip(), str(v.get("site", "")).strip()
            if key or site:
                if not re.fullmatch(r"[A-Za-z0-9]{16,64}", key) or not re.fullmatch(r"\d{1,12}", site):
                    return self.antwoord(400, {"fout": "API-key (letters en cijfers) of site-ID (alleen cijfers) klopt niet."})
                se(f"/site/{site}/details", key)  # eerst controleren, dan pas opslaan
                schrijf_env(key, site)
            haal_op()
            return self.antwoord(200, {"ok": True})
        except urllib.error.HTTPError as e:
            return self.antwoord(400, {"fout": f"SolarEdge weigert ({e.code}). Controleer API-key en site-ID."})
        except Exception as e:
            return self.antwoord(500, {"fout": f"Ophalen mislukt: {type(e).__name__}"})


def test():
    assert uur_index(datetime(2025, 1, 1, 0)) == 0
    assert uur_index(datetime(2025, 12, 31, 23)) == H - 1
    assert uur_index(datetime(2024, 12, 31, 23)) == H - 1  # schrikkeljaar
    assert uur_index(datetime(2024, 3, 1, 0)) == 59 * 24
    assert uur_index(datetime(2024, 2, 29, 5)) is None
    print("zelftest ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    elif "--serve" in sys.argv:
        print(f"Dashboard: http://127.0.0.1:{POORT}/  (stoppen met Ctrl+C)")
        ThreadingHTTPServer(("127.0.0.1", POORT), Handler).serve_forever()
    else:
        haal_op()
