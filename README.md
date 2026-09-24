# TriaCon Brandveiligheidsinspectie

Responsive webapp voor veldinspecties op iPad en verdere rapportuitwerking op pc. Meerdere inspecteurs kunnen gelijktijdig in één centrale omgeving werken.

## Eerste start

1. Installeer Python 3.11 of nieuwer via `python.org` en kies tijdens de installatie **Add Python to PATH**.
2. Dubbelklik op `start_app.bat`.
3. Bij de eerste start wordt automatisch een lokale `.venv` gemaakt en worden de benodigde onderdelen geïnstalleerd.
4. Open op de server-pc `http://localhost:8502`.
5. Open op een iPad in hetzelfde netwerk `http://<ip-adres-van-de-pc>:8502`.

Laat het opdrachtvenster open en voorkom dat de server-pc in slaapstand gaat zolang de app beschikbaar moet blijven.

## Accounts

- Een nieuwe gebruiker kiest op het startscherm **Registreren**.
- Vereist zijn naam, e-mailadres, wachtwoord en wachtwoordbevestiging.
- Wachtwoorden worden met PBKDF2-SHA256, een unieke salt en 600.000 iteraties opgeslagen; het oorspronkelijke wachtwoord wordt nooit bewaard.
- Na inloggen kan de gebruiker via **Account en wachtwoord** het wachtwoord wijzigen of uitloggen.
- Een inactieve sessie verloopt automatisch na 12 uur.
- Registraties wachten op goedkeuring door een beheerder. Een registratie verleent nooit automatisch toegang tot projecten.
- Beheerders zien alle projecten. Overige gebruikers zien alleen toegewezen projecten, met afzonderlijke rechten per project.
- Na wachtwoordreset of wijziging van accountrechten moet opnieuw worden ingelogd. Tijdelijke wachtwoorden moeten eerst worden gewijzigd.
- Na vijf mislukte loginpogingen binnen 15 minuten is het account vijf minuten geblokkeerd voor verdere loginpogingen.

## Beheer en rollen

De beschermde hoofdbeheerder is **Joost Prikken, jprikken@triacon.nl**. Dit is de enige hoofdbeheerder en het account kan niet via het beheerscherm worden verwijderd, gedegradeerd of geblokkeerd. Het startwachtwoord staat niet in de broncode of deze handleiding.

Via **Beheer** kunnen bevoegde beheerders accounts activeren/blokkeren, tijdelijke wachtwoorden instellen, projecttoegang beheren en recente beheerwijzigingen bekijken. Alleen de hoofdbeheerder kan andere beheerders benoemen of aanpassen.

| Rol | Standaardrechten |
| --- | --- |
| Hoofdbeheerder | Alles, inclusief beheer van beheerders |
| Beheerder | Alle projecten, gebruikers en projectkoppelingen; geen beheer van beheerders |
| Projectleider | Alle projecthandelingen binnen toegewezen projecten |
| Adviseur | Toegewezen projecten bekijken, rapporten aanmaken/bewerken, inspecteren en exporteren |
| Meelezer | Toegewezen projecten bekijken, zonder wijzigen of exporteren |

**Nieuwe projecten aanmaken** is een apart accountrecht voor niet-beheerders. Een nieuw eigen project neemt de accountrol als projectrol over. De beheerder kan per project de rol kiezen en vervolgens elk recht afzonderlijk aan- of uitzetten: bekijken, projectgegevens wijzigen, complexen aanmaken/wijzigen, rapporten aanmaken/inlezen, rapporten/bevindingen wijzigen, bevindingen verwijderen en exporteren. Zonder bekijkrecht zijn alle andere projectrechten ineffectief. Beheerders hebben altijd alle projectrechten.

De datalaag weigert onbevoegde bewerkingen ook wanneer een knop of object-id buiten de normale workflow wordt gebruikt. De actor is per sessie geïsoleerd; niet ingelogd betekent geen projecttoegang. Een expliciete ontzegging gaat binnen een project vóór de standaard projectrol. De database wordt naar versie 5 gemigreerd met een back-up vooraf. Bestaande bijdragers behouden adviseurstoegang tot hun projecten; overige koppelingen richt de beheerder in.

## Hoofdbeheerder op een nieuwe server

Gebruik dezelfde persistente database bij upgrades; dan blijven het account, het gewijzigde wachtwoord en de rechten behouden. Zet op een nieuwe lege installatie eenmalig de hoofdbeheerder klaar vóórdat de app publiek bereikbaar wordt:

```powershell
.\.venv\Scripts\python.exe provision_admin.py
```

De opdracht vraagt het startwachtwoord zonder het te tonen of naar een bestand te schrijven. Alternatief voor een beheerde server: stel `BRANDVEILIGHEID_BOOTSTRAP_PASSWORD` via de secretmanager van de hosting in. Minimaal 12 tekens. De accountnaam en het e-mailadres blijven zoals hierboven. Bij herstart wordt een bestaand ingericht account nooit opnieuw ingesteld. Verwijder het installatie-secret nadat de provisioning is voltooid. Het startwachtwoord moet bij de eerste login worden gewijzigd.

### Hoofdbeheerder op Streamlit Community Cloud

De online app gebruikt niet de database op je pc. Deploy de actuele code inclusief `access_control.py`, `user_admin.py` en `admin_ui.py`. Voeg in de appinstellingen onder Secrets een top-level TOML-instelling toe:

```toml
BRANDVEILIGHEID_BOOTSTRAP_PASSWORD = "VUL_HIER_EEN_NIEUW_STARTWACHTWOORD_IN"
```

Gebruik een eigen sterk wachtwoord van minimaal 12 tekens, niet de voorbeeldwaarde. Sla op en herstart de online app. Log in met `jprikken@triacon.nl` en dit startwachtwoord; wijzig het vervolgens in de app. De code leest zowel de omgevingsvariabele als Streamlit Secrets expliciet uit. Verwijder daarna het installatie-secret. Plaats het secret nooit in GitHub. Een al ingerichte hoofdbeheerder wordt hiermee niet gereset; daarvoor is toegang tot de betreffende serverdatabase nodig. Een lokale wachtwoordcontrole bewijst niet dat het online account bestaat of hetzelfde wachtwoord gebruikt.

Let op: deze instelling maakt opslag niet persistent. Gebruik voor productie duurzame database- en bestandsopslag; vertrouw niet op het lokale bestandssysteem van een tijdelijke cloudinstantie.

## Voor publicatie

Deze wijziging voegt applicatierechten toe; er is nog geen publieke hosting ingericht en dit is geen volledige beveiligingsaudit.

- Richt het hoofdbeheerdersaccount in en wijzig het startwachtwoord **voordat** je publieke toegang opent.
- Gebruik HTTPS, een vaste geheime Streamlit-cookie key en een reverse proxy met rate limiting. Laat CORS- en XSRF-bescherming ingeschakeld. Voor strengere organisatie-eisen: centrale identiteit/SSO en MFA; die zijn nog niet geïmplementeerd.
- Gebruik één appserver met een persistente, private opslagmap. Zet database, uploads, tekeningen, back-ups en serversecrets nooit in een openbare static-map of webdirectory.
- Publiceer geen oude databases, uploads, `.venv`, QA-bestanden of `work`/`outputs` uit deze ontwikkelomgeving. Start een nieuwe organisatieomgeving zonder meegeleverde `data/brandveiligheid.db`, tenzij het een bewust beveiligde migratie betreft.
- Migreer database **en** foto's/tekeningen samen en test herstel van back-ups. Back-ups bevatten wachtwoordhashes en moeten als vertrouwelijk worden behandeld.
- Controleer de projectkoppelingen van bestaande accounts. Bestaande downloads kunnen niet worden ingetrokken; medewerkers houden verantwoordelijkheid voor geëxporteerde bestanden.
- Voer op de gekozen hosting nog een acceptatie-/beveiligingstest uit, inclusief gelijktijdige sessies, downloadtoegang, uploadlimieten en herstel na herstart. Opslagfuncties zijn afgeschermd; directe shell- of databasetoegang tot de server valt buiten de applicatierechten.

## Werkstructuur

De vaste hiërarchie is:

```text
Project
└─ Complex
   └─ Rapport
      └─ Bevindingen en Word-export
```

Een rapport kan alleen onder een bestaand complex worden aangemaakt. Een complex kan alleen onder een bestaand project worden aangemaakt. De sidebar en breadcrumbs tonen altijd de actieve selectie.

## Inspecteren op iPad

- Bij een nieuwe bevinding kan direct met de iPad-camera een inspectiefoto worden gemaakt. Een bestaande foto uploaden blijft ook mogelijk.
- Meerdere standaardgebreken kunnen tegelijk worden gekozen; dubbele eisen en maatregelen worden bij het samenvoegen verwijderd.
- Veelgebruikte gebouw-, installatie- en organisatievelden gebruiken vaste keuzelijsten om invoerverschillen tussen inspecteurs te beperken.

## Migratie en back-up

Projecten, complexen, rapporten, bevindingen en foto's worden standaard blijvend opgeslagen in:

`%LOCALAPPDATA%\Triacon\Brandveiligheidsinspectie`

Deze locatie staat los van de appmap. Daardoor blijft dezelfde database gebruikt worden wanneer de appmap wordt verplaatst, opnieuw uitgepakt of door een nieuwe versie wordt vervangen. Bij de eerste start wordt de bestaande database uit de appmap automatisch naar deze vaste locatie gemigreerd, inclusief bestaande foto's.

De app maakt bij de eerste start van iedere dag automatisch een consistente databaseback-up in de submap `backups`. In de sidebar staat onder **Dataopslag en back-up** ook een knop om direct een extra back-up te maken en te downloaden.

Stel desgewenst vóór het starten `BRANDVEILIGHEID_DATA_DIR` in om een andere centrale opslagmap te gebruiken. Gebruik bij meerdere inspecteurs altijd één centrale appserver; laat niet meerdere losse appkopieën elk een eigen database openen.

De database gebruikt SQLite WAL-modus en een wachttijd voor gelijktijdige schrijftaken. Start slechts **één centrale appserver**. Start niet op meerdere pc's afzonderlijke appkopieën die rechtstreeks tegen hetzelfde gesynchroniseerde OneDrive-databasebestand schrijven. Voor gebruik op meerdere locaties verbinden alle inspecteurs met dezelfde server via bedrijfs-VPN of een beveiligd privénetwerk.

## Tekeningen en gebrekscodes

Open binnen een rapport het tabblad **Tekeningen**. Onder **Tekening inladen**
kun je een PDF (maximaal 30 pagina's), PNG of JPG opslaan, met tekeningnummer en
bouwlaag. De maximale bestandsgrootte is 40 MB. Iedere PDF-pagina wordt apart
selecteerbaar. DWG-bestanden eerst als PDF exporteren.

Tik op de tekening om het bestaande bevindingenformulier te openen. Tekeningnummer
en bouwlaag worden ingevuld. Pas na **Bevinding toevoegen** wordt de bevinding met
de positie opgeslagen en keer je terug naar de tekening met de rode gebrekscode.
Annuleren maakt geen bevinding of markering aan. Gebruik de zoomknoppen en veeg
over de tekening om details te bekijken; de posities blijven bij zoomen gelijk.

De tekeningen en markeringen blijven per rapport bewaard, ook na herstarten.
Bij de Word-export worden alle ingeladen pagina's inclusief rode gebrekscodes
aan het bestaande hoofdstuk **Bijlagen** toegevoegd. De overige rapportopbouw
blijft gelijk. Maak een nieuwe Word-export na wijzigingen aan bevindingen.

Tekeningen staan in de submap `drawings` van de vaste opslaglocatie. Neem deze
map, `uploads` en `brandveiligheid.db` samen mee in een volledige back-up;
de downloadknop **Databaseback-up** bevat alleen de database.

## Word-export

De export bewerkt `templates/rapportage_brandveiligheid_template.docx` rechtstreeks.

- Inleiding, 3.6, 3.7 en hoofdstuk 5 blijven de vaste teksten uit de template.
- In 3.2, 3.3 en 3.4 blijven labels, volgorde, opmaak en content controls uit de template behouden. Alleen de bestaande waardeslots worden ingevuld.
- In gebrekentabellen is ieder label met zijn waarde gekoppeld aan dezelfde Word-tabelrij. Meerregelige waarden kunnen volgende labels daardoor niet verticaal laten verschuiven.
- Werk na downloaden in Word de inhoudsopgave en velden zo nodig bij met `Ctrl+A` en `F9`.

## Excel-kostenraming

Naast de Word-export staat **Kostenraming Excel downloaden**. De export gebruikt
`templates/kostenraming_2026_template.xlsx` en behoudt de vaste vormgeving, formules,
percentages en totalen van de aangeleverde kostenraming.

- Bij een standaardmaatregel stelt de app automatisch passende regels uit
  `data/eenheidsprijzen_2026.xlsx` voor. De inspecteur kan deze koppeling bij het
  toevoegen of bewerken van een bevinding controleren en aanpassen.
- Het veld **Aantal** wordt gebruikt als hoeveelheid. Een leeg of onleesbaar aantal
  wordt als `1` geëxporteerd.
- **Opmerking TriaCon** blijft bij iedere export leeg en is uitsluitend bedoeld
  om achteraf handmatig in Excel aan te vullen.
- Als geen veilige koppeling kan worden gevonden, wordt de maatregel met € 0 en de
  melding **eenheidsprijs nader te bepalen** opgenomen. Zo wordt nooit stilzwijgend
  een mogelijk verkeerde prijs gekozen.
- De bronprijzen worden in een verborgen werkblad in het exportbestand opgenomen.
  Daardoor werken de keuzelijsten en berekeningen zonder externe Excel-koppeling.
- Meer dan tien kostenregels worden automatisch toegevoegd, met dezelfde opmaak als
  de vaste detailregels uit het format.

Voor een nieuwe jaarlijkse prijslijst: vervang `data/eenheidsprijzen_2026.xlsx` door
een bestand met dezelfde werkbladnaam en kolomindeling (omschrijving, prijs, eenheid).

## Beheer en beveiliging

- Publiceer poort 8502 niet rechtstreeks op internet.
- Gebruik voor externe toegang een VPN/Tailscale-verbinding of plaats de app achter HTTPS en centrale authenticatie.
- Open registratie staat standaard aan. Beheer daarom de netwerktoegang tot de server zorgvuldig.
- Voor een grotere cloudomgeving met meerdere serverprocessen moet SQLite worden vervangen door bijvoorbeeld PostgreSQL en moeten foto's in centrale objectopslag worden geplaatst.
# Update 8 september 2026

- Modules in de zijbalk: Inspecties, Kwaliteitscontroles en Quickscan. De laatste twee zijn voorbereid voor toekomstige invulling.
- Project/complex/rapport kiezen staat bovenaan binnen Inspecties. Opgeslagen inspecties blijven behouden.
- Onder Tekeningen → Bijgewerkte tekeningen downloaden: een pagina als PNG/PDF, of alle pagina's als één PDF, inclusief opgeslagen rode gebrekscodes. PDF-uitvoer is gerasteriseerd; originele uploads blijven ongewijzigd.
- De Word-inhoudsopgave begint op een eigen pagina met compacte TOC-stijlen; het ingebedde Excel-voorbeeld op de bijlagenpagina wordt niet meer geëxporteerd. Genereer bestaande rapporten opnieuw om dit te zien.
