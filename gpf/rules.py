"""Règles d'affichage — déclarées ici, appliquées par le code.

Ce module rassemble, en un seul endroit lisible, les règles que l'on est
*obligé* d'appliquer pour que l'arborescence de téléchargement de la
Géoplateforme soit présentée « au mieux » à l'utilisateur. L'API expose un flux
plat et parfois redondant ; ces règles reconstruisent une hiérarchie propre.

Le but est documentaire autant que fonctionnel : chaque règle porte un nom et une
description en langage clair, pour qu'on puisse relire « ce qu'on impose à tous
les produits » sans lire la logique de crawl. `crawl.py` importe ces règles et
les applique — il n'en définit aucune lui-même.

Pour ajouter/retirer/réordonner une règle de classement, on édite `GROUP_LEVELS`
ci-dessous ; le crawl suit automatiquement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GroupLevel:
    """Une règle de classement : range les sous-ressources d'un produit dans un
    niveau de dossiers (territoire, date, format…).

    - name        : nom court de la règle (pour la doc / le débogage).
    - description : ce que la règle fait, en clair.
    - key         : entry → (term, libellé). `term` sert de nom de dossier (slug)
                    et de clé de tri ; `libellé` est le texte affiché.
    - reverse     : trier les dossiers de ce niveau en ordre décroissant ?
    - collapse_when_single : si toutes les entrées partagent une seule valeur pour
                    ce niveau, faut-il le supprimer de l'arborescence (dossier
                    inutile) ? La valeur figure alors déjà dans le nom du fichier.
    - sort_key    : clé de tri des dossiers de ce niveau, appliquée à `(term,
                    present)` où `present` est l'ensemble des terms du même niveau
                    (défaut : le term lui-même = tri alphabétique). `present` permet
                    un tri dépendant du contexte — ex. zone : le représentant d'un
                    territoire DROM dépend des autres codes présents (ISO/région/dépt).
    """
    name: str
    description: str
    key: Callable[[dict], tuple[str, str]]
    reverse: bool
    collapse_when_single: bool
    sort_key: Callable[..., object] = lambda term, present, product_id=None: term


# Codes zone désignant un agrégat national ou une étendue supra-départementale.
_NATIONAL_ZONES = {"FRA", "FXX", "FR", "EUR", "WLD"}

# Exception : produits où « FR » n'est PAS un agrégat national mais un simple code de
# bloc (à trier comme les autres, pas en tête). Cas du LiDAR HD, découpé en blocs dont
# l'un s'appelle « FR ». Pour ces produits, « FR » est retiré des zones nationales.
_FR_IS_BLOCK_PRODUCTS = {"LiDARHD-NUALID"}

# Régions mono-départementales d'outre-mer → code ISO du même territoire. Sert à
# rapprocher, dans le tri, le code région d'un DROM (R01…) de son ISO (GLP…) et de
# son département (D971…). Les COM (SPM, BLM, MAF) n'ont pas de code région.
REGION_TO_ISO = {
    "R01": "GLP",           # Guadeloupe
    "R02": "MTQ",           # Martinique
    "R03": "GUF",           # Guyane
    "R04": "REU",           # La Réunion
    "R06": "MYT",           # Mayotte
}

# Libellés de secours pour les codes zone que l'API laisse sans nom (label vide ou
# égal au code). Le nom de dossier reste le code ; seul le TEXTE affiché est enrichi,
# au format « CODE Nom » pour rester cohérent avec les zones nommées par l'API
# (ex. « D054 Meurthe-et-Moselle »). À compléter si d'autres codes non nommés surgissent.
ZONE_LABELS = {
    # DROM (départements/régions d'outre-mer) — normalement nommés par l'API, mais
    # présents ici en secours (certains produits les laissent sans label).
    "D971": "Guadeloupe",
    "D972": "Martinique",
    "D973": "Guyane",
    "D974": "La Réunion",
    "D976": "Mayotte",
    # COM et collectivités (souvent non nommées par l'API).
    "D975": "Saint-Pierre-et-Miquelon",
    "D977": "Saint-Barthélemy",
    "D978": "Saint-Martin",
    "D984": "Terres australes et antarctiques françaises",
    "D986": "Wallis-et-Futuna",   # code INSEE 986, non nommé par l'API sur BD ORTHO
    "D987": "Polynésie française",
    "D988": "Nouvelle-Calédonie",
}


def zone_label(entry: dict) -> str:
    """Libellé d'affichage d'une zone : celui fourni par l'API s'il existe, sinon un
    repli depuis ZONE_LABELS au format « CODE Nom », sinon le code seul. Ne modifie
    jamais le nom de dossier (le code zone), seulement le texte montré."""
    code = entry["zone"]
    api_label = entry["zone_label"]
    if api_label and api_label != code:
        return api_label
    name = ZONE_LABELS.get(code)
    return f"{code} {name}" if name else (api_label or code)


def unlabeled_zones(entries: list[dict]) -> list[dict]:
    """Entrées dont l'API n'a PAS nommé la zone (label vide ou égal au code), une par
    code (la première rencontrée). On leur applique ensuite un repli (ZONE_LABELS ou
    fusion DROM §3), mais on expose la liste pour journaliser le fichier amont concerné
    et le remonter au producteur. Fonction pure."""
    seen: set[str] = set()
    out = []
    for e in entries:
        code, lab = e["zone"], e["zone_label"]
        if code and (not lab or lab == code) and code not in seen:
            seen.add(code)
            out.append(e)
    return out


def _is_metro_dept(term: str) -> bool:
    """« D » + 2 chiffres ≤ 95 (Corse D02A/D02B incluse) : département de métropole."""
    return (len(term) == 4 and term[0] == "D"
            and term[1:3].isdigit() and int(term[1:3]) <= 95)


def _is_region(term: str) -> bool:
    """« R » + 2 chiffres : code région INSEE (R11, R24…, R01…R06 pour les DROM)."""
    return len(term) == 3 and term[0] == "R" and term[1:].isdigit()


def _drom_granularity(term: str) -> int:
    """Rang de granularité d'un code DROM/COM au sein de son territoire, pour ordonner
    ISO → région → département : 0 = ISO (ou ancien code IGN SBA/SMA), 1 = région
    (R0x), 2 = département (D9xx)."""
    if term in REGION_TO_ISO:
        return 1
    if term in DROM_CANONICAL and term[0] == "D":
        return 2
    return 0   # code ISO (GLP, MTQ, SPM…) ou ancien code IGN (SBA, SMA)


def _drom_territory(term: str) -> str:
    """Code ISO canonique du territoire d'un code DROM/COM (clé de regroupement) :
    D9xx/SBA/SMA → ISO via DROM_CANONICAL, R0x → ISO via REGION_TO_ISO, un code ISO
    est déjà sa propre clé."""
    return DROM_CANONICAL.get(term) or REGION_TO_ISO.get(term) or term


def _drom_representative(territory: str, present: set) -> str:
    """Code « représentant » d'un territoire DROM/COM, servant de clé de tri du groupe :
    le meilleur code présent dans le lot selon la priorité ISO > région > département
    (à granularité égale, ordre alphabétique). Ex. si GLP, R01 et D971 sont présents,
    le représentant est GLP (ISO) ; si seuls R02 et D972 le sont, c'est R02 (région)."""
    codes = [z for z in present if _drom_territory(z) == territory] or [territory]
    return min(codes, key=lambda z: (_drom_granularity(z), z))


def zone_sort_key(term: str, present: set | None = None,
                  product_id: str | None = None) -> tuple:
    """Ordre d'affichage des dossiers de territoire :
      1. national / étendu (FRA, FXX, EUR…) ;
      2. régions de métropole (R11, R24… triées par numéro) ;
      3. départements de métropole (D001…D095, dont D02A/D02B, triés par numéro) ;
      4. DROM / COM, regroupés par territoire (codes côte à côte, ordre interne ISO →
         région → département), les territoires ordonnés alphabétiquement sur leur code
         « représentant » = le meilleur code présent, priorité ISO > région > dépt.
    `present` = ensemble des codes zone du même niveau (fourni par crawl) ; sert à
    choisir le représentant de chaque territoire. À défaut (appel isolé), le terme
    lui-même fait office de représentant. Le regroupement DROM/COM se fait via le code
    ISO canonique (DROM_CANONICAL / REGION_TO_ISO) ; ce tri reste correct que la fusion
    des DROM (canonicalize_zones) ait eu lieu ou non."""
    # « FR » est national par défaut, sauf pour les produits où c'est un code de bloc
    # (ex. LiDAR HD) : il est alors trié comme un bloc ordinaire, pas hissé en tête.
    national = _NATIONAL_ZONES
    if product_id in _FR_IS_BLOCK_PRODUCTS:
        national = national - {"FR"}
    if term in national:
        return (0, term)
    # Régions de métropole (les régions DROM R0x sont traitées avec leur territoire).
    if _is_region(term) and term not in REGION_TO_ISO:
        return (1, int(term[1:]), term)
    # Départements de métropole.
    if _is_metro_dept(term):
        return (2, int(term[1:3]), term)
    # DROM / COM : les territoires sont ordonnés par leur représentant (alpha, priorité
    # ISO > région > dépt) ; à l'intérieur d'un territoire, par granularité.
    territory = _drom_territory(term)
    rep = _drom_representative(territory, present) if present else territory
    return (3, rep, _drom_granularity(term), term)


_RADIOMETRY_RE = re.compile(r"(RVB|IRC)")


def radiometry(entry: dict) -> tuple[str, str]:
    """Radiométrie d'une sous-ressource d'imagerie, lue dans son titre (l'API ne
    l'expose pas en champ dédié) : « RVB » / « IRC » (naturelles / infrarouge
    couleur), ou « Graphe de mosaïquage » (produit annexe SHP). (term, label) vide
    pour tout produit non concerné → le niveau se replie (aucune valeur distincte).
    Le term sert de nom de dossier ; la résolution (0M20…) reste dans les fichiers."""
    title = entry.get("title") or ""
    m = _RADIOMETRY_RE.search(title)
    if m:
        return (m.group(1), m.group(1))
    if "GRAPHE" in title or "MOSAIQUAGE" in title:
        return ("GRAPHE", "Graphe de mosaïquage")
    return ("", "")


# --------------------------------------------------------------------------- #
# Règles de classement : zone → date d'édition → radiométrie → format.
# Ordre = ordre des niveaux de dossiers, du plus haut au plus profond.
# --------------------------------------------------------------------------- #
GROUP_LEVELS: list[GroupLevel] = [
    GroupLevel(
        name="zone",
        description="Ranger par territoire : national (FRA/FXX) d'abord, puis les "
                    "départements de métropole, puis les DROM/COM (codes d'un même "
                    "territoire rapprochés). Toujours conservé, même unique.",
        key=lambda e: (e["zone"], zone_label(e)),
        reverse=False,
        collapse_when_single=False,
        sort_key=zone_sort_key,
    ),
    GroupLevel(
        name="date",
        description="Ranger par date d'édition (millésime), la plus récente en "
                    "premier. Replié s'il n'y a qu'une seule date : la valeur "
                    "figure déjà dans le nom des fichiers.",
        key=lambda e: (e["editionDate"] or "sans-date",
                       e["editionDate"] or "(date inconnue)"),
        reverse=True,
        collapse_when_single=True,
    ),
    GroupLevel(
        name="radiometry",
        description="Ranger l'imagerie par radiométrie : RVB (couleurs naturelles), "
                    "IRC (infrarouge couleur), Graphe de mosaïquage. Lu dans le titre "
                    "(l'API ne l'expose pas en champ). Replié si valeur unique — donc "
                    "absent de tout produit non-imagerie (radiométrie vide partout).",
        key=radiometry,
        reverse=False,
        collapse_when_single=True,
    ),
    GroupLevel(
        name="format",
        description="Ranger par format (GPKG, SHP, GeoTIFF…). Replié s'il n'y a "
                    "qu'un seul format : le dossier de format n'offre alors aucun "
                    "choix (le format figure déjà dans le nom des fichiers).",
        key=lambda e: (e["fmt"], e["fmt_label"] or e["fmt"]),
        reverse=False,
        collapse_when_single=True,
    ),
]


def surviving_levels(entries: list[dict],
                     levels: list[GroupLevel]) -> list[GroupLevel]:
    """Niveaux de classement qui subsistent pour ce lot d'`entries` : tout niveau
    `collapse_when_single` dont les entrées partagent une seule valeur est retiré
    (dossier inutile). L'ordre relatif des niveaux restants est conservé. Fonction
    pure — c'est la règle appliquée par crawl._build_grouped."""
    return [lv for lv in levels
            if not (lv.collapse_when_single
                    and len({lv.key(e)[0] for e in entries}) <= 1)]


# --------------------------------------------------------------------------- #
# Fusion des DROM sous codes concurrents.
# L'API expose certains DROM sous DEUX codes zone : le code département INSEE
# (D971…) et le code ISO 3166 (GLP…), souvent avec des millésimes disjoints (SHP
# ancien sous Dxxx, GPKG récents sous ISO). Résultat : le même territoire apparaît
# deux fois dans le listing. On fusionne les deux sous le code ISO (stable,
# international, porté par les millésimes récents) — SAUF conflit (une même date
# d'édition présente sous les deux codes), auquel cas fusionner risquerait de mêler
# ou d'écraser des livraisons distinctes : on laisse alors les deux dossiers.
# --------------------------------------------------------------------------- #
DROM_CANONICAL = {          # code zone → code ISO 3166 canonique
    "D971": "GLP",          # Guadeloupe
    "D972": "MTQ",          # Martinique
    "D973": "GUF",          # Guyane
    "D974": "REU",          # La Réunion
    "D976": "MYT",          # Mayotte
    "D975": "SPM",          # Saint-Pierre-et-Miquelon
    "D977": "BLM",          # Saint-Barthélemy (code département INSEE)
    "D978": "MAF",          # Saint-Martin (code département INSEE)
    "SBA": "BLM",           # Saint-Barthélemy (ancien code IGN, millésimes ≤ 2021)
    "SMA": "MAF",           # Saint-Martin (ancien code IGN, millésimes ≤ 2021)
}


# Codes DROM/COM à 3 chiffres (971…, 988) : sert à reconnaître un « D0971 » comme un
# « D971 » mal formé (voir _normalize_zone_padding).
_DROM_COM_DIGITS = {"971", "972", "973", "974", "975", "976", "977", "978",
                    "984", "986", "987", "988"}


def _normalize_zone_padding(code: str) -> str:
    """Corrige un code zone DROM/COM avec un zéro de remplissage parasite : certains
    produits (ex. OCS GE Artificialisation) exposent « D0971 » — le padding sur 4
    chiffres appliqué aux départements métropolitains (D001…) déborde sur les codes
    DROM/COM qui en font naturellement 3. On retire le zéro pour retrouver « D971 »,
    afin que label, fusion et tri traitent ce doublon comme le code standard. Ne
    touche qu'au pattern exact « D0<ddd> » où <ddd> est un code DROM/COM connu."""
    if code.startswith("D0") and code[2:] in _DROM_COM_DIGITS:
        return "D" + code[2:]
    return code


def canonicalize_zones(entries: list[dict]) -> tuple[list[dict], list[str]]:
    """Réétiquette la zone des entries portant un code INSEE de DROM (D971…) vers
    son code ISO canonique (GLP…), UNIQUEMENT quand un vrai doublon existe — c.-à-d.
    quand le même territoire est présent dans le lot sous plusieurs codes (ex. D971
    ET GLP) — et sauf conflit (une même date d'édition sous les deux codes). Un code
    seul dans son territoire (ex. D971 sans GLP, cas BD ORTHO) n'est PAS réétiqueté :
    rien à fusionner, on préserve le code d'origine. Les codes DROM/COM à zéro de
    remplissage (« D0971 ») sont d'abord normalisés (« D971 ») pour être dédupliqués
    avec le code standard. Fonction pure : renvoie de NOUVEAUX dicts, sans muter les
    entrées d'origine.

    Retour : (entries [réétiquetées], conflits) où `conflits` liste les codes INSEE
    non fusionnés faute d'une date commune, pour journalisation."""
    # Normalise d'abord les codes à padding parasite (D0971 → D971) sur des copies,
    # pour que toute la suite (index, fusion, label) voie le code standard.
    entries = [{**e, "zone": _normalize_zone_padding(e["zone"])} for e in entries]
    # Dates présentes par code zone (pour détecter les collisions).
    dates: dict[str, set] = {}
    # Codes distincts présents par territoire (ISO canonique) : sert à ne fusionner
    # que s'il y a effectivement un doublon (≥ 2 codes pour le même territoire).
    codes_by_territory: dict[str, set] = {}
    for e in entries:
        z = e["zone"]
        dates.setdefault(z, set()).add(e["editionDate"])
        territory = DROM_CANONICAL.get(z, z)   # ISO canonique (ou le code si non-DROM)
        codes_by_territory.setdefault(territory, set()).add(z)
    # Libellé ISO de référence (celui d'une entry déjà sous le code ISO), s'il existe.
    iso_label = {e["zone"]: e["zone_label"] for e in entries}

    conflicts, out = [], []
    for e in entries:
        iso = DROM_CANONICAL.get(e["zone"])
        has_duplicate = iso and len(codes_by_territory[iso]) > 1
        if not has_duplicate:
            # Aucun autre code pour ce territoire → rien à fusionner : code conservé.
            out.append(e)
        elif dates.get(iso) and (dates[e["zone"]] & dates[iso]):
            # Une date commune aux deux codes → conflit : on ne fusionne pas.
            conflicts.append(e["zone"])
            out.append(e)
        else:
            merged = dict(e)
            merged["zone"] = iso
            # Reprendre le libellé ISO si connu ; sinon nettoyer le préfixe INSEE.
            merged["zone_label"] = iso_label.get(iso) or e["zone_label"]
            out.append(merged)
    return out, sorted(set(conflicts))
