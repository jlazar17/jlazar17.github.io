#!/usr/bin/env python3
"""
Fetch publications from INSPIRE-HEP and regenerate publications.html.

Usage:
    python scripts/update_publications.py

Requires no third-party libraries (stdlib only).
"""

import json
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

INSPIRE_BAI   = "Jeffrey.Lazar.1"
HEADERS       = {"User-Agent": "jlazar-website-updater/1.0"}
OUTPUT        = Path(__file__).resolve().parent.parent / "publications.html"

# Exclude `authors` here — large collaboration papers have 400+ authors and
# blow up the response. We fetch authors separately for non-collaboration papers.
INSPIRE_URL = (
    "https://inspirehep.net/api/literature"
    "?sort=mostrecent"
    "&size=100"
    "&page=1"
    f"&q=a+{INSPIRE_BAI}"
    "&fields=titles,arxiv_eprints,publication_info,"
    "earliest_date,dois,collaborations,author_count"
)

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
        collab = collaborations[0].get("value", "Collaboration")
        return f"{collab} Collaboration (incl. J. Lazar)"

    formatted = []
    for i, a in enumerate(authors):
        name = initials(a.get("full_name", ""))
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
    journal = info.get("journal_title", "")
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


def pub_html(meta: dict, inspire_id: str) -> str:
    title        = meta.get("titles", [{}])[0].get("title", "Untitled")
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

    return f"""\
            <div class="pub">
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

def render(pubs_by_year: dict) -> str:
    year_blocks = []
    for year in sorted(pubs_by_year.keys(), reverse=True):
        entries = "\n".join(pub_html(p["metadata"], p["id"]) for p in pubs_by_year[year])
        year_blocks.append(
            f'            <div class="section-hdr"># {year}</div>\n{entries}'
        )
    pubs_html = "\n\n".join(year_blocks)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Publications &mdash; Jeffrey Lazar</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;1,300;1,400&display=swap" rel="stylesheet">
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

        <div class="cmd">
{PROMPT}
                <span class="c">ls -lt</span>
            </span>
        </div>
        <div class="out">
            <div class="muted" style="margin-bottom: 12px;">
                # full list on
                <a href="https://inspirehep.net/authors/1771794" target="_blank">INSPIRE-HEP</a>
                and
                <a href="https://arxiv.org/search/?searchtype=author&query=Lazar%2C+J" target="_blank">arXiv</a>
            </div>

{pubs_html}

        </div>

        <div class="cmd">
{PROMPT}
                <span class="cursor"></span>
            </span>
        </div>


    </div>
</div>
</body>
</html>
"""


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching publications from INSPIRE-HEP...")
    pubs = fetch_pubs()
    print(f"  Found {len(pubs)} records.")

    by_year = defaultdict(list)
    for pub in pubs:
        year = (pub["metadata"].get("earliest_date") or "0000")[:4]
        by_year[year].append(pub)

    html = render(by_year)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"  Written to {OUTPUT}")


if __name__ == "__main__":
    main()
