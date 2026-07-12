"""Fonctions pures : formatage, slug, identité de ressource. Sans effet de bord,
sans réseau — tout est testable en isolation (cf. test_gpf.py)."""

from __future__ import annotations

import re
import unicodedata
import urllib.parse
from datetime import datetime

_MD5_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MONTHS = ("janv.", "févr.", "mars", "avr.", "mai", "juin",
           "juil.", "août", "sept.", "oct.", "nov.", "déc.")


def human_size(n: int | None) -> str:
    """Taille lisible en base 1024 (IEC) : « 143 », « 9.8 Kio », « 233 Mio »…
    Renvoie « — » si inconnue ou invalide (None, négatif)."""
    if n is None or n < 0:
        return "—"
    if n < 1024:
        return str(n)
    size = float(n)
    unit = "Kio"
    for unit in ("Kio", "Mio", "Gio", "Tio", "Pio", "Eio"):
        size /= 1024.0
        if size < 1024.0:
            break
    # < 10 → une décimale (« 9.8 Kio ») ; sinon entier. L'arrondi entier peut
    # atteindre 1024 au bord de plage : on remonte alors d'une unité (« 1.0 Mio »
    # plutôt que « 1024 Kio »), sauf déjà à la plus grande unité.
    if size >= 10:
        rounded = round(size)
        if rounded >= 1024 and unit != "Eio":
            _units = ("Kio", "Mio", "Gio", "Tio", "Pio", "Eio")
            return f"1.0 {_units[_units.index(unit) + 1]}"
        return f"{rounded} {unit}"
    return f"{size:.1f} {unit}"


def fmt_date(s: str | None) -> str:
    """Formate une date/datetime ISO en « 15 juil. 2025 ». Chaîne vide si illisible."""
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return ""
    return f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}"


def slug(name: str, used: set[str] | None = None) -> str:
    """Nom de dossier sûr : [A-Za-z0-9._-]. Les accents sont translittérés en ASCII
    (« Différentiel » → « Differentiel », pas « Diff_rentiel ») ; le reste devient
    « _ ». Si `used` est fourni, les collisions sont suffixées -2, -3, … et le
    résultat y est enregistré.

    En pratique un filet de sécurité : les termes issus de l'API (dernier segment
    d'`<id>`, codes zone/format, dates ISO) sont déjà slug-safe."""
    ascii_name = (unicodedata.normalize("NFKD", name)
                  .encode("ascii", "ignore").decode("ascii"))
    s = _SLUG_RE.sub("_", ascii_name).strip("_") or "item"
    if used is not None:
        base, i = s, 2
        while s in used:
            s = f"{base}-{i}"
            i += 1
        used.add(s)
    return s


def last_segment(url: str) -> str:
    """Dernier segment d'une URL (décodé), sans slash final."""
    return urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1])


def resource_id(entry: dict) -> str:
    """Identifiant stable d'une ressource = dernier segment de son <id> Atom
    (repli : href, puis titre). C'est la clé de jointure avec le catalogue et le
    nom de base du dossier. Les titres pouvant être dupliqués (« Cartes
    anciennes »), <id> donne des identifiants distincts."""
    return (last_segment(entry.get("id") or "")
            or last_segment(entry.get("href") or "")
            or entry.get("title") or "item")


def is_md5(text: str | None) -> bool:
    return bool(text) and bool(_MD5_RE.match(text.strip()))


def is_md5_file(href: str, title: str = "") -> bool:
    """Vrai si l'entrée est un sidecar de checksum « .md5 » : non listé, son
    contenu (le hash) figure déjà en colonne MD5 du fichier de données associé."""
    return (title or last_segment(href)).lower().endswith(".md5")
