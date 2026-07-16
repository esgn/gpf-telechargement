"""Client HTTP throttlé + accès au catalogue live de la Géoplateforme.

Les attentes réseau peuvent se chevaucher, mais les départs restent espacés par un
limiteur global : l'API plafonne à 10 requêtes/seconde par IP."""

from __future__ import annotations

import email.utils
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .atom import parse_feed

# Le WAF de data.geopf.fr renvoie 403 sur le User-Agent par défaut « Python-urllib »
# et sur tout UA contenant « bot ». On force un UA neutre.
_HEADERS = {
    "User-Agent": "geopf-index/1.0 (+https://github.com/esgn/gpf-telechargement)",
    "Accept": "application/atom+xml, application/xml, */*",
}

_BACKOFF_CAP = 60.0   # plafond du délai de backoff (s), avant jitter


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _parse_retry_after(headers) -> float | None:
    """Délai (s) demandé par un header « Retry-After », ou None s'il est absent ou
    illisible. RFC 7231 : soit un entier de secondes (« 5 »), soit une date HTTP
    (« Wed, 21 Oct 2025 07:28:00 GMT »). L'API Géoplateforme renvoie des secondes
    (durée de blocage initialisée à 5 s, décroissante)."""
    if headers is None:
        return None
    raw = headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (ValueError, TypeError):   # format de date invalide → on ignore le header
        return None
    delay = dt.timestamp() - time.time()
    return delay if delay > 0 else None


def _backoff(attempt: int) -> float:
    """Backoff exponentiel plafonné, avec jitter, pour les échecs sans Retry-After
    exploitable (5xx, timeout, réseau). Le jitter (±50 %) désynchronise les workers
    parallèles : sans lui, ceux qui échouent en même temps re-tapent en phase."""
    base = min(_BACKOFF_CAP, 2.0 ** attempt)
    return base * random.uniform(0.5, 1.5)


class Client:
    """Client limité à `rps` requêtes/seconde, avec backoff exponentiel sur
    429/5xx/timeout. 404 → None (ressource disparue, pas une erreur fatale).
    `page_size` est plafonné à 50 par l'API.

    Sur 429, l'API renvoie un header Retry-After (durée de blocage décroissant TANT
    QUE la sur-sollicitation cesse). Un 429 pose donc un « mur » global partagé
    (`_retry_until`) : tous les workers se taisent jusqu'à son expiration, sinon le
    trafic des autres empêcherait le compteur de redescendre (429 en boucle)."""

    def __init__(self, rps: float = 10, timeout: int = 30,
                 max_retries: int = 5, page_size: int = 50):
        # L'API plafonne à 10 req/s ; on borne dans (0, 10] pour éviter à la fois
        # une division par zéro et un throttle négatif (qui martèlerait l'API).
        rps = min(10.0, rps) if rps and rps > 0 else 10.0
        self.min_interval = 1.0 / rps
        self.timeout = timeout
        self.max_retries = max_retries
        self.page_size = page_size
        self.requests = 0
        self._last = 0.0
        self._retry_until = 0.0       # mur 429 global (time.monotonic), 0 = aucun
        self._throttle_lock = threading.Lock()

    def _pause_all(self, delay: float) -> None:
        """Pose un mur 429 global : recule `_retry_until` d'au moins `delay` s pour
        que tous les workers observent la pause au prochain `_wait_for_slot`. On ne
        raccourcit jamais un mur déjà plus lointain (max)."""
        with self._throttle_lock:
            self._retry_until = max(self._retry_until, time.monotonic() + delay)

    def _wait_for_slot(self) -> None:
        """Réserve un départ de requête en respectant le débit global et un éventuel
        mur 429.

        Le verrou reste pris pendant l'attente afin que les fetch parallèles des
        sous-dossiers d'un même parent espacent leurs départs, tout en pouvant
        attendre leurs réponses réseau en parallèle. Il reste pris aussi pendant la
        pause du mur 429 : c'est voulu, tous les workers doivent se taire ensemble
        pour que la sur-sollicitation cesse.
        """
        with self._throttle_lock:
            wall = self._retry_until - time.monotonic()
            if wall > 0:
                time.sleep(wall)
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1

    def _get(self, url: str) -> bytes | None:
        # Cause du dernier essai raté (code HTTP, timeout, erreur réseau), gardée pour
        # le message d'échec définitif : sans elle, on ne saurait pas si un feed mort
        # l'est à cause d'un 503, d'un timeout ou d'une coupure DNS.
        last_cause = "cause inconnue"
        for attempt in range(self.max_retries):
            self._wait_for_slot()
            try:
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 429:
                    # Rate-limit : mur GLOBAL. On suit Retry-After si l'API le donne,
                    # sinon backoff jitteré. Tous les workers attendront ce mur.
                    last_cause = f"HTTP 429 {e.reason}"
                    delay = _parse_retry_after(e.headers) or _backoff(attempt)
                    self._pause_all(delay)
                    continue
                if 500 <= e.code < 600:
                    # Panne serveur ponctuelle : backoff LOCAL, pas de mur global.
                    last_cause = f"HTTP {e.code} {e.reason}"
                    time.sleep(_backoff(attempt))
                    continue
                log(f"  ! HTTP {e.code} {e.reason} sur {url}")
                return None
            except (TimeoutError, socket.timeout):
                last_cause = f"timeout ({self.timeout}s)"
                time.sleep(_backoff(attempt))
            except urllib.error.URLError as e:
                # DNS, connexion refusée, TLS… : la cause utile est dans e.reason.
                last_cause = f"URLError: {e.reason}"
                time.sleep(_backoff(attempt))
            except (ConnectionError, OSError) as e:
                last_cause = f"{type(e).__name__}: {e}"
                time.sleep(_backoff(attempt))
        log(f"  ! échec définitif après {self.max_retries} essais "
            f"(dernière cause : {last_cause}) : {url}")
        return None

    def feed(self, feed_url: str, page: int = 1):
        """Récupère et parse une page d'un feed. None si inaccessible ou XML
        invalide. Renvoie (pagecount, totalentries, feed_updated, entries)."""
        sep = "&" if "?" in feed_url else "?"
        data = self._get(f"{feed_url}{sep}page={page}&limit={self.page_size}")
        if data is None:
            return None
        try:
            return parse_feed(data)
        except ET.ParseError as e:
            log(f"  ! XML invalide ({e}) sur {feed_url} (page {page})")
            return None

    def all_entries(self, feed_url: str):
        """Toutes les entries d'un feed, pages concaténées.
        Renvoie (totalentries, feed_updated, entries, complete) ou None si la 1re
        page échoue. `complete` est False si une page intermédiaire a échoué : la
        liste est alors partielle (l'appelant peut le signaler)."""
        first = self.feed(feed_url, page=1)
        if first is None:
            return None
        pagecount, total, updated, entries = first
        entries = list(entries)
        complete = True
        for page in range(2, pagecount + 1):
            more = self.feed(feed_url, page=page)
            if more is None:
                complete = False
                continue
            updated = more[2] or updated
            entries.extend(more[3])
        return total, updated, entries, complete


def fetch_capabilities(client: Client, service: dict):
    """Liste des ressources exposées par le service (niveau 1). None si inaccessible.
    `service` : dict {base_url, capabilities_path} (cf. build._service)."""
    got = client.all_entries(service["base_url"] + service["capabilities_path"])
    if got is None:
        log("ERREUR : catalogue inaccessible — abandon.")
        return None
    if not got[3]:
        log("  ! catalogue partiellement récupéré (une page a échoué).")
    return got[2]
