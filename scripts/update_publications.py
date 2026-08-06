#!/usr/bin/env python3
"""
Fetch publications from INSPIRE-HEP and regenerate publications.html.

Usage:
    python scripts/update_publications.py

Requires no third-party libraries (stdlib only).
"""

import html
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

INSPIRE_BAI   = "Jeffrey.Lazar.1"
HEADERS       = {"User-Agent": "jlazar-website-updater/1.0"}
OUTPUT        = Path(__file__).resolve().parent.parent / "publications.html"
JSON_OUTPUT   = Path(__file__).resolve().parent.parent / "publications.json"

# Collaboration papers older than this many years are dropped entirely.
# Own (few-author) papers are always kept regardless of age.
COLLAB_YEARS_CUTOFF = 3

FEATURED_FILE = Path(__file__).resolve().parent / "featured_collabs.txt"
MERGED_FILE   = Path(__file__).resolve().parent / "merged_records.txt"


def load_merges() -> dict:
    """Return {drop_inspire_id: keep_inspire_id} for un-merged duplicate records."""
    if not MERGED_FILE.exists():
        return {}
    merges = {}
    for line in MERGED_FILE.read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        keep, drop = line.split()[:2]
        merges[drop] = keep
    return merges


def has_venue(meta: dict) -> bool:
    """True if the record names a journal, not just a bare conference reference."""
    return any(info.get("journal_title") for info in meta.get("publication_info") or [])


def graft(keep_meta: dict, drop_meta: dict) -> None:
    """Fill gaps in the kept record from its duplicate (in place).

    The preprint record carries the arXiv ID; the published record carries the
    journal reference and DOI. Whichever we keep, we want both.
    """
    for field in ("arxiv_eprints", "dois"):
        if not keep_meta.get(field) and drop_meta.get(field):
            keep_meta[field] = drop_meta[field]
    # A preprint record often has a publication_info entry holding only a
    # conference reference, which is truthy but renders as "Submitted".
    if not has_venue(keep_meta) and has_venue(drop_meta):
        keep_meta["publication_info"] = drop_meta["publication_info"]


def load_featured() -> set:
    """Return set of arXiv IDs / INSPIRE record IDs that should always be shown."""
    if not FEATURED_FILE.exists():
        return set()
    ids = set()
    for line in FEATURED_FILE.read_text().splitlines():
        line = line.split("#")[0].strip()
        if line:
            ids.add(line)
    return ids


def is_featured(arxiv, inspire_id, featured: set) -> bool:
    """Featured entries may be given as an arXiv ID or an INSPIRE record ID.

    Conference proceedings often have no arXiv preprint, so the INSPIRE record
    ID is the only stable handle for them.
    """
    return (arxiv is not None and arxiv in featured) or str(inspire_id) in featured

# Exclude `authors` here — large collaboration papers have 400+ authors and
# blow up the response. We fetch authors separately for non-collaboration papers.
INSPIRE_URL = (
    "https://inspirehep.net/api/literature"
    "?sort=mostrecent"
    "&size=1000"
    "&page=1"
    f"&q=a+{INSPIRE_BAI}"
    "&fields=titles,arxiv_eprints,publication_info,"
    "earliest_date,dois,collaborations,author_count,document_type"
)


def is_proceedings(meta: dict) -> bool:
    """Conference proceedings go in their own section below the regular papers.

    A record tagged both 'article' and 'conference paper' (e.g. a whitepaper that
    was later published in a journal) counts as a regular paper.
    """
    doc_types = meta.get("document_type", [])
    if "article" in doc_types:
        return False
    return "conference paper" in doc_types or "proceedings" in doc_types

# ── helpers ──────────────────────────────────────────────────────────────────

def _get(url: str) -> dict:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=60) as resp:
        chunks = []
        while chunk := resp.read(65536):
            chunks.append(chunk)
        return json.loads(b"".join(chunks))


def fetch_pubs() -> list:
    return _get(INSPIRE_URL)["hits"]["hits"]


def fetch_authors(inspire_id: str) -> list:
    """Fetch author list for a single paper (only called for small papers)."""
    url = (
        f"https://inspirehep.net/api/literature/{inspire_id}"
        "?fields=authors"
    )
    return _get(url).get("metadata", {}).get("authors", [])


# INSPIRE returns titles in three flavours: plain text, MathML markup, and raw
# LaTeX. The first two render fine; the third shows up literally on the page.
LATEX_SYMBOLS = {
    r"\chi": "χ", r"\nu": "ν", r"\mu": "μ", r"\tau": "τ", r"\alpha": "α",
    r"\beta": "β", r"\gamma": "γ", r"\delta": "δ", r"\epsilon": "ε",
    r"\theta": "θ", r"\lambda": "λ", r"\pi": "π", r"\sigma": "σ",
    r"\phi": "φ", r"\psi": "ψ", r"\omega": "ω", r"\Omega": "Ω",
    r"\Delta": "Δ", r"\Lambda": "Λ", r"\Gamma": "Γ", r"\Sigma": "Σ",
    r"\times": "×", r"\pm": "±", r"\to": "→", r"\rightarrow": "→",
    r"\ell": "ℓ", r"\bar": "", r"\rm": "", r"\mathrm": "", r"\text": "",
}


def latex_to_html(text: str) -> str:
    """Convert $...$ spans to HTML. Input must already be escaped."""
    def convert(m):
        s = m.group(1)
        for tex, char in sorted(LATEX_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
            s = s.replace(tex, char)
        # LaTeX pads freely around scripts and braces; HTML would show it.
        s = re.sub(r"\s+([_^])", r"\1", s)
        # Sub- and superscripts, with or without braces: _{\mu} or ^2
        s = re.sub(r"_\{\s*([^{}]*?)\s*\}", r"<sub>\1</sub>", s)
        s = re.sub(r"\^\{\s*([^{}]*?)\s*\}", r"<sup>\1</sup>", s)
        s = re.sub(r"_(\w)", r"<sub>\1</sub>", s)
        s = re.sub(r"\^(\w)", r"<sup>\1</sup>", s)
        return re.sub(r"\s+", " ", re.sub(r"[{}]", "", s)).strip()

    return re.sub(r"\$(.+?)\$", convert, text)


def clean_title(title: str) -> str:
    """Make a title safe to drop into the page, without breaking its markup.

    Titles carrying MathML are passed through -- browsers render it natively --
    with only bare ampersands escaped. Everything else is fully escaped and then
    scanned for LaTeX math.
    """
    if "<math" in title:
        # Escape ampersands that do not already begin a character reference.
        return re.sub(r"&(?!#?\w+;)", "&amp;", title)
    return latex_to_html(html.escape(title, quote=False))


# INSPIRE's collaboration values carry footnote markers and inconsistent casing.
COLLAB_CANONICAL = {
    "icecube": "IceCube",
    "icecube-gen2": "IceCube-Gen2",
    "km3net": "KM3NeT",
    "tambo": "TAMBO",
    "chips": "CHIPS",
    "hawc": "HAWC",
    "veritas": "VERITAS",
    "magic": "MAGIC",
    "antares": "ANTARES",
    "fermi-lat": "Fermi-LAT",
    "h.e.s.s.": "H.E.S.S.",
    "hess": "H.E.S.S.",
    "pierre auger": "Pierre Auger",
    "auger": "Pierre Auger",
    "telescope array": "Telescope Array",
    "ligo scientific": "LIGO Scientific",
    "virgo": "Virgo",
    "kagra": "KAGRA",
    "pico": "PICO",
    "act": "ACT",
    "svom": "SVOM",
    "fact": "FACT",
    "asas-sn": "ASAS-SN",
    "pan-starrs": "Pan-STARRS",
}


def clean_collaboration(value: str) -> str:
    """'(IceCube Collaboration)∥' -> 'IceCube'; 'ICECUBE' -> 'IceCube'."""
    name = re.sub(r"[()]", "", value)
    # Drop the trailing footnote daggers INSPIRE appends.
    name = re.sub(r"[^\w\s.\-]+$", "", name).strip()
    # The word "Collaboration" is added back by the caller. Any digits that
    # trail it are INSPIRE's ("IceCube collaboration2") -- but digits that are
    # part of the name are not, so only strip them here. IceCube-Gen2 keeps its 2.
    name = re.sub(r"\s*collaborations?\d*\s*$", "", name, flags=re.I).strip()
    return COLLAB_CANONICAL.get(name.lower(), name)


def initials(full_name: str) -> str:
    """'Lazar, Jeffrey Phillip' → 'J. P. Lazar'"""
    parts = full_name.split(", ", 1)
    if len(parts) == 2:
        last, first = parts
        inits = " ".join(w[0] + "." for w in first.split())
        return f"{inits} {last}"
    return full_name


def format_authors(authors: list, collaborations: list, author_count: int) -> str:
    # Large collaborations or papers with many authors: use collaboration name
    if collaborations and author_count > 10:
        collab = clean_collaboration(collaborations[0].get("value", ""))
        if not collab:
            return "Collaboration (incl. J. Lazar)"
        return f"{html.escape(collab)} Collaboration (incl. J. Lazar)"

    formatted = []
    for i, a in enumerate(authors):
        name = html.escape(initials(a.get("full_name", "")))
        if "Lazar" in name:
            name = f"<strong>{name}</strong>"
        formatted.append(name)
        if i == 4 and len(authors) > 5:
            formatted.append("et al.")
            break

    return ", ".join(formatted) if formatted else "J. Lazar et al."


def format_venue(pub_info: list, dois: list) -> str:
    if not pub_info:
        return '<span class="muted">Submitted</span>'
    info = pub_info[0]
    journal = html.escape(info.get("journal_title", ""))
    if not journal:
        return '<span class="muted">Submitted</span>'
    volume = info.get("journal_volume", "")
    page   = info.get("page_start", "")
    year   = info.get("year", "")
    text   = journal
    if volume:
        text += f" {volume}"
    if page:
        text += f", {page}"
    if year:
        text += f" ({year})"
    if dois:
        doi = dois[0].get("value", "")
        return f'<span class="journal"><a href="https://doi.org/{doi}" target="_blank">{text}</a></span>'
    return f'<span class="journal">{text}</span>'


def pub_html(meta: dict, inspire_id: str, featured: set = frozenset()) -> str:
    title        = clean_title(meta.get("titles", [{}])[0].get("title", "Untitled"))
    year         = (meta.get("earliest_date") or "0000")[:4]
    arxivs       = meta.get("arxiv_eprints", [])
    arxiv        = arxivs[0].get("value") if arxivs else None
    collabs      = meta.get("collaborations", [])
    author_count = meta.get("author_count", 0)
    pub_info     = meta.get("publication_info", [])
    dois         = meta.get("dois", [])

    # Only fetch full author list for small (non-collaboration) papers
    if collabs or author_count > 10:
        authors_raw = []
    else:
        authors_raw = fetch_authors(inspire_id)

    authors_str = format_authors(authors_raw, collabs, author_count)
    venue_str   = format_venue(pub_info, dois)

    arxiv_link = ""
    if arxiv:
        arxiv_link = f'<a href="https://arxiv.org/abs/{arxiv}" target="_blank">arXiv:{arxiv}</a>'

    is_collab = (bool(collabs) or author_count > 10) and not is_featured(
        arxiv, inspire_id, featured
    )
    collab_attr = ' data-collab="true"' if is_collab else ""

    return f"""\
            <div class="pub"{collab_attr}>
                <div class="pub-year">{year}</div>
                <div class="pub-body">
                    <div class="pub-title">{title}</div>
                    <div class="pub-authors">{authors_str}</div>
                    <div class="pub-venue">{venue_str}</div>
                    <div class="pub-links">{arxiv_link}</div>
                </div>
            </div>"""


# ── page template ─────────────────────────────────────────────────────────────

PROMPT = """\
            <span class="ps1">
                <span class="u">jlazar</span><span class="at">@</span><span class="h">uclouvain</span><span class="colon">:</span><span class="p">~/publications</span><span class="dollar"> $</span>\
"""

def render_years(pubs_by_year: dict, featured: set = frozenset()) -> str:
    year_blocks = []
    for year in sorted(pubs_by_year.keys(), reverse=True):
        entries = "\n".join(pub_html(p["metadata"], p["id"], featured) for p in pubs_by_year[year])
        year_blocks.append(
            f'            <div class="section-hdr"># {year}</div>\n{entries}'
        )
    return "\n\n".join(year_blocks)


def render(papers_by_year: dict, proc_by_year: dict, featured: set = frozenset()) -> str:
    papers_html = render_years(papers_by_year, featured)
    proc_html   = render_years(proc_by_year, featured)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Publications &mdash; Jeffrey Lazar</title>
    <meta name="description" content="Publications of Jeffrey P. Lazar in high-energy neutrino astrophysics, generated from INSPIRE-HEP: papers and conference proceedings.">
    <meta property="og:title" content="Publications &mdash; Jeffrey Lazar">
    <meta property="og:description" content="Publications of Jeffrey P. Lazar in high-energy neutrino astrophysics, generated from INSPIRE-HEP: papers and conference proceedings.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://www.jefflazaris.online/publications.html">
    <meta name="twitter:card" content="summary">
    <link rel="icon" href="favicon.svg" type="image/svg+xml">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;1,300;1,400&amp;display=swap" rel="stylesheet">
    <link rel="stylesheet" href="style.css">
</head>
<body>
<div class="window">
    <div class="title-bar">
        <div class="dots">
            <div class="dot dot-r"></div>
            <div class="dot dot-y"></div>
            <div class="dot dot-g"></div>
        </div>
        <span class="title-text">jlazar@uclouvain: ~/publications</span>
    </div>
    <div class="body">

        <nav class="nav">
            <span class="ps">$</span>
            <a href="index.html">~</a>
            <span class="sep">/</span>
            <a href="research.html">research</a>
            <span class="sep">/</span>
            <a href="publications.html" class="active">publications</a>
            <span class="sep">/</span>
            <a href="cv.html">cv</a>
        </nav>

        <div class="cmd" data-group="papers">
{PROMPT}
                <span class="c">ls -lt papers/</span>
            </span>
        </div>
        <div class="out" data-group="papers">
            <div style="margin-bottom: 14px; display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;">
                <span class="muted"># full list on
                <a href="https://inspirehep.net/authors/1771794" target="_blank">INSPIRE-HEP</a>
                and
                <a href="https://arxiv.org/search/?searchtype=author&amp;query=Lazar%2C+J" target="_blank">arXiv</a></span>
                <button id="collab-toggle" onclick="toggleCollabs()" class="toggle-btn"></button>
            </div>
            <script>
                var _ch = localStorage.getItem('hideCollabs') !== 'false';
                function _apply() {{
                    document.documentElement.classList.toggle('hide-collabs', _ch);
                    var btn = document.getElementById('collab-toggle');
                    if (btn) btn.textContent = _ch ? '[show collab papers]' : '[hide collab papers]';
                }}
                function _applyHeaders() {{
                    document.querySelectorAll('.section-hdr').forEach(function(hdr) {{
                        var sib = hdr.nextElementSibling;
                        var visible = false;
                        while (sib && sib.classList.contains('pub')) {{
                            if (!_ch || !sib.hasAttribute('data-collab')) {{ visible = true; break; }}
                            sib = sib.nextElementSibling;
                        }}
                        hdr.style.display = visible ? '' : 'none';
                    }});
                    // Hide a whole group (and its prompt) when every entry in it is hidden.
                    document.querySelectorAll('.out[data-group]').forEach(function(out) {{
                        var pubs = out.querySelectorAll('.pub');
                        var visible = false;
                        for (var i = 0; i < pubs.length; i++) {{
                            if (!_ch || !pubs[i].hasAttribute('data-collab')) {{ visible = true; break; }}
                        }}
                        var cmd = document.querySelector('.cmd[data-group="' + out.dataset.group + '"]');
                        out.style.display = visible ? '' : 'none';
                        if (cmd) cmd.style.display = visible ? '' : 'none';
                    }});
                }}
                function toggleCollabs() {{
                    _ch = !_ch;
                    localStorage.setItem('hideCollabs', String(_ch));
                    _apply();
                    _applyHeaders();
                }}
                _apply();
                document.addEventListener('DOMContentLoaded', _applyHeaders);
            </script>

{papers_html}

        </div>

        <div class="cmd" data-group="proceedings">
{PROMPT}
                <span class="c">ls -lt proceedings/</span>
            </span>
        </div>
        <div class="out" data-group="proceedings">

{proc_html}

        </div>

        <div class="cmd">
{PROMPT}
                <span class="cursor"></span>
            </span>
        </div>


    </div>
</div>
<script src="terminal.js" defer></script>
</body>
</html>
"""


def record_json(meta: dict, inspire_id: str, kind: str, featured: set) -> dict:
    """One publication as plain data, mirroring what pub_html renders."""
    arxivs   = meta.get("arxiv_eprints", [])
    arxiv    = arxivs[0].get("value") if arxivs else None
    collabs  = meta.get("collaborations", [])
    count    = meta.get("author_count", 0)
    pub_info = (meta.get("publication_info") or [{}])[0]
    dois     = meta.get("dois", [])
    title    = re.sub(r"<[^>]+>", "", clean_title(meta.get("titles", [{}])[0].get("title", "")))
    return {
        "id": inspire_id,
        "year": (meta.get("earliest_date") or "0000")[:4],
        "title": html.unescape(title),
        "authors": html.unescape(re.sub(r"<[^>]+>", "", format_authors(
            [] if (collabs or count > 10) else fetch_authors(inspire_id), collabs, count))),
        "venue": pub_info.get("journal_title", ""),
        "arxiv": arxiv,
        "doi": dois[0].get("value") if dois else None,
        "collab": bool(collabs) or count > 10,
        "featured": is_featured(arxiv, inspire_id, featured),
        "kind": kind,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching publications from INSPIRE-HEP...")
    featured = load_featured()
    print(f"  Featured papers: {featured or 'none'}")

    pubs = fetch_pubs()
    print(f"  Found {len(pubs)} records.")

    # Fold duplicate records into the one we keep before anything else looks at them.
    merges = load_merges()
    by_id  = {p["id"]: p for p in pubs}
    n_merged = 0
    for drop_id, keep_id in merges.items():
        if drop_id in by_id and keep_id in by_id:
            graft(by_id[keep_id]["metadata"], by_id[drop_id]["metadata"])
            n_merged += 1
        elif drop_id in by_id or keep_id in by_id:
            print(f"  WARNING: merge {keep_id} <- {drop_id}: only one record found")
    pubs = [p for p in pubs if p["id"] not in merges]
    if n_merged:
        print(f"  Merged {n_merged} duplicate record(s).")

    cutoff = datetime.now().year - COLLAB_YEARS_CUTOFF

    papers_by_year = defaultdict(list)
    proc_by_year   = defaultdict(list)
    n_dropped = 0
    for pub in pubs:
        meta         = pub["metadata"]
        year         = int((meta.get("earliest_date") or "0000")[:4])
        arxivs       = meta.get("arxiv_eprints", [])
        arxiv        = arxivs[0].get("value") if arxivs else None
        is_collab    = bool(meta.get("collaborations")) or meta.get("author_count", 0) > 10
        if is_collab and year < cutoff and not is_featured(arxiv, pub["id"], featured):
            n_dropped += 1
            continue
        bucket = proc_by_year if is_proceedings(meta) else papers_by_year
        bucket[str(year)].append(pub)

    n_papers = sum(len(v) for v in papers_by_year.values())
    n_proc   = sum(len(v) for v in proc_by_year.values())
    print(f"  Dropped {n_dropped} collab papers older than {COLLAB_YEARS_CUTOFF} years.")
    print(f"  Rendering {n_papers} papers and {n_proc} proceedings.")

    html = render(papers_by_year, proc_by_year, featured)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"  Written to {OUTPUT}")

    # The same records as machine-readable data, for the site's terminal.
    records = []
    for kind, buckets in (("paper", papers_by_year), ("proceedings", proc_by_year)):
        for year, pubs_in_year in buckets.items():
            for pub in pubs_in_year:
                records.append(record_json(pub["metadata"], pub["id"], kind, featured))
    records.sort(key=lambda r: (-int(r["year"] or 0), r["title"].lower()))
    JSON_OUTPUT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  Written to {JSON_OUTPUT} ({len(records)} records)")


if __name__ == "__main__":
    main()
