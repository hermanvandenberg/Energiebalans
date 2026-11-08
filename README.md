# Energiebalans

Dashboard voor SolarEdge (zonnepanelen en accu) en Frank Energie (stroom en gas), met een scenario-tool om te rekenen aan:

- 1 of 2 extra accu's
- extra zonnepanelen
- van het gas af met een warmtepomp (hybride, lucht-water, bodem-water, lucht-lucht of eigen keuze)

Eén bestand (`index.html`), geen build en geen server nodig. Rekenen gebeurt in de browser.

## Echte data koppelen

Alles gaat via het dashboard, tab **Bronnen → Instellingen**. Je pc hoeft niet aan te staan.

1. **SolarEdge** (Monitoring API v2): maak op developer.solaredge.com een *Site Access*-app met scope `SITE_DATA`, Origin URL `https://hermanvandenberg.github.io`, Redirect URI `https://hermanvandenberg.github.io/Energiebalans/`. Vul de Client ID in, klik *Toestemming geven*, keur goed bij SolarEdge en vul daarna het Client Secret in.
2. **Frank Energie**: e-mail en wachtwoord van je Frank-account (voor je gasverbruik; prijzen zijn openbaar).
3. **Wachtwoord voor je data** (minimaal 8 tekens).
4. Klik *Versleutelen en naar GitHub*, open de link en klik op GitHub *Commit changes*.

GitHub Actions (`.github/workflows/data.yml`) haalt daarna de data op, en verder elke ochtend.

### Hoe het veilig blijft

- De pagina versleutelt je invoer met een publieke sleutel (RSA-OAEP + AES-GCM). Het bijbehorende privé-deel staat alleen in GitHub Secrets (`PRIVE_SLEUTEL`), dus alleen de workflow kan het lezen. Opgeslagen in `instellingen.enc`.
- De data staat in `energie.enc`, versleuteld met jouw wachtwoord (PBKDF2 600.000 rondes + AES-GCM). Een apparaat onthoudt na ontgrendelen alleen de afgeleide sleutel.
- `status.json` is openbaar en bevat alleen of het ophalen lukte.
- SolarEdge geeft per aanroep max. 24 uur uurdata; de eerste keer kost een jaar ~365 van de 2.000 gratis aanroepen per maand (ongeveer 45 minuten), daarna 1 per dag.

Nieuw sleutelpaar (eenmalig, of als de sleutel ooit uitlekt): `pip install pynacl` en `python haal_data_op.py --sleutel`, daarna `index.html` committen en de instellingen opnieuw invullen.

## Aannames in de berekening

- Teruglevering tegen marktprijs min terugleverkosten (geen salderen). Bij een negatieve prijs wordt opbrengst afgeregeld.
- Accu laadt met zonne-overschot en levert aan het huis. Optioneel laden op goedkope winteruren.
- Warmtepomp: gas omgerekend naar warmte (9,77 kWh per m³), gedeeld door het SCOP.
- Tarieven, prijzen en subsidie zijn invulvelden met voorbeeldwaarden.
- Geen degradatie, restwaarde of inflatie van onderhoud.
