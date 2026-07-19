"""Crawl récursif d'un produit → arborescence de dossiers, chacun avec un
index.html listant fichiers et sous-dossiers.

Trois aménagements du listing brut de l'API :
  - les sidecars « .md5 » ne sont pas listés (leur checksum figure déjà en
    colonne MD5 du fichier associé) ;
  - une sous-ressource qui se réduit à UNE unité téléchargeable (fichier unique
    ou volumes d'un même .7z.NNN) est « aplatie » : ses fichiers sont listés
    directement dans le dossier parent, sans dossier dédié ;
  - quand les sous-ressources portent zone + format, elles sont classées en
    zone/date/format, un niveau à valeur unique étant replié.

Le crawl ne produit aucun HTML : il assemble des `rows` et délègue le rendu à
render.write_page / render.listing_table."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import re
import shutil

from . import render
from .api import Client, log
from .model import is_md5_file, last_segment, resource_id, slug
from .rules import (GROUP_LEVELS, canonicalize_zones, format_label,
                    surviving_levels, unlabeled_zones)

_VOLUME_RE = re.compile(r"^(.*)\.(\d{3,})$")  # « ….7z.001 » → base « ….7z », vol « 001 »
_DEFAULT_HTTP_WORKERS = 8  # défaut si Ctx n'en reçoit pas (surchargeable via --workers)
_NOT_FETCHED = object()


class Ctx:
    """État mutable partagé pendant un build : client, dossier de sortie, méta de
    page, garde-fou volumétrie, compteurs."""

    def __init__(self, client: Client, out_dir: str, footer: str,
                 max_entries: int = 0, workers: int = _DEFAULT_HTTP_WORKERS):
        self.client = client
        self.out_dir = out_dir
        self.footer = footer          # bloc <footer> HTML pré-rendu (identique partout)
        self.max_entries = max_entries
        self.workers = workers        # requêtes de crawl en parallèle (throttle global du client)
        self.pages = 0
        self.errors: list[str] = []      # réseau/données : rendent le build fatal
        self.warnings: list[str] = []    # éditorial : signalés mais non bloquants

    def write_page(self, fs_dir, title, body, crumbs):
        render.write_page(fs_dir, title, body, crumbs=crumbs, footer=self.footer,
                          out_dir=self.out_dir)
        self.pages += 1


def _file_row(entry: dict, feed_updated: str) -> dict:
    return {
        "name": entry["title"] or last_segment(entry["href"]),
        "href": entry["href"],
        "is_dir": False,
        "date": entry["updated"] or feed_updated,
        "size": entry["length"],
        "md5": entry["md5"],
    }


def _dir_row(name: str, href: str, date: str = "") -> dict:
    """Row d'un sous-dossier de navigation (schéma symétrique de _file_row, consommé
    par render.listing_table) : pas de taille ni de MD5."""
    return {"name": name, "href": href, "is_dir": True,
            "date": date, "size": None, "md5": None}


def _nav_row(name: str, href: str, formats: list[str] | None, size: int | None,
             date: str = "") -> dict:
    """Row d'un sous-dossier de NAVIGATION (niveau de groupement zone/date/radiométrie,
    ou dossier famille/série), consommé par render.nav_table : au lieu de la taille/MD5
    d'un fichier, on décrit ce qui se trouve DESSOUS — les formats disponibles et la
    taille agrégée. `formats` vaut None quand la colonne n'a pas de sens (page de format,
    où la ligne EST le format ; ou famille sans métadonnée de format). `date` (Modifié
    le) n'est renseignée que pour les dossiers famille/série (feeds datés)."""
    return {"name": name, "href": href, "formats": formats, "size": size, "date": date}


def _row_sort_key(row: dict):
    """Ordre d'affichage d'un listing : dossiers d'abord, puis par nom (insensible à
    la casse). Utilisé partout où l'on trie des rows (dossiers + fichiers/volumes)."""
    return (not row["is_dir"], row["name"].lower())


def _is_single_unit(file_entries: list[tuple[dict, str]]) -> bool:
    """Vrai si `file_entries` forme UNE unité téléchargeable : un fichier unique,
    ou les volumes d'un même fichier découpé (X.7z.001, X.7z.002…), qui partagent
    la même base et ne diffèrent que par le suffixe « .NNN ». Un vrai dossier
    multi-fichiers (jeu shapefile .shp/.dbf/.shx, tuiles…) a des bases différentes
    → False. Sert à l'aplatissement."""
    if len(file_entries) <= 1:
        return len(file_entries) == 1
    bases = set()
    for e, _ in file_entries:
        m = _VOLUME_RE.match(e["title"] or last_segment(e["href"]))
        if not m:
            return False
        bases.add(m.group(1))
    return len(bases) == 1


def _descend(crumbs, label):
    """Fil d'Ariane pour un sous-dossier : chaque crumb existant recule d'un cran
    (up + 1), et le sous-dossier devient la page courante (up = 0)."""
    return [(lbl, up + 1) for lbl, up in crumbs] + [(label, 0)]


def build_dir(ctx: Ctx, feed_url: str, fs_dir: str, crumbs, depth: int,
              fetched=_NOT_FETCHED):
    """Construit le dossier de `feed_url` et renvoie comment le parent doit le lister :
      ("files", rows) → aplati : le parent liste directement ce(s) fichier(s) ;
      ("dir",  None)  → un dossier a été écrit ; le parent liste un lien de dossier.
    crumbs : fil d'Ariane [(label, up)] du dossier courant (cf. render.breadcrumb).
    depth : 1 = ressource, 2 = sous-ressource, …

    La récursion build_dir → _write_dir/_build_grouped → build_dir gère une
    imbrication de feeds de profondeur QUELCONQUE, mais c'est défensif : l'API GPF
    est plate en pratique (ressource → sous-ressources → fichiers, soit depth 2).
    Sondé sur les 52 produits du catalogue, aucun sous-feed n'en contient d'autres
    — le cas « ressource → sous-ressource → sous-sous-ressource » ne se présente
    pas. La profondeur visible du site (zone/date/format) vient de _build_grouped
    qui éclate la LISTE PLATE des sous-ressources, non d'une descente dans des feeds
    imbriqués : c'est donc _build_grouped, et non ce _write_dir récursif, qui est le
    chemin courant."""
    got = ctx.client.all_entries(feed_url) if fetched is _NOT_FETCHED else fetched
    if got is None:
        # Feed inaccessible : le CI est de toute façon rendu rouge en fin de build
        # (cf. run_build), donc rien n'est publié. On écrit une page de secours pour
        # laisser un site cohérent en dev, sans réutiliser d'ancien contenu.
        ctx.write_page(fs_dir, crumbs[-1][0], render.unavailable_body(feed_url),
                      render.breadcrumb(crumbs))
        ctx.errors.append(f"{crumbs[-1][0]} : feed inaccessible ({feed_url})")
        return ("dir", None)
    total, feed_updated, entries, complete = got
    if not complete:
        # Listing partiel (page intermédiaire échouée) : on publie ce qu'on a mais
        # on le signale comme fatal, pour ne pas publier un dossier tronqué.
        log(f"  ! {crumbs[-1][0]} : listing partiel (une page a échoué)")
        ctx.errors.append(f"{crumbs[-1][0]} : listing partiel ({feed_url})")

    if ctx.max_entries and total > ctx.max_entries:
        log(f"  ~ {crumbs[-1][0]} : trop volumineux ({total} entrées), non déplié")
        ctx.write_page(fs_dir, crumbs[-1][0], render.oversized_body(feed_url, total),
                      render.breadcrumb(crumbs))
        prune_subdirs(fs_dir, keep=())
        return ("dir", None)

    dirs = [e for e in entries if e["is_dir"]]
    files = [(e, feed_updated) for e in entries
             if not e["is_dir"] and not is_md5_file(e["href"], e["title"])]
    dir_listings = _fetch_dirs(ctx, dirs)

    # Aplatissement (depth ≥ 2 : on garde toujours un dossier par ressource niveau 1).
    if depth >= 2 and not dirs and _is_single_unit(files):
        return ("files", [_file_row(e, fu) for e, fu in files])

    # Classement zone/date/format si toutes les sous-ressources sont ainsi typées.
    if not files and dirs and all(e["zone"] and e["fmt"] for e in dirs):
        # Zones que l'API livre SANS libellé (SBA, SMA, D986…) : on leur applique un
        # repli d'affichage (ZONE_LABELS / fusion DROM), mais on journalise ICI le
        # fichier amont concerné, pour pouvoir le remonter au producteur.
        for e in unlabeled_zones(dirs):
            log(f"  ⚠ {crumbs[-1][0]} : zone « {e['zone']} » sans libellé API "
                f"→ ex. {e['title'] or last_segment(e['href'])} ({e['href']})")
            ctx.warnings.append(f"{crumbs[-1][0]} : zone {e['zone']} sans libellé API "
                                f"(ex. {e['href']})")
        # Fusion des DROM sous codes concurrents (D971→GLP…) hors conflit de date.
        dirs, conflicts = canonicalize_zones(dirs)
        for code in conflicts:
            log(f"  ~ {crumbs[-1][0]} : {code} non fusionné "
                f"(date en conflit avec son code ISO)")
            ctx.warnings.append(f"{crumbs[-1][0]} : zone {code} non fusionnée "
                                f"(date en conflit avec son code ISO)")
        # id du produit (dernier segment du feed .../resource/<id>) : donne le contexte
        # au tri des zones (ex. « FR » = bloc et non national pour le LiDAR HD).
        _build_grouped(ctx, fs_dir, crumbs, dirs, GROUP_LEVELS, depth,
                       product_id=last_segment(feed_url), dir_listings=dir_listings)
        return ("dir", None)

    _write_dir(ctx, fs_dir, crumbs, dirs, files, depth, dir_listings=dir_listings)
    return ("dir", None)


def _fetch_dirs(ctx: Ctx, dirs: list[dict]) -> dict[str, object]:
    """Récupère le contenu COMPLET de chaque sous-feed (toutes pages, toutes entrées),
    en parallèle sur `ctx.workers`, sous le throttle global du client. La récursion
    (_write_dir / _build_grouped) réutilise ensuite ces listings via `fetched=…` au
    lieu de refetcher : le seul rôle de cette fonction est donc de PARALLÉLISER la
    récupération des sous-feeds frères, que la descente ferait sinon une par une."""
    if len(dirs) < 2:
        return {}
    workers = min(ctx.workers, len(dirs))
    # Ces appels tournent DANS le pool de largeur : chacun pagine son sous-feed en
    # série (parallel=False) pour ne pas imbriquer un 2e pool (cf. all_entries).
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {e["href"]: executor.submit(ctx.client.all_entries, e["href"],
                                              parallel=False)
                   for e in dirs}
        return {href: future.result() for href, future in futures.items()}


def _write_dir(ctx, fs_dir, crumbs, dirs, files, depth, dir_listings=None):
    """Écrit un dossier : fichiers directs + sous-dossiers récursifs (avec aplatissement
    des enfants mono-unité), puis purge les dossiers obsolètes. Deux rendus selon le
    contenu :
      - dossier de NAVIGATION pur (que des sous-dossiers, aucun fichier — famille/série
        non typée zone/format, ex. « cartes anciennes ») → nav_table, avec taille agrégée
        et formats disponibles quand ils existent, date « Modifié le » conservée ;
      - dès qu'il y a des fichiers → listing de fichiers classique (listing_table).
    La taille d'un sous-dossier est sommée depuis son feed déjà récupéré (dir_listings) :
    exact quand une sous-ressource est un feed de fichiers (cas courant, API plate) ;
    pour une famille à structure plus profonde, la taille retombe à None → colonne
    masquée (jamais de total faux)."""
    dir_listings = dir_listings or {}
    file_rows = [_file_row(e, fu) for e, fu in files]
    dir_entries = []
    used, kept = set(), set()
    for e in dirs:
        name = e["title"] or resource_id(e)
        child = slug(resource_id(e), used)
        kind, payload = build_dir(ctx, e["href"], os.path.join(fs_dir, child),
                                  _descend(crumbs, name), depth + 1,
                                  fetched=dir_listings.get(e["href"], _NOT_FETCHED))
        if kind == "files":
            file_rows.extend(payload)          # enfant aplati → ses fichiers remontent
        else:
            kept.add(child)
            dir_entries.append((name, child, e))
    if dir_entries and not file_rows:
        rows = [_nav_row(name, child + "/", _group_formats([e]) or None,
                         _group_bytes([e], dir_listings), date=e["updated"])
                for name, child, e in dir_entries]
        rows.sort(key=lambda r: r["name"].lower())
        _emit(ctx, fs_dir, crumbs, rows, table=render.nav_table)
    else:
        rows = file_rows + [_dir_row(name, child + "/", e["updated"])
                            for name, child, e in dir_entries]
        rows.sort(key=_row_sort_key)
        _emit(ctx, fs_dir, crumbs, rows)
    prune_subdirs(fs_dir, keep=kept)


def _group_formats(entries: list[dict]) -> list[str]:
    """Libellés de format distincts présents sous un groupe (zone, date…), triés pour
    un affichage stable. Alimente la colonne « Formats disponibles » des pages de
    navigation (render.nav_table) : annoncer d'emblée ce qu'on trouvera plus bas plutôt
    que d'avoir à y descendre. Libellés curés via rules.format_label (mêmes formulations
    que les dossiers de format). Déduplication sur le LIBELLÉ affiché : deux codes fondus
    sous un même nom (ex. TIF et TIFF → GeoTIFF) ne s'affichent qu'une fois. Fonction
    pure."""
    return sorted({format_label(e) for e in entries if e["fmt"]}, key=str.lower)


def _group_bytes(entries: list[dict], dir_listings: dict) -> int | None:
    """Taille agrégée d'un groupe (zone, date…) : somme des tailles des fichiers de
    toutes ses sous-ressources. Les listings ont déjà été récupérés par _fetch_dirs
    (aucune requête réseau ici) ; on additionne les `length` connues, en excluant les
    sidecars .md5 et d'éventuels sous-dossiers. Renvoie None si aucune taille n'est
    disponible (sous-ressource non pré-chargée, ou `length` absente du feed) — la
    cellule reste alors vide plutôt que d'annoncer un total faux. Fonction pure."""
    total, seen = 0, False
    for e in entries:
        got = dir_listings.get(e["href"])
        if not got:                       # None (feed inaccessible) ou absent du cache
            continue
        _total, _updated, sub_entries, _complete = got
        for f in sub_entries:
            if f["is_dir"] or is_md5_file(f["href"], f["title"]):
                continue
            if f["length"]:
                total += f["length"]
                seen = True
    return total if seen else None


def _build_grouped(ctx, fs_dir, crumbs, entries, levels, depth, product_id=None,
                   dir_listings=None):
    """Classe `entries` selon `levels` (règles rules.GROUP_LEVELS) : un sous-dossier
    par valeur de term. Tout niveau `collapse_when_single` dont les entrées
    partagent une seule valeur est retiré, où qu'il soit dans la hiérarchie (pas de
    dossier inutile). Quand aucun niveau ne reste, les sous-ressources sont écrites
    directement. `product_id` (id du produit racine) est transmis au tri des niveaux
    pour d'éventuels cas dépendant du produit (cf. rules.zone_sort_key)."""
    levels = surviving_levels(entries, levels)
    dir_listings = dir_listings or {}
    if not levels:
        # Une seule sous-ressource au bout du classement : son dossier porterait un
        # nom brut (id API : « …__FLATGEOBUF…_FRA_2026-01-01 ») entièrement redondant
        # avec le chemin zone/date/format déjà parcouru. On la crawle directement
        # dans le dossier courant : ses fichiers (mono-unité OU multi-couches .fgb)
        # remontent d'un cran, sans dossier intermédiaire.
        if len(entries) == 1 and entries[0]["is_dir"]:
            kind, payload = build_dir(ctx, entries[0]["href"], fs_dir, crumbs,
                                      depth + 1,
                                      fetched=dir_listings.get(entries[0]["href"],
                                                             _NOT_FETCHED))
            if kind == "files":
                # SR mono-unité (ex. les volumes d'un .7z) : build_dir n'a rien
                # écrit et renvoie les fichiers dans l'ordre du flux (non trié). On
                # les trie comme _write_dir (dossiers d'abord, puis par nom) pour que
                # les volumes .7z.001, .002… ressortent dans l'ordre.
                payload.sort(key=_row_sort_key)
                _emit(ctx, fs_dir, crumbs, payload)
                prune_subdirs(fs_dir, keep=())
            # kind == "dir" : build_dir a déjà écrit fs_dir (listing multi-fichiers).
            return
        _write_dir(ctx, fs_dir, crumbs, entries, [], depth, dir_listings=dir_listings)
        return

    level = levels[0]
    groups, labels = {}, {}
    for e in entries:
        term, label = level.key(e)
        labels.setdefault(term, label)
        groups.setdefault(term, []).append(e)

    used, rows = set(), []
    # sort_key reçoit aussi l'ensemble des terms du niveau : certains tris en
    # dépendent (ex. zone : le représentant d'un territoire DROM dépend des codes
    # ISO/région/dépt présents dans ce lot). cf. rules.GroupLevel.sort_key.
    present = set(groups)
    for term in sorted(groups, key=lambda t: level.sort_key(t, present, product_id),
                       reverse=level.reverse):
        sslug = slug(term, used)
        label = labels[term]
        grp = groups[term]
        _build_grouped(ctx, os.path.join(fs_dir, sslug),
                       _descend(crumbs, label), grp, levels[1:], depth + 1,
                       product_id=product_id, dir_listings=dir_listings)
        # Page de navigation : formats disponibles (sauf sur le niveau format lui-même,
        # où la ligne EST le format) + taille agrégée, tous deux calculés sur le groupe.
        formats = None if level.name == "format" else _group_formats(grp)
        rows.append(_nav_row(label, sslug + "/", formats,
                             _group_bytes(grp, dir_listings)))
    # rows suit déjà l'ordre du niveau ; nav_table (et non listing_table) : ces lignes
    # sont des dossiers de groupement, décrits par formats + taille, pas des fichiers.
    _emit(ctx, fs_dir, crumbs, rows, table=render.nav_table)
    prune_subdirs(fs_dir, keep={r["href"].rstrip("/") for r in rows})


def _emit(ctx, fs_dir, crumbs, rows, *, table=render.listing_table):
    """Écrit le index.html d'un dossier : fil d'Ariane, remontée, table. `table` est le
    rendu de listing employé : render.listing_table pour des fichiers (défaut),
    render.nav_table pour un niveau de navigation (groupement zone/date/…)."""
    body = ""
    if len(crumbs) > 1:
        body += '<a class="up" href="../">↑ Dossier parent</a>'
    body += table(rows)
    ctx.write_page(fs_dir, crumbs[-1][0], body, render.breadcrumb(crumbs))


def prune_subdirs(fs_dir: str, keep) -> None:
    """Supprime les sous-dossiers de fs_dir absents de `keep` (obsolètes au rebuild :
    sous-ressources aplaties, disparues, repliées ; ou thèmes retirés, cf. build).
    `keep` : tout itérable de noms de sous-dossiers à conserver."""
    keep = set(keep)
    try:
        names = os.listdir(fs_dir)
    except OSError:
        return
    for name in names:
        path = os.path.join(fs_dir, name)
        if name not in keep and os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
