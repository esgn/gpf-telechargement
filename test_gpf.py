"""Tests des fonctions pures et du chargement du catalogue. Aucun réseau.

    python -m unittest
"""

import unittest

from build import _cards, _splice_cloud, _CLOUD_START, _CLOUD_END
from gpf import atom, cloud, render
from gpf.markdown import split_sections, to_html
from gpf.catalogue import (CatalogueError, Product, load_catalogue,
                           strip_json_comments)
from gpf.crawl import (_group_bytes, _group_formats, _is_single_unit,
                       _row_sort_key)
from gpf.rules import (GROUP_LEVELS, canonicalize_zones, surviving_levels,
                       zone_label, zone_sort_key)
from gpf.model import (fmt_date, fmt_datetime, human_size, is_md5, is_md5_file,
                       last_segment, resource_id, slug)


class TestModel(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(human_size(None), "—")
        self.assertEqual(human_size(-1), "—")            # taille invalide
        self.assertEqual(human_size(0), "0")
        self.assertEqual(human_size(143), "143")
        self.assertEqual(human_size(1024), "1.0 Kio")
        self.assertEqual(human_size(1536), "1.5 Kio")
        self.assertEqual(human_size(10 * 1024), "10 Kio")
        self.assertEqual(human_size(233 * 1024 ** 2), "233 Mio")
        # bord de plage : arrondi à 1024 → on remonte d'une unité
        self.assertEqual(human_size(1024 ** 2 - 1), "1.0 Mio")
        # dépassement de la plus grande unité : reste en Eio (pas de nom manquant)
        self.assertTrue(human_size(2 ** 70).endswith("Eio"))

    def test_fmt_date(self):
        self.assertEqual(fmt_date(""), "")
        self.assertEqual(fmt_date(None), "")
        self.assertEqual(fmt_date("pas-une-date"), "")
        self.assertEqual(fmt_date("2025-07-15"), "15 juil. 2025")
        self.assertEqual(fmt_date("2025-07-15T14:59:00+01:00"), "15 juil. 2025")

    def test_fmt_datetime(self):
        self.assertEqual(fmt_datetime(""), "")
        self.assertEqual(fmt_datetime(None), "")
        self.assertEqual(fmt_datetime("pas-une-date"), "")
        # heure prise telle quelle (pas de conversion de fuseau), zéro-padding
        self.assertEqual(fmt_datetime("2026-07-13T14:30:00+02:00"), "13 juil. 2026 à 14:30")
        self.assertEqual(fmt_datetime("2026-01-05T09:05:00+01:00"), "5 janv. 2026 à 09:05")
        # date seule → minuit
        self.assertEqual(fmt_datetime("2025-07-15"), "15 juil. 2025 à 00:00")

    def test_slug(self):
        self.assertEqual(slug("ADMIN-EXPRESS"), "ADMIN-EXPRESS")
        self.assertEqual(slug("Différentiel"), "Differentiel")  # accents translittérés
        self.assertEqual(slug("a b/c"), "a_b_c")
        self.assertEqual(slug(""), "item")

    def test_slug_dedup(self):
        used = set()
        self.assertEqual(slug("cartes", used), "cartes")
        self.assertEqual(slug("cartes", used), "cartes-2")
        self.assertEqual(slug("cartes", used), "cartes-3")

    def test_last_segment_and_resource_id(self):
        self.assertEqual(last_segment("https://x/telechargement/resource/BDTOPO"), "BDTOPO")
        self.assertEqual(last_segment("https://x/a/b/"), "b")
        self.assertEqual(resource_id({"id": "https://x/resource/RGEALTI"}), "RGEALTI")
        # repli sur href puis titre
        self.assertEqual(resource_id({"id": "", "href": "https://x/A"}), "A")
        self.assertEqual(resource_id({"id": "", "href": "", "title": "T"}), "T")

    def test_is_md5(self):
        self.assertTrue(is_md5("d41d8cd98f00b204e9800998ecf8427e"))
        self.assertFalse(is_md5("nope"))
        self.assertFalse(is_md5(None))

    def test_is_md5_file(self):
        self.assertTrue(is_md5_file("https://x/data.7z.md5"))
        self.assertTrue(is_md5_file("https://x/data", title="ARCHIVE.MD5"))
        self.assertFalse(is_md5_file("https://x/data.7z"))


class TestAtom(unittest.TestCase):
    FEED = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:gpf_dl="https://data.geopf.fr/annexes/ressources/xsd/gpf_dl.xsd"
          gpf_dl:pagecount="1" gpf_dl:totalentries="2">
      <updated>2025-07-23T14:59:00+01:00</updated>
      <entry>
        <title>ADMIN-EXPRESS_sub</title>
        <id>https://data.geopf.fr/telechargement/resource/ADMIN-EXPRESS/SUB</id>
        <updated>2025-07-23T14:59:00+01:00</updated>
        <link rel="alternate" type="application/atom+xml"
              href="https://data.geopf.fr/telechargement/resource/ADMIN-EXPRESS/SUB"/>
        <gpf_dl:zone term="FXX" label="FXX France métropolitaine"/>
        <gpf_dl:format term="GPKG" label="GPKG (GeoPackage)"/>
        <gpf_dl:editionDate>2025-07-15</gpf_dl:editionDate>
      </entry>
      <entry>
        <title>archive.7z</title>
        <id>https://data.geopf.fr/telechargement/download/archive.7z</id>
        <content>d41d8cd98f00b204e9800998ecf8427e</content>
        <link rel="alternate" type="application/x-7z-compressed"
              gpf_dl:length="12345"
              href="https://data.geopf.fr/telechargement/download/archive.7z"/>
      </entry>
    </feed>""".encode("utf-8")

    def test_parse_feed(self):
        pagecount, total, updated, entries = atom.parse_feed(self.FEED)
        self.assertEqual((pagecount, total), (1, 2))
        self.assertEqual(updated, "2025-07-23T14:59:00+01:00")
        self.assertEqual(len(entries), 2)

        d, f = entries
        self.assertTrue(d["is_dir"])
        self.assertEqual(d["zone"], "FXX")
        self.assertEqual(d["fmt"], "GPKG")
        self.assertEqual(d["editionDate"], "2025-07-15")
        self.assertIsNone(d["md5"])

        self.assertFalse(f["is_dir"])
        self.assertEqual(f["length"], 12345)
        self.assertEqual(f["md5"], "d41d8cd98f00b204e9800998ecf8427e")

    def test_parse_feed_fmt_all_lists_every_format(self):
        # entrée « produit » du capabilities : plusieurs <gpf_dl:format>. fmt = le
        # premier, fmt_all = tous (base du garde-fou build._warn_uncurated_formats).
        feed = b"""<feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:gpf_dl="https://data.geopf.fr/annexes/ressources/xsd/gpf_dl.xsd">
          <entry><title>ADMIN-EXPRESS-COG-CARTO</title>
            <link rel="alternate" type="application/atom+xml" href="https://x/resource/AE"/>
            <gpf_dl:format term="GPKG" label="GPKG (GeoPackage)"/>
            <gpf_dl:format term="SHP" label="SHP (Shapefile)"/>
            <gpf_dl:format term="FlatGeoBuf" label="FlatGeoBuf"/>
          </entry></feed>"""
        _, _, _, entries = atom.parse_feed(feed)
        self.assertEqual(entries[0]["fmt"], "GPKG")                 # premier
        self.assertEqual(entries[0]["fmt_all"], ["GPKG", "SHP", "FlatGeoBuf"])
        # entrée sans format (fichier) → fmt_all vide, pas d'erreur.
        nofmt = b"""<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>f</title><link rel="alternate" href="https://x/a.7z"/></entry></feed>"""
        _, _, _, e2 = atom.parse_feed(nofmt)
        self.assertEqual(e2[0]["fmt_all"], [])

    def test_malformed_counts_dont_crash(self):
        # pagecount/totalentries non numériques → valeurs de repli, pas de ValueError
        feed = ('<feed xmlns="http://www.w3.org/2005/Atom" '
                'xmlns:gpf_dl="https://data.geopf.fr/annexes/ressources/xsd/gpf_dl.xsd" '
                'gpf_dl:pagecount="abc" gpf_dl:totalentries=""></feed>').encode()
        pagecount, total, _, entries = atom.parse_feed(feed)
        self.assertEqual((pagecount, total, entries), (1, 0, []))

    def test_pick_link_prefers_section(self):
        feed = b"""<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>vol</title>
            <link rel="self" href="https://x/self"/>
            <link rel="section" href="https://x/data.7z.001"/>
          </entry></feed>"""
        _, _, _, entries = atom.parse_feed(feed)
        self.assertEqual(entries[0]["href"], "https://x/data.7z.001")


class TestCrawlHelpers(unittest.TestCase):
    def _f(self, name):
        return ({"title": name, "href": "https://x/" + name}, "")

    def test_single_unit(self):
        self.assertTrue(_is_single_unit([self._f("a.7z")]))
        self.assertFalse(_is_single_unit([]))
        # volumes d'une même base = une unité
        self.assertTrue(_is_single_unit([self._f("x.7z.001"), self._f("x.7z.002")]))
        # bases différentes = vrai dossier multi-fichiers
        self.assertFalse(_is_single_unit([self._f("x.shp"), self._f("x.dbf")]))

    def test_row_sort_orders_multipart_volumes(self):
        # Un lot de volumes .7z.NNN arrivant en désordre du flux doit se trier en
        # 001..006 : c'est l'invariant appliqué à l'aplatissement d'une sous-ressource
        # mono-unité (crawl._build_grouped) comme au listing ordinaire (_write_dir).
        rows = [{"name": f"x.7z.{n:03d}", "is_dir": False}
                for n in (6, 2, 1, 4, 5, 3)]
        rows.sort(key=_row_sort_key)   # la vraie fonction de production, pas une copie
        self.assertEqual([r["name"] for r in rows],
                         [f"x.7z.{n:03d}" for n in (1, 2, 3, 4, 5, 6)])

    @staticmethod
    def _sr_file(name, length):
        return {"href": "https://x/" + name, "title": name,
                "is_dir": False, "length": length}

    def test_group_formats_distinct_sorted(self):
        # libellés bruts de l'API en entrée ; _group_formats applique format_label,
        # dédoublonne par code et trie (insensible à la casse).
        entries = [{"fmt": "SHP", "fmt_label": "SHP (Shapefile)"},
                   {"fmt": "GPKG", "fmt_label": "GPKG (GeoPackage)"},
                   {"fmt": "SHP", "fmt_label": "SHP (Shapefile)"},   # doublon dédupliqué
                   {"fmt": "", "fmt_label": ""}]                     # sans format : ignoré
        self.assertEqual(_group_formats(entries), ["GeoPackage", "Shapefile"])

    def test_group_formats_dedup_on_display_label(self):
        # TIF et TIFF sont des codes distincts fondus sous « GeoTIFF » : la colonne
        # ne doit l'afficher qu'une fois (déduplication sur le libellé, pas le code).
        entries = [{"fmt": "TIF", "fmt_label": "TIF"},
                   {"fmt": "TIFF", "fmt_label": "TIFF (Tagged Image File Format)"}]
        self.assertEqual(_group_formats(entries), ["GeoTIFF"])

    def test_group_bytes_sums_excluding_md5_and_dirs(self):
        # deux sous-ressources dont les listings sont déjà en cache (après _fetch_dirs).
        dir_listings = {
            "https://x/a": (0, "", [self._sr_file("a.gpkg", 1000),
                                    self._sr_file("a.gpkg.md5", 32),      # exclu
                                    {"href": "https://x/sub", "title": "sub",
                                     "is_dir": True, "length": None}], True),  # exclu
            "https://x/b": (0, "", [self._sr_file("b.gpkg", 2000)], True),
        }
        entries = [{"href": "https://x/a"}, {"href": "https://x/b"}]
        self.assertEqual(_group_bytes(entries, dir_listings), 3000)

    def test_group_bytes_none_when_unknown(self):
        # sous-ressource absente du cache (non pré-chargée) → aucune taille → None.
        self.assertIsNone(_group_bytes([{"href": "https://x/missing"}], {}))
        # présente mais toutes les `length` absentes du feed → None (cellule vide).
        dl = {"https://x/a": (0, "", [self._sr_file("a.tif", None)], True)}
        self.assertIsNone(_group_bytes([{"href": "https://x/a"}], dl))

    def test_format_label_curated_and_fallback(self):
        from gpf.rules import format_label
        # codes curés → formulation choisie (le libellé API redondant est ignoré) ;
        # chaque format est tranché à la main, aucune règle dérivable.
        self.assertEqual(format_label({"fmt": "GPKG", "fmt_label": "GPKG (GeoPackage)"}),
                         "GeoPackage")                          # garde le nom
        self.assertEqual(format_label({"fmt": "SHP", "fmt_label": "SHP (Shapefile)"}),
                         "Shapefile")                           # garde le nom
        self.assertEqual(
            format_label({"fmt": "SQL", "fmt_label": "SQL (Structured Query Language)"}),
            "SQL")                                              # garde le sigle
        # raster : TIF et TIFF (codes distincts) fondus sous « GeoTIFF ».
        self.assertEqual(format_label({"fmt": "TIF", "fmt_label": "TIF"}), "GeoTIFF")
        self.assertEqual(
            format_label({"fmt": "TIFF", "fmt_label": "TIFF (Tagged Image File Format)"}),
            "GeoTIFF")
        # JP2 : le suffixe E080/E100 est conservé (dit ce qu'on télécharge) ; jp2 nu
        # → « JPEG 2000 » générique.
        self.assertEqual(
            format_label({"fmt": "JP2-E100", "fmt_label": "JP2-E100 (JPEG2000 …)"}),
            "JPEG 2000 (E100)")
        self.assertEqual(format_label({"fmt": "JP2-E080", "fmt_label": "JP2-E080"}),
                         "JPEG 2000 (E080)")
        self.assertEqual(format_label({"fmt": "jp2", "fmt_label": "jp2"}), "JPEG 2000")
        # alias fondu sous le libellé canonique.
        self.assertEqual(format_label({"fmt": "FGB", "fmt_label": "FlatGeoBuf"}),
                         "FlatGeoBuf")
        # code non curé → libellé API tel quel (repli).
        self.assertEqual(format_label({"fmt": "FOO", "fmt_label": "FOO (Bar)"}),
                         "FOO (Bar)")
        # ni mapping ni libellé API → le code seul.
        self.assertEqual(format_label({"fmt": "XYZ", "fmt_label": ""}), "XYZ")

    def test_uncurated_formats(self):
        from gpf.rules import uncurated_formats
        # seuls les codes hors FORMAT_LABELS ressortent ; le vide est ignoré.
        self.assertEqual(
            uncurated_formats({"GPKG", "TIF", "NOUVEAU", "AUTRE", ""}),
            {"NOUVEAU", "AUTRE"})
        self.assertEqual(uncurated_formats({"GPKG", "SHP", "JP2-E080"}), set())

    def test_format_level_key_uppercases_url_keeps_label(self):
        fmt_level = next(lv for lv in GROUP_LEVELS if lv.name == "format")
        # code mixte : URL (term/slug) en majuscules, affichage en casse humaine.
        term, label = fmt_level.key({"fmt": "FlatGeoBuf", "fmt_label": "FlatGeoBuf"})
        self.assertEqual(term, "FLATGEOBUF")
        self.assertEqual(label, "FlatGeoBuf")
        # code déjà en majuscules : URL inchangée, libellé curé.
        self.assertEqual(fmt_level.key({"fmt": "GPKG", "fmt_label": "GPKG (GeoPackage)"}),
                         ("GPKG", "GeoPackage"))

    def test_group_levels_shape(self):
        # ordre des niveaux : zone → date → radiométrie → format
        self.assertEqual([lv.name for lv in GROUP_LEVELS],
                         ["zone", "date", "radiometry", "format"])
        # zone non repliable (dossier territoire toujours conservé) ;
        # date, radiométrie et format repliés quand ils n'offrent qu'une seule valeur.
        self.assertEqual([lv.collapse_when_single for lv in GROUP_LEVELS],
                         [False, True, True, True])

    @staticmethod
    def _entry(zone, date, fmt, title=""):
        return {"zone": zone, "zone_label": zone, "editionDate": date,
                "fmt": fmt, "fmt_label": fmt, "title": title}

    def _surviving(self, entries):
        return [lv.name for lv in surviving_levels(entries, GROUP_LEVELS)]

    def test_single_format_level_collapsed(self):
        # une zone, une date, un seul format, pas de radiométrie (titre vide) →
        # date/radiométrie/format repliés, zone gardée. (cas ADMIN-EXPRESS)
        self.assertEqual(self._surviving([self._entry("MTQ", "2026-06-29", "GPKG")]),
                         ["zone"])

    def test_multi_format_level_kept(self):
        # plusieurs formats pour une même zone/date → le niveau format est conservé.
        self.assertEqual(
            self._surviving([self._entry("MTQ", "2026-06-29", "GPKG"),
                             self._entry("MTQ", "2026-06-29", "SHP")]),
            ["zone", "format"])

    def test_multi_date_single_format(self):
        # plusieurs dates, un format chacune → date gardée, format replié.
        self.assertEqual(
            self._surviving([self._entry("MTQ", "2026-06-29", "GPKG"),
                             self._entry("MTQ", "2025-01-01", "GPKG")]),
            ["zone", "date"])

    def test_radiometry_level_kept_for_ortho(self):
        # BDORTHO : à une même zone/date, RVB / IRC / Graphe (radiométrie lue dans le
        # titre) → le niveau radiométrie est conservé, entre date et format.
        t = "BDORTHO_1-0_{}_JP2-E080_LAMB93_D054_2018-01-01"
        entries = [
            self._entry("D054", "2018-01-01", "JP2-E080", t.format("RVB-0M20")),
            self._entry("D054", "2018-01-01", "JP2-E080", t.format("IRC-0M20")),
            self._entry("D054", "2018-01-01", "SHP",
                        "BDORTHO_2-0_GRAPHE-MOSAIQUAGE__LAMB93_D054_2018-01-01"),
        ]
        # radiométrie a 3 valeurs (RVB/IRC/GRAPHE) → conservée ; format a 2 valeurs
        # (JP2/SHP) → conservé ; zone/date uniques → date repliée, zone gardée.
        self.assertEqual(self._surviving(entries), ["zone", "radiometry", "format"])

    def test_radiometry_extraction(self):
        from gpf.rules import radiometry
        self.assertEqual(radiometry({"title": "BDORTHO_1-0_RVB-0M20_JP2-E080_x"}),
                         ("RVB", "RVB"))
        self.assertEqual(radiometry({"title": "BDORTHO_1-0_IRC-0M50_JP2-E080_x"}),
                         ("IRC", "IRC"))
        self.assertEqual(radiometry({"title": "BDORTHO_2-0_GRAPHE-MOSAIQUAGE__x"}),
                         ("GRAPHE", "Graphe de mosaïquage"))
        # produit non-imagerie → radiométrie vide (niveau replié)
        self.assertEqual(radiometry({"title": "BDTOPO_3-5_TOUSTHEMES_GPKG_x"}), ("", ""))

    @staticmethod
    def _zone(zone, label, date):
        return {"zone": zone, "zone_label": label, "editionDate": date, "fmt": "X"}

    def test_drom_merge_no_conflict(self):
        # D971 (2024) + GLP (2025) : dates disjointes → D971 réétiqueté en GLP,
        # et son label prend le libellé ISO. Aucun conflit signalé.
        entries = [self._zone("D971", "D971 Guadeloupe", "2024-04-15"),
                   self._zone("GLP", "GLP Guadeloupe", "2025-01-01")]
        out, conflicts = canonicalize_zones(entries)
        self.assertEqual(conflicts, [])
        self.assertEqual([e["zone"] for e in out], ["GLP", "GLP"])
        self.assertTrue(all(e["zone_label"] == "GLP Guadeloupe" for e in out))
        # entries d'origine non mutées (fonction pure)
        self.assertEqual(entries[0]["zone"], "D971")

    def test_drom_conflict_kept_separate(self):
        # D972 et MTQ partagent la date 2025-01-01 → conflit : pas de fusion.
        entries = [self._zone("D972", "D972 Martinique", "2025-01-01"),
                   self._zone("MTQ", "MTQ Martinique", "2025-01-01")]
        out, conflicts = canonicalize_zones(entries)
        self.assertEqual(conflicts, ["D972"])
        self.assertEqual(sorted(e["zone"] for e in out), ["D972", "MTQ"])

    def test_drom_no_merge_when_alone(self):
        # D973 seul (pas de GUF ni autre code guyanais dans le lot) : AUCUN doublon
        # à résorber → code conservé tel quel (cas BD ORTHO, qui n'expose que des D9xx).
        out, conflicts = canonicalize_zones(
            [self._zone("D973", "D973 Guyane", "2024-04-15")])
        self.assertEqual(conflicts, [])
        self.assertEqual(out[0]["zone"], "D973")
        self.assertEqual(out[0]["zone_label"], "D973 Guyane")

    def test_drom_department_only_batch_untouched(self):
        # lot BD ORTHO : que des codes département (aucun ISO) → aucune fusion,
        # tous les codes préservés (donc triables en 971→986).
        codes = ["D971", "D972", "D977", "D978", "D986"]
        out, conflicts = canonicalize_zones(
            [self._zone(z, f"{z} X", "2020-01-01") for z in codes])
        self.assertEqual(conflicts, [])
        self.assertEqual(sorted(e["zone"] for e in out), codes)

    def test_drom_sba_merges_when_blm_present(self):
        # ancien code IGN SBA fusionne dans BLM si un autre code du territoire (D977)
        # est présent et les dates sont disjointes.
        entries = [self._zone("SBA", "SBA", "2014-01-01"),
                   self._zone("D977", "D977 Saint-Barthélemy", "2024-01-01")]
        out, conflicts = canonicalize_zones(entries)
        self.assertEqual(conflicts, [])
        self.assertEqual(sorted(e["zone"] for e in out), ["BLM", "BLM"])

    def test_non_drom_zone_untouched(self):
        # FXX n'est pas un DROM à double code → inchangé.
        out, conflicts = canonicalize_zones(
            [self._zone("FXX", "FXX France métropolitaine", "2025-01-01")])
        self.assertEqual(conflicts, [])
        self.assertEqual(out[0]["zone"], "FXX")

    @staticmethod
    def _sorted(codes):
        # reproduit ce que fait crawl._build_grouped : sort_key reçoit l'ensemble
        # des terms présents (pour choisir le représentant de chaque territoire DROM).
        present = set(codes)
        return sorted(codes, key=lambda t: zone_sort_key(t, present))

    def test_zone_sort_order(self):
        # national, puis régions métropole, puis départements métropole, puis DROM/COM.
        codes = ["GLP", "D971", "D002", "FXX", "D001", "MTQ", "FRA", "BLM", "R24", "R11"]
        ordered = self._sorted(codes)
        # FRA/FXX en tête (ordre entre eux : alpha)
        self.assertEqual(ordered[:2], ["FRA", "FXX"])
        # puis régions métropole triées par numéro
        self.assertEqual(ordered[2:4], ["R11", "R24"])
        # puis départements métropole triés par numéro
        self.assertEqual(ordered[4:6], ["D001", "D002"])
        # les DROM/COM ferment la liste
        self.assertEqual(set(ordered[6:]), {"BLM", "D971", "GLP", "MTQ"})
        # D971 et GLP (même territoire) sont adjacents, ISO avant département
        self.assertLess(ordered.index("GLP"), ordered.index("D971"))
        self.assertEqual(ordered.index("D971") - ordered.index("GLP"), 1)

    def test_zone_sort_fr_national_by_default(self):
        # sans contexte produit, « FR » est un agrégat national → en tête.
        codes = ["FR", "AE", "AF", "BE"]
        present = set(codes)
        ordered = sorted(codes, key=lambda t: zone_sort_key(t, present))
        self.assertEqual(ordered[0], "FR")

    def test_zone_sort_fr_is_block_for_lidarhd(self):
        # pour LiDARHD-NUALID, « FR » est un code de bloc : trié alphabétiquement
        # avec les autres blocs (AE, AF, BE), pas hissé en tête.
        codes = ["FR", "AE", "AF", "BE"]
        present = set(codes)
        ordered = sorted(codes,
                         key=lambda t: zone_sort_key(t, present, "LiDARHD-NUALID"))
        self.assertEqual(ordered, ["AE", "AF", "BE", "FR"])
        # FRA (France entière) reste national même pour ce produit.
        codes2 = ["FRA", "FR", "AE"]
        present2 = set(codes2)
        ordered2 = sorted(codes2,
                          key=lambda t: zone_sort_key(t, present2, "LiDARHD-NUALID"))
        self.assertEqual(ordered2[0], "FRA")

    def test_zone_sort_drom_alpha_by_representative(self):
        # territoires ordonnés alpha sur leur code représentant (ici tous ISO) :
        # BLM, GLP, GUF, MAF, MTQ, MYT, REU, SPM.
        codes = ["MAF", "BLM", "GLP", "MTQ", "GUF", "REU", "SPM", "MYT"]
        self.assertEqual(self._sorted(codes),
                         ["BLM", "GLP", "GUF", "MAF", "MTQ", "MYT", "REU", "SPM"])

    def test_zone_sort_drom_representative_priority(self):
        # priorité ISO > région > dépt pour LE REPRÉSENTANT du territoire.
        # Guadeloupe a un ISO (GLP) → représentant GLP ; Martinique n'a que région+dépt
        # → représentant R02. GLP < R02 → Guadeloupe (groupée) avant Martinique.
        self.assertEqual(self._sorted(["D971", "GLP", "R02", "D972"]),
                         ["GLP", "D971", "R02", "D972"])
        # que des départements → tri alpha des départements
        self.assertEqual(self._sorted(["D976", "D971", "D973"]),
                         ["D971", "D973", "D976"])
        # que des régions → tri alpha des régions
        self.assertEqual(self._sorted(["R04", "R01", "R02"]),
                         ["R01", "R02", "R04"])

    def test_zone_sort_metropole_regions_before_departments(self):
        # une région métropole (R84) passe avant tout département métropole (D001).
        self.assertEqual(self._sorted(["D001", "R84", "D095", "R11"]),
                         ["R11", "R84", "D001", "D095"])

    def test_zone_sort_drom_iso_region_department(self):
        # un DROM à 3 granularités : ISO → région → département, groupés ensemble.
        self.assertEqual(self._sorted(["D971", "R01", "GLP", "D972", "R02", "MTQ"]),
                         ["GLP", "R01", "D971", "MTQ", "R02", "D972"])

    def test_zone_sort_corsica_in_metropole(self):
        # D02A/D02B (Corse) restent dans la métropole, après D002.
        self.assertEqual(self._sorted(["D030", "D02A", "D02B", "D002"]),
                         ["D002", "D02A", "D02B", "D030"])

    def test_zone_sort_com_pairs_adjacent(self):
        # les COM à double code (D975/SPM, D977/BLM, D978/MAF) sont appariées,
        # ISO avant département (les COM n'ont pas de code région).
        for insee, iso in (("D975", "SPM"), ("D977", "BLM"), ("D978", "MAF")):
            ordered = self._sorted([iso, insee, "GLP", "D001"])
            self.assertEqual(ordered.index(insee) - ordered.index(iso), 1,
                             f"{iso} et {insee} devraient être adjacents (ISO avant INSEE)")

    def test_zone_label_fallback(self):
        # code sans nom dans l'API (label vide ou == code) → repli « CODE Nom »
        self.assertEqual(zone_label({"zone": "D986", "zone_label": "D986"}),
                         "D986 Wallis-et-Futuna")
        self.assertEqual(zone_label({"zone": "D986", "zone_label": ""}),
                         "D986 Wallis-et-Futuna")
        # label fourni par l'API → conservé tel quel (jamais écrasé)
        self.assertEqual(zone_label({"zone": "D054", "zone_label": "D054 Meurthe-et-Moselle"}),
                         "D054 Meurthe-et-Moselle")
        # code non nommé et absent de la table → code seul (pas de faux nom)
        self.assertEqual(zone_label({"zone": "D999", "zone_label": "D999"}), "D999")


class TestCatalogue(unittest.TestCase):
    def test_strip_comments_and_trailing_commas(self):
        raw = """{
          // commentaire pleine ligne
          "a": 1, // commentaire de fin
          "b": [1, 2,],
        }"""
        import json
        self.assertEqual(json.loads(strip_json_comments(raw)), {"a": 1, "b": [1, 2]})

    def test_slash_in_string_preserved(self):
        # les « // » à l'intérieur d'une chaîne (URL) ne sont PAS des commentaires
        raw = '{ "url": "https://data.geopf.fr/x" }'
        import json
        self.assertEqual(json.loads(strip_json_comments(raw)),
                         {"url": "https://data.geopf.fr/x"})

    def test_comma_inside_string_preserved(self):
        # une virgule suivie de ] DANS une chaîne ne doit pas être supprimée
        import json
        raw = '{ "summary": "tuiles A,B,]", "n": [1, 2,] }'
        self.assertEqual(json.loads(strip_json_comments(raw)),
                         {"summary": "tuiles A,B,]", "n": [1, 2]})

    def test_trailing_comma_across_newlines_and_comments(self):
        import json
        raw = '{\n  "a": 1,  // fin\n  "b": 2,\n}'
        self.assertEqual(json.loads(strip_json_comments(raw)), {"a": 1, "b": 2})

    def test_product_defaults(self):
        p = Product({"id": "X"})
        self.assertEqual((p.title, p.theme, p.summary), ("", "", ""))
        self.assertTrue(p.include)
        self.assertFalse(p.retired)
        self.assertEqual(p.order, 100)
        self.assertEqual(p.specs, [])

    def test_product_retired_flag(self):
        self.assertTrue(Product({"id": "X", "retired": True}).retired)
        self.assertFalse(Product({"id": "X", "retired": False}).retired)

    def test_product_page(self):
        self.assertEqual(Product({"id": "X", "page": "x.md"}).page, "x.md")
        self.assertEqual(Product({"id": "X"}).page, "")           # défaut vide

    def test_product_specs_and_label_fallback(self):
        p = Product({"id": "X", "specs": [
            {"url": "https://x/a.pdf"},                    # label absent → url
            {"label": "Doc", "url": "https://x/b.pdf"},
            {"label": "sans url"},                         # ignoré (pas d'url)
        ]})
        self.assertEqual([s["label"] for s in p.specs], ["https://x/a.pdf", "Doc"])

    def test_product_spec_type(self):
        p = Product({"id": "X", "specs": [
            {"label": "A", "url": "https://x/a", "type": "livraison"},
            {"label": "B", "url": "https://x/b"},          # type absent → ""
        ]})
        self.assertEqual([s["type"] for s in p.specs], ["livraison", ""])

    def test_product_requires_id(self):
        with self.assertRaises(CatalogueError):
            Product({"title": "sans id"})

    def test_real_catalogue_loads(self):
        cat = load_catalogue("catalogue.json")
        self.assertGreater(len(cat.included()), 0)
        # tout produit inclus se résout vers un thème connu ou « autres »
        labels = dict(cat.themes_in_display_order())
        for p in cat.included():
            self.assertIn(cat.resolve_theme(p), labels)

    def test_fallback_theme(self):
        # construit un catalogue minimal via load : thème inconnu → autres (si non inclus,
        # pas d'erreur ; si inclus, erreur de validation)
        p = Product({"id": "X", "theme": "inexistant"})
        from gpf.catalogue import Catalogue, FALLBACK_THEME
        cat = Catalogue({}, {}, [{"id": "admin", "label": "Admin"}], [p])
        self.assertEqual(cat.resolve_theme(p), FALLBACK_THEME)

    def test_malformed_theme_rejected(self):
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write('{"themes":[{"label":"sans id"}],"products":[]}')
            with self.assertRaises(CatalogueError):
                load_catalogue(path)
        finally:
            os.remove(path)

    def test_duplicate_id_rejected(self):
        import json
        import os
        import tempfile
        data = '{"themes":[],"products":[{"id":"A"},{"id":"A"}]}'
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
            with self.assertRaises(CatalogueError):
                load_catalogue(path)
        finally:
            os.remove(path)


class TestProducers(unittest.TestCase):
    def _load(self, blob: str):
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(blob)
            return load_catalogue(path)
        finally:
            os.remove(path)

    def test_product_producer_default_empty(self):
        self.assertEqual(Product({"id": "X"}).producers, [])

    def test_resolve_producers(self):
        cat = self._load(
            '{"producers":[{"id":"ign","name":"IGN","logo":"logos/ign.svg"}],'
            '"themes":[],"products":[{"id":"A","producer":"ign"},{"id":"B"}]}')
        self.assertEqual(cat.resolve_producers(cat.get("A")),
                         [{"name": "IGN", "logo": "logos/ign.svg"}])
        # produit sans producteur → liste vide
        self.assertEqual(cat.resolve_producers(cat.get("B")), [])

    def test_resolve_producers_coedition_order_preserved(self):
        # champ « producer » en LISTE (coédition) → plusieurs producteurs, ordre gardé
        cat = self._load(
            '{"producers":[{"id":"ign","name":"IGN","logo":"logos/ign.svg"},'
            '{"id":"insee","name":"INSEE","logo":"logos/insee.svg"}],'
            '"themes":[],"products":[{"id":"A","producer":["ign","insee"]}]}')
        self.assertEqual(cat.resolve_producers(cat.get("A")),
                         [{"name": "IGN", "logo": "logos/ign.svg"},
                          {"name": "INSEE", "logo": "logos/insee.svg"}])

    def test_producer_list_dedup_and_trim(self):
        # doublons et vides écartés, ordre déclaré conservé
        self.assertEqual(Product({"id": "X", "producer": ["ign", "", "ign", "insee"]}).producers,
                         ["ign", "insee"])
        # une chaîne simple reste acceptée (rétro-compat)
        self.assertEqual(Product({"id": "X", "producer": "ign"}).producers, ["ign"])

    def test_producer_logo_optional(self):
        cat = self._load('{"producers":[{"id":"insee","name":"INSEE"}],'
                         '"themes":[],"products":[{"id":"A","producer":"insee"}]}')
        self.assertEqual(cat.resolve_producers(cat.get("A")),
                         [{"name": "INSEE", "logo": ""}])

    def test_producer_requires_id_and_name(self):
        with self.assertRaises(CatalogueError):
            self._load('{"producers":[{"name":"sans id"}],"themes":[],"products":[]}')
        with self.assertRaises(CatalogueError):
            self._load('{"producers":[{"id":"x"}],"themes":[],"products":[]}')

    def test_duplicate_producer_rejected(self):
        with self.assertRaises(CatalogueError):
            self._load('{"producers":[{"id":"a","name":"A"},{"id":"a","name":"A"}],'
                       '"themes":[],"products":[]}')

    def test_unknown_producer_ref_rejected(self):
        with self.assertRaises(CatalogueError):
            self._load('{"producers":[],"themes":[],'
                       '"products":[{"id":"A","producer":"nope"}]}')

    def test_unknown_producer_ref_in_list_rejected(self):
        # un seul id inconnu dans la liste de coédition suffit à lever
        with self.assertRaises(CatalogueError):
            self._load('{"producers":[{"id":"ign","name":"IGN"}],"themes":[],'
                       '"products":[{"id":"A","producer":["ign","nope"]}]}')

    def test_unknown_producer_ref_ok_if_excluded(self):
        # produit exclu → pas de validation de sa référence producteur
        cat = self._load('{"producers":[],"themes":[],'
                         '"products":[{"id":"A","producer":"nope","include":false}]}')
        self.assertEqual(cat.resolve_producers(cat.get("A")), [])


class TestCardOrder(unittest.TestCase):
    def _entries(self, spec):
        # spec : liste de (id, order) dans l'ordre du catalogue
        return [{"id": i, "title": i, "summary": "", "order": o} for i, o in spec]

    def test_catalogue_order_preserved_when_order_equal(self):
        # à order égal (défaut), l'ordre du fichier est conservé, PAS l'alphabétique
        cards = _cards(self._entries([("Zeta", 100), ("Alpha", 100)]), "")
        self.assertEqual([c["href"] for c in cards], ["Zeta/", "Alpha/"])

    def test_order_field_controls_sort(self):
        cards = _cards(self._entries([("a", 30), ("b", 10), ("c", 20)]), "")
        self.assertEqual([c["href"] for c in cards], ["b/", "c/", "a/"])

    def test_prefix_applied(self):
        cards = _cards(self._entries([("X", 100)]), "topo/")
        self.assertEqual(cards[0]["href"], "topo/X/")

    def test_no_producer(self):
        # entrée sans producteur → liste vide sur la carte
        cards = _cards(self._entries([("X", 100)]), "")
        self.assertEqual(cards[0]["producers"], [])

    def test_producer_logo_path_relative_to_depth(self):
        entries = [{"id": "X", "title": "X", "summary": "", "order": 100,
                    "producers": [{"name": "IGN", "logo": "logos/ign.svg"}]}]
        # accueil (depth 0) : chemin depuis la racine du site
        self.assertEqual(_cards(entries, "topo/", depth=0)[0]["producers"],
                         [{"name": "IGN", "logo": "assets/logos/ign.svg"}])
        # page de thème (depth 1) : remonte d'un cran
        self.assertEqual(_cards(entries, "", depth=1)[0]["producers"],
                         [{"name": "IGN", "logo": "../assets/logos/ign.svg"}])

    def test_producer_name_only_no_logo_path(self):
        entries = [{"id": "X", "title": "X", "summary": "", "order": 100,
                    "producers": [{"name": "INSEE", "logo": ""}]}]
        self.assertEqual(_cards(entries, "", depth=1)[0]["producers"],
                         [{"name": "INSEE", "logo": ""}])

    def test_coedition_logos_both_path_prefixed(self):
        # coédition : les deux logos sont préfixés du chemin relatif, ordre gardé
        entries = [{"id": "X", "title": "X", "summary": "", "order": 100,
                    "producers": [{"name": "IGN", "logo": "logos/ign.svg"},
                                  {"name": "INSEE", "logo": "logos/insee.svg"}]}]
        self.assertEqual(_cards(entries, "", depth=1)[0]["producers"],
                         [{"name": "IGN", "logo": "../assets/logos/ign.svg"},
                          {"name": "INSEE", "logo": "../assets/logos/insee.svg"}])


class TestRender(unittest.TestCase):
    def test_escaping(self):
        self.assertEqual(render.esc('<a>&"'), "&lt;a&gt;&amp;&quot;")

    def test_breadcrumb_relative_paths(self):
        out = render.breadcrumb([("Accueil", 2), ("Thème", 1), ("Produit", 0)])
        self.assertIn('href="../../"', out)   # Accueil, 2 crans
        self.assertIn('href="../"', out)       # Thème, 1 cran
        self.assertIn('aria-current="page"', out)  # Produit, courant
        self.assertNotIn('href', out.split("Produit")[1])  # produit non cliquable

    def test_listing_table_dir_vs_file(self):
        rows = [
            {"name": "FXX", "href": "FXX/", "is_dir": True, "date": "", "size": None, "md5": None},
            {"name": "a.7z", "href": "https://x/a.7z", "is_dir": False,
             "date": "2025-07-15", "size": 2048, "md5": "d41d8cd98f00b204e9800998ecf8427e"},
        ]
        html = render.listing_table(rows)
        self.assertIn('class="dir"', html)
        self.assertIn("2.0 Kio", html)
        self.assertIn("d41d8cd98f00b204e9800998ecf8427e", html)

    def test_nav_table_formats_and_size(self):
        rows = [
            {"name": "Métropole", "href": "FXX/",
             "formats": ["GeoPackage", "SHP"], "size": 2048},
            {"name": "Martinique", "href": "MTQ/", "formats": ["SHP"], "size": 1024},
        ]
        html = render.nav_table(rows)
        self.assertIn("<th>Formats disponibles</th>", html)
        self.assertIn("<th>Taille</th>", html)
        self.assertNotIn("MD5", html)              # colonne fichier, absente en nav
        self.assertNotIn("Modifié le", html)
        self.assertIn("GeoPackage, SHP", html)
        self.assertIn("2.0 Kio", html)
        self.assertIn('class="dir"', html)          # repères de dossier conservés

    def test_nav_table_family_dir_shows_date_hides_empty_formats(self):
        # Dossier famille/série (ex. cartes anciennes) : date « Modifié le » présente,
        # taille agrégée, mais aucun format déclaré → colonne Formats masquée.
        rows = [
            {"name": "CASSINI", "href": "CASSINI/", "date": "2024-02-26",
             "formats": None, "size": 4_509_715_660},
            {"name": "ETATMAJOR", "href": "ETATMAJOR/", "date": "2024-03-02",
             "formats": None, "size": 9_341_837_312},
        ]
        html = render.nav_table(rows)
        self.assertIn("<th>Modifié le</th>", html)
        self.assertIn("<th>Taille</th>", html)
        self.assertNotIn("Formats disponibles", html)   # aucun format → colonne absente
        self.assertIn("26 févr. 2024", html)             # date formatée
        self.assertIn("4.2 Gio", html)

    def test_nav_table_omits_formats_column_on_format_level(self):
        # page de format : formats=None → pas de colonne « Formats disponibles »
        # (la ligne EST le format), mais la taille agrégée reste affichée.
        rows = [{"name": "GeoPackage", "href": "GPKG/", "formats": None, "size": 4096},
                {"name": "SHP", "href": "SHP/", "formats": None, "size": 1024}]
        html = render.nav_table(rows)
        self.assertNotIn("Formats disponibles", html)
        self.assertIn("<th>Taille</th>", html)
        self.assertIn("4.0 Kio", html)

    def test_write_page_renders_full_document(self):
        # write_page est le point d'entrée réel : substitute lève si un $var manque.
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            render.write_page(d, "Titre", "<p>corps</p>", crumbs="",
                              footer="<footer>pied</footer>", out_dir=d)
            page = open(os.path.join(d, "index.html"), encoding="utf-8").read()
        self.assertIn("<p>corps</p>", page)
        self.assertIn("<footer>pied</footer>", page)
        # CSS externalisé : la page pointe vers style.css (racine ici), plus inline.
        self.assertIn('<link rel="stylesheet" href="style.css">', page)
        self.assertNotIn("<style>", page)
        self.assertNotIn("$", page)                    # aucun placeholder résiduel

    def test_write_stylesheet_and_relative_href(self):
        # le CSS est écrit une fois dans style.css ; les pages en profondeur le
        # référencent avec le bon nombre de « ../ ».
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            render.write_stylesheet(d)
            css = open(os.path.join(d, "style.css"), encoding="utf-8").read()
            self.assertIn("prefers-color-scheme", css)   # le vrai CSS est bien là
            # page en profondeur 2 → href "../../style.css"
            sub = os.path.join(d, "theme", "produit")
            render.write_page(sub, "T", "x", crumbs="", footer="<footer>f</footer>",
                              out_dir=d)
            page = open(os.path.join(sub, "index.html"), encoding="utf-8").read()
        self.assertIn('href="../../style.css"', page)

    def test_card_grid_producer_logo(self):
        html = render._card_grid([
            {"href": "X/", "title": "X", "summary": "s",
             "producers": [{"name": "IGN", "logo": "assets/logos/ign.svg"}]}])
        self.assertIn('<img src="assets/logos/ign.svg"', html)
        self.assertIn('alt="IGN"', html)
        self.assertIn('class="producer"', html)

    def test_card_grid_producer_name_only(self):
        html = render._card_grid([
            {"href": "X/", "title": "X", "summary": "",
             "producers": [{"name": "INSEE", "logo": ""}]}])
        self.assertIn('<span class="producer"><span>INSEE</span></span>', html)
        self.assertNotIn("<img", html)

    def test_card_grid_no_producer(self):
        html = render._card_grid([
            {"href": "X/", "title": "X", "summary": "", "producers": []}])
        self.assertNotIn("producer", html)
        self.assertNotIn("<img", html)

    def test_card_grid_coedition_two_logos(self):
        # coédition : deux <img> dans un seul badge .producer, ordre gardé
        html = render._card_grid([
            {"href": "X/", "title": "X", "summary": "s",
             "producers": [{"name": "IGN", "logo": "assets/logos/ign.svg"},
                           {"name": "INSEE", "logo": "assets/logos/insee.svg"}]}])
        self.assertEqual(html.count("<img"), 2)
        self.assertLess(html.index("ign.svg"), html.index("insee.svg"))
        self.assertEqual(html.count('class="producer"'), 1)  # un seul conteneur

    def test_card_grid_update_line(self):
        # « Mise à jour » affichée (échappée) quand renseignée…
        html = render._card_grid([
            {"href": "X/", "title": "X", "summary": "s", "update": "trimestriel"}])
        self.assertIn('class="update"', html)
        self.assertIn("Mise à jour", html)
        self.assertIn("trimestriel", html)
        # …et absente quand vide ou non fournie
        self.assertNotIn('class="update"', render._card_grid(
            [{"href": "X/", "title": "X", "summary": "s", "update": ""}]))
        self.assertNotIn('class="update"', render._card_grid(
            [{"href": "X/", "title": "X", "summary": "s"}]))

    def test_card_grid_retired(self):
        # produit arrêté : <li class="retired">, carte card--retired, badge « Arrêté »
        html = render._card_grid([
            {"href": "X/", "title": "X", "summary": "s", "retired": True}])
        self.assertIn('<li class="retired">', html)
        self.assertIn('class="card card--retired"', html)
        self.assertIn('class="retired-flag"', html)
        self.assertIn("Arrêté", html)

    def test_card_grid_not_retired(self):
        # produit actif (retired absent ou False) : aucune trace du marquage arrêté
        for card in ({"href": "X/", "title": "X", "summary": "s"},
                     {"href": "X/", "title": "X", "summary": "s", "retired": False}):
            html = render._card_grid([card])
            self.assertNotIn("retired", html)
            self.assertIn('class="card"', html)

    def test_product_header_retired_banner(self):
        p = Product({"id": "X", "title": "X", "retired": True,
                     "update": "Remplacé par Y"})
        html = render.product_header(p)
        self.assertIn('class="retired-banner"', html)
        self.assertIn("Produit arrêté", html)
        self.assertIn("Remplacé par Y", html)          # motif repris de update
        # produit actif : aucun bandeau
        self.assertNotIn("retired-banner",
                         render.product_header(Product({"id": "X", "title": "X"})))

    def test_spec_icon_by_type(self):
        self.assertEqual(render._spec_icon({"type": "contenu"}), "📄")
        self.assertEqual(render._spec_icon({"type": "livraison"}), "📦")
        self.assertEqual(render._spec_icon({"type": "carte"}), "🗺️")

    def test_spec_icon_default_and_unknown(self):
        # type absent → défaut, sans erreur
        self.assertEqual(render._spec_icon({"label": "X"}), "📄")
        self.assertEqual(render._spec_icon({"type": ""}), "📄")
        # type inconnu → défaut aussi (le warning part sur stderr, non testé ici)
        self.assertEqual(render._spec_icon({"type": "typo", "label": "X"}), "📄")

    def test_product_header_spec_icons(self):
        p = Product({"id": "X", "title": "X", "specs": [
            {"label": "Contenu", "url": "https://x/a", "type": "contenu"},
            {"label": "Livraison", "url": "https://x/b", "type": "livraison"},
        ]})
        html = render.product_header(p)
        self.assertIn('<span class="spec-icon" aria-hidden="true">📄</span>', html)
        self.assertIn('<span class="spec-icon" aria-hidden="true">📦</span>', html)

    def test_theme_toggle_present(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            render.write_page(d, "T", "x", crumbs="", footer="<footer>f</footer>",
                              out_dir=d)
            page = open(os.path.join(d, "index.html"), encoding="utf-8").read()
        self.assertIn('id="theme-toggle"', page)               # le bouton
        self.assertIn("localStorage.setItem('theme'", page)    # la mémorisation
        self.assertIn("dataset.theme=t", page)                 # l'anti-flash

    def test_home_body_intro_rendered_and_escaped(self):
        html = render.home_body([], site_title="T", intro="Salut & <bienvenue>",
                                help_url="https://x")
        self.assertIn('<p class="lead">Salut &amp; &lt;bienvenue&gt;</p>', html)

    def test_home_body_intro_empty_omitted(self):
        # intro vide → pas de <p class="lead"> du tout (pas de chapô fantôme)
        html = render.home_body([], site_title="T", intro="", help_url="https://x")
        self.assertNotIn('class="lead"', html)

    def test_home_body_help_block(self):
        # help_text présent → bloc « aide » avec lien vers help_url
        html = render.home_body([], site_title="T", intro="", help_url="https://x",
                                help_text="Besoin d'aide ? Voir", help_link_label="aide")
        self.assertIn('<a href="https://x">aide</a>', html)
        self.assertIn("Besoin d", html)

    def test_home_body_help_block_omitted(self):
        # help_text vide → pas de bloc aide du tout
        html = render.home_body([], site_title="T", intro="", help_url="https://x",
                                help_text="", help_link_label="aide")
        self.assertNotIn('class="meta"', html)

    def test_render_footer(self):
        # préfixe « Généré le <date>. » + Markdown converti, lien externe en nouvel onglet
        f = render.render_footer("Via [x](https://e/y).", "12 juil. 2026")
        self.assertIn('<span class="footer-text">Généré le 12 juil. 2026. ', f)
        self.assertIn('<a href="https://e/y" target="_blank" rel="noopener">x</a>', f)
        self.assertNotIn("<p>", f)          # pas d'enrobage <p> dans le footer
        self.assertTrue(f.startswith("<footer>") and f.endswith("</footer>"))

    def test_render_footer_repo_link(self):
        # repo_url renseigné → lien dépôt (nouvel onglet) ; vide → aucun lien repo
        f = render.render_footer("x.", "g", repo_url="https://github.com/u/r")
        self.assertIn('class="repo-link"', f)
        self.assertIn('href="https://github.com/u/r"', f)
        self.assertNotIn("repo-link", render.render_footer("x.", "g"))


class TestMarkdown(unittest.TestCase):
    def test_headings(self):
        self.assertEqual(to_html("# T"), "<h1>T</h1>")
        self.assertEqual(to_html("## T"), "<h2>T</h2>")
        self.assertEqual(to_html("### T"), "<h3>T</h3>")

    def test_paragraph_and_inline(self):
        html = to_html("Un **gras**, de l'*ital* et du `code`.")
        self.assertEqual(
            html, "<p>Un <strong>gras</strong>, de l'<em>ital</em> et du <code>code</code>.</p>")

    def test_code_span_content_is_literal(self):
        # le contenu d'un span code n'est pas réinterprété (gras/italique/lien) ;
        # le balisage hors code, lui, s'applique normalement.
        self.assertEqual(to_html("`a*b*c`"), "<p><code>a*b*c</code></p>")
        self.assertEqual(to_html("`**x**`"), "<p><code>**x**</code></p>")
        self.assertEqual(to_html("`[x](u)`"), "<p><code>[x](u)</code></p>")
        self.assertEqual(to_html("voir `x*y*z` et **g**"),
                         "<p>voir <code>x*y*z</code> et <strong>g</strong></p>")

    def test_list(self):
        self.assertEqual(to_html("- a\n- b"), "<ul><li>a</li><li>b</li></ul>")

    def test_hr(self):
        self.assertEqual(to_html("---"), "<hr>")

    def test_external_link_new_tab(self):
        html = to_html("[x](https://e/y)")
        self.assertIn('href="https://e/y" target="_blank" rel="noopener"', html)

    def test_internal_link_same_tab(self):
        html = to_html("[x](../y/)")
        self.assertIn('<a href="../y/">x</a>', html)
        self.assertNotIn("target", html)

    def test_html_is_escaped(self):
        # sécurité : aucun HTML brut ne doit passer, tout est échappé
        html = to_html("Danger <script>alert(1)</script> & co")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)

    def test_blank_lines_separate_blocks(self):
        html = to_html("# T\n\npara\n\n- item")
        self.assertEqual(html, "<h1>T</h1>\n<p>para</p>\n<ul><li>item</li></ul>")

    def test_fenced_code_block(self):
        # bloc clôturé ``` → <pre><code>, multi-lignes préservées, blocs voisins intacts
        html = to_html("avant\n\n```sql\nSELECT *\nFROM t\n```\n\naprès")
        self.assertIn("<pre><code>SELECT *\nFROM t</code></pre>", html)
        self.assertIn("<p>avant</p>", html)
        self.assertIn("<p>après</p>", html)

    def test_fenced_code_is_literal(self):
        # contenu NON réinterprété (titre/gras/lien) ni joint en paragraphe. La ligne
        # « # … » est colorée comme COMMENTAIRE (span vert), pas transformée en titre
        # <h1> ; « **gras** » reste littéral (pas de <strong>).
        html = to_html("```\n# pas un titre\n**pas gras** [x](u)\n```")
        self.assertIn('<pre><code><span class="tok-comment"># pas un titre</span>\n'
                      "**pas gras** [x](u)</code></pre>", html)
        self.assertNotIn("<strong>", html)
        self.assertNotIn("<h1>", html)

    def test_fenced_code_escapes_html(self):
        html = to_html("```\n<script>a & b</script>\n```")
        self.assertIn("&lt;script&gt;a &amp; b&lt;/script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_fenced_code_unclosed(self):
        # fence non refermée en fin de source → clôturée proprement
        self.assertEqual(to_html("```\nx\ny"), "<pre><code>x\ny</code></pre>")

    def test_split_sections(self):
        intro, secs = split_sections(
            "préambule\n\n## DuckDB\ntexte\n\n```sql\n## pas un séparateur\n"
            "SELECT 1\n```\n\n## Python\n```python\nx = 1\n```")
        self.assertIn("<p>préambule</p>", intro)
        self.assertEqual([t for t, _ in secs], ["DuckDB", "Python"])
        # le « ## » DANS le bloc de code n'a PAS créé de section (2 sections, pas 3)
        self.assertIn("## pas un séparateur", secs[0][1])
        self.assertIn("<pre><code>", secs[0][1])

    def test_fenced_code_comment_highlight(self):
        # lignes de commentaire (# ou --) enveloppées d'un span vert ; code normal non
        sql = to_html("```sql\n-- un commentaire\nSELECT 1;\n```")
        self.assertIn('<span class="tok-comment">-- un commentaire</span>', sql)
        self.assertNotIn('<span class="tok-comment">SELECT 1;', sql)
        self.assertIn('<span class="tok-comment"># note</span>',
                      to_html("```python\n# note\nx = 1\n```"))
        # un flag « -spat » (un seul tiret) n'est PAS un commentaire
        self.assertNotIn("tok-comment", to_html("```bash\n  -spat 1 2 3 4\n```"))

    def test_split_sections_no_heading(self):
        # aucun « ## » : tout part en intro, aucune section
        intro, secs = split_sections("juste du texte\n\nsur deux blocs")
        self.assertEqual(secs, [])
        self.assertIn("juste du texte", intro)


class TestCloud(unittest.TestCase):
    def test_layer_name_strips_cloud_extensions(self):
        self.assertEqual(cloud.layer_name("https://x/troncon_de_route.parquet"),
                         "troncon_de_route")
        self.assertEqual(cloud.layer_name("https://x/pylone.fgb.zip"), "pylone")
        self.assertEqual(cloud.layer_name("https://x/contours_iris.fgb"), "contours_iris")
        self.assertEqual(cloud.layer_name("https://x/foo.zip"), "foo")
        # extension inconnue : segment gardé tel quel (pas de coupe hasardeuse)
        self.assertEqual(cloud.layer_name("https://x/lisezmoi.txt"), "lisezmoi.txt")

    @staticmethod
    def _leaf(fmt, date, href):
        return {"is_dir": True, "fmt": fmt, "fmt_label": fmt, "editionDate": date,
                "href": href, "zone_label": "France entière"}

    def test_latest_leaf_per_format_picks_latest_and_orders(self):
        entries = [
            self._leaf("GeoParquet", "2025-06-15", "https://x/pq-2025"),
            self._leaf("GeoParquet", "2026-06-15", "https://x/pq-2026"),   # plus récent
            self._leaf("FlatGeoBuf", "2026-06-15", "https://x/fgb"),
            self._leaf("geoflatbuffer/sozip", "2026-06-15", "https://x/sozip"),  # non surfacé
            {"is_dir": False, "fmt": "GeoParquet", "fmt_label": "GeoParquet",
             "editionDate": "2027-01-01", "href": "https://x/file"},          # fichier : ignoré
        ]
        out = cloud.latest_leaf_per_format(entries)
        # GeoParquet avant FlatGeoBuf (ordre CLOUD_FORMAT_LABELS) ; sozip écarté.
        self.assertEqual([lbl for lbl, _ in out], ["GeoParquet", "FlatGeoBuf"])
        # l'édition la plus récente est retenue pour GeoParquet.
        self.assertEqual(out[0][1]["href"], "https://x/pq-2026")

    def test_has_surfaced_format(self):
        # badge conditionné aux formats déclarés au capabilities (fmt_all), même règle
        # que l'encart : GeoParquet / FlatGeoBuf (et leurs alias) oui, le reste non.
        self.assertTrue(cloud.has_surfaced_format({"fmt_all": ["FlatGeoBuf", "GeoParquet"]}))
        self.assertTrue(cloud.has_surfaced_format({"fmt_all": ["PARQUET"]}))   # alias
        self.assertFalse(cloud.has_surfaced_format({"fmt_all": ["PMTILES"]}))
        self.assertFalse(cloud.has_surfaced_format({"fmt_all": ["geoflatbuffer/sozip"]}))
        self.assertFalse(cloud.has_surfaced_format({}))               # fmt_all absent

    def test_latest_leaf_per_format_alias_folded(self):
        # PARQUET / FGB (alias) sont fondus sous GeoParquet / FlatGeoBuf via format_label.
        out = cloud.latest_leaf_per_format([
            self._leaf("PARQUET", "2026-01-01", "https://x/pq"),
            self._leaf("FGB", "2026-01-01", "https://x/fgb")])
        self.assertEqual([lbl for lbl, _ in out], ["GeoParquet", "FlatGeoBuf"])

    def test_latest_leaf_per_format_pinned_edition(self):
        entries = [
            self._leaf("GeoParquet", "2026-06-15", "https://x/pq-new"),
            self._leaf("GeoParquet", "2026-03-15", "https://x/pq-pin"),
            self._leaf("FlatGeoBuf", "2026-06-15", "https://x/fgb-new"),  # pas de 2026-03-15
        ]
        pinned = {l: e["href"] for l, e in
                  cloud.latest_leaf_per_format(entries, "2026-03-15")}
        self.assertEqual(pinned["GeoParquet"], "https://x/pq-pin")     # édition épinglée
        self.assertEqual(pinned["FlatGeoBuf"], "https://x/fgb-new")    # repli : épingle absente
        # sans épingle → la plus récente pour chaque format
        latest = {l: e["href"] for l, e in cloud.latest_leaf_per_format(entries)}
        self.assertEqual(latest["GeoParquet"], "https://x/pq-new")


class TestCloudBlock(unittest.TestCase):
    LAYERS = {
        "formats": [{"label": "GeoParquet", "edition": "2026-06-15"},
                    {"label": "FlatGeoBuf", "edition": "2026-06-15"}],
        "zone_label": "France entière",
        "edition": "2026-06-15",
        "couches": [
            {"name": "cours_d_eau",
             "urls": {"GeoParquet": "https://x/cours_d_eau.parquet",
                      "FlatGeoBuf": "https://x/cours_d_eau.fgb.zip"}},
            {"name": "troncon_de_route",           # présent en GeoParquet seulement
             "urls": {"GeoParquet": "https://x/troncon_de_route.parquet"}},
        ],
    }

    def test_cloud_block_structure(self):
        html = render.cloud_block(self.LAYERS)
        self.assertIn('class="cloud-dt"', html)
        self.assertIn("Cloud-native", html)
        self.assertIn("Couches disponibles (2)", html)   # décompte des couches
        self.assertIn("France entière", html)
        self.assertIn("dernière édition 2026-06-15", html)
        # bouton de copie (pas un lien) portant l'URL en data-url
        self.assertIn('data-url="https://x/cours_d_eau.parquet"', html)
        self.assertIn('data-url="https://x/cours_d_eau.fgb.zip"', html)
        self.assertIn("cloud-copy", html)
        # couche absente d'un format → cellule « — », pas de bouton fantôme
        self.assertIn('class="cloud-none"', html)
        # jamais de lien <a> cliquable vers un .parquet (téléchargement intégral évité)
        self.assertNotIn('href="https://x/troncon_de_route.parquet"', html)

    def test_cloud_block_help_link_optional(self):
        self.assertNotIn("exemples et tutoriels", render.cloud_block(self.LAYERS))
        with_link = render.cloud_block(self.LAYERS, help_url="https://tuto")
        self.assertIn('href="https://tuto"', with_link)
        self.assertIn("exemples et tutoriels", with_link)

    def test_cloud_block_empty_layers(self):
        self.assertEqual(render.cloud_block({}), "")
        self.assertEqual(render.cloud_block({"formats": [], "couches": []}), "")

    def test_cloud_block_tuto_tabs(self):
        # sans tuto_tabs : pas d'onglets
        self.assertNotIn("cloud-tabs", render.cloud_block(self.LAYERS))
        # avec tuto_tabs : onglets CSS (radios + labels, 1er coché) + panneaux
        with_tabs = render.cloud_block(self.LAYERS, tuto_tabs=[
            ("DuckDB", "<pre><code>a</code></pre>"),
            ("Python", "<pre><code>b</code></pre>")])
        self.assertIn('<details class="cloud-tuto">', with_tabs)   # section repliable
        self.assertIn("Comment interroger ces couches", with_tabs)
        self.assertIn('class="cloud-tabs"', with_tabs)
        self.assertEqual(with_tabs.count("cloud-tab-radio"), 2)   # 2 onglets
        self.assertIn(" checked>", with_tabs)                     # 1er coché
        self.assertIn(">DuckDB</label>", with_tabs)
        self.assertIn("<pre><code>a</code></pre>", with_tabs)
        # les onglets sont AU-DESSUS de la liste des couches
        self.assertLess(with_tabs.index('class="cloud-tabs"'),
                        with_tabs.index('class="cloud-couches"'))

    def test_card_grid_cloud_badge(self):
        html = render._card_grid([
            {"href": "X/", "title": "X", "summary": "s", "cloud_native": True}])
        self.assertIn('class="cloud-badge"', html)
        self.assertIn("Cloud-native", html)
        self.assertIn('title="Interrogeable à distance', html)   # infobulle au survol
        # absent quand le produit n'a pas d'accès direct
        self.assertNotIn("cloud-badge", render._card_grid(
            [{"href": "X/", "title": "X", "summary": "s"}]))


class TestServices(unittest.TestCase):
    def _load(self, blob: str):
        import os
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(blob)
            return load_catalogue(path)
        finally:
            os.remove(path)

    def test_services_parsed(self):
        cat = self._load('{"services":{"download":{"base_url":"https://d"},'
                         '"chunk":{"base_url":"https://c"}},"themes":[],"products":[]}')
        self.assertEqual(cat.services["download"]["base_url"], "https://d")
        self.assertEqual(cat.services["chunk"]["base_url"], "https://c")

    def test_legacy_service_becomes_download(self):
        # ancien schéma « service » unique → exposé comme services["download"]
        cat = self._load('{"service":{"base_url":"https://old"},'
                         '"themes":[],"products":[]}')
        self.assertEqual(cat.services["download"]["base_url"], "https://old")

    def test_product_cloud_native_default_and_set(self):
        self.assertEqual(Product({"id": "X"}).cloud_native, "")
        self.assertEqual(Product({"id": "X", "cloud_native": "X_PQT"}).cloud_native,
                         "X_PQT")

    def test_product_cloud_edition_default_and_set(self):
        self.assertEqual(Product({"id": "X"}).cloud_edition, "")
        self.assertEqual(Product({"id": "X", "cloud_edition": "2026-03-15"}).cloud_edition,
                         "2026-03-15")

    def test_real_catalogue_cloud_native_declared(self):
        # le vrai catalogue déclare au moins un accès direct (BD TOPO, Contours IRIS…)
        cat = load_catalogue("catalogue.json")
        self.assertTrue(any(p.cloud_native for p in cat.products))
        self.assertEqual(cat.get("BDTOPO").cloud_native, "BDTOPO_PQT")


class TestCloudOnly(unittest.TestCase):
    def test_splice_cloud_replaces_between_markers(self):
        # --cloud-only remplace ce qui est entre les marqueurs, sans toucher au reste.
        page = f"<main>EN-TETE{_CLOUD_START}VIEUX{_CLOUD_END}<hr>ARBRE</main>"
        self.assertEqual(_splice_cloud(page, "NEUF"),
                         f"<main>EN-TETE{_CLOUD_START}NEUF{_CLOUD_END}<hr>ARBRE</main>")

    def test_splice_cloud_absent_or_incoherent(self):
        # marqueurs absents → None (le patch ne réécrit rien) ; fin avant début → None
        self.assertIsNone(_splice_cloud("<main>sans marqueurs</main>", "NEUF"))
        self.assertIsNone(_splice_cloud(_CLOUD_END + "x" + _CLOUD_START, "NEUF"))


if __name__ == "__main__":
    unittest.main()
