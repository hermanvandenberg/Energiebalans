# Energiebalans

Dashboard voor SolarEdge (zonnepanelen en accu) en Frank Energie (stroom en gas), met een scenario-tool om te rekenen aan:

- 1 of 2 extra accu's
- extra zonnepanelen
- van het gas af met een warmtepomp (hybride, lucht-water, bodem-water, lucht-lucht of eigen keuze)

Eén bestand (`index.html`), geen build en geen server nodig. Rekenen gebeurt in de browser.

## Status

Het dashboard rekent nu met **voorbeeldprofielen** voor een heel jaar (opbrengst, verbruik en uurprijzen per uur). Je eigen jaartotalen en tarieven vul je in bij het tabblad Scenario's. Je invoer wordt bewaard in `localStorage` van je browser.

## Online zetten met GitHub Pages

1. Maak een nieuwe repository, bijvoorbeeld `Energiebalans`.
2. Zet `index.html` en dit bestand in de hoofdmap en push.
3. Ga naar Settings, Pages, kies "Deploy from a branch", branch `main`, map `/ (root)`.
4. Na een minuut staat het op `https://<gebruikersnaam>.github.io/Energiebalans/`.

Zet de repository op privé als je geen openbare pagina wilt. Pages op een privé repository vraagt een betaald GitHub-abonnement. De pagina bevat geen persoonlijke gegevens, maar plaats later nooit API-keys in de repository.

## Volgende stap: echte data

Een webpagina mag niet rechtstreeks bij de SolarEdge- of Frank-API. Plan:

1. Een klein script (Python) op je eigen computer haalt data op:
   - SolarEdge Monitoring API: API-key en site-ID uit het monitoringportaal.
   - Frank Energie: prijzen zijn openbaar, eigen verbruik vraagt inloggen.
2. Het script schrijft `data/energie.json`.
3. `index.html` leest dat bestand met `fetch('data/energie.json')` en vervangt de voorbeeldprofielen.

Bewaar API-keys in een `.env` bestand en zet dat in `.gitignore`.

## Aannames in de berekening

- Teruglevering tegen marktprijs min terugleverkosten (geen salderen). Bij een negatieve prijs wordt opbrengst afgeregeld.
- Accu laadt met zonne-overschot en levert aan het huis. Optioneel laden op goedkope winteruren.
- Warmtepomp: gas omgerekend naar warmte (9,77 kWh per m³), gedeeld door het SCOP.
- Tarieven, prijzen en subsidie zijn invulvelden met voorbeeldwaarden.
- Geen degradatie, restwaarde of inflatie van onderhoud.
