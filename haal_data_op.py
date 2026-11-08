"""Energiebalans: haalt SolarEdge- en Frank Energie-data op, draait in GitHub Actions.

Veiligheid:
- Je instellingen (SolarEdge-app, Frank-login, wachtwoord) vul je in op het dashboard. De browser versleutelt ze
  met de publieke sleutel; ze komen als invoer/*.json in de repo. Alleen de workflow kan ze lezen, met PRIVE_SLEUTEL
  uit GitHub Secrets. Daarna bewaart de workflow ze, weer versleuteld, in instellingen.enc.
- De data zelf staat in energie.enc, versleuteld met jouw wachtwoord. status.json is openbaar en bevat geen gegevens.

  python haal_data_op.py            ophalen (in GitHub Actions, met PRIVE_SLEUTEL in de omgeving)
  python haal_data_op.py --sleutel  eenmalig: nieuw sleutelpaar; privé-deel naar GitHub Secrets, publiek deel in index.html
  python haal_data_op.py --test     zelftest
"""
import base64
import calendar
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAP = Path(__file__).resolve().parent
INST = MAP / "instellingen.enc"
INVOER = MAP / "invoer"
ENC = MAP / "energie.enc"
STATUS = MAP / "status.json"
REPO = "hermanvandenberg/Energiebalans"
REDIRECT = "https://hermanvandenberg.github.io/Energiebalans/"  # zelfde als bij je SolarEdge-app
ITER = 600_000  # PBKDF2-SHA256, zelfde getal staat in index.html
H = 8760
FRANK = "https://graphql.frankenergie.nl"
FRANK_PRIJS = ("query MarketPrices($date: String!, $resolution: PriceResolution!){ marketPrices(date:$date, resolution:$resolution){"
               " electricityPrices{ from marketPrice sourcingMarkupPrice energyTaxPrice } gasPrices{ from allInPrice } } }")
SE = "https://monitoringapi.solaredge.com/v2"
SE_PAUZE = 6.5  # gratis: max. 10 aanroepen per minuut
OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
b64e = lambda b: base64.b64encode(b).decode()
b64d = base64.b64decode


# ---------- versleuteling ----------

def hybride_uit(priv, blob):
    """Ontsleutelt wat de browser met de publieke sleutel versleutelde (RSA-OAEP + AES-GCM)."""
    sleutel = priv.decrypt(b64d(blob["k"]), OAEP)
    return json.loads(AESGCM(sleutel).decrypt(b64d(blob["iv"]), b64d(blob["data"]), None))


def hybride_in(pub, obj):
    sleutel, iv = AESGCM.generate_key(256), os.urandom(12)
    return {"k": b64e(pub.encrypt(sleutel, OAEP)), "iv": b64e(iv),
            "data": b64e(AESGCM(sleutel).encrypt(iv, json.dumps(obj).encode(), None))}


def ww_sleutel(ww, salt):
    return hashlib.pbkdf2_hmac("sha256", ww.encode(), salt, ITER)


def ww_in(tekst, ww, salt):
    iv = os.urandom(12)
    return {"salt": b64e(salt), "iv": b64e(iv), "data": b64e(AESGCM(ww_sleutel(ww, salt)).encrypt(iv, tekst.encode(), None))}


def ww_uit(blob, ww):
    return json.loads(AESGCM(ww_sleutel(ww, b64d(blob["salt"]))).decrypt(b64d(blob["iv"]), b64d(blob["data"]), None))


# ---------- tijd ----------

def uur_index(t):
    """Plek van een lokaal uur in een jaar van 8760 uur (1 jan 00:00 = 0). 29 februari geeft None."""
    if t.month == 2 and t.day == 29:
        return None
    dag = t.timetuple().tm_yday - 1
    if calendar.isleap(t.year) and t.month > 2:
        dag -= 1
    return dag * 24 + t.hour


def lokaal(ts):
    # ponytail: lokale tijd = tijdzone van de machine; de workflow zet TZ=Europe/Amsterdam.
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()


# ---------- http ----------

def http(url, body=None, token=None):
    h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Energiebalans"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    for poging in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            wacht = e.headers.get("retry-after")
            if e.code == 429 and wacht and poging < 2:  # te snel: wachten en opnieuw
                time.sleep(int(wacht) + 1)
                continue
            fout = e.read().decode(errors="replace")[:200]
            raise RuntimeError(f"HTTP {e.code}: {fout}") from None


def frank(query, variables=None, token=None):
    r = http(FRANK, {"query": query, "variables": variables or {}}, token)
    if r.get("errors"):
        raise RuntimeError(r["errors"][0]["message"])
    return r["data"]


# ---------- Frank Energie ----------

def haal_frank_prijzen(dagen):
    stroom, gas, laatste = [None] * H, [], {}
    with ThreadPoolExecutor(8) as pool:
        for mp in pool.map(lambda d: frank(FRANK_PRIJS, {"date": d.isoformat(), "resolution": "PT60M"})["marketPrices"], dagen):
            for p in mp["electricityPrices"]:
                i = uur_index(lokaal(p["from"]))
                if i is not None:
                    stroom[i] = p["marketPrice"]
                laatste = p
            gas += [p["allInPrice"] for p in mp["gasPrices"]]
    return {"prijs_stroom": stroom, "energiebelasting": laatste.get("energyTaxPrice"),
            "inkoopkosten": laatste.get("sourcingMarkupPrice"), "gasprijs": round(sum(gas) / len(gas), 4) if gas else None}


def haal_frank_gas(email, ww, dagen):
    """Eigen gasverbruik via je Frank-account (API niet officieel gedocumenteerd)."""
    token = frank("mutation L($email: String!, $password: String!){ login(email:$email, password:$password){ authToken } }",
                  {"email": email, "password": ww})["login"]["authToken"]
    site = frank("query { userSites { reference } }", token=token)["userSites"][0]["reference"]
    q = "query P($date: String!, $s: String!){ periodUsageAndCosts(date:$date, siteReference:$s){ gas { usageTotal } } }"

    def dag(d):
        try:
            return frank(q, {"date": d.isoformat(), "s": site}, token)["periodUsageAndCosts"]["gas"]["usageTotal"]
        except Exception:
            return None  # bv. een dag van voor je contract

    with ThreadPoolExecutor(8) as pool:
        per_dag = [v for v in pool.map(dag, dagen) if v is not None]
    if len(per_dag) < 300:
        raise RuntimeError(f"maar {len(per_dag)} dagen gasverbruik")
    return {"gas_m3": round(sum(per_dag) * 365 / len(per_dag))}


# ---------- SolarEdge (Monitoring API v2, OAuth) ----------

def se_token(st):
    if st.get("se_code"):  # net toestemming gegeven: code inwisselen (kan maar één keer)
        body = {"grant_type": "authorization_code", "code": st.pop("se_code"), "redirect_uri": REDIRECT}
    else:
        body = {"grant_type": "refresh_token", "refresh_token": st["se_refresh"]}
    r = http(f"{SE}/oauth2/token", {**body, "client_id": st["se_client_id"], "client_secret": st["se_client_secret"]})
    st["se_refresh"] = r["refresh_token"]  # elke keer een nieuwe; de oude werkt niet meer
    return r["access_token"]


def haal_solaredge(st, oud, eind):
    """Vult het jaar aan met de dagen die nog ontbreken. Max. 24 uur per aanroep, dus de eerste keer ~365 aanroepen."""
    token, site = se_token(st), st["se_site"]
    uit = {k: oud.get(k) or [None] * H for k in ("opbrengst_kwh", "verbruik_kwh")}
    uit["kwp"] = http(f"{SE}/sites/{site}", token=token).get("peakPower") or oud.get("kwp")
    van = max(eind - timedelta(days=364), date.fromisoformat(oud["se_tot"]) + timedelta(days=1) if oud.get("se_tot") else date.min)
    uit["se_tot"] = oud.get("se_tot")
    d = van
    while d <= eind:
        time.sleep(SE_PAUZE)
        begin = datetime(d.year, d.month, d.day).astimezone()
        q = urllib.parse.urlencode({"from": begin.isoformat(), "to": (begin + timedelta(hours=24)).isoformat(), "resolution": "HOUR"})
        meters = http(f"{SE}/sites/{site}/meters/telemetry?{q}", token=token).get("meters") or {}
        for veld, sleutel in (("productionEnergy", "opbrengst_kwh"), ("consumptionEnergy", "verbruik_kwh")):
            som = {}
            for m in meters.values():  # meerdere meters: optellen
                for v in (m.get(veld) or {}).get("values", []):
                    if v.get("value") is not None:
                        som[v["timestamp"]] = som.get(v["timestamp"], 0) + v["value"]
            for ts, wh in som.items():
                i = uur_index(lokaal(ts))
                if i is not None:
                    uit[sleutel][i] = round(wh / 1000, 4)
        uit["se_tot"] = d.isoformat()
        d += timedelta(days=1)
    return uit


# ---------- hoofdlijn ----------

def git(*a):
    return subprocess.run(["git", *a], cwd=MAP, capture_output=True, text=True)


def run():
    priv = serialization.load_pem_private_key(os.environ["PRIVE_SLEUTEL"].encode(), None)
    st = hybride_uit(priv, json.loads(INST.read_text())) if INST.exists() else {}
    # Oude data eerst openen met het oude wachtwoord: dan hoeft SolarEdge niet alles opnieuw.
    oud = {}
    if ENC.exists() and st.get("wachtwoord"):
        try:
            oud = ww_uit(json.loads(ENC.read_text()), st["wachtwoord"])
        except Exception:
            pass
    invoer = sorted(INVOER.glob("*.json")) if INVOER.exists() else []
    for f in invoer:
        nieuw = {k: v for k, v in hybride_uit(priv, json.loads(f.read_text())).items() if v}
        if "se_code" in nieuw:
            st.pop("se_refresh", None)
        if nieuw.get("se_site") and nieuw["se_site"] != st.get("se_site"):
            oud.pop("se_tot", None)  # andere installatie: opnieuw beginnen
        st.update(nieuw)
    if os.environ.get("GITHUB_ACTIONS"):
        for v in st.values():  # nooit in de logs, ook niet per ongeluk
            print(f"::add-mask::{v}")

    eind = date.today() - timedelta(days=1)
    dagen = [eind - timedelta(days=n) for n in range(365, -1, -1)]
    data = {"gemaakt": datetime.now().isoformat(timespec="seconds"), "van": str(dagen[0]), "tot": str(eind)}
    status = {"bijgewerkt": data["gemaakt"]}
    data.update(haal_frank_prijzen(dagen))
    try:
        if st.get("frank_email") and st.get("frank_wachtwoord"):
            data.update(haal_frank_gas(st["frank_email"], st["frank_wachtwoord"], dagen))
            status["frank"] = "ok"
        else:
            status["frank"] = "alleen prijzen (geen login ingevuld)"
    except Exception as e:
        status["frank"] = f"fout: {e}"[:200]
    try:
        if all(st.get(k) for k in ("se_client_id", "se_client_secret", "se_site")) and (st.get("se_code") or st.get("se_refresh")):
            data.update(haal_solaredge(st, oud, eind))
            status["solaredge"] = f"ok t/m {data['se_tot']}"
        else:
            status["solaredge"] = "niet gekoppeld"
    except Exception as e:
        status["solaredge"] = f"fout: {e}"[:200]
        for k in ("opbrengst_kwh", "verbruik_kwh", "kwp", "se_tot"):  # wat er al was niet kwijtraken
            if oud.get(k) is not None:
                data[k] = oud[k]
    finally:
        # Altijd bewaren: SolarEdge geeft bij elke vernieuwing een nieuw token.
        INST.write_text(json.dumps(hybride_in(priv.public_key(), st)))

    if st.get("wachtwoord"):
        salt = b64d(json.loads(ENC.read_text())["salt"]) if ENC.exists() else os.urandom(16)
        ENC.write_text(json.dumps(ww_in(json.dumps(data, separators=(",", ":")), st["wachtwoord"], salt)))
    else:
        status["data"] = "geen wachtwoord ingevuld, data niet opgeslagen"
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=1))

    for f in invoer:
        git("rm", "-q", str(f))
    git("add", INST.name, ENC.name, STATUS.name)
    if git("commit", "-q", "-m", "Data bijgewerkt").returncode == 0:
        git("pull", "-q", "--rebase")
        r = git("push", "-q")
        print("Gepusht." if r.returncode == 0 else f"Pushen mislukt: {r.stderr.strip()}")


def nieuwe_sleutel():
    """Maakt een sleutelpaar. Privé-deel gaat direct naar GitHub Secrets (nooit op schijf), publiek deel in index.html."""
    from nacl import encoding, public  # pip install pynacl, alleen voor deze stap
    token = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True).stdout.split("password=")[1].split("\n")[0]
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{REPO}/actions/secrets"
    with urllib.request.urlopen(urllib.request.Request(api + "/public-key", headers=h)) as r:
        gh = json.load(r)
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    doos = public.SealedBox(public.PublicKey(gh["key"].encode(), encoding.Base64Encoder()))
    body = json.dumps({"encrypted_value": b64e(doos.encrypt(pem)), "key_id": gh["key_id"]}).encode()
    urllib.request.urlopen(urllib.request.Request(api + "/PRIVE_SLEUTEL", data=body, headers=h, method="PUT"))
    spki = b64e(k.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
    html = MAP / "index.html"
    html.write_text(re.sub(r"var PUBLIEK='[^']*'", f"var PUBLIEK='{spki}'", html.read_text(encoding="utf-8")), encoding="utf-8")
    print("PRIVE_SLEUTEL staat in GitHub Secrets; publieke sleutel in index.html gezet. Commit en push index.html.")


def test():
    assert uur_index(datetime(2025, 1, 1, 0)) == 0
    assert uur_index(datetime(2025, 12, 31, 23)) == H - 1
    assert uur_index(datetime(2024, 12, 31, 23)) == H - 1  # schrikkeljaar
    assert uur_index(datetime(2024, 3, 1, 0)) == 59 * 24
    assert uur_index(datetime(2024, 2, 29, 5)) is None
    assert ww_uit(ww_in('{"a":1}', "geheim123", b"0" * 16), "geheim123") == {"a": 1}
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert hybride_uit(k, hybride_in(k.public_key(), {"x": "y"})) == {"x": "y"}
    print("zelftest ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        test()
    elif "--sleutel" in sys.argv:
        nieuwe_sleutel()
    else:
        run()
