"""Détection de dérive : compare le catalogue local au catalogue live de l'API,
pour maintenir catalogue.json à jour quand l'IGN ajoute/retire des ressources."""

from __future__ import annotations

from .api import Client, fetch_capabilities, log
from .catalogue import Catalogue
from .model import resource_id


def check_drift(client: Client, catalogue: Catalogue, download_service: dict,
                chunk_service: dict) -> int:
    """Affiche un rapport de dérive des DEUX services (sans rien construire) : le
    service de téléchargement (produits du catalogue ↔ ressources) et le service
    cloud-native (« cloud_native » déclarés ↔ ressources chunk). Renvoie 0 si aucun
    écart, 1 si le catalogue de téléchargement (principal) est inaccessible ; le
    service cloud-native est SECONDAIRE, son indisponibilité est signalée sans faire
    échouer. `*_service` : dicts {base_url, capabilities_path} (cf. build._service)."""
    resources = fetch_capabilities(client, download_service,
                                   label="catalogue de téléchargement")
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

    log(f"\n--- Dérive catalogue local ↔ {download_service['base_url']} ---")
    log(f"  catalogue : {len(known)} produit(s) déclaré(s), "
        f"{len(included)} inclus ; API : {len(live)} ressource(s).")
    _section("nouveaux dans l'API, absents du catalogue",
             [f"{i}  « {live[i]} »" for i in new])
    _section("au catalogue mais disparus de l'API", missing)
    _section("inclus mais introuvables (généreront une page vide au build)", orphan)
    if not (new or missing or orphan):
        log("  ✓ catalogue aligné avec l'API.")

    _check_cloud_drift(client, catalogue, chunk_service)
    return 0


def _check_cloud_drift(client: Client, catalogue: Catalogue,
                       chunk_service: dict) -> None:
    """Volet cloud-native du rapport : compare les « cloud_native » déclarés dans le
    catalogue aux ressources du service chunk. Signale (a) les accès directs déclarés
    qui ne résolvent plus (à corriger) et (b) les ressources chunk non encore
    référencées (accès direct possible à câbler). Non bloquant : si le service chunk
    est inaccessible, on l'indique et on s'arrête là (le volet téléchargement, lui,
    a déjà son verdict)."""
    resources = fetch_capabilities(client, chunk_service,
                                   label="service cloud-native (chunk)")
    if resources is None:
        return

    live = {resource_id(e): (e["title"] or resource_id(e)) for e in resources}
    declared = {p.cloud_native: p.id for p in catalogue.products if p.cloud_native}

    log(f"\n--- Dérive cloud-native ↔ {chunk_service['base_url']} ---")
    log(f"  catalogue : {len(declared)} produit(s) à accès direct ; "
        f"service chunk : {len(live)} ressource(s).")
    broken = sorted(cn for cn in declared if cn not in live)
    unref = sorted(live.keys() - set(declared))
    _section("« cloud_native » déclaré(s) mais absent(s) du service chunk",
             [f"{cn}  (produit « {declared[cn]} »)" for cn in broken])
    _section("ressource(s) chunk non référencée(s) (accès direct possible à câbler)",
             [f"{i}  « {live[i]} »" for i in unref])
    if not (broken or unref):
        log("  ✓ accès direct aligné avec le service chunk.")


def _section(title: str, items: list[str]) -> None:
    if items:
        log(f"\n  {len(items)} {title} :")
        for it in items:
            log(f"      {it}")
