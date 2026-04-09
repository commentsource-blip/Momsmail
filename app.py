"""
Moms & Afgifter Radar
=====================
Streamlit-dashboard der henter de seneste nyheder om moms og afgifter
fra officielle danske og EU-kilder.

Kør med:  streamlit run app.py
"""

import streamlit as st
import requests
import feedparser
from datetime import datetime
import json
import re

try:
    from duckduckgo_search import DDGS
    DDG_OK = True
except ImportError:
    DDG_OK = False

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
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def safe_get(url: str, timeout: int = 15, **kwargs):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, **kwargs)
        r.raise_for_status()
        return r
    except requests.RequestException:
        return None


def ddg_soeg(query: str, max_results: int = 8) -> list[dict]:
    """Søg via DuckDuckGo – kræver duckduckgo-search pakken."""
    if not DDG_OK:
        return [{"fejl": "duckduckgo-search er ikke installeret. Kør: pip install duckduckgo-search"}]
    try:
        with DDGS() as ddgs:
            resultater = []
            for r in ddgs.text(query, max_results=max_results):
                resultater.append({
                    "titel": r.get("title", "Uden titel"),
                    "dato": "",
                    "url": r.get("href", ""),
                    "resume": clean_text(r.get("body", ""))[:200],
                })
            return resultater if resultater else [{"fejl": f"Ingen resultater fundet."}]
    except Exception as e:
        return [{"fejl": f"DuckDuckGo søgefejl: {e}"}]


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_folketing() -> list[dict]:
    """
    Folketing Open Data API (ODA) – officiel REST API, meget stabil.
    Docs: https://oda.ft.dk/api/
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
    except Exception:
        return [{"fejl": "Ugyldigt svar fra Folketing API."}]

    resultater = []
    for item in data.get("value", []):
        sagsnr = item.get("Nummer", "")
        samling = item.get("Samling", {})
        samlings_id = samling.get("Id", "") if isinstance(samling, dict) else ""
        ft_url = (
            f"https://www.ft.dk/samling/{samlings_id}/lovforslag/l{sagsnr}/index.htm"
            if sagsnr and samlings_id
            else "https://www.ft.dk/da/dokumenter/dokumentlister/lovforslag"
        )
        dato_raw = item.get("Opdateringsdato", "")
        dato = dato_raw[:10] if dato_raw else ""
        resultater.append({
            "titel": clean_text(item.get("Titel", "Uden titel")),
            "dato": dato,
            "url": ft_url,
            "resume": clean_text(item.get("Resume", ""))[:250],
        })

    return resultater if resultater else [{"fejl": "Ingen lovforslag fundet."}]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_retsinformation() -> list[dict]:
    """
    Retsinformation.dk – finder love og bekendtgørelser om moms.
    Forsøger den officielle API og falder tilbage til tredjeparts-API.
    """
    # Officiel Retsinformation API
    url = (
        "https://www.retsinformation.dk/api/document"
        "?search=moms&documentType=LOV,BEK,CIR,VEJ&pageSize=10"
    )
    r = safe_get(url)

    if r is None:
        # Tredjeparts wrapper API
        url = "https://retsinformation-api.dk/v1/lovgivning/?search=moms&limit=10"
        r = safe_get(url)

    if r is None:
        return [{"fejl": "Kunne ikke hente data fra Retsinformation."}]

    try:
        data = r.json()
    except Exception:
        return [{"fejl": "Ugyldigt svar fra Retsinformation API."}]

    resultater = []
    items = data if isinstance(data, list) else data.get("results", data.get("value", []))

    for item in items[:10]:
        titel = (
            item.get("title") or item.get("Titel") or
            item.get("name") or item.get("shortTitle") or "Uden titel"
        )
        dato = (
            item.get("publishedDate") or item.get("Dato") or
            item.get("updated") or item.get("date") or ""
        )
        if dato:
            dato = dato[:10]
        item_url = item.get("url") or item.get("Uri") or item.get("link") or ""
        if item_url and not item_url.startswith("http"):
            item_url = "https://www.retsinformation.dk" + item_url
        resume = clean_text(
            item.get("abstract") or item.get("Resume") or item.get("description") or ""
        )[:200]
        if titel and titel != "Uden titel":
            resultater.append({
                "titel": clean_text(titel),
                "dato": dato,
                "url": item_url,
                "resume": resume,
            })

    return resultater if resultater else [{"fejl": "Ingen resultater fra Retsinformation."}]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_skat_styresignaler() -> list[dict]:
    """
    Nyeste styresignaler om moms via DuckDuckGo.
    (info.skat.dk er JavaScript-renderet og kan ikke scrapes direkte)
    """
    return ddg_soeg(
        'site:info.skat.dk styresignal moms afgifter 2025 OR 2026',
        max_results=8,
    )


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_skat_afgoerelser() -> list[dict]:
    """
    Nyeste afgørelser og domme om moms via DuckDuckGo.
    """
    return ddg_soeg(
        'site:info.skat.dk SKM2025 OR SKM2026 moms '
        'Landsskatteretten OR Skatterådet OR Højesteret OR Landsret',
        max_results=8,
    )


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_skat_vejledninger() -> list[dict]:
    """
    Nyeste vejledningsopdateringer om moms via DuckDuckGo.
    """
    return ddg_soeg(
        'site:info.skat.dk "Den juridiske vejledning" moms 2025 OR 2026',
        max_results=8,
    )


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_hoeringsporten() -> list[dict]:
    """
    Officielle Atom-feeds fra Høringsporten:
    - Skatteministeriet (authorityId=613)
    - SKAT (authorityId=643)
    - Skatter og afgifter (formAreaId=15)
    Disse feeds er stabile og kræver ingen JS-rendering.
    """
    feeds = [
        "https://hoeringsportalen.dk/Syndication/HearingsByAuthorityFeed?authorityId=613",
        "https://hoeringsportalen.dk/Syndication/HearingsByAuthorityFeed?authorityId=643",
        "https://hoeringsportalen.dk/Syndication/HearingsByFormAreaFeed?formAreaId=15",
    ]

    seen = set()
    resultater = []

    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                titel = clean_text(entry.get("title", "Uden titel"))
                if titel in seen:
                    continue
                seen.add(titel)

                link = entry.get("link", "")
                dato = ""
                if entry.get("published_parsed"):
                    dato = datetime(*entry.published_parsed[:3]).strftime("%d.%m.%Y")
                elif entry.get("updated_parsed"):
                    dato = datetime(*entry.updated_parsed[:3]).strftime("%d.%m.%Y")

                resume = clean_text(re.sub(r"<[^>]+>", "", entry.get("summary", "")))[:250]

                resultater.append({
                    "titel": titel,
                    "dato": dato,
                    "url": link,
                    "resume": resume,
                })
        except Exception:
            continue

    resultater.sort(key=lambda x: x.get("dato", ""), reverse=True)
    return resultater[:15] if resultater else [{"fejl": "Ingen høringer fundet i Atom-feed."}]


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def hent_eu_domme() -> list[dict]:
    """
    EU-momsdomme via DuckDuckGo (CURIA og EUR-Lex er JS-renderede).
    """
    resultater = ddg_soeg(
        'site:curia.europa.eu merværdiafgift OR moms dom 2025 OR 2026',
        max_results=6,
    )
    if resultater and "fejl" not in resultater[0]:
        return resultater

    return ddg_soeg(
        'site:eur-lex.europa.eu moms merværdiafgift dom Danmark 2025 OR 2026',
        max_results=6,
    )


# ---------------------------------------------------------------------------
# UI-komponenter
# ---------------------------------------------------------------------------

def vis_resultater(resultater: list[dict], kilde_url: str):
    for item in resultater:
        if "fejl" in item:
            st.warning(f"⚠️ {item['fejl']}")
            st.markdown(f"[Åbn kilde direkte ↗]({kilde_url})")
            continue

        titel = item.get("titel", "Uden titel")
        url = item.get("url", "")
        dato = item.get("dato", "")
        resume = item.get("resume", "")

        col1, col2 = st.columns([6, 1])
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
    key = f"data_{re.sub(r'[^a-zA-Z0-9]', '_', titel)}"
    key_ts = f"ts_{re.sub(r'[^a-zA-Z0-9]', '_', titel)}"

    with st.expander(f"{ikon}  {titel}", expanded=True):
        col_btn, col_link = st.columns([1, 1])
        with col_btn:
            if st.button("🔄 Hent", key=f"btn_{key}"):
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
# Kildekatalog
# ---------------------------------------------------------------------------

ALLE_KILDER = {
    "Lovforslag – Folketing": {
        "ikon": "🏛️",
        "url": "https://www.ft.dk/da/dokumenter/dokumentlister/lovforslag?numberOfDays=-93&searchText=*moms*",
        "fn": hent_folketing,
        "args": (),
        "kategori": "dk",
    },
    "Love & bekendtgørelser – Retsinformation": {
        "ikon": "📜",
        "url": "https://www.retsinformation.dk/",
        "fn": hent_retsinformation,
        "args": (),
        "kategori": "dk",
    },
    "Styresignaler – Skattestyrelsen": {
        "ikon": "📢",
        "url": "https://info.skat.dk/data.aspx?oid=16010",
        "fn": hent_skat_styresignaler,
        "args": (),
        "kategori": "dk",
    },
    "Afgørelser & domme – Skattestyrelsen": {
        "ikon": "⚖️",
        "url": "https://info.skat.dk/data.aspx?oid=124",
        "fn": hent_skat_afgoerelser,
        "args": (),
        "kategori": "dk",
    },
    "Vejledninger – Den Juridiske Vejledning": {
        "ikon": "📖",
        "url": "https://info.skat.dk/data.aspx?oid=74288",
        "fn": hent_skat_vejledninger,
        "args": (),
        "kategori": "dk",
    },
    "Høringer – Skatteministeriet": {
        "ikon": "📬",
        "url": "https://hoeringsportalen.dk/Hearing?Authorities=Skatteministeriet",
        "fn": hent_hoeringsporten,
        "args": (),
        "kategori": "hearing",
    },
    "EU-domme – EU-Domstolen": {
        "ikon": "🇪🇺",
        "url": "https://curia.europa.eu/juris/recherche.jsf?language=da",
        "fn": hent_eu_domme,
        "args": (),
        "kategori": "eu",
    },
}


def hent_alle(valgte_kategorier: list[str]):
    ts = datetime.now().strftime("%d.%m.%Y %H:%M")
    filtrerede = [
        (t, c) for t, c in ALLE_KILDER.items()
        if "alle" in valgte_kategorier or c["kategori"] in valgte_kategorier
    ]
    bar = st.progress(0, text="Henter alle kilder…")
    for i, (titel, cfg) in enumerate(filtrerede):
        key = f"data_{re.sub(r'[^a-zA-Z0-9]', '_', titel)}"
        key_ts = f"ts_{re.sub(r'[^a-zA-Z0-9]', '_', titel)}"
        try:
            cfg["fn"].clear()
            st.session_state[key] = cfg["fn"](*cfg["args"])
            st.session_state[key_ts] = ts
        except Exception as e:
            st.session_state[key] = [{"fejl": str(e)}]
            st.session_state[key_ts] = ts
        bar.progress((i + 1) / len(filtrerede), text=f"Henter… ({i+1}/{len(filtrerede)})")
    bar.empty()


# ---------------------------------------------------------------------------
# Hoved-layout
# ---------------------------------------------------------------------------

st.title("⚖️ Moms & Afgifter Radar")
st.caption(
    "Nyhedsoverblik for tax professionals · "
    "Henter direkte fra officielle danske og EU-kilder"
)

if not DDG_OK:
    st.warning(
        "⚠️ **duckduckgo-search** er ikke installeret — "
        "skat.dk-søgninger og EU-domme virker ikke. "
        "Installér med: `pip install duckduckgo-search`"
    )

col_all, col_filter, col_ts = st.columns([2, 4, 2])

with col_filter:
    kat_labels = {"alle": "Alle", "dk": "Dansk ret", "hearing": "Høringer", "eu": "EU"}
    valgte = st.multiselect(
        "Kategorier",
        options=list(kat_labels.keys()),
        default=["alle"],
        format_func=lambda x: kat_labels[x],
        label_visibility="collapsed",
    )
    if not valgte:
        valgte = ["alle"]

with col_all:
    if st.button("🔄 Opdater alle", type="primary", use_container_width=True):
        hent_alle(valgte)
        st.rerun()

with col_ts:
    st.caption(f"🕐 {datetime.now().strftime('%d.%m.%Y %H:%M')}")

st.divider()

for titel, cfg in ALLE_KILDER.items():
    if "alle" in valgte or cfg["kategori"] in valgte:
        kilde_sektion(titel, cfg["ikon"], cfg["url"], cfg["fn"], *cfg["args"])
