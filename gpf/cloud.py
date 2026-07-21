"""Accès « cloud-native » : sonde la ressource du service chunk d'un produit pour
lister ses couches interrogeables à distance (GeoParquet / FlatGeoBuf), format par
format.

Contrairement à crawl.py (arborescence de téléchargement PROFONDE du service
classique — zone / date / format / fichiers), on ne fait ici qu'une descente
COURTE et ciblée :

    ressource chunk  →  feuille de format (édition la plus récente)  →  fichiers

Le résultat alimente l'encart « accès direct pour l'analyse » de la fiche produit
(render.cloud_block) et le badge des cartes. Le service chunk expose exactement la
même structure de flux Atom que le service classique : on réutilise donc le même
parseur (gpf.atom, via client.all_entries) et les mêmes libellés de format
(rules.format_label).

Le service chunk livre un fichier PAR COUCHE thématique (un GeoParquet / FlatGeoBuf
= une table = une couche ; « tous thèmes » n'est pas un fichier unique), chaque
couche couvrant la même emprise. « Extraire une couche » = choisir son fichier."""

from __future__ import annotations

from .api import Client
from .model import is_md5_file, last_segment
from .rules import FORMAT_LABELS, format_label

# Formats surfacés dans l'encart : fichiers interrogeables à distance (range
# requests sur un GeoParquet brut, SOZip sur un FlatGeoBuf zippé). On raisonne sur
# le LIBELLÉ curé (rules.format_label) pour fondre les alias (PARQUET → GeoParquet,
# FGB → FlatGeoBuf) et écarter d'office les termes non curés (« geoflatbuffer/sozip »,
# PMTiles…). L'ordre du tuple fixe l'ordre des colonnes de l'encart.
CLOUD_FORMAT_LABELS = ("GeoParquet", "FlatGeoBuf")

# Extensions cloud-native retirées pour déduire le nom de couche depuis le fichier.
# Ordre important : « .fgb.zip » avant « .zip » et « .fgb » (préfixe le plus long).
_LAYER_EXTS = (".fgb.zip", ".parquet", ".fgb", ".zip")


def layer_name(href: str) -> str:
    """Nom de couche déduit d'une URL de fichier : dernier segment débarrassé de son
    extension cloud-native (« …/troncon_de_route.parquet » → « troncon_de_route »).
    Fonction pure."""
    seg = last_segment(href)
    low = seg.lower()
    for ext in _LAYER_EXTS:
        if low.endswith(ext):
            return seg[: -len(ext)]
    return seg


def _edition_better(ed: str, cur_ed: str, prefer: str) -> bool:
    """`ed` est-il un meilleur choix de feuille que `cur_ed` ? L'édition épinglée
    (`prefer`) prime ; sinon (ou entre deux non épinglées) la plus récente gagne
    (comparaison lexicographique des dates ISO). Fonction pure."""
    if prefer and (ed == prefer) != (cur_ed == prefer):
        return ed == prefer          # l'édition épinglée bat une non épinglée
    return ed > cur_ed               # sinon, la plus récente


def latest_leaf_per_format(entries: list[dict],
                           prefer_edition: str = "") -> list[tuple[str, dict]]:
    """Parmi les sous-ressources d'un produit chunk (niveau 2 : une entrée par couple
    format × édition), retient POUR CHAQUE format cloud-native surfacé UNE feuille :
    l'édition `prefer_edition` si fournie ET disponible pour ce format, sinon la plus
    récente (repli). Renvoie une liste [(libellé, entrée)] ordonnée selon
    CLOUD_FORMAT_LABELS. Formats non surfacés et entrées non-dossier ignorés. Pure."""
    best: dict[str, dict] = {}
    for e in entries:
        if not e.get("is_dir"):
            continue
        label = format_label(e)
        if label not in CLOUD_FORMAT_LABELS:
            continue
        if label not in best or _edition_better(
                e.get("editionDate") or "",
                best[label].get("editionDate") or "", prefer_edition):
            best[label] = e
    return [(lbl, best[lbl]) for lbl in CLOUD_FORMAT_LABELS if lbl in best]


def has_surfaced_format(entry: dict) -> bool:
    """Vrai si l'entrée d'une ressource (niveau capabilities chunk) déclare au moins un
    format cloud-native surfacé (CLOUD_FORMAT_LABELS), d'après ses `fmt_all`. Permet de
    conditionner le BADGE de carte à la même règle que l'encart — sans requête
    supplémentaire, les formats figurant déjà au capabilities — pour que badge et encart
    ne divergent pas. Fonction pure."""
    return any((FORMAT_LABELS.get(t) or t) in CLOUD_FORMAT_LABELS
               for t in entry.get("fmt_all") or ())


def fetch_product_layers(client: Client, resource_entry: dict,
                         prefer_edition: str = "") -> dict | None:
    """Sonde la ressource chunk d'un produit et renvoie ses couches interrogeables à
    distance, ou None si la ressource est inaccessible ou n'expose aucun format
    cloud-native exploitable. `resource_entry` est l'entrée de la ressource au niveau
    capabilities du service chunk (son `href` pointe le flux de la ressource).

    Structure renvoyée (consommée par render.cloud_block) :

        {
          "formats": [ {"label": "GeoParquet", "edition": "2026-06-15"},
                       {"label": "FlatGeoBuf", "edition": "2026-06-15"} ],   # ordonné
          "zone_label": "France entière",   # si uniforme sur les feuilles retenues, sinon ""
          "edition": "2026-06-15",          # édition la plus récente (ligne méta)
          "couches": [ {"name": "troncon_de_route",
                        "urls": {"GeoParquet": "https://…", "FlatGeoBuf": "https://…"}}, … ],
        }

    Descente courte : 1 requête pour la ressource + 1 par format retenu. Un fichier
    présent dans un seul format n'a d'URL que pour ce format (les jeux de couches
    GeoParquet et FlatGeoBuf ne coïncident pas toujours)."""
    got = client.all_entries(resource_entry["href"])
    if got is None or not got[3]:      # inaccessible ou listing partiel → on n'expose rien
        return None
    leaves = latest_leaf_per_format(got[2], prefer_edition)
    if not leaves:
        return None

    editions: dict[str, str] = {}      # label → date d'édition, formats ayant contribué
    couches: dict[str, dict] = {}
    zones: set[str] = set()
    for label, leaf in leaves:
        sub = client.all_entries(leaf["href"])
        if sub is None or not sub[3]:  # feuille inaccessible/partielle : format ignoré
            continue
        contributed = False
        for f in sub[2]:
            if f["is_dir"] or is_md5_file(f["href"], f["title"]):
                continue
            couches.setdefault(layer_name(f["href"]), {})[label] = f["href"]
            contributed = True
        if contributed:
            editions[label] = leaf.get("editionDate") or ""
            if leaf.get("zone_label"):
                zones.add(leaf["zone_label"])

    if not couches:
        return None
    dated = [d for d in editions.values() if d]
    return {
        # Uniquement les formats ayant effectivement fourni des couches (pas de colonne
        # fantôme si une feuille était vide/inaccessible). Ordre = CLOUD_FORMAT_LABELS.
        "formats": [{"label": lbl, "edition": editions[lbl]}
                    for lbl in CLOUD_FORMAT_LABELS if lbl in editions],
        "zone_label": next(iter(zones)) if len(zones) == 1 else "",
        "edition": max(dated) if dated else "",
        "couches": [{"name": name, "urls": couches[name]} for name in sorted(couches)],
    }
