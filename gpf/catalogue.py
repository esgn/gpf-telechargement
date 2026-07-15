"""Chargement du catalogue éditorial (catalogue.json) et jointure avec le live.

L'API Géoplateforme ne fournit aucune métadonnée éditoriale (titre affichable,
thème, description, lien de spécification) : tout cela est maintenu ici, dans un
fichier JSON local, joint au crawl via l'identifiant de ressource (`id`).

Le fichier est lu par json.loads après un mini-nettoyage tolérant les
commentaires `//` en début de ligne et les virgules finales — pour qu'il reste
éditable et annotable à la main sans dépendance à un parseur YAML/TOML."""

from __future__ import annotations

import json

# Thème de repli : tout produit inclus sans thème valide y atterrit, plutôt que
# de disparaître de la navigation.
FALLBACK_THEME = "autres"
FALLBACK_THEME_LABEL = "Autres jeux de données"



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
                 "order", "producers", "retired", "page")

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
        # publié (contrairement à include=false) mais sa carte est grisée et masquée
        # par défaut, révélable via le bouton d'affichage. Défaut False = actif.
        self.retired: bool = raw.get("retired", False)
        # Entrée « page éditoriale » : si renseigné, ce n'est pas un produit crawlé
        # mais une page de contenu rédigé. Nom d'un fichier Markdown dans pages/
        # (ex. « mnt-lidarhd.md ») : le build le convertit en HTML et génère une page
        # interne dédiée ; aucune ressource API n'est attendue (ni crawlée, ni
        # signalée par --check). Vide = produit normal, joint au crawl via son id.
        self.page: str = raw.get("page") or ""
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
    def __init__(self, site: dict, service: dict, themes: list[dict],
                 products: list[Product], producers: dict[str, dict] | None = None):
        self.site = site                          # présentation du site web
        self.service = service                    # accès au service de téléchargement
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


def strip_json_comments(text: str) -> str:
    """Retire les commentaires `//` (jusqu'à la fin de ligne, hors chaîne) et les
    virgules finales, pour tolérer un JSON annoté à la main. Analyse en tenant
    compte des chaînes : une virgule ou un `//` À L'INTÉRIEUR d'une chaîne (p. ex.
    une URL, ou un résumé décrivant du JSON) est préservé tel quel."""
    out: list[str] = []
    in_str = esc = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
        elif ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif ch == "/" and text[i + 1:i + 2] == "/":
            i = text.find("\n", i)          # saute le commentaire jusqu'au \n
            if i < 0:
                break
        elif ch == ",":
            # Virgule finale = suivie (espaces/commentaires/sauts de ligne mis à
            # part) de } ou ]. On regarde le prochain caractère significatif.
            j = _next_significant(text, i + 1)
            if j < n and text[j] in "}]":
                i += 1                       # on la retire
            else:
                out.append(ch)
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _next_significant(text: str, i: int) -> int:
    """Index du prochain caractère non-blanc et hors commentaire `//` à partir de i."""
    n = len(text)
    while i < n:
        if text[i].isspace():
            i += 1
        elif text[i] == "/" and text[i + 1:i + 2] == "/":
            nl = text.find("\n", i)
            if nl < 0:
                return n
            i = nl + 1
        else:
            return i
    return n


def load_catalogue(path: str) -> Catalogue:
    """Charge, nettoie et valide le catalogue. Lève CatalogueError sur toute
    incohérence (fichier absent, JSON invalide, id dupliqué, thème inconnu)."""
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

    return Catalogue(data.get("site", {}), data.get("service", {}),
                     themes, products, producers)
