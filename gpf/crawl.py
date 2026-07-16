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
from .rules import GROUP_LEVELS, canonicalize_zones, surviving_levels

_VOLUME_RE = re.compile(r"^(.*)\.(\d{3,})$")  # « ….7z.001 » → base « ….7z », vol « 001 »
_HTTP_WORKERS = 8
_NOT_FETCHED = object()


class Ctx:
    """État mutable partagé pendant un build : client, dossier de sortie, méta de
    page, garde-fou volumétrie, compteurs."""

    def __init__(self, client: Client, out_dir: str, footer: str,
                 max_entries: int = 0):
        self.client = client
        self.out_dir = out_dir
        self.footer = footer          # bloc <footer> HTML pré-rendu (identique partout)
        self.max_entries = max_entries
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
    depth : 1 = ressource, 2 = sous-ressource, …"""
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
    prefetched = _prefetch_dirs(ctx, dirs)

    # Aplatissement (depth ≥ 2 : on garde toujours un dossier par ressource niveau 1).
    if depth >= 2 and not dirs and _is_single_unit(files):
        return ("files", [_file_row(e, fu) for e, fu in files])

    # Classement zone/date/format si toutes les sous-ressources sont ainsi typées.
    if not files and dirs and all(e["zone"] and e["fmt"] for e in dirs):
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
                       product_id=last_segment(feed_url), prefetched=prefetched)
        return ("dir", None)

    _write_dir(ctx, fs_dir, crumbs, dirs, files, depth, prefetched=prefetched)
    return ("dir", None)


def _prefetch_dirs(ctx: Ctx, dirs: list[dict]) -> dict[str, object]:
    """Récupère en parallèle les feeds enfants, avec le throttle global du client."""
    if len(dirs) < 2:
        return {}
    workers = min(_HTTP_WORKERS, len(dirs))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {e["href"]: executor.submit(ctx.client.all_entries, e["href"])
                   for e in dirs}
        return {href: future.result() for href, future in futures.items()}


def _write_dir(ctx, fs_dir, crumbs, dirs, files, depth, prefetched=None):
    """Écrit un dossier « ordinaire » : fichiers directs + sous-dossiers récursifs
    (avec aplatissement des enfants mono-unité), puis purge les dossiers obsolètes."""
    rows = [_file_row(e, fu) for e, fu in files]
    prefetched = prefetched or {}
    used, kept = set(), set()
    for e in dirs:
        name = e["title"] or resource_id(e)
        child = slug(resource_id(e), used)
        kind, payload = build_dir(ctx, e["href"], os.path.join(fs_dir, child),
                                  _descend(crumbs, name), depth + 1,
                                  fetched=prefetched.get(e["href"], _NOT_FETCHED))
        if kind == "files":
            rows.extend(payload)
        else:
            kept.add(child)
            rows.append(_dir_row(name, child + "/", e["updated"]))
    rows.sort(key=_row_sort_key)
    _emit(ctx, fs_dir, crumbs, rows)
    prune_subdirs(fs_dir, keep=kept)


def _build_grouped(ctx, fs_dir, crumbs, entries, levels, depth, product_id=None,
                   prefetched=None):
    """Classe `entries` selon `levels` (règles rules.GROUP_LEVELS) : un sous-dossier
    par valeur de term. Tout niveau `collapse_when_single` dont les entrées
    partagent une seule valeur est retiré, où qu'il soit dans la hiérarchie (pas de
    dossier inutile). Quand aucun niveau ne reste, les sous-ressources sont écrites
    directement. `product_id` (id du produit racine) est transmis au tri des niveaux
    pour d'éventuels cas dépendant du produit (cf. rules.zone_sort_key)."""
    levels = surviving_levels(entries, levels)
    prefetched = prefetched or {}
    if not levels:
        # Une seule sous-ressource au bout du classement : son dossier porterait un
        # nom brut (id API : « …__FLATGEOBUF…_FRA_2026-01-01 ») entièrement redondant
        # avec le chemin zone/date/format déjà parcouru. On la crawle directement
        # dans le dossier courant : ses fichiers (mono-unité OU multi-couches .fgb)
        # remontent d'un cran, sans dossier intermédiaire.
        if len(entries) == 1 and entries[0]["is_dir"]:
            kind, payload = build_dir(ctx, entries[0]["href"], fs_dir, crumbs,
                                      depth + 1,
                                      fetched=prefetched.get(entries[0]["href"],
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
        _write_dir(ctx, fs_dir, crumbs, entries, [], depth, prefetched=prefetched)
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
        _build_grouped(ctx, os.path.join(fs_dir, sslug),
                       _descend(crumbs, label), groups[term], levels[1:], depth + 1,
                       product_id=product_id, prefetched=prefetched)
        rows.append(_dir_row(label, sslug + "/"))
    _emit(ctx, fs_dir, crumbs, rows)          # rows suit déjà l'ordre du niveau
    prune_subdirs(fs_dir, keep={r["href"].rstrip("/") for r in rows})


def _emit(ctx, fs_dir, crumbs, rows):
    """Écrit le index.html d'un dossier de navigation : fil d'Ariane, remontée, table."""
    body = ""
    if len(crumbs) > 1:
        body += '<a class="up" href="../">↑ Dossier parent</a>'
    body += render.listing_table(rows)
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
