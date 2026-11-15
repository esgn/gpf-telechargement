"""Chargement du catalogue éditorial (catalogue.json) et jointure avec le live.

L'API Géoplateforme ne fournit aucune métadonnée éditoriale (titre affichable,
thème, description, lien de spécification) : tout cela est maintenu ici, dans un
fichier JSON local, joint au crawl via l'identifiant de ressource (`id`).

Le fichier est lu par json.loads après un mini-nettoyage tolérant les
commentaires `//` en début de ligne et les virgules finales — pour qu'il reste
éditable et annotable à la main sans dépendance à un parseur YAML/TOML."""

from __future__ import annotations

import json
import re

# Thème de repli : tout produit inclus sans thème valide y atterrit, plutôt que
# de disparaître de la navigation.
FALLBACK_THEME = "autres"
FALLBACK_THEME_LABEL = "Autres jeux de données"

# Réglages facultatifs du bloc « site », avec la valeur neutre qui les désactive quand
# ils sont absents du catalogue : texte vide (bloc masqué), pas de lien, pas de
# comptage, 0 = pas de limite. Le titre, lui, est obligatoire (cf. load_catalogue).
SITE_OPTIONS = {
    "intro": "", "official_help_url": "", "help_text": "", "help_link_label": "",
    "footer": "", "repo_url": "", "goatcounter": "", "max_entries": 0,
    "cloud_help_url": "",
}


class CatalogueError(Exception):
    """Catalogue absent, JSON invalide, ou contenu incohérent."""


def _as_id_list(value) -> list[str]:
    """Normalise le champ « producer » en liste d'ids, en tolérant les deux formes
    éditables à la main : une chaîne (« ign ») ou une liste (« [ign, insee] »).
    Vides et doublons écartés ; l'ordre déclaré est conservé (ordre d'affichage)."""
    if not value:
        return []
    raw = [value] if isinstance(value, str) else list(value)
    seen, out = set(), []
    for v in raw:
        v = (v or "").strip() if isinstance(v, str) else ""
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


class Product:
    __slots__ = ("id", "title", "theme", "summary", "update", "specs", "include",
                 "order", "producers", "retired", "page", "cloud_native",
                 "cloud_edition")

    def __init__(self, raw: dict):
        if not isinstance(raw, dict) or not raw.get("id"):
            raise CatalogueError(f"produit sans « id » : {raw!r}")
        self.id: str = raw["id"]
        self.title: str = raw.get("title") or ""
        self.theme: str = raw.get("theme") or ""
        self.summary: str = raw.get("summary") or ""
        # Rythme ou statut de mise à jour, texte libre affiché tel quel sur la carte
        # (« mensuel », « annuel », « arrêté depuis 2024 »…). Vide = ligne masquée.
        self.update: str = raw.get("update") or ""
        self.include: bool = raw.get("include", True)
        # Produit arrêté : plus maintenu, généralement remplacé par un autre. Reste
        # publié (contrairement à include=false), mais sa carte porte un fond ocre et
        # un badge « Arrêté », et sa fiche un bandeau de statut. Défaut False = actif.
        self.retired: bool = raw.get("retired", False)
        # Entrée « page éditoriale » : si renseigné, ce n'est pas un produit crawlé
        # mais une page de contenu rédigé. Nom d'un fichier Markdown dans pages/
        # (ex. « mnt-lidarhd.md ») : le build le convertit en HTML et génère une page
        # interne dédiée ; aucune ressource API n'est attendue (ni crawlée, ni
        # signalée par --check). Vide = produit normal, joint au crawl via son id.
        self.page: str = raw.get("page") or ""
        # Accès « cloud-native » : identifiant de la ressource du service chunk
        # (services.chunk) exposant ce produit en formats interrogeables à distance
        # (GeoParquet / FlatGeoBuf). Explicite car l'id chunk diffère de l'id du
        # produit (ex. « BDTOPO » → « BDTOPO_PQT », « CONTOURS-IRIS » →
        # « CONTOURS-IRIS-PARTIEL »). Vide = pas d'accès direct (ni encart, ni badge).
        self.cloud_native: str = raw.get("cloud_native") or ""
        # Édition (date ISO, ex. « 2026-03-15 ») à ÉPINGLER pour l'accès direct, au lieu
        # de la plus récente. Utile quand la dernière édition est en cours de publication
        # (jeux de couches incohérents entre formats, cf. BD TOPO 2026-06-15). Vide
        # (défaut) = dernière édition disponible, par format.
        self.cloud_edition: str = raw.get("cloud_edition") or ""
        self.order: int = raw.get("order", 100)
        # id(s) du/des producteur(s), référence(s) vers catalogue.producers. Le
        # champ « producer » accepte une chaîne (« ign ») ou une liste (coédition,
        # ex. [« ign », « insee »]) ; normalisé ici en liste d'ids, vide = aucun.
        self.producers: list[str] = _as_id_list(raw.get("producer"))
        # « type » : catégorie du document (contenu, livraison, guide…), qui pilote
        # l'emoji affiché (cf. render.SPEC_ICONS). Optionnel : vide = document par
        # défaut. Le rendu signale un type inconnu (typo) sans bloquer.
        self.specs = [
            {"label": s.get("label") or s["url"], "url": s["url"],
             "type": s.get("type") or ""}
            for s in raw.get("specs", []) if isinstance(s, dict) and s.get("url")
        ]


class Catalogue:
    def __init__(self, site: dict, services: dict[str, str], themes: list[dict],
                 products: list[Product], producers: dict[str, dict] | None = None):
        self.site = site                          # présentation du site web
        # URL de base des services de téléchargement interrogés, par nom : « download »
        # (arborescence classique) et « chunk » (accès direct cloud-native).
        self.services = services
        self.themes = themes                      # ordonnés (ordre d'affichage)
        self.products = products
        self.producers = producers or {}          # id → {name, logo}
        self._by_id = {p.id: p for p in products}
        self._theme_labels = {t["id"]: t["label"] for t in themes}

    def get(self, product_id: str) -> Product | None:
        return self._by_id.get(product_id)

    def included(self) -> list[Product]:
        return [p for p in self.products if p.include]

    def resolve_producers(self, product: Product) -> list[dict]:
        """Producteurs d'un produit ([{name, logo}, …], dans l'ordre déclaré), ou
        liste vide s'il n'en déclare aucun. Un id inconnu est écarté silencieusement
        (la validation ne l'aurait laissé passer que pour un produit non inclus)."""
        return [self.producers[pid] for pid in product.producers
                if pid in self.producers]

    def theme_label(self, theme_id: str) -> str:
        return self._theme_labels.get(theme_id, FALLBACK_THEME_LABEL)

    def resolve_theme(self, product: Product) -> str:
        """Thème effectif d'un produit : le sien s'il est déclaré, sinon `autres`."""
        return product.theme if product.theme in self._theme_labels else FALLBACK_THEME

    def themes_in_display_order(self) -> list[tuple[str, str]]:
        """(id, label) des thèmes déclarés dans l'ordre du fichier, suivi de
        `autres` s'il est effectivement utilisé par un produit inclus."""
        order = [(t["id"], t["label"]) for t in self.themes]
        if any(self.resolve_theme(p) == FALLBACK_THEME for p in self.included()):
            order.append((FALLBACK_THEME, FALLBACK_THEME_LABEL))
        return order


# Le texte est parcouru de gauche à droite à la recherche de trois motifs : une chaîne
# JSON, gardée telle quelle ; un commentaire « // » ou une virgule finale, retirés.
# Une chaîne étant lue d'un seul bloc, un « // » ou une virgule qu'elle contient (URL,
# résumé) est préservé. Le « *+ » possessif lit chaque commentaire jusqu'au bout de sa
# ligne : sans lui, un « // }, » placé après une virgule la ferait passer pour finale.
_JSONC = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|,(?=(?:\s|//[^\n]*+)*[}\]])')


def strip_json_comments(text: str) -> str:
    """Retire les commentaires `//` et les virgules finales d'un JSON annoté à la
    main, sans toucher au contenu des chaînes (cf. _JSONC)."""
    return _JSONC.sub(lambda m: m[0] if m[0].startswith('"') else "", text)


def load_catalogue(path: str) -> Catalogue:
    """Charge, nettoie et valide le catalogue. Lève CatalogueError sur toute
    incohérence (fichier absent, JSON invalide, id dupliqué, thème inconnu, titre du
    site ou URL de service manquant)."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        raise CatalogueError(f"catalogue introuvable : {path} ({e})") from e
    try:
        data = json.loads(strip_json_comments(raw))
    except json.JSONDecodeError as e:
        raise CatalogueError(f"JSON invalide dans {path} : {e}") from e

    themes = data.get("themes", [])
    for t in themes:
        if not isinstance(t, dict) or not t.get("id") or not t.get("label"):
            raise CatalogueError(f"thème mal formé (id et label requis) : {t!r}")
    known = {t["id"] for t in themes}

    producers: dict[str, dict] = {}
    for pr in data.get("producers", []):
        if not isinstance(pr, dict) or not pr.get("id") or not pr.get("name"):
            raise CatalogueError(f"producteur mal formé (id et name requis) : {pr!r}")
        if pr["id"] in producers:
            raise CatalogueError(f"producteur dupliqué : « {pr['id']} »")
        producers[pr["id"]] = {"name": pr["name"], "logo": pr.get("logo") or ""}

    products = [Product(p) for p in data.get("products", [])]

    seen: set[str] = set()
    for p in products:
        if p.id in seen:
            raise CatalogueError(f"produit dupliqué : « {p.id} »")
        seen.add(p.id)
        if p.include and p.theme and p.theme not in known:
            raise CatalogueError(
                f"« {p.id} » : thème inconnu « {p.theme} » "
                f"(déclarez-le dans themes[] ou laissez-le vide pour « {FALLBACK_THEME} »)")
        if p.include:
            for pid in p.producers:
                if pid not in producers:
                    raise CatalogueError(
                        f"« {p.id} » : producteur inconnu « {pid} » "
                        f"(déclarez-le dans producers[] ou laissez-le vide)")

    # Réglages du site : le titre est obligatoire, une option absente prend sa valeur
    # neutre (cf. SITE_OPTIONS).
    site = {**SITE_OPTIONS, **data.get("site", {})}
    if not site.get("title"):
        raise CatalogueError("titre du site manquant (site.title)")

    # Services de téléchargement interrogés : l'URL de base de chacun est obligatoire.
    services = {}
    for name in ("download", "chunk"):
        service = (data.get("services") or {}).get(name)
        url = service.get("base_url") if isinstance(service, dict) else ""
        if not url:
            raise CatalogueError(f"URL du service « {name} » manquante "
                                 f"(services.{name}.base_url)")
        services[name] = url

    return Catalogue(site, services, themes, products, producers)
