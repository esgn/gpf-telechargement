"""Parsing du flux Atom de la Géoplateforme.

L'API expose une hiérarchie à 3 niveaux, tous des <feed> Atom de structure
identique :

    1. catalogue       GET {base}/capabilities              → ressources
    2. ressource       GET {base}/resource/{NOM}             → sous-ressources
    3. sous-ressource  GET {base}/resource/{NOM}/{SOUS-NOM}  → fichiers

Chaque <entry> porte un <link> : rel="alternate" type="application/atom+xml"
désigne un sous-niveau à explorer ; tout autre type désigne un fichier
téléchargeable. Les fichiers découpés (.7z.001, .7z.002…) arrivent en
rel="section". Le href pointe toujours directement vers data.geopf.fr.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .model import is_md5

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "gpf_dl": "https://data.geopf.fr/annexes/ressources/xsd/gpf_dl.xsd",
}
_GPF = "{%s}" % NS["gpf_dl"]        # préfixe pour lire les ATTRIBUTS gpf_dl ({URI}local)
_ATOM_TYPE = "application/atom+xml"  # un link de ce type = sous-niveau à explorer
_FILE_RELS = {"alternate", "section"}  # section = partie d'un fichier multi-volumes


def parse_feed(xml_bytes: bytes):
    """Parse un <feed> Atom → (pagecount, totalentries, feed_updated, entries).

    Chaque entry est un dict : title, id, updated, is_dir, href, length (int|None),
    md5 (str|None), fmt/fmt_label, fmt_all, zone/zone_label, editionDate. Les entries
    sans <link> exploitable sont ignorées. Lève ET.ParseError si le XML est tronqué.

    `fmt` est le PREMIER format déclaré (le seul, au niveau sous-ressource) ; `fmt_all`
    liste TOUS les <gpf_dl:format term> de l'entrée — utile au niveau capabilities, où
    une entrée produit énumère l'ensemble de ses formats (cf. garde-fou du build)."""
    root = ET.fromstring(xml_bytes)
    pagecount = _int(_gpf_attr(root, "pagecount"), 1)
    totalentries = _int(_gpf_attr(root, "totalentries"), 0)
    feed_updated = root.findtext("atom:updated", default="", namespaces=NS)

    entries = []
    for e in root.findall("atom:entry", NS):
        link = _pick_link(e)
        if link is None or not link.get("href"):
            continue

        content = (e.findtext("atom:content", default="", namespaces=NS) or "").strip()
        fmt = e.find("gpf_dl:format", NS)
        zone = e.find("gpf_dl:zone", NS)

        entries.append({
            "title": e.findtext("atom:title", default="", namespaces=NS).strip(),
            "id": e.findtext("atom:id", default="", namespaces=NS).strip(),
            "updated": e.findtext("atom:updated", default="", namespaces=NS).strip(),
            "is_dir": (link.get("type") or "").strip() == _ATOM_TYPE,
            "href": link.get("href"),
            "length": _int(_gpf_attr(link, "length"), None),
            # <content> est polysémique : hash MD5 au niveau fichier, sinon description.
            "md5": content if is_md5(content) else None,
            "fmt": _plain_attr(fmt, "term"),
            "fmt_label": _plain_attr(fmt, "label"),
            "fmt_all": [t for f in e.findall("gpf_dl:format", NS)
                        if (t := _plain_attr(f, "term"))],
            "zone": _plain_attr(zone, "term"),
            "zone_label": _plain_attr(zone, "label"),
            "editionDate": (e.findtext("gpf_dl:editionDate", default="",
                                       namespaces=NS).strip() or None),
        })
    return pagecount, totalentries, feed_updated, entries


def _int(value, default):
    """int() tolérant : renvoie `default` si value est None ou non numérique
    (attribut absent, vide, ou corrompu par une page d'erreur bien formée)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gpf_attr(el: ET.Element, name: str, default=None):
    """Lit un attribut porté PAR le namespace gpf_dl (pagecount, length…).
    .get() n'accepte pas de dict de namespaces : on passe la notation {URI}local."""
    return el.get(_GPF + name, default)


def _plain_attr(el: ET.Element | None, name: str):
    """Lit un attribut du namespace VIDE (term, label sur <format>/<zone>).
    Les attributs XML n'héritent PAS du namespace de leur élément : bien que
    <gpf_dl:format> soit dans gpf_dl, ses attributs term/label sont nus."""
    return el.get(name) if el is not None else None


def _pick_link(entry) -> ET.Element | None:
    """Le <link> exploitable d'une entry : rel="alternate" (sous-niveau ou fichier
    simple) ou rel="section" (volume d'un fichier découpé), sinon le premier link
    sans rel. Ignore self/up/search/describedby/pagination. None si rien."""
    fallback = None
    for ln in entry.findall("atom:link", NS):
        rel = ln.get("rel")
        if rel in _FILE_RELS:
            return ln
        if rel is None and fallback is None:
            fallback = ln
    return fallback
