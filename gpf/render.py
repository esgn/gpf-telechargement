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
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#14171c; --fg:#e6e8eb; --muted:#98a2b3; --border:#2a2f37;
    --link:#8ab4ff; --row:#1a1e24; --code:#20252d; --accent:#8ab4ff;
    --card:#191d23; --shadow:none;
    --retired-card:#221e15; --retired-border:#3a3320; --retired-badge:#d9bd74;
  }
}
:root[data-theme="dark"] {
  --bg:#14171c; --fg:#e6e8eb; --muted:#98a2b3; --border:#2a2f37;
  --link:#8ab4ff; --row:#1a1e24; --code:#20252d; --accent:#8ab4ff;
  --card:#191d23; --shadow:none;
  --retired-card:#221e15; --retired-border:#3a3320; --retired-badge:#d9bd74;
}
* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
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
.listing th, .listing td { padding:.5rem .6rem; border-bottom:1px solid var(--border);
                           text-align:left; vertical-align:top; }
.listing th { color:var(--muted); font-weight:600; white-space:nowrap; }
.listing tbody tr:hover { background:var(--row); }
.listing td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
/* MD5 : hash de 32 car. gardé sur une seule ligne (jamais cassé). Le nom de
   fichier absorbe la contrainte de largeur et se coupe proprement (aux séparateurs
   _ - . via overflow-wrap:anywhere, plutôt qu'en plein milieu d'un mot). */
.listing td.md5 code { color:var(--muted); white-space:nowrap; }
.listing td:first-child a { overflow-wrap:anywhere; }
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
                            theme_init=_THEME_INIT, theme_toggle=_THEME_TOGGLE)
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
        summary = (f'<span class="summary">{esc(c["summary"])}</span>'
                   if c["summary"] else "")
        update = (f'<span class="update">Mise à jour&nbsp;: {esc(c["update"])}</span>'
                  if c.get("update") else "")
        items.append(f'<li{li_cls}><a class="{a_cls}" href="{esc(c["href"])}">'
                     + flag + head + summary + update + "</a></li>")
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
