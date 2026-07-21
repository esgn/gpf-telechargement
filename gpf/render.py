"""Rendu HTML : squelette de page (string.Template) + CSS sobre, responsive et
compatible mode sombre, servi via une feuille partagée « style.css » (écrite une
fois par write_stylesheet, référencée en relatif par chaque page → mise en cache
par le navigateur). Aucune dépendance externe : le CSS est servi par le site
lui-même. Seul JS = le toggle de thème, inline (minime, et l'anti-flash DOIT rester
dans <head>).

string.Template (`$var`) est utilisé pour le squelette de page : substitution
simple par nom, et robuste si le corps HTML contient des `{}` (contrairement à un
f-string / str.format qui les interpréteraient)."""

from __future__ import annotations

import html
import os
from string import Template

from .api import log
from .model import fmt_date, human_size

# --------------------------------------------------------------------------- #
# CSS — une seule constante, écrite dans style.css (write_stylesheet) et référencée
# en relatif par chaque page. Source unique de vérité pour tout le style du site.
# --------------------------------------------------------------------------- #

CSS = """
/* Palette claire par défaut. Le mode sombre s'applique de deux façons, dans cet
   ordre de priorité : (1) préférence OS via prefers-color-scheme si l'utilisateur
   n'a rien choisi ; (2) choix explicite via data-theme sur <html>, posé par le
   bouton — data-theme gagne toujours, dans les DEUX sens (forcer clair ou sombre). */
:root {
  --bg:#ffffff; --fg:#1a1a1a; --muted:#5b6470; --border:#e4e7eb;
  --link:#0b57d0; --row:#f7f8fa; --code:#f0f2f5; --accent:#0b57d0;
  --card:#ffffff; --shadow:0 1px 2px rgba(0,0,0,.06);
  /* Carte de produit arrêté : fond et bordure ambrés discrets pour la distinguer
     sans crier ; le badge « Arrêté » reprend ces mêmes tons plus soutenus. */
  --retired-card:#fbf6ec; --retired-border:#e7d9b8; --retired-badge:#8a6d1f;
  /* Encart « accès direct » cloud-native + badge de carte : fond bleuté dérivé de
     l'accent, distinct du flux normal sans le concurrencer. */
  --panel-bg:#f1f6fe; --panel-border:#cadffb;
  --code-comment:#137333;   /* commentaires des blocs de code, en vert */
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#14171c; --fg:#e6e8eb; --muted:#98a2b3; --border:#2a2f37;
    --link:#8ab4ff; --row:#1a1e24; --code:#20252d; --accent:#8ab4ff;
    --card:#191d23; --shadow:none;
    --retired-card:#221e15; --retired-border:#3a3320; --retired-badge:#d9bd74;
    --panel-bg:#161d2a; --panel-border:#2c3b52;
    --code-comment:#7ee787;
  }
}
:root[data-theme="dark"] {
  --bg:#14171c; --fg:#e6e8eb; --muted:#98a2b3; --border:#2a2f37;
  --link:#8ab4ff; --row:#1a1e24; --code:#20252d; --accent:#8ab4ff;
  --card:#191d23; --shadow:none;
  --retired-card:#221e15; --retired-border:#3a3320; --retired-badge:#d9bd74;
  --panel-bg:#161d2a; --panel-border:#2c3b52;
  --code-comment:#7ee787;
}
* { box-sizing:border-box; }
body {
  margin:0 auto; max-width:64rem; padding:1.5rem clamp(1rem,4vw,2.5rem) 4rem;
  background:var(--bg); color:var(--fg);
  font:16px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
a { color:var(--link); text-decoration:none; }
a:hover { text-decoration:underline; }
a:visited { color:var(--link); }
/* Liens dans le corps de texte (pages éditoriales Markdown) : une URL longue sans
   espace ne doit pas pousser la page en largeur — on la laisse se couper. Ciblé sur
   les paragraphes pour ne pas toucher la navigation (fil d'Ariane, cartes, thèmes). */
main p a { overflow-wrap:anywhere; }
h1 { font-size:1.7rem; line-height:1.2; margin:0 0 .4rem; }
h2 { font-size:1.15rem; margin:2.2rem 0 .8rem; }
p { margin:.5rem 0; }
/* Pages éditoriales : plus d'air entre le titre et le 1ᵉʳ paragraphe de contenu.
   Exclut p.lead (chapô d'accueil / résumé de fiche), volontairement rapproché du h1. */
main h1 + p:not(.lead) { margin-top:1rem; }
hr { border:0; border-top:1px solid var(--border); margin:2rem 0; }
code { background:var(--code); padding:.1em .35em; border-radius:4px;
       font-size:.85em; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
/* Bloc de code (```… en Markdown → <pre><code>), pour les pages éditoriales comme
   pour les tutos cloud-native : boîte qui défile en largeur (le code long ne pousse
   jamais la page). Le fond/padding du <code> inline est neutralisé dans un <pre>. */
pre { margin:.6rem 0; overflow-x:auto; background:var(--code); border:1px solid var(--border);
      border-radius:8px; padding:.75rem .9rem; font-size:.85em; line-height:1.5;
      font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
pre code { background:none; padding:0; border-radius:0; font-size:1em; }
/* Coloration légère des blocs de code : seules les lignes de commentaire (# ou --,
   cf. gpf.markdown._highlight_code) passent en vert, lisible en clair comme en sombre. */
pre .tok-comment { color:var(--code-comment); }
/* Bouton « Copier » posé par JS (_CODE_COPY_JS) en haut à droite d'un bloc de code :
   icône « deux carrés » (convention presse-papiers), qui passe en ✓ vert un court
   instant après copie. .code-wrap (position:relative) le tient hors du <pre> qui défile.
   L'icône est un MASQUE SVG teinté par currentColor → suit le thème clair/sombre. */
.code-wrap { position:relative; }
.code-copy { position:absolute; top:.4rem; right:.4rem; cursor:pointer;
  display:inline-flex; align-items:center; justify-content:center;
  width:1.7rem; height:1.7rem; padding:0; line-height:0;
  color:var(--muted); background:var(--card);
  border:1px solid var(--border); border-radius:6px;
  opacity:.6; transition:opacity .15s, color .15s, border-color .15s; }
.code-copy::before { content:""; width:.95rem; height:.95rem; background-color:currentColor;
  -webkit-mask:url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>') center/contain no-repeat;
          mask:url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>') center/contain no-repeat; }
.code-wrap:hover .code-copy { opacity:1; }
.code-copy:hover { color:var(--accent); border-color:var(--accent); }
.code-copy:focus-visible { opacity:1; outline:2px solid var(--accent); outline-offset:2px; }
/* Confirmation : coche verte un court instant (classe .copied posée par le JS). */
.code-copy.copied { opacity:1; color:var(--code-comment); border-color:var(--code-comment); }
.code-copy.copied::before {
  -webkit-mask-image:url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>');
          mask-image:url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="black" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>'); }

nav.crumbs { font-size:.9rem; color:var(--muted); margin-bottom:1.2rem;
             word-break:break-word; }
nav.crumbs a { color:var(--muted); }
nav.crumbs a:hover { color:var(--link); }
nav.crumbs span[aria-current] { color:var(--fg); }

/* Pas de max-width ici : le chapô suit la largeur du contenu (body, 64rem), aligné
   avec les cartes et le pied de page — plutôt qu'un bloc plus étroit isolé. */
p.lead { color:var(--muted); font-size:1.05rem; }
/* Sommaire de thèmes (accueil) : puces compactes qui défilent vers la section
   correspondante (liens #ancre, même page). Discret, ne pousse pas les cartes trop bas. */
nav.theme-nav { display:flex; flex-wrap:wrap; gap:.4rem .5rem; margin:1.1rem 0 1.8rem; }
nav.theme-nav a { font-size:.85rem; color:var(--muted); text-decoration:none;
                  padding:.2rem .6rem; border:1px solid var(--border);
                  border-radius:999px; background:var(--row); white-space:nowrap; }
nav.theme-nav a:hover { color:var(--link); border-color:var(--accent); }
/* Bandeau « produit arrêté » en tête de fiche : même palette ambrée que les cartes. */
p.retired-banner { max-width:46rem; margin:.6rem 0; padding:.6rem .85rem;
                   font-size:.95rem; color:var(--fg);
                   background:var(--retired-card);
                   border:1px solid var(--retired-border);
                   border-left:3px solid var(--retired-badge); border-radius:6px; }
p.retired-banner strong { color:var(--retired-badge); }

/* Accueil : sections thématiques + grille de cartes produit */
section.theme { margin-top:2.2rem; }
/* Le titre de thème est un lien vers sa page : couleur de texte normale, il ne se
   colore et se souligne qu'au survol (pour ne pas alourdir la hiérarchie). */
section.theme h2 a { color:inherit; }
section.theme h2 a:hover { color:var(--link); }
ul.grid { list-style:none; margin:0; padding:0; display:grid; gap:.8rem;
          grid-template-columns:repeat(auto-fill,minmax(17rem,1fr)); }
ul.grid li { margin:0; }
a.card { display:flex; flex-direction:column; height:100%; padding:.9rem 1rem;
         border:1px solid var(--border); border-radius:10px; background:var(--card);
         box-shadow:var(--shadow); color:inherit; }
a.card:hover { border-color:var(--accent); text-decoration:none; }
/* En-tête de carte : titre à gauche, badge producteur à droite (flex, robuste). */
a.card .card-head { display:flex; align-items:flex-start; justify-content:space-between;
                    gap:1rem; }
a.card strong { font-size:1.02rem; color:var(--link); }
/* margin-bottom : garantit un minimum d'air entre la fin du résumé et le filet du
   pied, même quand la carte est « pleine » (margin-top:auto du pied ne laisse alors
   aucun espace). */
a.card .summary { margin-top:.25rem; margin-bottom:.9rem; font-size:.9rem;
                  color:var(--muted); }
/* Pied de carte « Mise à jour » : détaché du corps par un filet (border-top) qui
   court bord à bord (marges négatives = padding de la carte). Poussé en bas
   (margin-top:auto) pour aligner les cartes d'une même rangée. */
a.card .update { margin-top:auto; padding:.5rem 1rem 0; margin-left:-1rem;
                 margin-right:-1rem; border-top:1px solid var(--border);
                 font-size:.8rem; color:var(--muted); font-style:italic; }
/* Badge producteur : logo (img) ou nom, calé en haut à droite. flex-shrink:0
   pour qu'il ne s'écrase pas ; le titre prend la place restante. Le gap sépare
   les logos entre eux (coédition IGN + INSEE) pour qu'ils ne se touchent pas. */
a.card .producer { flex:0 0 auto; max-width:50%; font-size:.78rem;
                   color:var(--muted); text-align:right;
                   display:flex; align-items:center; gap:.7rem;
                   justify-content:flex-end; flex-wrap:wrap; }
/* height (et non max-height) : le logo SVG n'a pas de dimensions intrinsèques
   (viewBox seul) ; sans hauteur imposée, width:auto s'effondre à 0 en flex et
   l'image devient invisible. Hauteur fixe → largeur calculée par le ratio. */
a.card .producer img { display:block; height:0.8rem; max-width:100%;
                       width:auto; margin-left:auto; opacity:.65; }

/* Produit arrêté : carte au fond ambré, distincte du flux principal. Affichée en
   ligne avec les autres pour l'instant (pas de masquage) ; le badge « Arrêté » et le
   fond signalent le statut. */
a.card.card--retired { background:var(--retired-card);
                       border-color:var(--retired-border); }
a.card.card--retired:hover { border-color:var(--retired-badge); }
/* Badge « Arrêté » calé à gauche de la ligne d'en-tête, avant le titre. */
a.card .retired-flag { display:inline-block; font-size:.7rem; font-weight:600;
                       letter-spacing:.02em; text-transform:uppercase;
                       color:var(--retired-badge); border:1px solid var(--retired-border);
                       border-radius:5px; padding:.05rem .35rem; margin-bottom:.35rem;
                       align-self:flex-start; }

/* Fiche produit : liens de spécification */
ul.specs { list-style:none; margin:.5rem 0; padding:0; }
ul.specs li { margin:.3rem 0; }
/* L'emoji est posé dans le HTML (par type de doc, cf. _spec_icon), pas en ::before,
   pour pouvoir varier d'une ligne à l'autre. */
ul.specs .spec-icon { font-style:normal; }
p.meta { font-size:.9rem; color:var(--muted); }

/* Listing de fichiers/dossiers */
table.listing { width:100%; border-collapse:collapse; font-size:.94rem; margin-top:.5rem; }
/* Filet anti-débordement : nom et MD5 étant en nowrap (voir plus bas), un tableau plus
   large que son conteneur défile DANS ce cadre, sans jamais pousser la page en largeur.
   Le mode « cartes » (≤768px) repasse .scroll en overflow-x:visible (rien ne déborde). */
.scroll { overflow-x:auto; }
.listing th, .listing td { padding:.5rem; border-bottom:1px solid var(--border);
                           text-align:left; vertical-align:top; }
.listing th { color:var(--muted); font-weight:600; white-space:nowrap; }
.listing tbody tr:hover { background:var(--row); }
/* Taille : chiffres alignés à droite. Pas de nowrap → elle peut s'enrouler (« 4.0 Gio »
   → deux lignes) pour céder la largeur au nom et au MD5 quand la place manque. */
.listing td.num { text-align:right; font-variant-numeric:tabular-nums; }
/* MD5 : hash de 32 car. gardé sur une seule ligne (jamais cassé). Le nom de
   fichier absorbe la contrainte de largeur et se coupe proprement (aux séparateurs
   _ - . via overflow-wrap:anywhere, plutôt qu'en plein milieu d'un mot). */
.listing td.md5 code { color:var(--muted); white-space:nowrap; }
/* Sur mobile (mode « cartes empilées » ci-dessous), une longue chaîne sans espace doit
   pouvoir se couper aux séparateurs (_ - .) pour ne pas déborder l'écran étroit. */
.listing td:first-child a { overflow-wrap:anywhere; }
/* >768px (rendu tableau) : on protège NOM et MD5 (jamais coupés) ; Modifié le et Taille
   cèdent (s'enroulent) quand la place manque. En layout auto, un contenu en nowrap
   réclame toute sa largeur, un contenu enroulable se réduit à son mot le plus long : Nom
   (nowrap ici) et MD5 (nowrap plus haut) gardent donc la priorité, la date et la taille
   se tassent en premier. Scopé >768px : en mode cartes, le nom occupe toute la largeur
   et DOIT pouvoir s'enrouler (écran étroit). */
@media (min-width:769px) {
  .listing td:first-child { white-space:nowrap; }
}
/* Dossier signalé par 📁 (préfixe) + le suffixe « / ». Fichier signalé par une
   petite icône « document » (SVG inline en data-URI, fond blanc + contour sombre)
   posée en ::before — définie une seule fois dans le CSS, donc légère même sur un
   listing de milliers de fichiers. `:not(.dir)` évite tout conflit avec le 📁. */
.listing a.dir::before { content:"📁 "; }
.listing a.dir::after { content:"/"; color:var(--muted); }
.listing td:first-child a:not(.dir)::before {
  content:""; display:inline-block; width:.72em; height:.9em;
  margin-right:.4em; vertical-align:-.12em;
  background:url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 265 323"><path fill="%23fff" stroke="%231a1a1a" stroke-width="14" d="M13 24.12v274.76c0 6.16 5.87 11.12 13.17 11.12H239c7.3 0 13.17-4.96 13.17-11.12V136.15S132.6 13 128.37 13H26.17C18.87 13 13 17.96 13 24.12z"/></svg>') no-repeat center/contain;
}
.up { display:inline-block; margin:.4rem 0 .2rem; }
/* Listing de NAVIGATION (niveaux zone/date/radiométrie, cf. render.nav_table) :
   réutilise table.listing. La colonne « Formats disponibles » résume ce qu'on
   trouvera en dessous ; texte discret pour ne pas concurrencer le nom (lien). */
.listing td.formats { color:var(--muted); }

/* --------------------------------------------------------------------------- */
/* Accès cloud-native : badge de carte (⚡) + encart « accès direct » repliable  */
/* en tête de fiche. Fond bleuté (--panel-*), distinct du flux normal. cf.        */
/* render.cloud_block et gpf.cloud.                                              */
/* --------------------------------------------------------------------------- */
/* Badge de carte : signale un produit interrogeable à distance, sous le titre. */
a.card .cloud-badge { align-self:flex-start; display:inline-flex; align-items:center;
  gap:.3rem; margin:.5rem 0 0; font-size:.7rem; font-weight:600; letter-spacing:.02em;
  color:var(--accent); background:var(--panel-bg); border:1px solid var(--panel-border);
  border-radius:999px; padding:.12rem .55rem; }

/* Encart : <details> replié par défaut, liseré accent à gauche (comme le bandeau
   « produit arrêté », mais en bleu accent). */
details.cloud-dt { border:1px solid var(--panel-border); border-left:3px solid var(--accent);
  border-radius:10px; background:var(--panel-bg); margin:1.4rem 0; }
details.cloud-dt > summary { list-style:none; cursor:pointer; display:flex;
  align-items:center; gap:.5rem; flex-wrap:wrap; padding:.7rem .9rem; }
details.cloud-dt > summary::-webkit-details-marker { display:none; }
details.cloud-dt > summary:focus-visible { outline:2px solid var(--accent);
  outline-offset:2px; border-radius:8px; }
.cloud-bolt { font-size:1.05rem; }
.cloud-sum { flex:1; min-width:12rem; font-size:.93rem; }
.cloud-tag { font-size:.68rem; font-weight:600; letter-spacing:.03em;
  text-transform:uppercase; color:var(--accent); background:var(--card);
  border:1px solid var(--panel-border); border-radius:999px; padding:.1rem .5rem;
  white-space:nowrap; }
/* Repère d'ouverture : le marqueur natif du <details> est retiré (list-style:none),
   on le remplace par un « Afficher ▾ / Masquer ▴ » explicite (couleur accent) — sinon
   le résumé passe pour une bannière figée et l'utilisateur ne devine pas qu'il déplie. */
.cloud-disclose { font-size:.8rem; font-weight:600; color:var(--accent); white-space:nowrap; }
details.cloud-dt:not([open]) > summary .cloud-disclose::after { content:"Afficher ▾"; }
details.cloud-dt[open] > summary .cloud-disclose::after { content:"Masquer ▴"; }
details.cloud-dt > summary:hover .cloud-disclose { text-decoration:underline; }
.cloud-body { padding:0 1.05rem 1rem; }
.cloud-meta { font-size:.82rem; color:var(--muted); margin:.1rem 0 .3rem; }
.cloud-how { font-size:.85rem; color:var(--muted); margin:.5rem 0 .2rem; }
details.cloud-couches { margin-top:.7rem; }
details.cloud-couches > summary { cursor:pointer; font-size:.85rem; font-weight:600;
  color:var(--accent); }
details.cloud-couches > summary:focus-visible { outline:2px solid var(--accent);
  outline-offset:2px; border-radius:4px; }
/* Tutos en ONGLETS, 100% CSS (radios cachés + sélecteur ~ sur :checked), placés
   AU-DESSUS de la liste des couches. Un onglet = une section « ## » du Markdown
   tutos/<produit>.md (cf. gpf.markdown.split_sections) ; règles génériques jusqu'à 4
   onglets. Sans JS : si le CSS ou le JS venait à manquer, chaque panneau reste
   atteignable (le premier est affiché par défaut, les radios sont navigables). */
details.cloud-tuto { margin-top:.7rem; }
details.cloud-tuto > summary { cursor:pointer; font-size:.85rem; font-weight:600;
  color:var(--accent); }
details.cloud-tuto > summary:focus-visible { outline:2px solid var(--accent);
  outline-offset:2px; border-radius:4px; }
.cloud-tuto-intro { font-size:.85rem; color:var(--muted); margin:.5rem 0 .1rem; }
.cloud-tabs { margin-top:.6rem; }
/* Radio caché mais focusable (pas display:none) : le label sert de bouton d'onglet. */
.cloud-tab-radio { position:absolute; opacity:0; pointer-events:none; }
.cloud-tab-label { display:inline-block; cursor:pointer; font-size:.85rem; font-weight:500;
  color:var(--muted); padding:.35rem .7rem; border-bottom:2px solid transparent; }
.cloud-tab-label:hover { color:var(--fg); }
.cloud-tab-radio:checked + .cloud-tab-label { color:var(--accent);
  border-bottom-color:var(--accent); font-weight:600; }
.cloud-tab-radio:focus-visible + .cloud-tab-label { outline:2px solid var(--accent);
  outline-offset:2px; border-radius:4px; }
.cloud-tab-panels { border-top:1px solid var(--panel-border); padding-top:.3rem; }
.cloud-tab-panel { display:none; font-size:.9rem; }
.cloud-tab-panel p { margin:.3rem 0; color:var(--muted); }
/* Onglet i coché → panneau i visible (position à position). */
.cloud-tab-radio:nth-of-type(1):checked ~ .cloud-tab-panels > .cloud-tab-panel:nth-child(1),
.cloud-tab-radio:nth-of-type(2):checked ~ .cloud-tab-panels > .cloud-tab-panel:nth-child(2),
.cloud-tab-radio:nth-of-type(3):checked ~ .cloud-tab-panels > .cloud-tab-panel:nth-child(3),
.cloud-tab-radio:nth-of-type(4):checked ~ .cloud-tab-panels > .cloud-tab-panel:nth-child(4) {
  display:block; }
/* Bouton « Copier » : PAS un lien — ces fichiers pèsent souvent plusieurs Gio, on
   copie leur URL pour les interroger à distance, on ne les clique pas (un clic
   déclencherait un téléchargement intégral). */
.cloud-copy { cursor:pointer; font:inherit; font-size:.8rem; font-weight:600;
  color:var(--accent); background:transparent; border:1px solid var(--panel-border);
  border-radius:6px; padding:.15rem .5rem; white-space:nowrap; }
.cloud-copy:hover { border-color:var(--accent); }
.cloud-copy:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.cloud-none { color:var(--muted); }
/* Colonnes de format (2e, 3e…) : compactes, calées à droite (comme .num). */
table.cloud-layers th:not(:first-child),
table.cloud-layers td:not(:first-child) { text-align:right; white-space:nowrap; width:1%; }
/* Mode « cartes » (≤768px) : la table est délinéarisée (bloc média en fin de CSS) et
   les cellules de format passeraient inline, collées (« Copier FlatGeoBuf : … »). On
   les remet en bloc, une par ligne sous le nom de couche, alignées à gauche et espacées. */
@media (max-width:768px) {
  table.cloud-layers td[data-label] { display:block; width:auto; text-align:left;
    margin:.35rem 0 0; }
}

footer { margin-top:3rem; padding-top:1.2rem; border-top:1px solid var(--border);
         font-size:.85rem; color:var(--muted);
         display:flex; align-items:flex-start; gap:1rem; }
/* Le texte du footer coule normalement (un seul bloc) et prend la largeur ; l'icône
   dépôt reste à droite. */
footer .footer-text { flex:1; }
/* Lien dépôt : icône GitHub discrète mais bien visible, en gris muted, passant à la
   couleur du texte au survol. flex-shrink:0 : ne s'écrase pas. display:flex sur le
   lien pour que le SVG ne soit pas rogné par la hauteur de ligne. */
footer .repo-link { flex:0 0 auto; display:flex; color:var(--muted); }
footer .repo-link:hover { color:var(--fg); }

/* Bouton de bascule clair/sombre, fixé en haut à droite. Discret mais détaché du
   fond : fond légèrement teinté (--row, distinct du blanc de la page), bordure plus
   soutenue et ombre portée explicite (--shadow est nul en sombre, d'où une valeur
   propre ici) pour qu'il ne se fonde pas — surtout en thème clair sur fond blanc. */
/* Interrupteur clair/sombre : une pilule (le <button>) + une poignée ronde blanche
   (::before) qui glisse, portant l'icône de l'état courant (::after : lune en clair,
   soleil en sombre). Le thème effectif a 3 sources, dans cet ordre de priorité :
   data-theme=light, data-theme=dark, sinon prefers-color-scheme. On décline donc la
   position de la poignée et l'icône pour ces 3 cas (comme la palette plus haut). */
#theme-toggle {
  /* Calé dans le coin haut-droit de la fenêtre, avec une marge pour le décoller. */
  position:fixed; top:1.25rem; right:2rem; z-index:10;
  width:3.4rem; height:1.9rem; padding:0; border:none; border-radius:1rem;
  background:#bcd7f5; cursor:pointer; box-shadow:inset 0 1px 3px rgba(0,0,0,.18);
  transition:background .2s;
}
#theme-toggle:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
/* La poignée : disque blanc, calé à gauche (état clair par défaut). */
#theme-toggle::before {
  content:""; position:absolute; top:.2rem; left:.2rem;
  width:1.5rem; height:1.5rem; border-radius:50%;
  background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.3);
  transition:left .2s;
}
/* L'icône, centrée sur la poignée, suit son déplacement. */
#theme-toggle::after {
  content:"☀️"; position:absolute; top:0; left:.2rem;
  width:1.5rem; height:1.9rem; display:flex; align-items:center;
  justify-content:center; font-size:.95rem; transition:left .2s;
}
/* --- État SOMBRE : track nuit, poignée + icône à droite, lune. --- */
:root[data-theme="dark"] #theme-toggle { background:#2a2f42; }
:root[data-theme="dark"] #theme-toggle::before { left:calc(100% - 1.7rem); }
:root[data-theme="dark"] #theme-toggle::after  { left:calc(100% - 1.7rem); content:"🌙"; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) #theme-toggle { background:#2a2f42; }
  :root:not([data-theme="light"]) #theme-toggle::before { left:calc(100% - 1.7rem); }
  :root:not([data-theme="light"]) #theme-toggle::after  { left:calc(100% - 1.7rem); content:"🌙"; }
}

/* Sur mobile/tablette portrait, le bouton fixé (position:fixed) à la fenêtre
   chevauchait tout contenu atteignant le coin haut-droit (titre, fil d'Ariane, liens
   de spécifications, listing) et interceptait leurs clics. On le sort du fixed : il
   revient dans le flux, en tête de <body>, en float:right — le fil d'Ariane et le
   contenu s'enroulent donc à sa gauche (au lieu de couler dessous), sans vide au-dessus.
   Étant dans le flux, il défile avec la page (comportement mobile voulu, pas d'élément
   flottant qui gênerait plus bas). position:relative (et non le fixed neutralisé) pour
   que la poignée/icône (::before/::after en absolute) restent calées sur le bouton.
   footer { clear:both } : sur une page courte, le bas du float peut dépasser le contenu ;
   sans clear, le filet du pied de page s'enroulerait autour du bouton au lieu de partir
   pleine largeur. */
@media (max-width:768px) {
  #theme-toggle { position:relative; float:right; top:0; right:0;
                  margin:0 0 .3rem .6rem; }
  footer { clear:both; }
}

@media (max-width:600px) {
  .scroll { overflow-x:auto; }
  h1 { font-size:1.4rem; }
}

/* Listing en « cartes empilées » sur mobile/tablette portrait. Sous ce seuil, le
   tableau à 4 colonnes est illisible : le nom se compresse et le hash MD5 (32 car.,
   non cassable) pousse la page en largeur. On délinéarise donc chaque <tr> en bloc
   vertical — nom en pleine largeur, méta condensée en dessous, MD5 masqué — sans
   toucher au HTML sémantique (table conservée). Au-dessus de 768px : rendu tableau
   d'origine, strictement inchangé. Les td portent un data-label (posé côté HTML par
   listing_table) dont le CSS ci-dessous se sert pour réétiqueter les cellules ; cet
   attribut est invisible tant que ces règles ne s'appliquent pas (donc nul sur desktop). */
@media (max-width:768px) {
  /* Le conteneur .scroll ne sert plus (pas de débordement en mode carte). */
  .scroll { overflow-x:visible; }
  table.listing, .listing tbody, .listing tr, .listing td { display:block; width:100%; }
  /* En-tête de colonnes sans objet en mode carte : retiré du flux mais gardé pour
     les lecteurs d'écran (position hors écran plutôt que display:none). */
  .listing thead { position:absolute; width:1px; height:1px; overflow:hidden;
                   clip:rect(0 0 0 0); white-space:nowrap; }
  .listing tr { padding:.7rem .1rem; }
  .listing tbody tr:hover { background:transparent; }
  /* Ligne 1 — le NOM, pleine largeur, priorité de lecture. La règle générale
     .listing td (border-bottom, padding) est neutralisée cellule par cellule. */
  .listing td { border:0; padding:0; }
  .listing td:first-child { padding-bottom:.3rem; font-size:1rem; }
  /* Cible tactile confortable sur le lien du nom. */
  .listing td:first-child a { display:inline-block; font-weight:500;
                              min-height:1.6rem; padding:.15rem 0; }
  /* Lignes méta — date puis taille (ordre DOM), en petit et muted, sur une même ligne.
     Réétiquetées via data-label ; alignées à gauche, contrairement au tableau. Une
     cellule vide (taille absente d'un dossier) est retirée pour ne pas afficher un
     libellé « Taille : » orphelin. */
  .listing td[data-label] {
    display:inline; font-size:.85rem; color:var(--muted);
    text-align:left; white-space:normal;
  }
  .listing td[data-label]:empty { display:none; }
  .listing td[data-label]::before { content:attr(data-label) " : "; }
  /* Séparateur « · » posé AVANT la taille pour la détacher de la date qui la précède.
     :not(:empty) → pas de séparateur en tête si la taille manque (dossier). */
  .listing td.num:not(:empty)::before {
    content:" · " attr(data-label) " : "; color:var(--muted);
  }
  /* MD5 — coupable n°1 du débordement (hash de 32 car. non cassable). Rarement
     consulté depuis un mobile ; on le masque simplement sous ce seuil. Le hash reste
     présent dans le HTML (accessible sur écran large / au partage), juste non affiché. */
  .listing td.md5 { display:none; }
}
"""

# Script anti-flash : posé dans <head>, il applique le thème mémorisé AVANT le
# rendu du corps (sinon un « flash » de thème apparaîtrait). Sans choix mémorisé,
# on ne pose rien et le CSS suit prefers-color-scheme (préférence OS).
_THEME_INIT = ("<script>try{var t=localStorage.getItem('theme');"
               "if(t)document.documentElement.dataset.theme=t;}catch(e){}</script>")

# Bouton + bascule. Au clic : calcule le thème courant effectif (data-theme, sinon
# la préférence OS), bascule vers l'autre, l'applique et le mémorise. Seul JS de la
# page, inline, sans dépendance.
_THEME_TOGGLE = (
    '<button id="theme-toggle" type="button" aria-label="Basculer le thème clair/sombre"'
    ' title="Basculer le thème clair/sombre"></button>'
    "<script>(function(){var b=document.getElementById('theme-toggle');"
    "b.addEventListener('click',function(){"
    "var r=document.documentElement,cur=r.dataset.theme||"
    "(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'),"
    "next=cur==='dark'?'light':'dark';"
    "r.dataset.theme=next;try{localStorage.setItem('theme',next);}catch(e){}});})();</script>")

# Bouton « Copier » ajouté en haut à droite de chaque bloc de code au chargement.
# Amélioration progressive : sans JS, le code reste sélectionnable, simplement sans
# bouton. Le <pre> est enveloppé d'un .code-wrap positionné (le bouton reste fixé au
# coin même quand le code défile) ; le bouton copie le texte brut du <code> (les spans
# de coloration sont ignorés par textContent). Repli execCommand si clipboard absent.
_CODE_COPY_JS = (
    "<script>(function(){"
    "function copy(txt,btn){var done=function(){btn.classList.add('copied');"
    "setTimeout(function(){btn.classList.remove('copied');},1200);};"
    "if(navigator.clipboard&&navigator.clipboard.writeText){"
    "navigator.clipboard.writeText(txt).then(done,function(){});}"
    "else{var t=document.createElement('textarea');t.value=txt;"
    "t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);"
    "t.focus();t.select();try{document.execCommand('copy');done();}catch(e){}"
    "document.body.removeChild(t);}}"
    "function enhance(){document.querySelectorAll('pre>code').forEach(function(code){"
    "var pre=code.parentNode;"
    "if(pre.parentNode&&pre.parentNode.classList.contains('code-wrap'))return;"
    "var wrap=document.createElement('div');wrap.className='code-wrap';"
    "pre.parentNode.insertBefore(wrap,pre);wrap.appendChild(pre);"
    "var btn=document.createElement('button');btn.type='button';"
    "btn.className='code-copy';btn.title='Copier';"
    "btn.setAttribute('aria-label','Copier le code');"
    "btn.addEventListener('click',function(){copy(code.textContent,btn);});"
    "wrap.appendChild(btn);});}"
    "if(document.readyState!=='loading')enhance();"
    "else document.addEventListener('DOMContentLoaded',enhance);"
    "})();</script>")

_PAGE = Template("""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<link rel="icon" type="image/svg+xml" href="$favicon_href">
<title>$title</title>
$theme_init<link rel="stylesheet" href="$css_href">
</head>
<body>
$theme_toggle
$crumbs<main>
$body
</main>
$footer
$code_copy
</body>
</html>
""")


# --------------------------------------------------------------------------- #
# Assemblage de page + fragments
# --------------------------------------------------------------------------- #

def esc(s) -> str:
    """Échappe une valeur pour insertion dans du HTML (texte ou attribut)."""
    return html.escape(str(s), quote=True)


# Logo GitHub officiel (mark-github d'Octicons, monochrome), en currentColor pour
# suivre la couleur du footer. aria-hidden : décorative, le lien porte l'aria-label.
_GITHUB_ICON = (
    '<svg viewBox="0 0 16 16" width="1.4em" height="1.4em" fill="currentColor"'
    ' aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59'
    '.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23'
    '-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87'
    '.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82'
    '-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0'
    ' 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27'
    '.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2'
    ' 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/></svg>')


def render_footer(footer_md: str, generated: str, repo_url: str = "") -> str:
    """Assemble le <footer> : « Généré le <date>. » (préfixe automatique) suivi du
    texte de pied de page rédigé en Markdown (converti en HTML). Si `repo_url` est
    renseigné, une petite icône GitHub (lien vers le dépôt) est ajoutée, discrète, à
    la fin. `generated` est une date déjà formatée ; elle est échappée, le Markdown
    est converti (texte échappé en interne). Renvoie le bloc <footer>…</footer>."""
    prefix = f"Généré le {esc(generated)}. " if generated else ""
    repo = (f'<a class="repo-link" href="{esc(repo_url)}" target="_blank"'
            f' rel="noopener" aria-label="Code source sur GitHub"'
            f' title="Code source sur GitHub">{_GITHUB_ICON}</a>') if repo_url else ""
    # Le texte est enveloppé pour rester UN seul bloc : sinon, le <footer> en flex
    # traiterait chaque nœud (texte, lien data.geopf.fr, icône) comme un item juxtaposé.
    return (f'<footer><span class="footer-text">{prefix}'
            f'{md_to_html_inline(footer_md)}</span>{repo}</footer>')


def md_to_html_inline(md: str) -> str:
    """Footer sur une seule ligne logique : on convertit le Markdown puis on retire
    l'enrobage <p> (un footer n'est pas un article), en gardant le balisage inline
    (liens, gras…). Import local pour éviter un cycle d'import au chargement."""
    from .markdown import to_html
    html_out = to_html(md).strip()
    # Footer court = un seul paragraphe : on déballe le <p>…</p> englobant.
    if html_out.startswith("<p>") and html_out.endswith("</p>") and html_out.count("<p>") == 1:
        html_out = html_out[3:-4]
    return html_out


STYLESHEET = "style.css"   # nom du CSS partagé, à la racine du site
ROBOTS = "robots.txt"      # fichier robots servi à la racine du site
FAVICON = "favicon.svg"    # icône SVG servie à la racine du site


def write_stylesheet(out_dir: str) -> None:
    """Écrit la feuille de style partagée (une seule fois) à la racine du site.
    Les pages la référencent en relatif — voir write_page. Le CSS reste défini une
    seule fois dans la constante CSS ; on l'externalise ici pour que le navigateur le
    mette en cache au lieu de le recharger inline sur chaque page (gain net sur un
    site de milliers de pages). Toujours servi par le site lui-même : aucune
    dépendance externe."""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, STYLESHEET), "w", encoding="utf-8") as f:
        f.write(CSS)


# robots.txt : les moteurs classiques restent AUTORISÉS à crawler, pour qu'ils lisent
# le « <meta name=robots content=noindex> » posé sur chaque page (c'est lui qui garantit
# la non-indexation). Les crawlers d'IA / d'entraînement, eux, ne désindexent rien : on
# les bloque explicitement — respect volontaire, sans effet sur les bots impolis.
_ROBOTS_TXT = """\
# Crawlers d'IA / entraînement (respect volontaire)
User-agent: GPTBot
User-agent: OAI-SearchBot
User-agent: ChatGPT-User
User-agent: ClaudeBot
User-agent: anthropic-ai
User-agent: Google-Extended
User-agent: CCBot
User-agent: PerplexityBot
User-agent: Bytespider
User-agent: Amazonbot
User-agent: Applebot-Extended
User-agent: Meta-ExternalAgent
Disallow: /

User-agent: *
Disallow:
"""


def write_robots(out_dir: str) -> None:
    """Écrit robots.txt à la racine du site (une seule fois). Voir _ROBOTS_TXT pour la
    stratégie : moteurs autorisés (pour qu'ils voient le noindex), bots IA bloqués."""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, ROBOTS), "w", encoding="utf-8") as f:
        f.write(_ROBOTS_TXT)


# Favicon SVG (servie une fois à la racine, référencée en relatif par chaque page).
# Tuile bleue (accent du site) + flèche de téléchargement blanche : sens direct (c'est
# un index de téléchargement), autonome, lisible en 16 px, neutre (pas le logo IGN).
_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="7" fill="#0b57d0"/>
  <g fill="none" stroke="#ffffff" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
    <path d="M16 7 V19"/>
    <path d="M10.5 14.5 L16 20 L21.5 14.5"/>
    <path d="M8 24.5 H24"/>
  </g>
</svg>
"""


def write_favicon(out_dir: str) -> None:
    """Écrit la favicon SVG à la racine du site (une seule fois)."""
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, FAVICON), "w", encoding="utf-8") as f:
        f.write(_FAVICON_SVG)


def write_page(fs_dir: str, title: str, body: str, *, crumbs: str,
               footer: str, out_dir: str) -> None:
    """Écrit une page. `out_dir` est la racine du site : il sert à calculer le chemin
    relatif vers la feuille de style partagée (profondeur = nb de dossiers entre la
    page et la racine)."""
    os.makedirs(fs_dir, exist_ok=True)
    rel = os.path.relpath(fs_dir, out_dir)     # "." à la racine, "a/b" en profondeur
    depth = 0 if rel == os.curdir else len(rel.split(os.sep))
    css_href = "../" * depth + STYLESHEET
    favicon_href = "../" * depth + FAVICON
    page = _PAGE.substitute(title=esc(title), css_href=css_href,
                            favicon_href=favicon_href, body=body,
                            crumbs=crumbs, footer=footer,
                            theme_init=_THEME_INIT, theme_toggle=_THEME_TOGGLE,
                            code_copy=_CODE_COPY_JS)
    with open(os.path.join(fs_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


def breadcrumb(crumbs: list[tuple[str, int]]) -> str:
    """crumbs : [(label, up)] où `up` = nombre de dossiers à remonter depuis la page
    courante pour atteindre ce crumb (0 = page courante, non cliquable). Les chemins
    relatifs sont ainsi corrects à toute profondeur."""
    parts = []
    for label, up in crumbs:
        if up > 0:
            parts.append(f'<a href="{"../" * up}">{esc(label)}</a>')
        else:
            parts.append(f'<span aria-current="page">{esc(label)}</span>')
    return '<nav class="crumbs" aria-label="Fil d\'Ariane">' + " / ".join(parts) + "</nav>"


def listing_table(rows: list[dict]) -> str:
    """rows : dicts {name, href, is_dir, date, size, md5}. Le tri éventuel est fait
    en amont. Rendu en tableau sur écran large ; sous 768px, le CSS délinéarise les
    lignes en « cartes empilées » (nom pleine largeur, méta condensée, MD5 masqué).
    Les data-label des cellules date/taille servent à ce mode carte (réétiquetage via
    CSS pour recréer les libellés de colonne) et sont inertes sur desktop."""
    trs = []
    for r in rows:
        cls = ' class="dir"' if r["is_dir"] else ""
        name = f'<a href="{esc(r["href"])}"{cls}>{esc(r["name"])}</a>'
        size = "" if r["is_dir"] else human_size(r.get("size"))
        md5 = f'<code>{esc(r["md5"])}</code>' if r.get("md5") else ""
        trs.append(
            f"<tr><td>{name}</td>"
            f'<td data-label="Modifié le">{esc(fmt_date(r.get("date")))}</td>'
            f'<td class="num" data-label="Taille">{size}</td>'
            f'<td class="md5">{md5}</td></tr>')
    return (
        '<div class="scroll"><table class="listing">'
        "<thead><tr><th>Nom</th><th>Modifié le</th><th>Taille</th><th>MD5</th></tr></thead>"
        f'<tbody>{"".join(trs)}</tbody></table></div>')


def nav_table(rows: list[dict]) -> str:
    """Listing de NAVIGATION : les niveaux de groupement (zone, date, radiométrie).
    Chaque ligne est un sous-dossier décrit non par la taille/MD5 d'un fichier —
    absents à ces niveaux — mais par les FORMATS disponibles en dessous et la TAILLE
    agrégée de ses fichiers (déjà connues du crawl, cf. crawl._group_formats /
    _group_bytes). Objet distinct de listing_table : on ne liste pas des fichiers à
    télécharger mais des dossiers où descendre.

    rows : dicts {name, href, date (str|None), formats (list[str]|None), size (int|None)}.
    Les colonnes « Modifié le », « Formats disponibles » et « Taille » n'apparaissent
    que si au moins une ligne les renseigne : ainsi la page de format (où la ligne EST
    le format) n'affiche pas de colonne formats redondante, et les pages zone/date (sans
    date) restent à trois colonnes. Réutilise table.listing — mêmes styles et même
    bascule « cartes empilées » sous 768px, via les data-label des cellules."""
    show_date = any(r.get("date") for r in rows)
    show_formats = any(r.get("formats") for r in rows)
    show_size = any(r.get("size") is not None for r in rows)
    head = ["<th>Nom</th>"]
    if show_date:
        head.append("<th>Modifié le</th>")
    if show_formats:
        head.append("<th>Formats disponibles</th>")
    if show_size:
        head.append("<th>Taille</th>")
    trs = []
    for r in rows:
        # class="dir" : mêmes repères visuels (📁 + « / ») que les dossiers du listing.
        cells = [f'<td><a href="{esc(r["href"])}" class="dir">{esc(r["name"])}</a></td>']
        if show_date:
            cells.append(f'<td data-label="Modifié le">{esc(fmt_date(r.get("date")))}</td>')
        if show_formats:
            fmts = ", ".join(esc(f) for f in (r.get("formats") or []))
            cells.append(f'<td class="formats" data-label="Formats disponibles">{fmts}</td>')
        if show_size:
            size = human_size(r["size"]) if r.get("size") is not None else ""
            cells.append(f'<td class="num" data-label="Taille">{size}</td>')
        trs.append(f"<tr>{''.join(cells)}</tr>")
    return (
        '<div class="scroll"><table class="listing">'
        f'<thead><tr>{"".join(head)}</tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table></div>')


# Emoji préfixant chaque lien de spécification, choisi par le champ « type » de la
# spec (déclaré dans le catalogue). Type absent → document par défaut 📄 ; type
# inconnu → 📄 aussi, mais signalé au build (typo probable).
SPEC_ICONS = {
    "contenu": "📄",      # descriptif de contenu
    "livraison": "📦",    # descriptif de livraison
    "fiche": "📋",        # fiche produit / présentation
    "guide": "📖",        # guide d'utilisation
    "tutoriel": "🧪",     # tutoriel technique
    "interface": "🖱️",    # interface interactive de téléchargement
    "carte": "🗺️",        # carte / emprise
    "explorateur": "🧭",   # explorateur interactif du produit (ex. BD TOPO Explorer)
}
_SPEC_ICON_DEFAULT = "📄"


def _spec_icon(spec: dict) -> str:
    """Emoji d'une spec d'après son champ « type ». Type vide → défaut 📄 (silencieux).
    Type renseigné mais inconnu → défaut 📄 + avertissement (typo probable)."""
    t = spec.get("type") or ""
    if not t:
        return _SPEC_ICON_DEFAULT
    if t not in SPEC_ICONS:
        log(f"  ! type de spec inconnu « {t} » (label : {spec.get('label', '')!r})")
        return _SPEC_ICON_DEFAULT
    return SPEC_ICONS[t]


def product_header(product) -> str:
    """En-tête d'une fiche produit : titre, éventuel bandeau « produit arrêté »,
    résumé, liens de spécification. Un produit arrêté reste accessible par son URL
    même quand sa carte est masquée : le bandeau lève toute ambiguïté sur son statut
    (le motif — remplacement, etc. — est repris du champ `update` s'il est renseigné)."""
    out = [f"<h1>{esc(product.title or product.id)}</h1>"]
    if getattr(product, "retired", False):
        motif = f" — {esc(product.update)}" if product.update else ""
        out.append('<p class="retired-banner" role="note"><strong>Produit '
                   f"arrêté</strong> : ce jeu de données n'est plus mis à "
                   f"jour{motif}.</p>")
    if product.summary:
        out.append(f'<p class="lead">{esc(product.summary)}</p>')
    if product.specs:
        items = "".join(
            f'<li><a href="{esc(s["url"])}" target="_blank" rel="noopener">'
            f'<span class="spec-icon" aria-hidden="true">{_spec_icon(s)}</span> '
            f'{esc(s["label"])}</a></li>'
            for s in product.specs)
        out.append(f'<h2>Spécifications</h2><ul class="specs">{items}</ul>')
    return "".join(out)


# Copie presse-papiers des boutons « Copier » de l'encart cloud-native, par
# délégation d'événement (un seul écouteur pour tous les boutons). Inline, sans
# dépendance ; posé avec l'encart, donc seulement sur les fiches concernées.
_CLOUD_COPY_JS = (
    "<script>document.addEventListener('click',function(e){"
    "var b=e.target.closest('.cloud-copy');if(!b)return;e.preventDefault();"
    "var u=b.getAttribute('data-url'),done=function(){"
    "var o=b.textContent;b.textContent='Copié';"
    "setTimeout(function(){b.textContent=o;},1200);};"
    "if(navigator.clipboard&&navigator.clipboard.writeText){"
    "navigator.clipboard.writeText(u).then(done,function(){});}"
    "else{var t=document.createElement('textarea');t.value=u;"
    "t.style.position='fixed';t.style.opacity='0';document.body.appendChild(t);"
    "t.focus();t.select();try{document.execCommand('copy');done();}catch(x){}"
    "document.body.removeChild(t);}});</script>")


def _cloud_tabs(intro: str, tabs: list[tuple[str, str]] | None) -> str:
    """Onglets de tutos, 100% CSS : radios cachés (le 1er coché) + labels servant de
    boutons, puis un panneau par onglet (affiché via le sélecteur CSS sur :checked).
    `tabs` : [(libellé, HTML du panneau)] (cf. gpf.markdown.split_sections) ; `intro` :
    HTML d'intro optionnel au-dessus. Renvoie « » s'il n'y a aucun onglet. Le libellé est
    échappé ; les corps sont déjà du HTML sûr (issus de to_html)."""
    if not tabs:
        return ""
    controls, panels = [], []
    for i, (label, body) in enumerate(tabs):
        checked = " checked" if i == 0 else ""
        controls.append(
            f'<input type="radio" name="cloud-tuto" id="cloud-tab-{i}"'
            f' class="cloud-tab-radio"{checked}>'
            f'<label for="cloud-tab-{i}" class="cloud-tab-label">{esc(label)}</label>')
        panels.append(f'<div class="cloud-tab-panel">{body}</div>')
    intro_html = f'<div class="cloud-tuto-intro">{intro}</div>' if intro else ""
    tabs_html = ('<div class="cloud-tabs">' + "".join(controls)
                 + '<div class="cloud-tab-panels">' + "".join(panels) + "</div></div>")
    # Repliable (replié par défaut), au même niveau que « Couches disponibles ». Les
    # onglets CSS restent internes à .cloud-tabs : le <details> ne perturbe pas leurs
    # sélecteurs (~ / :checked entre frères de .cloud-tabs).
    return ('<details class="cloud-tuto"><summary>Comment interroger ces couches&nbsp;?'
            '</summary><div class="cloud-tuto-body">' + intro_html + tabs_html
            + "</div></details>")


def cloud_block(layers: dict, *, help_url: str = "", tuto_intro: str = "",
                tuto_tabs: list[tuple[str, str]] | None = None) -> str:
    """Encart « accès direct pour l'analyse » d'une fiche produit : replié par défaut
    (<details>), inséré en HAUT de fiche (au-dessus de l'arbre de téléchargement, qui
    reste inchangé). Annonce les formats cloud-native (GeoParquet, FlatGeoBuf), montre
    les tutos en onglets, puis déplie la liste des couches avec, par format, un bouton
    copiant l'URL du fichier (jamais un lien : ces fichiers pèsent souvent plusieurs Gio
    et se copient pour être interrogés à distance, pas cliqués). `layers` : structure de
    cloud.fetch_product_layers. `help_url` : lien optionnel vers des tutoriels externes.
    `tuto_intro`/`tuto_tabs` : tutos (tutos/<produit>.md découpé par
    gpf.markdown.split_sections), rendus en ONGLETS CSS au-dessus des couches ; omis si
    `tuto_tabs` est vide. Renvoie « » si `layers` est vide (rien à montrer)."""
    if not layers or not layers.get("formats") or not layers.get("couches"):
        return ""
    fmt_labels = [f["label"] for f in layers["formats"]]

    # Ligne méta : formats · emprise (si uniforme) · un fichier par couche · édition.
    meta = [", ".join(esc(l) for l in fmt_labels)]
    if layers.get("zone_label"):
        meta.append(esc(layers["zone_label"]))
    meta.append("un fichier par couche")
    if layers.get("edition"):
        meta.append("dernière édition " + esc(layers["edition"]))

    # Tableau couches × formats. Chaque cellule de format : bouton « Copier » (data-url)
    # ou « — » si la couche n'existe pas dans ce format. data-label = format : sert de
    # libellé de colonne en mode « cartes » (mobile), où l'en-tête est masqué.
    head = "<th>Couche</th>" + "".join(f"<th>{esc(l)}</th>" for l in fmt_labels)
    trs = []
    for c in layers["couches"]:
        cells = [f'<td>{esc(c["name"])}</td>']
        for l in fmt_labels:
            url = c["urls"].get(l)
            if url:
                cells.append(
                    f'<td data-label="{esc(l)}"><button type="button"'
                    f' class="cloud-copy" data-url="{esc(url)}"'
                    f' title="Copier l\'URL {esc(l)}">Copier</button></td>')
            else:
                cells.append(f'<td class="cloud-none" data-label="{esc(l)}">—</td>')
        trs.append(f"<tr>{''.join(cells)}</tr>")
    table = ('<div class="scroll"><table class="listing cloud-layers">'
             f'<thead><tr>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>')

    # « Comment s'en servir » : phrase courte (braces littérales → PAS d'f-string) +
    # lien optionnel vers les tutoriels (le « super tuto » vit hors de la fiche).
    how = ('<p class="cloud-how">Interrogez la donnée à distance avec DuckDB, GDAL '
           "ou Pyarrow : seuls les objets que vous filtrez (par emprise ou par attribut) "
           "sont rapatriés, jamais le fichier entier. "
           "Données disponibles uniquement sur le <a href=\"https://cartes.gouv.fr/aide/fr/partenaires/ign/generalites-ign/actualites/2026-06-flatgeobuf-geoparquet/\" target=\"_blank\" rel=\"noopener\">service de téléchargement partiel</a>.")
    if help_url:
        how += (f' <a href="{esc(help_url)}" target="_blank" rel="noopener">'
                "exemples et tutoriels</a>.")
    how += "</p>"

    n = len(layers["couches"])
    tuto = _cloud_tabs(tuto_intro, tuto_tabs)
    return (
        '<details class="cloud-dt">'
        '<summary><span class="cloud-bolt" aria-hidden="true">⚡</span>'
        '<span class="cloud-sum"><strong>Accès direct pour l\'analyse</strong> : '
        "interroger la donnée à distance, sans tout télécharger</span>"
        '<span class="cloud-tag">Cloud-native</span>'
        '<span class="cloud-disclose" aria-hidden="true"></span></summary>'
        '<div class="cloud-body">'
        f'<p class="cloud-meta">{" · ".join(meta)}</p>'
        f"{how}"
        f"{tuto}"
        f'<details class="cloud-couches"><summary>Couches disponibles ({n})</summary>'
        f"{table}</details>"
        "</div>"
        f"{_CLOUD_COPY_JS}"
        "</details>")


def _producer_badge(producers: list[dict] | None) -> str:
    """Badge producteur(s) d'une carte : pour chaque producteur, son logo (<img>)
    s'il en a un, sinon son nom en texte. Plusieurs producteurs (coédition) sont
    juxtaposés dans l'ordre déclaré. Vide si la carte n'en a aucun. Chaque
    `producer` = {name, logo}, logo déjà résolu en chemin relatif (ou vide)."""
    if not producers:
        return ""
    parts = []
    for p in producers:
        name = esc(p["name"])
        if p.get("logo"):
            parts.append(f'<img src="{esc(p["logo"])}" alt="{name}" loading="lazy">')
        else:
            parts.append(f"<span>{name}</span>")
    return f'<span class="producer">{"".join(parts)}</span>'


def _card_grid(cards: list[dict]) -> str:
    """Grille <ul.grid> de cartes produit
    {href, title, summary, update, retired, producers}. Un badge « Arrêté » et un
    fond distinct signalent les produits arrêtés (`retired`) ; leur <li> porte la
    classe `retired`. Puis en-tête flex (titre + badge producteur(s)), résumé, et
    ligne méta « Mise à jour »."""
    items = []
    for c in cards:
        retired = c.get("retired", False)
        li_cls = ' class="retired"' if retired else ""
        a_cls = "card card--retired" if retired else "card"
        flag = '<span class="retired-flag">Arrêté</span>' if retired else ""
        head = ('<span class="card-head">'
                + f'<strong>{esc(c["title"])}</strong>'
                + _producer_badge(c.get("producers"))
                + "</span>")
        # Badge « Cloud-native » : produit interrogeable à distance (cf. cloud_block).
        # Nomme la CAPACITÉ, pas un format (GeoParquet/FlatGeoBuf), pour ne pas en
        # privilégier un. Posé sous l'en-tête, avant le résumé. `title` = infobulle
        # native au survol (courte explication, sans JS).
        cloud = ('<span class="cloud-badge" title="Interrogeable à distance '
                 '(GeoParquet, FlatGeoBuf), sans tout télécharger">⚡ Cloud-native</span>'
                 if c.get("cloud_native") else "")
        summary = (f'<span class="summary">{esc(c["summary"])}</span>'
                   if c["summary"] else "")
        update = (f'<span class="update">Mise à jour&nbsp;: {esc(c["update"])}</span>'
                  if c.get("update") else "")
        items.append(f'<li{li_cls}><a class="{a_cls}" href="{esc(c["href"])}">'
                     + flag + head + cloud + summary + update + "</a></li>")
    return f'<ul class="grid">{"".join(items)}</ul>'


def home_body(sections: list[dict], *, site_title: str, intro: str,
              help_url: str, help_text: str = "", help_link_label: str = "") -> str:
    """sections : [{id, label, href, cards:[{href, title, summary}]}] déjà ordonnées.
    Le titre de chaque thème renvoie vers sa page (`href`). `intro` est le chapô
    éditorial de l'accueil (texte, échappé ici) ; omis s'il est vide. Le bloc d'aide
    (`help_text` + lien `help_link_label` → `help_url`) est omis si `help_text` est
    vide."""
    out = [f"<h1>{esc(site_title)}</h1>"]
    if intro:
        out.append(f'<p class="lead">{esc(intro)}</p>')
    # Sommaire de thèmes : liens #ancre vers chaque section de CETTE page (les <h2>
    # portent déjà l'id du thème). Distinct du titre de section, qui mène à la page thème.
    if len(sections) > 1:
        links = "".join(f'<a href="#{esc(sec["id"])}">{esc(sec["label"])}</a>'
                         for sec in sections)
        out.append(f'<nav class="theme-nav" aria-label="Thèmes">{links}</nav>')
    for sec in sections:
        out.append(
            f'<section class="theme"><h2 id="{esc(sec["id"])}">'
            f'<a href="{esc(sec["href"])}">{esc(sec["label"])}</a></h2>'
            f'{_card_grid(sec["cards"])}</section>')
    if help_text:
        link = (f' <a href="{esc(help_url)}">{esc(help_link_label)}</a>'
                if help_link_label else "")
        out.append(f'<hr><p class="meta">{esc(help_text)}{link}.</p>')
    return "".join(out)


def theme_body(label: str, cards: list[dict]) -> str:
    """Page d'un thème : ses produits en grille (utile en arrivée par URL directe)."""
    return f"<h1>{esc(label)}</h1>{_card_grid(cards)}"


def unavailable_body(feed_url: str) -> str:
    """Corps de secours quand un feed est temporairement inaccessible au build."""
    return ('<p>Contenu temporairement indisponible lors de la dernière '
            f'génération. Source&nbsp;: <a href="{esc(feed_url)}" target="_blank" '
            f'rel="noopener">{esc(feed_url)}</a>.</p>')


def oversized_body(feed_url: str, total: int) -> str:
    """Corps pour un dossier trop volumineux pour être déplié (garde-fou)."""
    return (f"<p>Cette ressource contient <strong>{total}</strong> entrées : trop "
            "volumineuse pour être dépliée ici. Consultez-la directement via son "
            f'<a href="{esc(feed_url)}" target="_blank" rel="noopener">flux de '
            f'téléchargement</a>.</p>')
