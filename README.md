# Téléchargement Géoplateforme - index technique (non officiel)

Générateur de **site statique** pour faciliter le téléchargement des données de
l'IGN diffusées par le service de Téléchargement de la [Géoplateforme](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/telechargement/)
(`data.geopf.fr`). Les produits sont organisés **par thème**, chaque produit a
une **fiche** (résumé + liens vers ses spécifications officielles et ressources) et son
**arborescence de téléchargement**. Le site est régénéré de manière régulière.

👉 Le site statique généré est consultable ici : https://telecharger.geoplateforme.fr

Le site **n'héberge aucune donnée** : les liens de fichiers pointent directement
vers `data.geopf.fr`. C'est un index navigable, plus lisible que le service brut.

- **Zéro dépendance** - bibliothèque standard Python uniquement (Python ≥ 3.11).
- **Front minimal** - HTML sémantique + une feuille CSS partagée (`style.css`, sobre,
  responsive, mode sombre automatique) ; seul JavaScript : un petit script inline
  pour le bouton de bascule de thème clair/sombre.
- Hébergeable tel quel sur GitHub Pages (ou tout serveur statique).

## Comment ça marche

L'API de téléchargement de la Géoplateforme expose une hiérarchie [Atom](https://www.ietf.org/rfc/rfc4287.txt) à 3 niveaux :

| Niveau | URL | Contenu |
|---|---|---|
| catalogue | `…/telechargement/capabilities` | ~111 ressources (produits) |
| ressource | `…/resource/{ID}` | versions / zones / dates / formats |
| sous-ressource | `…/resource/{ID}/{SOUS}` | fichiers téléchargeables |

`build.py` crawle cette API pour les produits **sélectionnés dans le catalogue**
et reconstruit une arborescence de dossiers, chacun avec un `index.html`.

**Point clé** : l'API ne fournit que peu de métadonnées éditoriales (pas de
description courte, ni de thème, ni de lien vers les spécifications, etc.). Tout cela est
maintenu dans [`catalogue.json`](catalogue.json) et joint au crawl via l'`id` de ressource.

Trois aménagements du listing :
- les sidecars `.md5` ne sont pas listés (leur checksum figure déjà en colonne MD5) ;
- une sous-ressource qui se réduit à une seule unité téléchargeable (fichier
  unique, ou volumes d'un `.7z.NNN`) est **aplatie** (pas de dossier dédié) ;
- quand les sous-ressources portent zone + format, elles sont classées en
  `zone/date/format`, un niveau à valeur unique étant replié.

## Utilisation

```bash
python build.py                        # rebuild complet dans ./site
python build.py --only ADMIN-EXPRESS   # ne construire qu'un produit (pour test)
python build.py --only-theme admin     # ne construire qu'un thème (pour test)
python build.py --check                # dérive catalogue ↔ API (ne construit rien)
python -m unittest                     # tests des fonctions pures (sans réseau)
```

### Prévisualiser en local

Le site est statique, mais **ouvrir `site/index.html` en `file://` ne suffit
pas** : la navigation entre dossiers casse (les liens relatifs se terminent par
`/` et le navigateur n'y résout pas `index.html`). Il faut un serveur HTTP :

```bash
python3 -m http.server 8000 --directory site   # puis http://localhost:8000/
```

### Options

| Option                    | Effet                                                                                        |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| `--out DIR`               | dossier de sortie (défaut `site`)                                                            |
| `--catalogue FILE`        | fichier catalogue (défaut `catalogue.json`)                                                  |
| `--only ID`               | ne construire qu'un produit (test ; ne purge pas le reste)                                   |
| `--only-theme THEME`      | ne construire qu'un thème, par `id` (test ; ne purge pas le reste ; exclusif avec `--only`)  |
| `--check`                 | rapport de dérive catalogue ↔ API, sans rien construire                                      |
| `--requests-per-second N` | débit visé (défaut 10 ; la limite API est ≤ 10)                                              |

## Gérer les produits - [`catalogue.json`](catalogue.json)

Le catalogue est un JSON **tolérant les commentaires `//` et les virgules
finales** (pour rester éditable à la main). Trois blocs :

- `themes` - la taxonomie, **dans l'ordre d'affichage**. Chaque thème : `id`, `label`.
- `producers` - les producteurs affichés sur les cartes (voir ci-dessous).
- `products` - la liste des produits.

Champs d'un produit :

| Champ      | Oblig. | Rôle                                                                                                                                                                                                                                                                                                                    |
| ---------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`       | ✅     | Nom **exact** de la ressource dans `…/resource/{id}` - clé de jointure avec l'API.                                                                                                                                                                                                                                      |
| `title`    | -      | Titre affiché (repli sur le titre Atom).                                                                                                                                                                                                                                                                                |
| `theme`    | -      | `id` d'un thème déclaré. Vide ou inconnu → « Autres jeux de données ».                                                                                                                                                                                                                                                  |
| `summary`  | -      | Résumé éditorial (1-2 phrases, public technique).                                                                                                                                                                                                                                                                       |
| `update`   | -      | Rythme de mise à jour, **texte libre** (`mensuel`, `annuel`…). Affiché sur la carte ; vide → ligne masquée. Pour un produit arrêté, y mettre le motif (ex. `Remplacé par ADMIN EXPRESS`) : il est repris dans le bandeau de la fiche.                                                                                   |
| `producer` | -      | `id` d'un producteur déclaré dans `producers` (voir ci-dessous). Vide → aucun badge.                                                                                                                                                                                                                                    |
| `specs`    | -      | Liste de `{ "label", "url", "type" }` : liens de spécification. `type` (optionnel) choisit l'emoji de la ligne : `contenu` 📄, `livraison` 📦, `fiche` 📋, `guide` 📖, `tutoriel` 🧪, `interface` 🖱️, `carte` 🗺️, `explorateur` 🧭. Type absent → 📄 ; type inconnu → 📄 + avertissement au build.                                       |
| `include`  | -      | `false` pour masquer un produit sans le supprimer (défaut `true`).                                                                                                                                                                                                                                                      |
| `retired`  | -      | `true` pour un **produit arrêté** (plus maintenu, souvent remplacé) : reste publié et affiché en ligne, mais sa carte est ambrée avec un badge « Arrêté » et sa fiche porte un bandeau. Défaut `false`. À ne pas confondre avec les **archives** (données anciennes toujours utiles), qui restent des produits normaux. |
| `order`    | -      | Ordre d'affichage intra-thème, croissant (défaut 100). À `order` égal, l'**ordre du catalogue** est conservé (tri stable) : sans `order` explicite, les produits s'affichent donc dans leur ordre de déclaration dans `catalogue.json`.                                                                                 |
| `page`     | -      | Nom d'un fichier Markdown dans [`pages/`](pages/) (ex. `mnt-lidarhd.md`). Si renseigné, l'entrée est une **page éditoriale** (contenu rédigé, non crawlé) au lieu d'un produit de l'API : sa fiche est générée depuis ce Markdown, et `--check` l'ignore.                                                               |

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

1. `python build.py --check` liste les ressources de l'API absentes du catalogue.
2. Ajoutez une entrée `products` avec le bon `id`, un `theme`, un `summary`.
3. Renseignez `specs` avec les liens PDF officiels. Utilisez le host **durable**
   `https://data.geopf.fr/annexes/ressources/documentation/…` et non `geoservices.ign.fr` désormais fermé.
4. `python build.py --only <id>` pour vérifier le rendu du produit.

### Documents de spécification

Ce sont des **liens** vers les descriptifs de contenu / de livraison publiés par
l'IGN (on ne réhéberge rien). Les millésimes figurent dans les noms de fichiers
PDF (`DC_BDTOPO_3-5.pdf`…) : ils sont à mettre à jour à la main quand l'IGN publie
une nouvelle version - l'API de téléchargement ne fournit pas ces liens.

## Mise à jour automatique (GitHub Pages)

[`.github/workflows/build.yml`](.github/workflows/build.yml) régénère et publie
le site : un step `--check` signale la dérive du catalogue, puis génère le site et
déploie sur Pages (cron journalier + déclenchement manuel). Rien n'est committé dans ce dépôt.

Dans **Settings → Pages**, choisir **Source : GitHub Actions**.

## Architecture du code

```
build.py            CLI + orchestration (jointure catalogue×live, pages, copie assets)
catalogue.json      métadonnées éditoriales des produits (éditées à la main)
RULES.md            règles d'affichage appliquées à tous les produits (doc lisible)
assets/             statiques copiés tels quels vers site/assets (logos producteurs…)
pages/              sources Markdown des pages éditoriales (converties au build, non copiées)
gpf/
  model.py          fonctions pures : human_size, fmt_date, slug, resource_id, is_md5…
  atom.py           parsing du flux Atom (parse_feed)
  api.py            client HTTP throttlé (WAF/UA, backoff, pagination)
  catalogue.py      chargement + validation du catalogue, jointure éditoriale
  markdown.py       mini-convertisseur Markdown → HTML (pages éditoriales + footer)
  rules.py          règles d'affichage déclaratives (classement, repli, fusion DROM, tri)
  crawl.py          crawl récursif d'un produit → arborescence (applique gpf/rules)
  render.py         templates HTML (string.Template) + feuille CSS partagée style.css
                    (dark/responsive) + toggle de thème JS inline
  validate.py       détection de dérive (--check)
test_gpf.py         tests des fonctions pures + du catalogue (sans réseau)
```

Les règles de mise en forme appliquées à tous les produits (classement
zone/date/format, repli des niveaux inutiles, fusion des DROM, tri des territoires…)
sont déclarées dans [`gpf/rules.py`](gpf/rules.py) et décrites en clair dans
[`RULES.md`](RULES.md).

## Limites connues

- Chaque build re-crawle l'intégralité des produits inclus (pas de cache) : simple
  et toujours à jour, mais coûteux sur les gros jeux. Les ressources très
  volumineuses (dalles LiDAR HD complètes, prises de vue aériennes) peuvent prendre beaucoup de temps à indexer.
- Données diffusées sous les conditions de la Géoplateforme ; ce dépôt n'indexe
  que des liens publics et ne redistribue aucune donnée.

## Reste à faire

  - [x] Finaliser l'affichage tout supports
  - [x] Rajouter le service de téléchargement partiel (cloud native)
  - [ ] Ajouter PVA
  - [ ] Ajouter documents d'urbanisme
 
