#!/usr/bin/env python3
"""Génère un site statique de téléchargement pour les données IGN de la
Géoplateforme : produits organisés par thème, fiche par produit (résumé + liens
de spécification), arborescence de téléchargement pointant vers data.geopf.fr.

Stdlib uniquement (urllib + xml.etree). Aucune dépendance. Python ≥ 3.11.

    python build.py                          # rebuild complet dans ./site
    python build.py --only ADMIN-EXPRESS     # ne construire qu'un produit (test)
    python build.py --only-theme admin       # ne construire qu'un thème (test)
    python build.py --check                  # dérive catalogue ↔ API (ne construit rien)
    python build.py --cloud-only BDTOPO      # régénère le seul encart cloud-native (sans re-crawl)
    python -m unittest                       # tests des fonctions pures (sans réseau)

Prévisualisation locale (un serveur HTTP est requis, file:// ne résout pas les
index.html de sous-dossiers) :

    python3 -m http.server 8000 --directory site
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from gpf import cloud, render
from gpf.api import Client, fetch_capabilities, log
from gpf.catalogue import Catalogue, CatalogueError, load_catalogue
from gpf.crawl import Ctx, build_dir, prune_subdirs
from gpf.markdown import split_sections, to_html
from gpf.model import fmt_datetime, resource_id, slug
from gpf.rules import uncurated_formats
from gpf.validate import check_drift

DEFAULT_CATALOGUE = "catalogue.json"
DEFAULT_OUT = "site"
ASSETS_DIR = "assets"        # copié tel quel vers <out>/assets (logos de producteurs…)
PAGES_DIR = "pages"          # sources Markdown des pages éditoriales (converties, NON copiées)
TUTOS_DIR = "tutos"          # tutos cloud-native par produit : tutos/<id>.md (Markdown, convertis)
# Services de téléchargement interrogés, avec repli si le catalogue ne les précise
# pas. « download » = arborescence classique (service historique) ; « chunk » = accès
# direct cloud-native (GeoParquet / FlatGeoBuf interrogeables à distance à la couche).
DEFAULT_SERVICES = {
    "download": {"base_url": "https://data.geopf.fr/telechargement",
                 "capabilities_path": "/capabilities"},
    "chunk": {"base_url": "https://data.geopf.fr/chunk/telechargement",
              "capabilities_path": "/capabilities"},
}
# Repère d'insertion : _prepend_body insère l'en-tête produit juste après ce <main>
# du gabarit render._PAGE. Doit rester synchrone avec render._PAGE.
_MAIN_TAG = "<main>\n"
# Marqueurs (commentaires HTML) encadrant l'encart cloud-native dans le index.html d'une
# fiche : --cloud-only remplace ce qui est entre eux sans re-crawler l'arbre de télécharg.
_CLOUD_START = "<!--cloud-native:start-->"
_CLOUD_END = "<!--cloud-native:end-->"
DEFAULT_HELP = ("https://cartes.gouv.fr/aide/fr/guides-utilisateur/"
                "utiliser-les-services-de-la-geoplateforme/telechargement/")
# Chapô de l'accueil (repli si "intro" absent de la config site du catalogue).
DEFAULT_INTRO = ("Parcourez et téléchargez les données de l'IGN diffusées par la "
                 "Géoplateforme, organisées par thème. Chaque produit renvoie ses "
                 "spécifications et ses fichiers de téléchargement.")
# Pied de page (Markdown ; « Généré le <date>. » est préfixé automatiquement au build).
DEFAULT_FOOTER = ("Index non officiel. Données diffusées par l'IGN via "
                  "[data.geopf.fr](https://data.geopf.fr) ; ce site n'héberge aucune "
                  "donnée et pointe les liens de téléchargement directement vers "
                  "data.geopf.fr.")
# Bloc « Besoin d'aide » de l'accueil. Texte vide → bloc masqué.
DEFAULT_HELP_TEXT = "Besoin d'aide sur le service ? Voir"
DEFAULT_HELP_LABEL = "aide officielle cartes.gouv.fr"
# Lien vers le dépôt du code (icône GitHub discrète dans le footer). Vide → pas d'icône.
DEFAULT_REPO_URL = "https://github.com/esgn/gpf-telechargement"


def _site(cat: Catalogue) -> dict:
    """Réglages de présentation du site web, avec repli sur les défauts.
    (L'accès au service de téléchargement est séparé, voir _service.)"""
    s = cat.site
    return {
        "title": s.get("title", "Téléchargement Géoplateforme"),
        "intro": s.get("intro", DEFAULT_INTRO),
        "help_url": s.get("official_help_url", DEFAULT_HELP),
        # help_text absent → défaut ; présent mais vide → bloc aide masqué (choix voulu).
        "help_text": s.get("help_text", DEFAULT_HELP_TEXT),
        "help_link_label": s.get("help_link_label", DEFAULT_HELP_LABEL),
        "footer": s.get("footer", DEFAULT_FOOTER),
        "repo_url": s.get("repo_url", DEFAULT_REPO_URL),
        # Garde-fou de rendu : on ne déplie pas un dossier au-delà de ce nombre
        # d'entrées (le service, lui, pourrait en servir davantage). 0 = illimité.
        "max_entries": s.get("max_entries", 0),
        # Lien optionnel vers des exemples/tutoriels d'usage cloud-native (le tutoriel
        # détaillé vit hors de la fiche). Vide → l'encart n'affiche pas de lien.
        "cloud_help_url": s.get("cloud_help_url", ""),
    }


def _service(cat: Catalogue, name: str) -> dict:
    """Accès à un service de téléchargement (pas le site web), par nom (« download »
    ou « chunk »), avec repli sur DEFAULT_SERVICES pour toute clé absente du catalogue."""
    s = cat.services.get(name, {})
    d = DEFAULT_SERVICES[name]
    return {
        "base_url": s.get("base_url", d["base_url"]),
        "capabilities_path": s.get("capabilities_path", d["capabilities_path"]),
    }


def _section_card(product, title: str, cat: Catalogue,
                  cloud_native: bool = False) -> dict:
    """Dict d'un produit tel que stocké dans `sections` (consommé par _cards).
    Factorise les deux branches de run_build (page éditoriale / produit crawlé).
    `cloud_native` : le produit expose-t-il un accès direct (badge sur la carte) ?"""
    return {"id": product.id, "title": title, "summary": product.summary,
            "update": product.update, "order": product.order,
            "retired": product.retired, "cloud_native": cloud_native,
            "producers": cat.resolve_producers(product)}


def _product_crumbs(theme_label: str, title: str) -> list[tuple[str, int]]:
    """Fil d'Ariane d'une page produit à /<theme>/<produit>/ : Accueil = 2 crans
    plus haut, le thème 1, la page courante 0. Commun aux fiches et aux pages
    éditoriales."""
    return [("Accueil", 2), (theme_label, 1), (title, 0)]


def _filtered_out(only: str | None, only_theme: str | None,
                  product_id: str, theme: str) -> bool:
    """Vrai si un filtre --only / --only-theme est actif et exclut ce produit.
    Le produit reste listé dans la navigation (sa carte est déjà enregistrée),
    mais il n'est ni crawlé ni construit."""
    return bool((only and only != product_id)
                or (only_theme and only_theme != theme))


def _warn_uncurated_formats(ctx: Ctx, resources: list[dict]) -> None:
    """Garde-fou : signale tout code de format exposé par le service mais absent de
    rules.FORMAT_LABELS (il s'afficherait alors avec le libellé brut de l'API). La
    liste des formats vient du capabilities (`fmt_all` de chaque ressource) — la
    source de vérité — donc la vérification est complète même sous --only. Non
    bloquant : rappel de compléter le mapping quand un nouveau format apparaît."""
    codes = {c for r in resources for c in r.get("fmt_all", ())}
    for code in sorted(uncurated_formats(codes)):
        log(f"  ⚠ format « {code} » exposé par le service mais sans libellé curé "
            f"(repli sur l'API) — à ajouter dans rules.FORMAT_LABELS.")
        ctx.warnings.append(f"format « {code} » sans libellé curé (rules.FORMAT_LABELS)")


def _fetch_chunk_live(ctx: Ctx, cat: Catalogue) -> dict:
    """Ressources du service cloud-native (chunk), indexées par id, pour résoudre les
    « cloud_native » déclarés (badges des cartes et encarts d'accès direct). Renvoie {}
    si aucun produit inclus ne déclare d'accès direct (aucune requête) ou si le service
    est inaccessible : service SECONDAIRE, on n'échoue alors PAS le build (le site de
    téléchargement classique reste complet), on se contente d'un avertissement."""
    if not any(p.cloud_native for p in cat.included()):
        return {}
    resources = fetch_capabilities(ctx.client, _service(cat, "chunk"),
                                   label="service cloud-native (chunk)")
    if resources is None:
        ctx.warnings.append("service cloud-native (chunk) inaccessible "
                            "— badges et encarts d'accès direct omis")
        return {}
    return {resource_id(e): e for e in resources}


def _cloud_tuto(product_id: str) -> tuple[str, list[tuple[str, str]]]:
    """Tutos d'un produit découpés en sections (pour les onglets) : split de
    tutos/<product_id>.md par titres « ## », ou ("", []) si le fichier n'existe pas
    (l'encart s'affiche alors sans onglets). Contenu éditorial maintenu à la main,
    comme les pages/*.md."""
    path = os.path.join(TUTOS_DIR, f"{product_id}.md")
    if not os.path.isfile(path):
        return "", []
    with open(path, encoding="utf-8") as f:
        return split_sections(f.read())


def _cloud_block(ctx: Ctx, resource_entry: dict, product, site: dict) -> str:
    """HTML de l'encart d'accès direct d'un produit : sonde COURTE de sa ressource chunk
    (cloud.fetch_product_layers, en épinglant product.cloud_edition si défini) + tutos
    éditoriaux (tutos/<id>.md), puis rendu (render.cloud_block). Renvoie « » si la
    ressource n'expose finalement aucune couche exploitable (ex. feuilles inaccessibles
    au build, malgré un format annoncé au capabilities) — signalé, non bloquant. Appelé
    seulement pour un produit à accès direct effectivement construit."""
    layers = cloud.fetch_product_layers(ctx.client, resource_entry, product.cloud_edition)
    if not layers:
        rid = resource_id(resource_entry)
        log(f"  ! « {product.id} » : ressource cloud-native « {rid} » sans couche "
            "exploitable au build — encart omis.")
        ctx.warnings.append(f"{product.id} : cloud-native sans couche exploitable ({rid})")
        return ""
    # Édition épinglée demandée mais absente de tous les formats → repli sur la dernière,
    # signalé (sinon l'épingle serait silencieusement ignorée : footgun).
    if product.cloud_edition and all(
            f["edition"] != product.cloud_edition for f in layers["formats"]):
        log(f"  ! « {product.id} » : édition cloud épinglée « {product.cloud_edition} » "
            "introuvable — repli sur la plus récente.")
        ctx.warnings.append(f"{product.id} : cloud_edition « {product.cloud_edition} » "
                            "introuvable (repli dernière édition)")
    tuto_intro, tuto_tabs = _cloud_tuto(product.id)
    return render.cloud_block(layers, help_url=site["cloud_help_url"],
                              tuto_intro=tuto_intro, tuto_tabs=tuto_tabs)


def run_build(cat: Catalogue, out_dir: str, only: str | None,
              only_theme: str | None, rps: float, workers: int = 8) -> int:
    """Reconstruit le site : chaque produit inclus est re-crawlé (pas de cache).

    `only` / `only_theme` restreignent le crawl à un produit / un thème (test) ;
    dans les deux cas les autres dossiers ne sont pas purgés. Les pages de thème
    et l'accueil sont toujours régénérées à partir du catalogue complet, de sorte
    que la navigation reste cohérente même quand un seul produit/thème est crawlé."""
    t0 = time.monotonic()
    site = _site(cat)
    service = _service(cat, "download")
    client = Client(rps=rps, workers=workers)
    resources = fetch_capabilities(client, service, label="catalogue de téléchargement")
    if resources is None:
        return 1
    live = {resource_id(e): e for e in resources}

    # Horodatage du build en heure de Paris (indépendant du fuseau du runner CI).
    now_paris = datetime.now(ZoneInfo("Europe/Paris"))
    generated = f"{fmt_datetime(now_paris.isoformat())} (heure de Paris)"
    footer = render.render_footer(site["footer"], generated, repo_url=site["repo_url"])
    ctx = Ctx(client, out_dir, footer, max_entries=site["max_entries"], workers=workers)
    _warn_uncurated_formats(ctx, resources)
    # Ressources du 2e service (cloud-native), pour les badges et encarts d'accès direct.
    # {} si aucun produit ne le déclare ou si le service est indisponible (non bloquant).
    chunk_live = _fetch_chunk_live(ctx, cat)

    sections: dict[str, list[dict]] = {}   # theme_id → [{id, title, summary}, …]
    keep_themes: set[str] = set()
    built = 0

    for product in cat.included():
        # 1. Résoudre l'entrée API. Une « page éditoriale » (product.page) n'a pas de
        #    ressource API ; un produit crawlé absent de l'API est ignoré ici, avant
        #    même d'apparaître dans la navigation.
        entry = None
        if not product.page:
            entry = live.get(product.id)
            if entry is None:
                log(f"  ! « {product.id} » inclus mais absent de l'API — ignoré.")
                continue

        # 2. Enregistrer la carte pour la navigation — TOUJOURS, même si --only saute
        #    la construction plus bas : l'accueil et les pages de thème restent complets.
        theme = cat.resolve_theme(product)
        theme_dir = slug(theme)
        title = product.title or (entry and entry["title"]) or product.id
        keep_themes.add(theme_dir)
        # Accès direct disponible ? Ressource chunk résolue ET déclarant un format
        # surfacé (GeoParquet/FlatGeoBuf), d'après le capabilities : aucune requête de
        # plus, et MÊME règle que l'encart (badge et encart ne divergent pas). Exclut les
        # pages éditoriales (product.page : ni arbre ni encart). Calculable pour TOUTES
        # les cartes (badge), même celles que --only ne construit pas.
        cloud_entry = (chunk_live.get(product.cloud_native)
                       if product.cloud_native and not product.page else None)
        has_cloud = bool(cloud_entry and cloud.has_surfaced_format(cloud_entry))
        sections.setdefault(theme, []).append(
            _section_card(product, title, cat, has_cloud))

        # 3. Construire — sauf si un filtre --only/--only-theme exclut ce produit.
        if _filtered_out(only, only_theme, product.id, theme):
            continue
        log(f"+ {title}")
        prod_dir = os.path.join(out_dir, theme_dir, product.id)
        if product.page:
            # Page éditoriale : Markdown converti en HTML, pas de crawl ni de listing.
            _build_page(ctx, product, prod_dir, title, cat.theme_label(theme))
        else:
            # Encart d'accès direct : sonde COURTE du service chunk, seulement pour un
            # produit à accès direct effectivement construit (haut de fiche, au-dessus
            # de l'arbre). Vide sinon.
            cloud_html = (_cloud_block(ctx, cloud_entry, product, site)
                          if has_cloud else "")
            _build_product(ctx, product, entry, prod_dir, title,
                           cat.theme_label(theme), cloud_html)
        built += 1

    if not only and not only_theme:
        prune_subdirs(out_dir, keep_themes)
    _copy_assets(out_dir)
    render.write_stylesheet(out_dir)          # feuille de style partagée (une fois)
    render.write_robots(out_dir)              # robots.txt : blocage des crawlers IA
    render.write_favicon(out_dir)             # favicon SVG partagée (une fois)
    _write_theme_pages(ctx, cat, sections)
    _write_home(ctx, cat, sections, site)

    elapsed = time.monotonic() - t0
    eff_rps = client.requests / elapsed if elapsed else 0.0
    log(f"\nTerminé : {built} produit(s) construit(s), {ctx.pages} page(s), "
        f"{client.requests} requête(s) en {elapsed/60:.1f} min "
        f"({eff_rps:.1f} req/s effectif).")
    if client.rate_limits:
        log(f"  Rate-limit : {client.rate_limits} réponse(s) 429, "
            f"{client.rate_limit_wait:.1f}s d'attente mur global.")
    if client.retries:
        log(f"  Réessais : {client.retries} échec(s) transitoire(s) (5xx/timeout/réseau), "
            f"{client.retry_wait:.1f}s de backoff cumulé.")

    if ctx.warnings:
        log(f"\nAvertissements ({len(ctx.warnings)}) :")
        for w in ctx.warnings:
            log(f"  - {w}")

    if ctx.errors:
        # Erreurs réseau/données : le site rendu est incomplet. On échoue pour que
        # le workflow CI (upload-pages) ne publie pas un site tronqué.
        log(f"\nERREURS FATALES ({len(ctx.errors)}) :")
        for e in ctx.errors:
            log(f"  - {e}")
        return 1

    return 0


def _build_product(ctx: Ctx, product, entry, prod_dir, title, theme_label,
                   cloud_html: str = "") -> None:
    """Fiche produit : en-tête éditorial + éventuel encart d'accès direct cloud-native
    (`cloud_html`) + arborescence de téléchargement.

    build_dir écrit le index.html du dossier produit (avec le listing). On le
    laisse faire, puis on relit ce listing pour le préfixer de l'en-tête produit :
    plus simple, build_dir reste inchangé et gère tous les cas (aplatissement,
    groupement, garde-fou volumétrie). L'encart cloud-native s'insère ENTRE l'en-tête
    et l'arbre : visible dès l'ouverture, même sur une fiche à l'arbre très long."""
    build_dir(ctx, entry["href"], prod_dir, _product_crumbs(theme_label, title), depth=1)
    # Encart encadré de marqueurs → régénérable seul via --cloud-only (sans re-crawl).
    cloud_section = f"{_CLOUD_START}{cloud_html}{_CLOUD_END}" if cloud_html else ""
    header = render.product_header(product) + cloud_section + "<hr>"
    _prepend_body(os.path.join(prod_dir, "index.html"), header)


def _splice_cloud(page: str, inner: str) -> str | None:
    """Remplace, dans une page déjà rendue, le contenu entre les marqueurs cloud-native
    (marqueurs inclus) par `inner` (réenveloppé des marqueurs). Renvoie la page modifiée,
    ou None si les marqueurs sont absents/incohérents. Fonction pure."""
    i = page.find(_CLOUD_START)
    j = page.find(_CLOUD_END)
    if i < 0 or j < 0 or j < i:
        return None
    return page[:i] + _CLOUD_START + inner + _CLOUD_END + page[j + len(_CLOUD_END):]


def _patch_cloud(ctx: Ctx, product, resource_entry: dict, prod_dir: str, site: dict) -> bool:
    """Régénère l'encart cloud-native d'un produit et le réinjecte dans sa fiche DÉJÀ
    construite (`<prod_dir>/index.html`), SANS re-crawler l'arbre de téléchargement.
    Renvoie True si la fiche a été patchée. Non destructif sinon : signale et n'écrit rien
    si la fiche est absente ou dépourvue des marqueurs cloud (fiche à construire une fois
    en entier au préalable)."""
    index = os.path.join(prod_dir, "index.html")
    if not os.path.isfile(index):
        log(f"  ! « {product.id} » : fiche absente ({index}) — construire la fiche une fois "
            f"d'abord : python build.py --only {product.id}")
        ctx.warnings.append(f"{product.id} : fiche absente (build complet requis)")
        return False
    with open(index, encoding="utf-8") as f:
        page = f.read()
    patched = _splice_cloud(page, _cloud_block(ctx, resource_entry, product, site))
    if patched is None:
        log(f"  ! « {product.id} » : marqueurs cloud-native absents (fiche construite avant "
            f"cette option) — reconstruire la fiche une fois : python build.py --only {product.id}")
        ctx.warnings.append(f"{product.id} : marqueurs cloud absents (build complet requis)")
        return False
    with open(index, "w", encoding="utf-8") as f:
        f.write(patched)
    return True


def run_cloud_only(cat: Catalogue, out_dir: str, only: str | None,
                   rps: float, workers: int = 8) -> int:
    """Régénère UNIQUEMENT l'encart cloud-native des fiches (sonde courte du service chunk
    + tutos), sans re-crawler les arbres de téléchargement : patche les fiches existantes
    entre leurs marqueurs cloud, et réécrit la feuille de style partagée (pour refléter
    d'éventuels ajustements CSS). `only` : un id de produit, ou None = tous les produits à
    accès direct. Ne touche ni à l'accueil, ni aux pages de thème, ni aux scripts du
    gabarit (un build complet reste nécessaire pour ceux-là)."""
    t0 = time.monotonic()
    site = _site(cat)
    client = Client(rps=rps, workers=workers)
    ctx = Ctx(client, out_dir, footer="", workers=workers)
    targets = [p for p in cat.included()
               if p.cloud_native and (not only or p.id == only)]
    if only and not targets:
        log(f"ERREUR : « {only} » n'est pas un produit à accès direct (champ « cloud_native »).")
        return 2

    chunk_live = _fetch_chunk_live(ctx, cat)
    render.write_stylesheet(out_dir)          # applique aussi d'éventuels ajustements CSS
    if not chunk_live:
        log("Service cloud-native indisponible — aucun encart régénéré.")
        return 1 if targets else 0

    patched = 0
    for product in targets:
        entry = chunk_live.get(product.cloud_native)
        if not entry or not cloud.has_surfaced_format(entry):
            log(f"  ! « {product.id} » : « {product.cloud_native} » sans accès direct exploitable — ignoré.")
            ctx.warnings.append(f"{product.id} : cloud_native introuvable/sans format ({product.cloud_native})")
            continue
        prod_dir = os.path.join(out_dir, slug(cat.resolve_theme(product)), product.id)
        if _patch_cloud(ctx, product, entry, prod_dir, site):
            patched += 1
            log(f"~ {product.title or product.id} : encart cloud-native régénéré")

    log(f"\nTerminé : {patched}/{len(targets)} encart(s) régénéré(s), "
        f"{client.requests} requête(s) en {time.monotonic() - t0:.1f}s "
        f"(arbres de téléchargement NON re-crawlés).")
    if ctx.warnings:
        log(f"\nAvertissements ({len(ctx.warnings)}) :")
        for w in ctx.warnings:
            log(f"  - {w}")
    return 0 if patched or not targets else 1


def _build_page(ctx: Ctx, product, prod_dir, title, theme_label) -> None:
    """Page éditoriale : convertit pages/<product.page> (Markdown) en HTML et écrit
    la page dédiée à /<theme>/<produit>/. Pas de crawl, pas de listing.

    Lève CatalogueError si le fichier Markdown est introuvable : une entrée « page »
    qui pointe vers un fichier absent est une erreur de configuration à corriger,
    pas à ignorer silencieusement (la carte mènerait à une page vide)."""
    md_path = os.path.join(PAGES_DIR, product.page)
    if not os.path.isfile(md_path):
        raise CatalogueError(
            f"« {product.id} » : page « {md_path} » introuvable "
            f"(créez le fichier ou corrigez le champ « page »).")
    with open(md_path, encoding="utf-8") as f:
        body = to_html(f.read())
    crumbs = render.breadcrumb(_product_crumbs(theme_label, title))
    ctx.write_page(prod_dir, title, body, crumbs)


def _prepend_body(index_path: str, html_fragment: str) -> None:
    """Insère `html_fragment` juste après <main> dans un index.html déjà écrit.
    Lève si le repère <main> est introuvable : ce couplage avec render._PAGE ne
    doit pas casser silencieusement (sinon la fiche produit perdrait son en-tête)."""
    with open(index_path, encoding="utf-8") as f:
        page = f.read()
    if _MAIN_TAG not in page:
        raise RuntimeError(f"repère {_MAIN_TAG!r} absent de {index_path} "
                           "(gabarit render._PAGE modifié ?)")
    page = page.replace(_MAIN_TAG, _MAIN_TAG + html_fragment + "\n", 1)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(page)


def _cards(entries: list[dict], prefix: str, depth: int = 0) -> list[dict]:
    """Cartes produit, avec un préfixe de chemin sur le href (« » depuis la page
    de thème, « <theme>/ » depuis l'accueil). Ordonnées par `order` croissant ;
    à `order` égal, l'ordre du catalogue est conservé (tri stable de Python).

    `depth` = nombre de dossiers entre la page qui affiche la carte et la racine
    du site (0 = accueil, 1 = page de thème). Sert à préfixer le chemin des logos
    des producteurs (rangés sous `assets/`, à la racine) pour qu'ils restent relatifs."""
    up = "../" * depth
    return [{"href": f'{prefix}{e["id"]}/', "title": e["title"],
             "summary": e["summary"], "update": e.get("update", ""),
             "retired": e.get("retired", False),
             "cloud_native": e.get("cloud_native", False),
             "producers": _card_producers(e.get("producers"), up)}
            for e in sorted(entries, key=lambda e: e["order"])]


def _card_producers(producers: list[dict] | None, up: str) -> list[dict]:
    """Producteurs prêts à afficher : [{name, logo}, …] dans l'ordre déclaré, où
    `logo` est un chemin relatif depuis la page courante (préfixé de `up` et de
    `assets/`), ou vide. Liste vide si le produit n'a pas de producteur."""
    return [{"name": p["name"],
             "logo": f"{up}assets/{p['logo']}" if p["logo"] else ""}
            for p in (producers or [])]


def _write_theme_pages(ctx: Ctx, cat: Catalogue, sections) -> None:
    """Une page d'index par thème (ses produits en grille) sous /<theme>/."""
    for theme_id, label in cat.themes_in_display_order():
        entries = sections.get(theme_id)
        if not entries:
            continue
        crumbs = render.breadcrumb([("Accueil", 1), (label, 0)])
        ctx.write_page(os.path.join(ctx.out_dir, slug(theme_id)),
                       label, render.theme_body(label, _cards(entries, "", depth=1)),
                       crumbs)


def _write_home(ctx: Ctx, cat: Catalogue, sections, site) -> None:
    ordered = []
    for theme_id, label in cat.themes_in_display_order():
        entries = sections.get(theme_id)
        if not entries:
            continue
        ordered.append({"id": theme_id, "label": label,
                        "href": f"{slug(theme_id)}/",
                        "cards": _cards(entries, f"{slug(theme_id)}/")})
    body = render.home_body(ordered, site_title=site["title"],
                            intro=site["intro"], help_url=site["help_url"],
                            help_text=site["help_text"],
                            help_link_label=site["help_link_label"])
    ctx.write_page(ctx.out_dir, site["title"], body, crumbs="")


def _copy_assets(out_dir: str) -> None:
    """Copie ./assets vers <out>/assets (logos de producteurs et autres statiques).
    Sans dossier assets local, il n'y a rien à copier — cas normal si aucun logo
    n'est déclaré. La cible est reconstruite à chaque build (pas de résidu)."""
    dest = os.path.join(out_dir, ASSETS_DIR)
    if not os.path.isdir(ASSETS_DIR):
        shutil.rmtree(dest, ignore_errors=True)
        return
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(ASSETS_DIR, dest)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Générateur du site de téléchargement Géoplateforme.")
    p.add_argument("--catalogue", default=DEFAULT_CATALOGUE, help="fichier catalogue (défaut : catalogue.json)")
    p.add_argument("--out", default=DEFAULT_OUT, help="dossier de sortie (défaut : site)")
    p.add_argument("--only", metavar="ID", help="ne construire que ce produit (test ; ne purge pas le reste)")
    p.add_argument("--only-theme", metavar="THEME", dest="only_theme",
                   help="ne construire que ce thème, par id (test ; ne purge pas le reste)")
    p.add_argument("--check", action="store_true", help="rapport de dérive catalogue ↔ API, sans rien construire")
    p.add_argument("--cloud-only", nargs="?", const="", default=None, metavar="ID", dest="cloud_only",
                   help="régénère SEULEMENT l'encart cloud-native (sans re-crawler l'arbre de "
                        "téléchargement) : ID = un produit, ou vide = tous les produits à accès direct")
    p.add_argument("--requests-per-second", type=float, default=10, dest="rps", help="débit visé (défaut : 10)")
    p.add_argument("--workers", type=int, default=8, dest="workers",
                   help="nombre de requêtes de crawl en parallèle (défaut : 8)")
    args = p.parse_args(argv)

    if args.only and args.only_theme:
        p.error("--only et --only-theme sont exclusifs (un produit OU un thème).")

    if args.cloud_only is not None and (args.only or args.only_theme or args.check):
        p.error("--cloud-only ne se combine pas avec --only / --only-theme / --check.")

    if args.workers < 1:
        p.error("--workers doit être ≥ 1.")

    try:
        cat = load_catalogue(args.catalogue)
    except CatalogueError as e:
        log(f"ERREUR catalogue : {e}")
        return 2

    if args.only_theme:
        valid = {tid for tid, _ in cat.themes_in_display_order()}
        if args.only_theme not in valid:
            log(f"ERREUR : thème « {args.only_theme} » inconnu. "
                f"Thèmes disponibles : {', '.join(sorted(valid))}.")
            return 2

    if args.check:
        client = Client(rps=args.rps, workers=args.workers)
        return check_drift(client, cat, _service(cat, "download"), _service(cat, "chunk"))

    if args.cloud_only is not None:
        return run_cloud_only(cat, args.out, args.cloud_only or None, args.rps, args.workers)

    return run_build(cat, args.out, args.only, args.only_theme, args.rps, args.workers)


if __name__ == "__main__":
    sys.exit(main())
