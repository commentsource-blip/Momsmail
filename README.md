# ⚖️ Moms & Afgifter Radar

Streamlit-dashboard til tax professionals der holder øje med nyt indenfor moms og afgifter.

Henter automatisk data fra officielle danske og EU-kilder:

| Kilde | Indhold |
|---|---|
| 🏛️ Folketing (ODA API) | Lovforslag om moms |
| 📜 Lovtidende | Bekendtgørelser og love |
| 📢 Skattestyrelsen | Styresignaler |
| ⚖️ Skattestyrelsen | Afgørelser og domme |
| 📖 Skattestyrelsen | Vejledninger og satser |
| 📬 Høringsporten | Høringer fra Skatteministeriet |
| 🇪🇺 EUR-Lex / CURIA | EU-domme om moms |

---

## Kom i gang

### 1. Klon og installér

```bash
git clone https://github.com/DIT-BRUGERNAVN/moms-radar.git
cd moms-radar
pip install -r requirements.txt
```

### 2. Kør lokalt

```bash
streamlit run app.py
```

Åbn `http://localhost:8501` i din browser.

---

## Deploy til Streamlit Community Cloud (gratis)

1. Push koden til et **offentligt eller privat** GitHub-repo.
2. Gå til [share.streamlit.io](https://share.streamlit.io) og log ind med GitHub.
3. Klik **New app** → vælg repo og branch → sæt `app.py` som main file.
4. Klik **Deploy** — appen er live på få minutter.

---

## Tilføj flere kilder

Åbn `app.py` og:

1. Skriv en ny `@st.cache_data`-funktion der scraper kilden.
2. Tilføj et nyt entry i `ALLE_KILDER`-dict'en nederst.

### Eksempel: Tilføj Skatteankestyrelsen

```python
@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_skatteankestyrelsen() -> list[dict]:
    url = "https://www.skatteankestyrelsen.dk/afgoerelser"
    r = safe_get(url)
    if r is None:
        return [{"fejl": "Kunne ikke hente data."}]
    soup = BeautifulSoup(r.text, "html.parser")
    # ... parse og returnér liste af dicts med titel/dato/url/resume
    ...
```

Tilføj i `ALLE_KILDER`:
```python
"Skatteankestyrelsen": {
    "titel": "Afgørelser – Skatteankestyrelsen",
    "ikon": "🏗️",
    "url": "https://www.skatteankestyrelsen.dk/afgoerelser",
    "fn": hent_skatteankestyrelsen,
    "args": (),
},
```

---

## Bemærkninger

- Data caches i **1 time** (`CACHE_TTL = 3600`). Justér efter behov.
- Scrapers er baseret på den nuværende HTML-struktur af kildernes hjemmesider. Hvis en kilde opdaterer sin side, kan scraperen kræve tilpasning.
- Folketing-kilden bruger den officielle **ODA REST API** og er dermed den mest stabile.
- EU-domme hentes via **EUR-Lex** som fallback til CURIA.
