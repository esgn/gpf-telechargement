# Règles d'affichage

Ce document liste, en clair, les règles que le générateur **applique à tous les
produits** pour transformer le flux brut de l'API Géoplateforme en une arborescence
de téléchargement lisible. L'API expose un flux plat, parfois redondant ou mal
étiqueté ; ces règles reconstruisent une hiérarchie propre.

La plupart de ces règles sont **déclarées dans [`gpf/rules.py`](gpf/rules.py)** (un
seul endroit, éditable) et **appliquées par [`gpf/crawl.py`](gpf/crawl.py)**. Ce
`.md` en est la version lisible ; la source de vérité reste le code.

---

## 1. Structure de l'arborescence

### 1.1 — Un dossier par produit
Chaque produit inclus a son propre dossier de téléchargement, jamais aplati, même
s'il ne contient qu'une sous-ressource (uniformité de navigation).
→ [`crawl.py`](gpf/crawl.py) `build_dir` (aplatissement conditionné à `depth ≥ 2`).

### 1.2 — Classement zone → date → radiométrie → format
Quand toutes les sous-ressources portent une zone **et** un format, elles sont
rangées en niveaux de dossiers : **territoire → date d'édition → radiométrie →
format**. Le classement est **tout-ou-rien** : si une seule sous-ressource n'a pas de
zone/format, le dossier bascule en listing « ordinaire ».

Le niveau **radiométrie** ne concerne que l'imagerie (BD ORTHO…) : il sépare **RVB**
(couleurs naturelles), **IRC** (infrarouge couleur) et **Graphe de mosaïquage**. Cette
information n'est pas exposée en champ par l'API — elle est lue dans le titre de la
sous-ressource. Comme tout niveau à valeur unique, il est replié (§1.3) : pour un
produit sans radiométrie (tout le reste), il disparaît automatiquement.
→ [`rules.py`](gpf/rules.py) `GROUP_LEVELS`, `radiometry` ; [`crawl.py`](gpf/crawl.py) `_build_grouped`.

### 1.3 — Repli des niveaux à valeur unique
Un niveau de classement qui n'offre **aucun choix** (une seule valeur pour toutes
les entrées) est supprimé, pour éviter un dossier inutile — la valeur figure déjà
dans le nom des fichiers.

| Niveau | Replié si valeur unique ? | Raison |
|---|---|---|
| **zone** (territoire) | **non** | on garde toujours le dossier territoire (ex. `FXX/`) |
| **date** (millésime) | **oui** | une seule date → dossier de date superflu |
| **radiométrie** (RVB/IRC) | **oui** | absente hors imagerie → repliée partout ailleurs |
| **format** | **oui** | un seul format → dossier de format superflu |

→ [`rules.py`](gpf/rules.py) `surviving_levels` + le champ `collapse_when_single`.
_Exemple : `ADMIN-EXPRESS/MTQ/2026-06-29/` liste directement le fichier, au lieu
d'un dossier `GPKG/` intermédiaire vide._

### 1.4 — Aplatissement d'une sous-ressource mono-unité
Une sous-ressource qui se réduit à **une seule chose téléchargeable** — un fichier
unique, ou les volumes d'un même fichier découpé (`X.7z.001`, `X.7z.002`…) — ne crée
pas de dossier dédié : ses fichiers remontent dans le parent.
→ [`crawl.py`](gpf/crawl.py) `_is_single_unit`.

### 1.5 — Aplatissement de la sous-ressource unique au bout du classement
Quand le classement zone/date/format aboutit à un dossier ne contenant **qu'une
seule sous-ressource**, celle-ci n'ouvre pas un dossier de plus : son contenu (un
fichier, ou tout un jeu de couches — ex. les 18 `*.fgb` de FlatGeoBuf) est listé
**directement** dans le dossier de format. Le dossier de sous-ressource porterait
sinon un nom brut d'API (`…__FLATGEOBUF_WGS84G_FRA_2026-01-01/`) entièrement
redondant avec le chemin `zone/date/format` déjà parcouru.
→ [`crawl.py`](gpf/crawl.py) `_build_grouped` (branche `if not levels` : SR unique).
_Exemple : `ADMIN-EXPRESS-COG-CARTO/FRA/2026-01-01/FlatGeoBuf/` liste directement les
couches, au lieu d'un dossier `…__FLATGEOBUF…_FRA_2026-01-01/` intermédiaire._

---

## 2. Ordre d'affichage

### 2.1 — Tri des territoires : national → régions → départements → DROM/COM
Un même territoire peut être diffusé à plusieurs granularités (code ISO, code
région `Rxx`, code département `Dxxx`) : chacune est une sous-ressource distincte
(jamais plusieurs zones sur une même entrée). Les dossiers sont affichés dans cet ordre :
1. **national / étendu** — `FRA`, `FXX`, `FR`, `EUR`, `WLD` ;
2. **régions de métropole** — `R11`, `R24`… triées par numéro ;
3. **départements de métropole** — `D001`…`D095` (Corse `D02A`/`D02B` incluse), triés par numéro ;
4. **DROM / COM** — regroupés **par territoire** (les codes d'un même territoire
   restent côte à côte, ordre interne `code ISO → région → département`), les
   territoires ordonnés **alphabétiquement sur leur code « représentant »**.

Le **représentant** d'un territoire est le meilleur code présent dans le lot selon la
priorité **ISO > région > département** (à granularité égale, alphabétique). Concrètement :
- si le produit n'expose (pour tous ses territoires) qu'une seule granularité — que des
  ISO, que des régions, ou que des départements — le tri est simplement alphabétique
  sur cette granularité ;
- en cas de mélange, chaque territoire est classé sur son meilleur code : un territoire
  ayant un ISO (ex. `GLP`) est représenté par cet ISO ; un territoire n'ayant que
  région + département (ex. `R02` + `D972`) est représenté par sa région.

_Exemple (tous les territoires ont un ISO) : `BLM`, `GLP`+`R01`+`D971`, `GUF`+`R03`+`D973`,
`MAF`, `MTQ`+`R02`+`D972`, `MYT`+`R06`+`D976`, `REU`+`R04`+`D974`, `SPM`+`D975` — soit les
représentants ISO `BLM, GLP, GUF, MAF, MTQ, MYT, REU, SPM` dans l'ordre alphabétique._

Le regroupement DROM/COM se fait via le code ISO canonique du territoire, obtenu de
`DROM_CANONICAL` (`D9xx`/`SBA`/`SMA` → ISO) ou `REGION_TO_ISO` (`R0x` → ISO). `zone_sort_key`
reçoit l'ensemble des codes du niveau (fourni par le crawl) pour déterminer le représentant.
Ce tri reste correct que la fusion des DROM (§3) ait eu lieu ou non.

**Exception « FR » selon le produit :** `FR` est traité comme un code national (rang 1
ci-dessus) pour la plupart des produits, **mais** pour ceux où « FR » désigne un bloc de
données et non un agrégat national (ex. LiDAR HD, listés dans `_FR_IS_BLOCK_PRODUCTS`),
il est trié comme un bloc ordinaire — sinon il remonterait à tort en tête. Pour cela,
l'`id` du produit est transmis à `zone_sort_key`.

→ [`rules.py`](gpf/rules.py) `zone_sort_key`, `_FR_IS_BLOCK_PRODUCTS`, tables `DROM_CANONICAL` et `REGION_TO_ISO`.

### 2.2 — Tri des dates : plus récent d'abord
Les dossiers de millésime sont classés du plus récent au plus ancien.
→ [`rules.py`](gpf/rules.py) `GROUP_LEVELS` (niveau `date`, `reverse=True`).

### 2.3 — Dossier ordinaire : dossiers d'abord, puis fichiers, alphabétique
Dans un dossier non classé zone/date/format, les sous-dossiers sont listés avant les
fichiers, chaque groupe trié par nom.
→ [`crawl.py`](gpf/crawl.py) `_write_dir`.

---

## 3. Fusion des territoires à codes multiples (DROM/COM)

L'API expose certains territoires d'outre-mer sous **plusieurs codes** : code
département INSEE (`D971`), code ISO 3166 (`GLP`), voire d'anciens codes IGN
(`SBA`). Le même territoire apparaît alors en double/triple dans le listing.

**Règle :** quand un territoire est **réellement présent sous plusieurs codes** dans
le lot, ceux-ci sont **fusionnés sous le code ISO** (stable, international), **sauf
conflit** — c'est-à-dire si une même **date d'édition** existe sous deux codes,
auquel cas fusionner risquerait de mêler des livraisons distinctes : on garde alors
les dossiers séparés **et on le signale** au build (`~ … non fusionné`).

**Pas de doublon → pas de fusion :** si un code n'a aucun autre code concurrent pour
son territoire dans le lot (ex. BD ORTHO n'expose les DROM que sous leur code
département `D971`…`D986`, sans code ISO), il est **conservé tel quel** — il n'y a
rien à résorber. Ainsi ces départements restent `D971`…`D986` et se trient dans
l'ordre alphanumérique attendu (cf. §2.1), sans être renommés en ISO.

**Padding parasite normalisé :** certains produits (ex. OCS GE Artificialisation)
exposent un code DROM/COM avec un zéro de remplissage — `D0971` au lieu de `D971`
(débordement du format à 4 chiffres appliqué aux départements métropolitains). Ce code
est d'abord normalisé en `D971` afin que libellé, fusion et tri le traitent comme le
code standard (et le dédupliquent avec un éventuel `D971` déjà présent).

→ [`rules.py`](gpf/rules.py) `DROM_CANONICAL` (la table) + `canonicalize_zones` + `_normalize_zone_padding`.

Correspondances actuelles :

| Territoire | Codes fusionnés | Code canonique |
|---|---|---|
| Guadeloupe | `D971` | `GLP` |
| Martinique | `D972` | `MTQ` |
| Guyane | `D973` | `GUF` |
| La Réunion | `D974` | `REU` |
| Mayotte | `D976` | `MYT` |
| Saint-Pierre-et-Miquelon | `D975` | `SPM` |
| Saint-Barthélemy | `D977`, `SBA` | `BLM` |
| Saint-Martin | `D978`, `SMA` | `MAF` |

_La condition de conflit de date est le garde-fou universel : sur IRIS-GE, `SBA`
(millésimes 2014/2021) fusionne dans `BLM/` car ses dates sont disjointes des
millésimes récents ; les paires `D97x`/ISO qui partagent des dates ne fusionnent pas._

---

## 4. Filtrage

### 4.1 — Masquage des sidecars `.md5`
Les fichiers de checksum `.md5` ne sont jamais listés : leur hash figure déjà dans la
colonne MD5 du fichier de données associé.
→ [`crawl.py`](gpf/crawl.py) filtrage sur `is_md5_file` ; [`model.py`](gpf/model.py) `is_md5_file`.

### 4.2 — Seuls les produits `include: true` sont publiés
→ [`catalogue.py`](gpf/catalogue.py) `included()`.

### 4.3 — Garde-fou volumétrie
Un dossier dépassant un seuil configurable (`max_entries`) n'est pas déplié ; une
page de renvoi pointe vers le flux de téléchargement. Le défaut du code est 0
(illimité), mais la configuration livrée (`catalogue.json`, bloc `site`) fixe le seuil
à 50000 : le garde-fou est donc actif en pratique.
→ [`crawl.py`](gpf/crawl.py) `build_dir`.

### 4.4 — Doublons de ressources API : on garde la plus complète
Quand l'API expose deux ressources qui décrivent le même produit, on ne référence
dans le catalogue que la **plus complète** ; l'autre est laissée hors catalogue (elle
apparaît alors dans `build.py --check` comme « nouvelle », ce qui est normal).
Cas connu : `cartes_anciennes` (5 séries : Cadastre napoléonien, Cassini, État-major,
Série verte 100K, Série 50K) **contient** `cartes` (mêmes séries **sans** le Cadastre
napoléonien). On garde donc `cartes_anciennes` et on ignore `cartes`.
→ décision éditoriale dans [`catalogue.json`](catalogue.json) (aucun code dédié).

---

## 5. Présentation & formatage

- **Tailles** en base 1024 (IEC) : `233 Mio`, `9.8 Kio` ; inconnue → `—`. → [`model.py`](gpf/model.py) `human_size`.
- **Dates** au format court français : `15 juil. 2025`. → [`model.py`](gpf/model.py) `fmt_date`.
- **Colonnes du listing** : Nom · Modifié le · Taille · MD5. Le hash MD5 reste sur une
  seule ligne ; le nom de fichier se coupe proprement si besoin.
  → [`render.py`](gpf/render.py) `listing_table`.
- **Titres de thème** (accueil) cliquables vers la page du thème. → [`render.py`](gpf/render.py) `home_body`.
- **Noms de dossier** slugifiés (ASCII, accents translittérés), collisions suffixées `-2`. → [`model.py`](gpf/model.py) `slug`.
- **Libellé de zone de secours** : quand l'API ne nomme pas un code zone (libellé vide
  ou égal au code), un nom est ajouté au format « CODE Nom » (ex. `D986` →
  `D986 Wallis-et-Futuna`). La table couvre l'ensemble des DROM/COM parfois laissés sans
  nom par l'API (`D975` Saint-Pierre-et-Miquelon, `D984` TAAF, `D986` Wallis-et-Futuna,
  `D987` Polynésie française, `D988` Nouvelle-Calédonie…). Le **nom de dossier reste le
  code** ; seul le texte affiché est enrichi. Table extensible.
  → [`rules.py`](gpf/rules.py) `ZONE_LABELS`, `zone_label`.

---

## 6. Anomalies source laissées visibles (non traitées)

Certaines anomalies viennent de l'API et sont **volontairement laissées telles
quelles** pour l'instant (visibles, non corrigées) :

- **Zone corrompue** : quelques sous-ressources ont un champ `zone` contenant le
  titre complet au lieu du code territoire (ex. sur CONTOURS-IRIS, trois dossiers
  `CONTOURS-IRIS_2-1__SHP__FRA_201X`). Elles apparaissent comme de fausses « zones ».
- **Codes techniques sans libellé** : certains codes zone (`SBA`, `SMA`…) arrivent
  sans nom de territoire ; la fusion DROM (§3) en résorbe une partie, et un libellé de
  secours (§5, table `ZONE_LABELS`) nomme les cas connus restants (ex. `D986`).
- **Redondance de contenu sous codes concurrents** : sur certains produits (IRIS-GE,
  BDCARTO), deux codes d'un même territoire portent les mêmes dates avec un contenu
  identique mais des MD5 différents (emballage) — non fusionnés par prudence (règle §3).
