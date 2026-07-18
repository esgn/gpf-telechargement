#!/usr/bin/env python3
"""Génère un site statique de téléchargement pour les données IGN de la
Géoplateforme : produits organisés par thème, fiche par produit (résumé + liens
de spécification), arborescence de téléchargement pointant vers data.geopf.fr.

Stdlib uniquement (urllib + xml.etree). Aucune dépendance. Python ≥ 3.11.

    python build.py                          # rebuild complet dans ./site
    python build.py --only ADMIN-EXPRESS     # ne construire qu'un produit (test)
    python build.py --only-theme admin       # ne construire qu'un thème (test)
    python build.py --check                  # dérive catalogue ↔ API (ne construit rien)
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

from gpf import render
from gpf.api import Client, fetch_capabilities, log
from gpf.catalogue import Catalogue, CatalogueError, load_catalogue
from gpf.crawl import Ctx, build_dir, prune_subdirs
from gpf.markdown import to_html
from gpf.model import fmt_datetime, resource_id, slug
from gpf.validate import check_drift

DEFAULT_CATALOGUE = "catalogue.json"
DEFAULT_OUT = "site"
ASSETS_DIR = "assets"        # copié tel quel vers <out>/assets (logos de producteurs…)
PAGES_DIR = "pages"          # sources Markdown des pages éditoriales (converties, NON copiées)
CAPABILITIES = "/capabilities"
# Repère d'insertion : _prepend_body insère l'en-tête produit juste après ce <main>
# du gabarit render._PAGE. Doit rester synchrone avec render._PAGE.
_MAIN_TAG = "<main>\n"
DEFAULT_BASE = "https://data.geopf.fr/telechargement"
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
    }


def _service(cat: Catalogue) -> dict:
    """Accès au service de téléchargement Géoplateforme (pas le site web)."""
    s = cat.service
    return {
        "base_url": s.get("base_url", DEFAULT_BASE),
        "capabilities_path": s.get("capabilities_path", CAPABILITIES),
    }


def _section_card(product, title: str, cat: Catalogue) -> dict:
    """Dict d'un produit tel que stocké dans `sections` (consommé par _cards).
    Factorise les deux branches de run_build (page éditoriale / produit crawlé)."""
    return {"id": product.id, "title": title, "summary": product.summary,
            "update": product.update, "order": product.order,
            "retired": product.retired,
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


def run_build(cat: Catalogue, out_dir: str, only: str | None,
              only_theme: str | None, rps: float, workers: int = 8) -> int:
    """Reconstruit le site : chaque produit inclus est re-crawlé (pas de cache).

    `only` / `only_theme` restreignent le crawl à un produit / un thème (test) ;
    dans les deux cas les autres dossiers ne sont pas purgés. Les pages de thème
    et l'accueil sont toujours régénérées à partir du catalogue complet, de sorte
    que la navigation reste cohérente même quand un seul produit/thème est crawlé."""
    t0 = time.monotonic()
    site = _site(cat)
    service = _service(cat)
    client = Client(rps=rps, workers=workers)
    resources = fetch_capabilities(client, service)
    if resources is None:
        return 1
    live = {resource_id(e): e for e in resources}

    # Horodatage du build en heure de Paris (indépendant du fuseau du runner CI).
    now_paris = datetime.now(ZoneInfo("Europe/Paris"))
    generated = f"{fmt_datetime(now_paris.isoformat())} (heure de Paris)"
    footer = render.render_footer(site["footer"], generated, repo_url=site["repo_url"])
    ctx = Ctx(client, out_dir, footer, max_entries=site["max_entries"], workers=workers)

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
        sections.setdefault(theme, []).append(_section_card(product, title, cat))

        # 3. Construire — sauf si un filtre --only/--only-theme exclut ce produit.
        if _filtered_out(only, only_theme, product.id, theme):
            continue
        log(f"+ {title}")
        prod_dir = os.path.join(out_dir, theme_dir, product.id)
        if product.page:
            # Page éditoriale : Markdown converti en HTML, pas de crawl ni de listing.
            _build_page(ctx, product, prod_dir, title, cat.theme_label(theme))
        else:
            _build_product(ctx, product, entry, prod_dir, title, cat.theme_label(theme))
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


def _build_product(ctx: Ctx, product, entry, prod_dir, title, theme_label) -> None:
    """Fiche produit : en-tête éditorial + arborescence de téléchargement.

    build_dir écrit le index.html du dossier produit (avec le listing). On le
    laisse faire, puis on relit ce listing pour le préfixer de l'en-tête produit :
    plus simple, build_dir reste inchangé et gère tous les cas (aplatissement,
    groupement, garde-fou volumétrie)."""
    build_dir(ctx, entry["href"], prod_dir, _product_crumbs(theme_label, title), depth=1)
    header = render.product_header(product) + "<hr>"
    _prepend_body(os.path.join(prod_dir, "index.html"), header)


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
    p.add_argument("--requests-per-second", type=float, default=10, dest="rps", help="débit visé (défaut : 10)")
    p.add_argument("--workers", type=int, default=8, dest="workers",
                   help="nombre de requêtes de crawl en parallèle (défaut : 8)")
    args = p.parse_args(argv)

    if args.only and args.only_theme:
        p.error("--only et --only-theme sont exclusifs (un produit OU un thème).")

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
        return check_drift(Client(rps=args.rps, workers=args.workers), cat, _service(cat))

    return run_build(cat, args.out, args.only, args.only_theme, args.rps, args.workers)


if __name__ == "__main__":
    sys.exit(main())
