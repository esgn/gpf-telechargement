"""Client HTTP throttlé + accès au catalogue live de la Géoplateforme.

Mono-thread, aucun parallélisme : l'API plafonne à 10 requêtes/seconde par IP."""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .atom import parse_feed

# Le WAF de data.geopf.fr renvoie 403 sur le User-Agent par défaut « Python-urllib »
# et sur tout UA contenant « bot ». On force un UA neutre.
_HEADERS = {
    "User-Agent": "geopf-index/1.0 (+https://github.com/geoplateforme)",
    "Accept": "application/atom+xml, application/xml, */*",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


class Client:
    """Client limité à `rps` requêtes/seconde, avec backoff exponentiel sur
    429/5xx/timeout. 404 → None (ressource disparue, pas une erreur fatale).
    `page_size` est plafonné à 50 par l'API."""

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

    def _get(self, url: str) -> bytes | None:
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 429 or 500 <= e.code < 600:
                    time.sleep(2 ** attempt)
                    continue
                log(f"  ! HTTP {e.code} sur {url}")
                return None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                time.sleep(2 ** attempt)
        log(f"  ! échec définitif après {self.max_retries} essais : {url}")
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


def fetch_catalogue(client: Client, base_url: str, capabilities_path: str):
    """Liste des ressources du catalogue (niveau 1). None si inaccessible."""
    got = client.all_entries(base_url + capabilities_path)
    if got is None:
        log("ERREUR : catalogue inaccessible — abandon.")
        return None
    if not got[3]:
        log("  ! catalogue partiellement récupéré (une page a échoué).")
    return got[2]
