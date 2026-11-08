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

## Echte data

`haal_data_op.py` (alleen standaard-Python 3.11, geen pip nodig) haalt de laatste 366 dagen op en schrijft `data/energie.json`:

- Frank Energie: uurprijzen stroom (openbaar), energiebelasting, inkoopkosten en gemiddelde gasprijs.
- SolarEdge: opbrengst en verbruik per uur, en het piekvermogen (kWp).

```
python haal_data_op.py --serve
```

Open http://127.0.0.1:8000, tab Bronnen, vul API-key en site-ID in. Die komen in `.env` (staat in `.gitignore`). Daarna kan `python haal_data_op.py` ook zonder server. Het formulier werkt alleen op je eigen pc, niet op GitHub Pages.

`index.html` leest `data/energie.json`; zonder dat bestand rekent het met de voorbeeldprofielen. Bij nieuwe data worden kWp, opbrengst per kWp, stroomverbruik en tarieven één keer overgenomen in Scenario's.

## Aannames in de berekening

- Teruglevering tegen marktprijs min terugleverkosten (geen salderen). Bij een negatieve prijs wordt opbrengst afgeregeld.
- Accu laadt met zonne-overschot en levert aan het huis. Optioneel laden op goedkope winteruren.
- Warmtepomp: gas omgerekend naar warmte (9,77 kWh per m³), gedeeld door het SCOP.
- Tarieven, prijzen en subsidie zijn invulvelden met voorbeeldwaarden.
- Geen degradatie, restwaarde of inflatie van onderhoud.
