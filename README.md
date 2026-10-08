# Téléchargement Géoplateforme - index technique (non officiel)

Générateur de **site statique** pour faciliter le téléchargement des données de
l'IGN diffusées par le service de Téléchargement de la [Géoplateforme](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/telechargement/)
(`data.geopf.fr`). Les produits sont organisés **par thème**, chaque produit a
une **fiche** (résumé + liens vers ses spécifications officielles et ressources) et son
**arborescence de téléchargement**. Les produits compatibles proposent aussi un
**accès direct pour l'analyse** en GeoParquet ou FlatGeoBuf, avec des tutoriels
intégrés. Le site est régénéré quotidiennement.

👉 Le site statique généré est consultable ici : https://telecharger.geoplateforme.fr

Le site **n'héberge aucune donnée** : les liens de fichiers pointent directement
vers `data.geopf.fr`. C'est un index navigable, plus lisible que le service brut.

- **Zéro dépendance** - bibliothèque standard Python uniquement (Python ≥ 3.11).
- **Front minimal** - HTML sémantique + une feuille CSS partagée (`style.css`, sobre,
  responsive, mode sombre automatique) ; petits scripts JavaScript inline pour
  mémoriser le thème clair/sombre et copier les URL ou les exemples de code.
- Hébergeable tel quel sur GitHub Pages (ou tout serveur statique).

## Comment ça marche

Le générateur interroge deux services, configurés dans `catalogue.json` :

| Service | URL de base | Usage |
|---|---|---|
| `download` | `https://data.geopf.fr/telechargement` | Arborescence de téléchargement classique. |
| `chunk` | `https://data.geopf.fr/chunk/telechargement` | Accès direct aux couches GeoParquet et FlatGeoBuf. |

Ils exposent une hiérarchie [Atom](https://www.ietf.org/rfc/rfc4287.txt) à 3 niveaux
(chemins relatifs à leur URL de base) :

| Niveau | URL | Contenu |
|---|---|---|
| catalogue | `…/capabilities` | ressources (produits) disponibles |
| ressource | `…/resource/{ID}` | versions / zones / dates / formats |
| sous-ressource | `…/resource/{ID}/{SOUS}` | fichiers téléchargeables |

`build.py` parcourt le service `download` pour les produits **sélectionnés dans le
catalogue** et reconstruit une arborescence de dossiers, chacun avec un
`index.html`. Pour les produits déclarant un accès direct, une lecture ciblée du
service `chunk` alimente l'encart des couches disponibles. Les pages éditoriales
sont, elles, générées à partir des fichiers Markdown de [`pages/`](pages/).

**Point clé** : l'API ne fournit que peu de métadonnées éditoriales (pas de
description courte, ni de thème, ni de lien vers les spécifications, etc.). Tout cela est
maintenu dans [`catalogue.json`](catalogue.json) et joint au crawl via l'`id` de ressource.

Principaux aménagements du listing :

- les sidecars `.md5` ne sont pas listés (leur checksum figure déjà en colonne MD5) ;
- une sous-ressource qui se réduit à une seule unité téléchargeable (fichier
  unique, ou volumes d'un `.7z.NNN`) est **aplatie** (pas de dossier dédié) ;
- quand toutes les sous-ressources portent zone + format, elles sont classées en
  `zone/date/radiométrie/format` ; les niveaux date, radiométrie et format à valeur
  unique sont repliés, mais le niveau territoire est conservé ;
- les codes redondants d'un même territoire d'outre-mer sont fusionnés lorsqu'ils
  ne présentent pas de conflit de date.

Les règles détaillées sont décrites dans [`RULES.md`](RULES.md).

## Utilisation

Depuis la racine du dépôt, avec **Python ≥ 3.11** (aucune installation de
dépendances nécessaire). La génération et les commandes `--check` et
`--cloud-only` nécessitent un accès réseau aux services ; les tests sont sans
réseau.

```bash
python3 build.py                          # reconstruction complète dans ./site
python3 build.py --only ADMIN-EXPRESS      # ne construire qu'un produit (pour test)
python3 build.py --only-theme admin        # ne construire qu'un thème (pour test)
python3 build.py --check                   # dérive catalogue ↔ services (ne construit rien)
python3 build.py --cloud-only BDTOPO       # actualiser l'encart cloud d'une fiche existante
python3 build.py --cloud-only              # actualiser tous les encarts cloud existants
python3 build.py --help                    # liste de toutes les options
python3 -m unittest                       # tests sans réseau
```

### Prévisualiser en local

Le site est statique, mais **ouvrir `site/index.html` en `file://` ne suffit
pas** : la navigation entre dossiers casse (les liens relatifs se terminent par
`/` et le navigateur n'y résout pas `index.html`). Il faut un serveur HTTP :

```bash
python3 -m http.server 8000 --directory site   # puis http://localhost:8000/
```

### Options

| Option | Effet |
|---|---|
| `--out DIR` | Dossier de sortie (défaut `site`). |
| `--catalogue FILE` | Fichier catalogue (défaut `catalogue.json`). |
| `--only ID` | Ne construire qu'un produit, sans purger les autres produits. |
| `--only-theme THEME` | Ne construire qu'un thème, par `id`, sans purger les autres thèmes ; exclusif avec `--only`. |
| `--check` | Rapport de dérive du catalogue avec les deux services, sans construire le site. |
| `--cloud-only [ID]` | Régénérer l'encart cloud-native d'une fiche déjà construite, ou de toutes les fiches à accès direct si `ID` est omis ; exclusif avec `--only`, `--only-theme` et `--check`. |
| `--requests-per-second N` | Débit global visé (défaut 10 ; plafonné à 10 par le client). |
| `--workers N` | Nombre de requêtes de crawl en parallèle (défaut 8 ; au moins 1). |
| `--fail-fast` | Arrêter le crawl au premier flux en erreur fatale ; par défaut, collecter toutes les erreurs avant d'échouer. |
| `--help` | Afficher l'aide de la commande. |

Avec `--only` ou `--only-theme`, l'accueil, les pages de thème et les fichiers
partagés sont régénérés à partir du catalogue complet. Sur un dossier de sortie
neuf, la navigation peut donc pointer vers des fiches pas encore construites.

`--check` est un rapport informatif : les écarts trouvés ne provoquent pas un code
de sortie d'échec. L'indisponibilité du catalogue du service principal renvoie
un échec ; celle du service `chunk` est seulement signalée.

Le débit est partagé entre tous les workers. Le client gère la pagination, les
réessais sur les erreurs transitoires et une pause commune sur les réponses HTTP
429. Augmenter `--workers` ne relève pas le plafond de requêtes par seconde.

## Gérer les produits - [`catalogue.json`](catalogue.json)

Le catalogue est un JSON **tolérant les commentaires `//` et les virgules
finales** (pour rester éditable à la main). Cinq blocs :

- `site` - les textes et réglages du site généré.
- `services` - les URL des services `download` et `chunk`.
- `themes` - la taxonomie, **dans l'ordre d'affichage**. Chaque thème : `id`, `label`.
- `producers` - les producteurs affichés sur les cartes (voir ci-dessous).
- `products` - la liste des produits.

### Présentation du site et services

| Champ de `site` | Rôle |
|---|---|
| `title` | Titre du site et de l'accueil. |
| `intro` | Texte d'introduction de l'accueil ; vide pour le masquer. |
| `official_help_url` | URL de l'aide officielle. |
| `help_text`, `help_link_label` | Texte et libellé du lien d'aide de l'accueil ; `help_text` vide masque le bloc. |
| `footer` | Pied de page en Markdown ; la date de génération en heure de Paris est ajoutée automatiquement. |
| `repo_url` | Lien du dépôt dans le pied de page ; vide pour masquer l'icône GitHub. |
| `max_entries` | Seuil d'entrées au-delà duquel un dossier renvoie vers le flux source ; `0` = illimité. Le catalogue fourni le fixe à `50000`. |
| `cloud_help_url` | Lien optionnel vers des tutoriels externes dans l'encart d'accès direct. |

Chaque entrée de `services` accepte `base_url` et `capabilities_path` (défaut
`/capabilities`). Les URL par défaut sont celles du tableau « Comment ça marche ».

### Champs d'un produit

| Champ      | Oblig. | Rôle                                                                                                                                                                                                                                                                                                                    |
| ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`       | ✅     | Nom **exact** de la ressource dans `…/resource/{id}` du service `download` ; identifiant local unique pour une page éditoriale. |
| `title`    | -      | Titre éditorial. À défaut, la navigation utilise le titre Atom et l'en-tête de la fiche utilise l'`id`. |
| `theme`    | -      | `id` d'un thème déclaré. Vide → « Autres jeux de données » ; un thème inconnu provoque une erreur de validation pour un produit inclus. |
| `summary`  | -      | Résumé éditorial (1-2 phrases, public technique).                                                                                                                                                                                                                                                                       |
| `update`   | -      | Rythme de mise à jour, **texte libre** (`mensuel`, `annuel`…). Affiché sur la carte ; vide → ligne masquée. Pour un produit arrêté, y mettre le motif (ex. `Remplacé par ADMIN EXPRESS`) : il est repris dans le bandeau de la fiche.                                                                                   |
| `producer` | -      | `id` d'un producteur déclaré dans `producers`, ou liste d'`id` pour une coédition (voir ci-dessous). Vide → aucun badge. |
| `specs`    | -      | Liste de `{ "label", "url", "type" }` : liens de spécification. `type` (optionnel) choisit l'emoji de la ligne : `contenu` 📄, `livraison` 📦, `fiche` 📋, `guide` 📖, `tutoriel` 🧪, `interface` 🖱️, `carte` 🗺️, `explorateur` 🧭. Type absent → 📄 ; type inconnu → 📄 + avertissement au build.                                       |
| `include`  | -      | `false` pour masquer un produit sans le supprimer (défaut `true`).                                                                                                                                                                                                                                                      |
| `retired`  | -      | `true` pour un **produit arrêté** (plus maintenu, souvent remplacé) : reste publié et affiché en ligne, mais sa carte est ambrée avec un badge « Arrêté » et sa fiche porte un bandeau. Défaut `false`. À ne pas confondre avec les **archives** (données anciennes toujours utiles), qui restent des produits normaux. |
| `order`    | -      | Ordre d'affichage intra-thème, croissant (défaut 100). À `order` égal, l'**ordre du catalogue** est conservé (tri stable) : sans `order` explicite, les produits s'affichent donc dans leur ordre de déclaration dans `catalogue.json`.                                                                                 |
| `page`     | -      | Nom d'un fichier Markdown dans [`pages/`](pages/) (ex. `mnt-lidarhd.md`). Si renseigné, l'entrée est une **page éditoriale** (contenu rédigé, non crawlé) au lieu d'un produit de l'API : sa fiche est générée depuis ce Markdown, et `--check` l'ignore.                                                               |
| `cloud_native` | - | Identifiant de la ressource du service `chunk`, par exemple `BDTOPO_PQT` pour `BDTOPO`. Active la recherche de couches pour l'encart d'accès direct et le badge associé. |
| `cloud_edition` | - | Date ISO d'une édition à privilégier pour l'accès direct. Vide → dernière édition disponible par format ; si l'édition demandée manque pour un format, repli sur sa plus récente. |

### Producteurs (logo / nom sur les cartes)

Le bloc `producers` déclare les producteurs **une seule fois** ; chaque produit
en référence un (ou plusieurs) par son `id` via son champ `producer`. Un badge
apparaît alors en haut à droite de la carte : **le logo s'il est déclaré, sinon le
nom** en texte. Le champ `producer` accepte **une chaîne** (un producteur) ou **une
liste** (coédition - les logos sont juxtaposés dans l'ordre déclaré) :

```jsonc
"producers": [
  { "id": "ign", "name": "IGN", "logo": "logos/ign.svg" },
  { "id": "insee", "name": "INSEE", "logo": "logos/insee.svg" }
],
"products": [
  { "id": "BDTOPO", "title": "BD TOPO®", "theme": "topo", "producer": "ign", ... },
  // coédition : plusieurs producteurs, badges côte à côte dans cet ordre
  { "id": "IRIS-GE", "theme": "admin", "producer": ["ign", "insee"], ... }
]
```

| Champ producteur | Oblig. | Rôle                                                                                               |
| ---------------- | ------ | -------------------------------------------------------------------------------------------------- |
| `id`             | ✅     | Référencé par le champ `producer` des produits.                                                    |
| `name`           | ✅     | Nom affiché (et `alt` du logo).                                                                    |
| `logo`           | -      | Chemin **relatif au dossier [`assets/`](assets/)**, ex. `logos/ign.svg`. Sans logo → nom en texte. |

Les fichiers logo vivent dans `assets/` (typiquement `assets/logos/`) et sont
**copiés tels quels** vers `site/assets/` à chaque build. Aucun asset externe :
préférez un SVG léger. Un `producer` référençant un producteur inconnu déclenche
une erreur de validation (pour un produit inclus, chaque id de la liste est
vérifié) ; laissé vide, aucun badge.

### Ajouter / mettre à jour un produit

1. `python3 build.py --check` liste les ressources des deux services absentes du catalogue.
2. Ajoutez une entrée `products` avec le bon `id`, un `theme`, un `summary`.
3. Renseignez `specs` avec les liens PDF officiels. Utilisez les URL de documentation
   `https://data.geopf.fr/annexes/ressources/documentation/…`, comme les entrées du catalogue.
4. Si le produit propose un accès direct, renseignez `cloud_native` et son tutoriel
   dans `tutos/<id>.md` (voir ci-dessous).
5. `python3 build.py --only <id>`, puis le serveur HTTP local, permettent de vérifier
   le rendu du produit. Lancez aussi `python3 -m unittest` pour valider le catalogue.

### Documents de spécification

Ce sont des **liens** vers les descriptifs de contenu / de livraison publiés par
l'IGN (on ne réhéberge rien). Les millésimes figurent dans les noms de fichiers
PDF (`DC_BDTOPO_3-5.pdf`…) : ils sont à mettre à jour à la main quand l'IGN publie
une nouvelle version - l'API de téléchargement ne fournit pas ces liens.

### Accès direct et tutoriels

Un produit qui déclare `cloud_native` peut afficher un badge sur sa carte et un
encart **« Accès direct pour l'analyse »** au-dessus de son arborescence. Le
générateur y liste les couches GeoParquet et FlatGeoBuf, avec une URL à copier par
format disponible. Les FlatGeoBuf livrés en archive ZIP portent la mention SOZip.

La dernière édition est choisie **par format**. `cloud_edition` permet de
privilégier une édition donnée, par exemple lorsqu'une nouvelle livraison est
encore incomplète. Si elle manque pour tous les formats retenus, le build signale
le repli sur la plus récente. Une panne du service `chunk` ou un format
inaccessible est signalé sans faire échouer la génération du site classique ;
les accès indisponibles sont omis.

Les exemples sont rédigés dans [`tutos/`](tutos/), dans un fichier nommé d'après
l'**id du produit classique** : [`tutos/BDTOPO.md`](tutos/BDTOPO.md) pour `BDTOPO`,
et non `BDTOPO_PQT`. Le texte avant le premier titre `##` sert d'introduction ;
chaque section `##` devient un onglet (au maximum **4**, les suivants sont tronqués
avec un avertissement). Sans fichier de tutoriel, l'encart affiche seulement les
informations et les couches. Les URL et millésimes des exemples restent à mettre
à jour à la main, notamment lors d'un changement de `cloud_edition`.

Après une première construction de la fiche avec son encart, une modification du
tutoriel ou de l'édition peut être prévisualisée plus rapidement :

```bash
python3 build.py --only BDTOPO         # première construction avec l'encart cloud
# Modifier tutos/BDTOPO.md ou cloud_edition dans catalogue.json, puis :
python3 build.py --cloud-only BDTOPO   # encart et style.css, sans parcourir l'arbre classique
```

`--cloud-only` interroge toujours le service `chunk`. Cette commande remplace
l'encart entre ses marqueurs HTML et réécrit `style.css` ; elle ne régénère ni
l'accueil, ni les pages de thème, ni les scripts du gabarit commun. Si la fiche
ou ses marqueurs manquent, il faut la reconstruire avec `--only ID`.

### Pages éditoriales

Le champ `page` permet de publier une fiche rédigée dans [`pages/`](pages/) sans
ressource correspondante dans le service de téléchargement. C'est le cas des
pages MNT, MNS et MNH LiDAR HD. Le fichier Markdown fournit le contenu de la fiche,
y compris son titre et ses liens ; le catalogue fournit sa carte et son thème.

Les pages et tutoriels utilisent le convertisseur de [`gpf/markdown.py`](gpf/markdown.py) :
titres `#` à `###`, paragraphes, listes à puces, séparateurs, liens, gras, italique,
code en ligne et blocs de code clôturés. Deux espaces en fin de ligne permettent
un retour à la ligne dans un paragraphe. Les tableaux, listes numérotées ou
imbriquées, images et HTML brut ne sont pas pris en charge.

## Mise à jour automatique (GitHub Pages)

[`.github/workflows/build.yml`](.github/workflows/build.yml) régénère et publie
le site chaque jour à **2 h, heure de Paris**, et sur déclenchement manuel. Il
utilise Python 3.12 et suit ces étapes :

1. Installer WireGuard, résoudre les IP de `data.geopf.fr` et monter un tunnel qui
   route uniquement ces IP ; vérifier leur passage par le tunnel.
2. Exécuter les tests, puis `--check` à titre informatif.
3. Reconstruire le site avec `--fail-fast`, **8 workers** et **8 requêtes/s** par
   défaut. Les deux valeurs sont réglables au déclenchement manuel.
4. Téléverser le dossier `site/` comme artefact et le déployer sur GitHub Pages
   après réussite du build. Le tunnel est arrêté même en cas d'échec.

Pour utiliser ce workflow, choisir **Settings → Pages → Source : GitHub Actions**
et définir le secret Actions **`PR_WG_CFG`**, contenant la configuration WireGuard
encodée en base64. Le workflow retire ses lignes `DNS` et remplace `AllowedIPs`
par les IP résolues de `data.geopf.fr` afin de conserver le DNS du runner et de
limiter le routage au service.

Une erreur fatale du crawl bloque la publication ; le dernier site déployé reste
en ligne. Les fichiers générés ne sont pas committés dans le dépôt (`site/` est
ignoré par Git).

## Architecture du code

```
build.py            CLI + orchestration (crawl, pages, encarts cloud, assets)
catalogue.json      métadonnées éditoriales des produits (éditées à la main)
RULES.md            règles d'affichage appliquées à tous les produits (doc lisible)
assets/             statiques copiés tels quels vers site/assets (logos producteurs…)
pages/              sources Markdown des pages éditoriales (converties au build, non copiées)
tutos/              tutoriels d'accès direct par produit, convertis en onglets
gpf/
  model.py          fonctions pures : human_size, fmt_date, slug, resource_id, is_md5…
  atom.py           parsing du flux Atom (parse_feed)
  api.py            client HTTP parallèle, débit global, réessais et pagination
  catalogue.py      chargement + validation du catalogue, jointure éditoriale
  markdown.py       Markdown → HTML (pages, tutoriels, footer), découpage en sections
  rules.py          règles d'affichage déclaratives (classement, repli, fusion DROM, tri)
  crawl.py          crawl récursif d'un produit → arborescence (applique gpf/rules)
  cloud.py          lecture ciblée du service chunk, choix des éditions et couches
  render.py         templates HTML (string.Template) + feuille CSS partagée style.css
                    (dark/responsive), thème et copie JS inline, favicon, robots.txt
  validate.py       détection de dérive des deux services (--check)
test_gpf.py         tests du catalogue, du crawl, du rendu et de l'accès direct (sans réseau)
.github/workflows/
  build.yml         tests, contrôle de dérive, génération via VPN et publication Pages
```

Les règles de mise en forme appliquées à tous les produits (classement
zone/date/radiométrie/format, repli des niveaux inutiles, fusion des DROM, tri des territoires…)
sont déclarées dans [`gpf/rules.py`](gpf/rules.py) et décrites en clair dans
[`RULES.md`](RULES.md).

## Limites connues

- Une reconstruction complète parcourt tous les produits inclus du service
  classique, sans cache. Les ressources volumineuses, comme les nuages de points
  LiDAR HD, peuvent prendre beaucoup de temps à indexer. `--only`, `--only-theme`
  et `--cloud-only` permettent de cibler les vérifications locales.
- Les dossiers dépassant `site.max_entries` ne sont pas dépliés : une page renvoie
  vers le flux source. Le catalogue fourni fixe ce seuil à 50 000 entrées.
- Les éditions et jeux de couches peuvent différer entre formats d'accès direct ;
  seules les URL trouvées sont proposées. Les tutoriels ne sont pas réécrits
  automatiquement à chaque nouvelle édition.
- Données diffusées sous les conditions de la Géoplateforme ; ce dépôt n'indexe
  que des liens publics et ne redistribue aucune donnée.

## Reste à faire

- [x] Finaliser l'affichage tout supports
- [x] Rajouter le service de téléchargement partiel (cloud native)
- [ ] Ajouter PVA
- [ ] Ajouter documents d'urbanisme
