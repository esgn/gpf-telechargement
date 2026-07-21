"""Mini-convertisseur Markdown → HTML, volontairement minimal et sans dépendance.

Ne vise PAS la conformité CommonMark : juste le sous-ensemble utile pour rédiger
des pages éditoriales de produit. Couvre :
  - titres         # / ## / ###            → <h1>/<h2>/<h3>
  - séparateur     ---                      → <hr>
  - listes         lignes « - » / « * »     → <ul><li>
  - paragraphes    blocs de texte           → <p>
  - inline         **gras**, *italique*,
                   `code`, [texte](url)     → <strong>/<em>/<code>/<a>
  - bloc de code   ```…``` (clôturé)         → <pre><code> (rendu verbatim)

Hors périmètre (assumé) : tableaux, listes numérotées ou imbriquées, images, HTML
brut, blockquotes. Tout le texte est échappé (html.escape) AVANT d'insérer le
balisage, donc une page Markdown ne peut pas injecter de HTML.
Les liens externes (http/https) ouvrent dans un nouvel onglet (rel=noopener), comme
le reste du site.
"""

from __future__ import annotations

import html
import re

# Inline, appliqués sur du texte DÉJÀ échappé. Le contenu des spans `code` doit
# rester littéral : appliquer les regex en séquence ne suffit PAS (les passes
# gras/italique/lien re-parcourent la chaîne entière, code compris). On extrait donc
# d'abord le code sous forme de marqueurs, puis on le restaure à la fin (cf. _inline).
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
# Marqueur temporaire d'un span code : \x00 ne peut apparaître dans le texte source
# (déjà passé par html.escape) ni être produit par les autres regex → sûr.
_CODE_MARK = re.compile("\x00(\\d+)\x00")


def _link_sub(m: re.Match) -> str:
    text, url = m.group(1), m.group(2)
    # url est déjà échappé (esc en amont) ; les liens externes s'ouvrent à côté.
    ext = ' target="_blank" rel="noopener"' if url.startswith(("http://", "https://")) else ""
    return f'<a href="{url}"{ext}>{text}</a>'


def _inline(text: str) -> str:
    """Applique le balisage inline à un fragment de texte déjà échappé HTML. Le
    contenu des spans `code` est mis de côté avant les autres passes puis restauré
    tel quel, pour qu'un `*`, `**` ou `[...]()` à l'intérieur ne soit pas réinterprété."""
    codes: list[str] = []

    def _stash(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE.sub(_stash, text)
    text = _LINK.sub(_link_sub, text)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", text)
    text = _ITALIC.sub(lambda m: f"<em>{m.group(1)}</em>", text)
    return _CODE_MARK.sub(lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)


# Ligne de commentaire d'un bloc de code : début « # » (Python, shell, YAML…) ou
# « -- » (SQL). Heuristique volontairement simple (pas de lexer par langage) : elle
# couvre les tutos et suffit tant qu'un bloc n'est pas dans un langage où « # »/« -- »
# n'introduit pas un commentaire. Un flag « -spat » (un seul tiret) n'est PAS pris.
_CODE_COMMENT = re.compile(r"^\s*(#|--)")


def _highlight_code(lines: list[str]) -> str:
    """Assemble les lignes (déjà échappées) d'un bloc de code, en enveloppant les lignes
    de COMMENTAIRE dans <span class="tok-comment"> (colorées par le CSS). Le reste est
    laissé tel quel. Aucune coloration syntaxique au-delà des commentaires."""
    return "\n".join(f'<span class="tok-comment">{ln}</span>'
                     if _CODE_COMMENT.match(ln) else ln
                     for ln in lines)


def to_html(md: str) -> str:
    """Convertit une chaîne Markdown (sous-ensemble) en HTML. Le texte est échappé
    avant balisage : le rendu ne peut pas contenir de HTML non voulu."""
    lines = html.escape(md, quote=False).splitlines()
    out: list[str] = []
    para: list[str] = []          # lignes du paragraphe courant
    list_items: list[str] = []    # items de liste courants
    in_code = False               # dans un bloc de code clôturé (```) ?
    code_lines: list[str] = []    # lignes du bloc de code courant, verbatim

    def flush_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def flush_list():
        if list_items:
            lis = "".join(f"<li>{_inline(it)}</li>" for it in list_items)
            out.append(f"<ul>{lis}</ul>")
            list_items.clear()

    for raw in lines:
        # Bloc de code clôturé : rendu VERBATIM (ni inline, ni jointure de lignes) ;
        # une 2ᵉ ligne ``` le ferme. Le contenu est déjà échappé (html.escape en amont).
        if in_code:
            if raw.strip().startswith("```"):
                out.append("<pre><code>" + _highlight_code(code_lines) + "</code></pre>")
                code_lines.clear()
                in_code = False
            else:
                code_lines.append(raw)
            continue

        line = raw.rstrip()
        stripped = line.strip()

        if not stripped:                          # ligne vide : ferme les blocs
            flush_para()
            flush_list()
            continue

        if stripped.startswith("```"):            # ``` → ouverture d'un bloc de code
            flush_para()
            flush_list()
            in_code = True
            continue

        if re.fullmatch(r"-{3,}", stripped):      # --- → séparateur
            flush_para()
            flush_list()
            out.append("<hr>")
            continue

        h = re.match(r"(#{1,3})\s+(.*)", stripped)  # titres
        if h:
            flush_para()
            flush_list()
            level = len(h.group(1))
            out.append(f"<h{level}>{_inline(h.group(2).strip())}</h{level}>")
            continue

        item = re.match(r"[-*]\s+(.*)", stripped)   # item de liste
        if item:
            flush_para()
            list_items.append(item.group(1).strip())
            continue

        # sinon : ligne de paragraphe (une liste en cours est close)
        flush_list()
        para.append(stripped)

    if in_code:      # bloc de code non refermé en fin de source : on le clôt proprement
        out.append("<pre><code>" + "\n".join(code_lines) + "</code></pre>")
    flush_para()
    flush_list()
    return "\n".join(out)


_SECTION_H2 = re.compile(r"^##\s+(.+)$")


def split_sections(md: str) -> tuple[str, list[tuple[str, str]]]:
    """Découpe un Markdown en sections de titre « ## », pour un affichage en onglets.
    Renvoie (intro_html, [(titre, corps_html), …]) : `intro_html` est tout ce qui précède
    le premier « ## » (converti par to_html, « » si rien) ; puis une entrée par section,
    son titre en texte et son corps converti. Un « ## » situé DANS un bloc de code
    (``` … ```) n'est pas un séparateur. Fonction pure."""
    intro: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    in_code = False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            (sections[-1][1] if sections else intro).append(line)
            continue
        m = None if in_code else _SECTION_H2.match(s)
        if m:
            sections.append((m.group(1).strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            intro.append(line)
    return (to_html("\n".join(intro)).strip(),
            [(title, to_html("\n".join(body))) for title, body in sections])
