"""
Moms & Afgifter Radar
=====================
Streamlit dashboard der henter de seneste nyheder om moms og afgifter
fra officielle danske og EU-kilder.

Kør med:  streamlit run app.py
"""

import streamlit as st
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import re
import json

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Moms & Afgifter Radar",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

CACHE_TTL = 3600  # 1 time

# ---------------------------------------------------------------------------
# Hjælpefunktioner
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """Fjern overflødige whitespaces og linjeskift."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def format_date(raw: str) -> str:
    """Forsøg at parse og reformatere en dato til DD.MM.ÅÅÅÅ."""
    if not raw:
        return ""
    raw = raw.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw[:len(fmt)], fmt).strftime("%d.%m.%Y")
        except ValueError:
            pass
    return raw


def safe_get(url: str, timeout: int = 15, **kwargs) -> requests.Response | None:
    """Hent URL med fejlhåndtering."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, **kwargs)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        return None


# ---------------------------------------------------------------------------
# Scrapers – én funktion pr. kilde
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_folketing() -> list[dict]:
    """
    Folketing Open Data API (ODA).
    Henter lovforslag der indeholder 'moms' i titel eller resume,
    sorteret efter seneste opdatering.
    """
    url = (
        "https://oda.ft.dk/api/Sag"
        "?$filter=contains(tolower(Titel),'moms')"
        " or contains(tolower(Resume),'moms')"
        "&$orderby=Opdateringsdato desc"
        "&$top=10"
        "&$format=json"
    )
    r = safe_get(url)
    if r is None:
        return [{"fejl": "Kunne ikke hente data fra Folketing ODA API."}]

    try:
        data = r.json()
    except json.JSONDecodeError:
        return [{"fejl": "Ugyldigt JSON fra Folketing API."}]

    resultater = []
    for item in data.get("value", []):
        sagsnr = item.get("Nummer", "")
        periode = item.get("Samling", {})
        periode_id = periode.get("Id", "") if isinstance(periode, dict) else ""
        ft_url = (
            f"https://www.ft.dk/samling/{periode_id}/lovforslag/l{sagsnr}/index.htm"
            if sagsnr and periode_id
            else "https://www.ft.dk"
        )
        resultater.append({
            "titel": clean_text(item.get("Titel", "Uden titel")),
            "dato": format_date(item.get("Opdateringsdato", "")),
            "url": ft_url,
            "resume": clean_text(item.get("Resume", ""))[:300],
            "status": item.get("StatusId", ""),
        })
    return resultater if resultater else [{"fejl": "Ingen lovforslag fundet."}]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_lovtidende() -> list[dict]:
    """
    Lovtidende.dk – søg efter dokumenter med 'moms'.
    Siden er HTML-baseret og pagineret.
    """
    url = "https://www.lovtidende.dk/documents?o=40&t=%2Amoms%2A"
    r = safe_get(url)
    if r is None:
        return [{"fejl": "Kunne ikke hente data fra Lovtidende.dk."}]

    soup = BeautifulSoup(r.text, "html.parser")
    resultater = []

    # Lovtidende viser resultater i en tabel eller liste – prøv begge mønstre
    rows = soup.select("table tbody tr") or soup.select("ul.document-list li")

    for row in rows[:10]:
        cols = row.find_all("td")
        if cols and len(cols) >= 2:
            link_tag = row.find("a", href=True)
            titel = clean_text(link_tag.get_text() if link_tag else cols[0].get_text())
            href = link_tag["href"] if link_tag else ""
            full_url = ("https://www.lovtidende.dk" + href) if href.startswith("/") else href
            dato_text = clean_text(cols[1].get_text()) if len(cols) > 1 else ""
            resultater.append({
                "titel": titel,
                "dato": dato_text,
                "url": full_url,
                "resume": "",
            })
        else:
            # Prøv list-item mønster
            link_tag = row.find("a", href=True)
            if link_tag:
                href = link_tag["href"]
                full_url = ("https://www.lovtidende.dk" + href) if href.startswith("/") else href
                dato_tag = row.find(class_=re.compile(r"date|dato", re.I))
                resultater.append({
                    "titel": clean_text(link_tag.get_text()),
                    "dato": clean_text(dato_tag.get_text()) if dato_tag else "",
                    "url": full_url,
                    "resume": "",
                })

    return resultater if resultater else [{"fejl": "Ingen resultater fundet på Lovtidende.dk – siden kan have ændret struktur."}]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_skat(oid: str, label: str) -> list[dict]:
    """
    info.skat.dk – generisk scraper til skat.dk-sider.
    oid=16010  → styresignaler
    oid=124    → afgørelser og domme
    oid=74288  → vejledninger og satser
    """
    url = f"https://info.skat.dk/data.aspx?oid={oid}"
    r = safe_get(url)
    if r is None:
        return [{"fejl": f"Kunne ikke hente data fra skat.dk ({label})."}]

    soup = BeautifulSoup(r.text, "html.parser")
    resultater = []

    # skat.dk bruger typisk en tabel med klassen "table" eller en liste med links
    links = soup.select("table.table tr") or soup.select(".documentlist li") or soup.select("ul li")

    for row in links[:15]:
        link_tag = row.find("a", href=True)
        if not link_tag:
            continue
        href = link_tag["href"]
        if href.startswith("/"):
            href = "https://info.skat.dk" + href
        elif not href.startswith("http"):
            href = "https://info.skat.dk/" + href

        dato_tag = row.find(class_=re.compile(r"date|dato|published", re.I))
        dato = ""
        if dato_tag:
            dato = clean_text(dato_tag.get_text())
        else:
            # Prøv at finde en dato-lignende streng i rækken
            dato_match = re.search(r"\d{2}[.\-/]\d{2}[.\-/]\d{2,4}", row.get_text())
            if dato_match:
                dato = dato_match.group()

        titel = clean_text(link_tag.get_text())
        if titel:
            resultater.append({
                "titel": titel,
                "dato": dato,
                "url": href,
                "resume": "",
            })

    return resultater if resultater else [{"fejl": f"Ingen resultater fundet for {label}."}]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_hoeringsporten() -> list[dict]:
    """
    Høringsporten – høringer fra Skatteministeriet.
    """
    url = "https://hoeringsportalen.dk/Hearing?Authorities=Skatteministeriet"
    r = safe_get(url)
    if r is None:
        return [{"fejl": "Kunne ikke hente data fra Høringsporten."}]

    soup = BeautifulSoup(r.text, "html.parser")
    resultater = []

    # Høringsporten viser høringer i kort-layout
    cards = (
        soup.select(".hearing-list-item")
        or soup.select("article.card")
        or soup.select(".hearing-item")
        or soup.select("li.list-group-item")
    )

    for card in cards[:10]:
        link_tag = card.find("a", href=True)
        if not link_tag:
            continue
        href = link_tag["href"]
        full_url = ("https://hoeringsportalen.dk" + href) if href.startswith("/") else href

        titel = clean_text(link_tag.get_text())
        if not titel:
            h_tag = card.find(["h2", "h3", "h4"])
            titel = clean_text(h_tag.get_text()) if h_tag else "Uden titel"

        dato_tag = card.find(class_=re.compile(r"date|dato|deadline|frist", re.I))
        if not dato_tag:
            dato_tag = card.find("time")
        dato = clean_text(dato_tag.get_text()) if dato_tag else ""

        frist_match = re.search(r"[Ff]rist[:\s]+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})", card.get_text())
        frist = frist_match.group(1) if frist_match else ""

        if titel:
            resultater.append({
                "titel": titel,
                "dato": dato,
                "url": full_url,
                "resume": f"Høringsfrist: {frist}" if frist else "",
            })

    return resultater if resultater else [{"fejl": "Ingen høringer fundet fra Skatteministeriet."}]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_eu_domme() -> list[dict]:
    """
    EU-Domstolen – domme om moms (VAT/merværdiafgift) via EUR-Lex SPARQL/search.
    Bruger EUR-Lex søge-API som er mere stabilt end CURIA direkte.
    """
    # EUR-Lex full-text søgning – nyeste momsdomme
    url = (
        "https://eur-lex.europa.eu/search.html"
        "?scope=EURLEX&text=VAT+value+added+tax"
        "&lang=da&type=quick&qid=1&DD_YEAR=2024"
        "&DTS_DOM=EU_LAW"
        "&typeOfActStatus=CASE_LAW"
    )
    r = safe_get(url)
    if r is None:
        # Fallback: CURIA søgeside
        curia_url = (
            "https://curia.europa.eu/juris/liste.jsf"
            "?language=da&jur=C,T&num=&dates=&docnodecision=0"
            "&allcommjo=0&affint=0&affclose=0&alldocrec=0"
            "&docdecision=1&docor=1&docav=0&docsom=0"
            "&docinf=0&alldocord=0&docord=0&ray=0&nat=0"
            "&otherint=0&resc=0&reson=0&resmin=0&doctyp=0"
            "&domainInt=0&mots=TVA+merv%C3%A6rdiafgift&resmax=10"
        )
        r = safe_get(curia_url)
        if r is None:
            return [{"fejl": "Kunne ikke hente domme fra EU-Domstolen eller EUR-Lex."}]

    soup = BeautifulSoup(r.text, "html.parser")
    resultater = []

    # EUR-Lex resultater
    rows = (
        soup.select(".SearchResult")
        or soup.select("table.table tr")
        or soup.select(".result-item")
        or soup.select("li.result")
    )

    for row in rows[:10]:
        link_tag = row.find("a", href=True)
        if not link_tag:
            continue
        href = link_tag["href"]
        if href.startswith("/"):
            href = "https://eur-lex.europa.eu" + href
        elif "curia" in href or href.startswith("/"):
            href = "https://curia.europa.eu" + href

        titel = clean_text(link_tag.get_text())
        dato_tag = row.find(class_=re.compile(r"date|dato", re.I)) or row.find("time")
        dato = clean_text(dato_tag.get_text()) if dato_tag else ""

        if titel:
            resultater.append({
                "titel": titel,
                "dato": dato,
                "url": href,
                "resume": "",
            })

    return resultater if resultater else [{"fejl": "Ingen EU-domme fundet – siden kan have ændret struktur."}]


# ---------------------------------------------------------------------------
# UI – hjælpefunktioner
# ---------------------------------------------------------------------------

def vis_resultater(resultater: list[dict], kilde_url: str):
    """Vis en liste af resultater som Streamlit-komponenter."""
    for item in resultater:
        if "fejl" in item:
            st.warning(f"⚠️ {item['fejl']}")
            st.markdown(f"[Åbn kilde direkte ↗]({kilde_url})")
            continue

        titel = item.get("titel", "Uden titel")
        url = item.get("url", "")
        dato = item.get("dato", "")
        resume = item.get("resume", "")

        with st.container():
            col1, col2 = st.columns([5, 1])
            with col1:
                if url:
                    st.markdown(f"**[{titel}]({url})**")
                else:
                    st.markdown(f"**{titel}**")
                if resume:
                    st.caption(resume)
            with col2:
                if dato:
                    st.caption(dato)
            st.divider()


def kilde_sektion(titel: str, ikon: str, kilde_url: str, fetch_fn, *args):
    """
    Viser én kildekort med overskrift, hent-knap og resultater.
    Bruger st.session_state til at gemme resultater på tværs af genindlæsninger.
    """
    key = f"data_{titel.replace(' ', '_')}"
    key_ts = f"ts_{titel.replace(' ', '_')}"

    with st.expander(f"{ikon}  {titel}", expanded=True):
        col_header, col_btn, col_link = st.columns([4, 1, 1])
        with col_btn:
            if st.button("🔄 Hent", key=f"btn_{key}"):
                # Ryd cache for denne funktion og hent på ny
                fetch_fn.clear()
                with st.spinner("Henter…"):
                    st.session_state[key] = fetch_fn(*args)
                    st.session_state[key_ts] = datetime.now().strftime("%d.%m.%Y %H:%M")
        with col_link:
            st.markdown(f"[Åbn kilde ↗]({kilde_url})")

        if key_ts in st.session_state:
            st.caption(f"Senest opdateret: {st.session_state[key_ts]}")

        if key in st.session_state:
            vis_resultater(st.session_state[key], kilde_url)
        else:
            st.info("Tryk **Hent** for at hente de seneste data fra denne kilde.")


# ---------------------------------------------------------------------------
# Hent-alle funktion
# ---------------------------------------------------------------------------

def hent_alle():
    """Kald alle scrapers og gem i session_state."""
    opgaver = [
        ("data_Lovforslag_–_Folketing", "ts_Lovforslag_–_Folketing", hent_folketing),
        ("data_Bekendtgørelser_–_Lovtidende", "ts_Bekendtgørelser_–_Lovtidende", hent_lovtidende),
        ("data_Styresignaler_–_Skattestyrelsen", "ts_Styresignaler_–_Skattestyrelsen",
         lambda: hent_skat("16010", "Styresignaler")),
        ("data_Afgørelser_&_domme_–_Skattestyrelsen", "ts_Afgørelser_&_domme_–_Skattestyrelsen",
         lambda: hent_skat("124", "Afgørelser")),
        ("data_Vejledninger_&_satser_–_Skattestyrelsen", "ts_Vejledninger_&_satser_–_Skattestyrelsen",
         lambda: hent_skat("74288", "Vejledninger")),
        ("data_Høringer_–_Skatteministeriet", "ts_Høringer_–_Skatteministeriet", hent_hoeringsporten),
        ("data_EU-domme_–_EU-Domstolen", "ts_EU-domme_–_EU-Domstolen", hent_eu_domme),
    ]
    ts = datetime.now().strftime("%d.%m.%Y %H:%M")
    progress = st.progress(0, text="Henter alle kilder…")
    for i, (key, key_ts, fn) in enumerate(opgaver):
        try:
            # Ryd cache
            try:
                fn.__wrapped__.clear() if hasattr(fn, "__wrapped__") else None
            except Exception:
                pass
            st.session_state[key] = fn()
            st.session_state[key_ts] = ts
        except Exception as e:
            st.session_state[key] = [{"fejl": str(e)}]
            st.session_state[key_ts] = ts
        progress.progress((i + 1) / len(opgaver), text=f"Henter… ({i+1}/{len(opgaver)})")
    progress.empty()


# ---------------------------------------------------------------------------
# Hoved-layout
# ---------------------------------------------------------------------------

st.title("⚖️ Moms & Afgifter Radar")
st.caption(
    "Nyhedsoverblik til tax professionals · "
    "Henter direkte fra officielle danske og EU-kilder"
)

# Topbar
col_all, col_filter, col_info = st.columns([2, 4, 2])
with col_all:
    if st.button("🔄 Opdater alle kilder", type="primary", use_container_width=True):
        hent_alle()
        st.rerun()

with col_filter:
    valgte = st.multiselect(
        "Filtrer kategorier",
        options=["Lovforslag", "Lovtidende", "Styresignaler", "Afgørelser", "Vejledninger", "Høringer", "EU-domme"],
        default=["Lovforslag", "Lovtidende", "Styresignaler", "Afgørelser", "Vejledninger", "Høringer", "EU-domme"],
        label_visibility="collapsed",
    )

with col_info:
    st.caption(f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")

st.divider()

# Kildekorte
ALLE_KILDER = {
    "Lovforslag": {
        "titel": "Lovforslag – Folketing",
        "ikon": "🏛️",
        "url": "https://www.ft.dk/da/dokumenter/dokumentlister/lovforslag?numberOfDays=-93&searchText=*moms*",
        "fn": hent_folketing,
        "args": (),
    },
    "Lovtidende": {
        "titel": "Bekendtgørelser – Lovtidende",
        "ikon": "📜",
        "url": "https://www.lovtidende.dk/documents?o=40&t=%2Amoms%2A",
        "fn": hent_lovtidende,
        "args": (),
    },
    "Styresignaler": {
        "titel": "Styresignaler – Skattestyrelsen",
        "ikon": "📢",
        "url": "https://info.skat.dk/data.aspx?oid=16010",
        "fn": hent_skat,
        "args": ("16010", "Styresignaler"),
    },
    "Afgørelser": {
        "titel": "Afgørelser & domme – Skattestyrelsen",
        "ikon": "⚖️",
        "url": "https://info.skat.dk/data.aspx?oid=124",
        "fn": hent_skat,
        "args": ("124", "Afgørelser"),
    },
    "Vejledninger": {
        "titel": "Vejledninger & satser – Skattestyrelsen",
        "ikon": "📖",
        "url": "https://info.skat.dk/data.aspx?oid=74288",
        "fn": hent_skat,
        "args": ("74288", "Vejledninger"),
    },
    "Høringer": {
        "titel": "Høringer – Skatteministeriet",
        "ikon": "📬",
        "url": "https://hoeringsportalen.dk/Hearing?Authorities=Skatteministeriet",
        "fn": hent_hoeringsporten,
        "args": (),
    },
    "EU-domme": {
        "titel": "EU-domme – EU-Domstolen",
        "ikon": "🇪🇺",
        "url": "https://juris.curia.europa.eu/juris/recherche.jsf?language=da",
        "fn": hent_eu_domme,
        "args": (),
    },
}

for kategori, cfg in ALLE_KILDER.items():
    if kategori in valgte:
        kilde_sektion(
            cfg["titel"],
            cfg["ikon"],
            cfg["url"],
            cfg["fn"],
            *cfg["args"],
        )
