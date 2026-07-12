"""Détection de dérive : compare le catalogue local au catalogue live de l'API,
pour maintenir catalogue.json à jour quand l'IGN ajoute/retire des ressources."""

from __future__ import annotations

from .api import Client, fetch_catalogue, log
from .catalogue import Catalogue
from .model import resource_id


def check_drift(client: Client, catalogue: Catalogue, base_url: str,
                capabilities_path: str) -> int:
    """Affiche un rapport de dérive (sans rien construire). Renvoie un code de
    sortie : 0 si aucun écart, 1 si le catalogue live est inaccessible."""
    resources = fetch_catalogue(client, base_url, capabilities_path)
    if resources is None:
        return 1

    live = {resource_id(e): (e["title"] or resource_id(e)) for e in resources}
    # Entrées « page éditoriale » : ce ne sont pas des ressources de l'API, elles
    # n'ont donc pas à figurer dans la dérive (ni « disparues », ni « introuvables »).
    editorial = {p.id for p in catalogue.products if p.page}
    known = {p.id for p in catalogue.products} - editorial
    included = {p.id for p in catalogue.included()} - editorial

    new = sorted(live.keys() - known - editorial)
    missing = sorted(known - live.keys())
    orphan = sorted(included - live.keys())

    log(f"\n--- Dérive catalogue local ↔ {base_url} ---")
    log(f"  catalogue : {len(known)} produit(s) déclaré(s), "
        f"{len(included)} inclus ; API : {len(live)} ressource(s).")
    _section("nouveaux dans l'API, absents du catalogue",
             [f"{i}  « {live[i]} »" for i in new])
    _section("au catalogue mais disparus de l'API", missing)
    _section("inclus mais introuvables (généreront une page vide au build)", orphan)
    if not (new or missing or orphan):
        log("  ✓ catalogue aligné avec l'API.")
    return 0


def _section(title: str, items: list[str]) -> None:
    if items:
        log(f"\n  {len(items)} {title} :")
        for it in items:
            log(f"      {it}")
