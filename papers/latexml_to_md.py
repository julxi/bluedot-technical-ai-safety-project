"""Convert an arXiv LaTeXML HTML rendering to GitHub Markdown (pandoc not available).

Usage: python3 -I latexml_to_md.py <paper.html> <out.md>
Handles: headings, paragraphs, inline/display math (from the TeX annotation),
tables (GFM), text-box figures (blockquotes), itemize lists, bibliography.
Fails loudly on any element class it does not know how to handle at block level.
"""

import re
import sys
from pathlib import Path

import bs4

WS = re.compile(r"\s+")


def classes(t):
    return t.get("class") or []


def tex_of(math):
    ann = math.find("annotation", attrs={"encoding": "application/x-tex"})
    assert ann is not None, f"math without TeX annotation: {math.get('id')}"
    tex = WS.sub(" ", ann.get_text()).strip()
    tex = tex.replace("\\displaystyle ", "").replace("\\displaystyle", "")
    return tex


def inline(node):
    """Render a node's content as one line of inline Markdown."""
    if isinstance(node, bs4.NavigableString):
        if isinstance(node, bs4.Comment):
            return ""
        return WS.sub(" ", str(node))
    name = node.name
    cl = classes(node)
    if name == "math":
        return f"${tex_of(node)}$"
    if name in ("svg",):
        raise AssertionError(f"svg in inline context: {node.get('id')}")
    if "ltx_rule" in cl:
        return ""
    if "ltx_itemize" in cl:
        assert node.find_parent("td") is not None, (
            f"list in inline context outside a table cell: {node.get('id')}"
        )
        items = node.find_all(class_="ltx_item", recursive=False)
        assert items, f"empty list {node.get('id')}"
        rendered = []
        for it in items:
            body = "".join(
                inline(c)
                for c in it.children
                if not (isinstance(c, bs4.Tag) and "ltx_tag_item" in classes(c))
            )
            rendered.append("• " + WS.sub(" ", body).strip())
        print(f"list {node.get('id')} in table cell rendered inline with <br>", file=sys.stderr)
        return " <br>" + "<br>".join(rendered) + "<br>"
    inner = "".join(inline(c) for c in node.children)
    if name == "br":
        return " "
    bold = "ltx_font_bold" in cl or name in ("b", "strong")
    ital = "ltx_font_italic" in cl or name in ("i", "em")
    mono = "ltx_font_typewriter" in cl
    if (bold or ital or mono) and inner.strip():
        lead = inner[: len(inner) - len(inner.lstrip())]
        trail = inner[len(inner.rstrip()) :]
        core = inner.strip()
        if mono:
            core = f"`{core}`"
        if ital:
            core = f"*{core}*"
        if bold:
            core = f"**{core}**"
        inner = lead + core + trail
    return inner


def line(node):
    return WS.sub(" ", inline(node)).strip()


def table_md(tab):
    rows = []
    for tr in tab.find_all("tr"):
        cells = []
        for td in tr.find_all(["td", "th"], recursive=False):
            span = int(td.get("colspan", 1))
            txt = line(td).replace("|", "\\|")
            cells.append(txt)
            cells.extend([""] * (span - 1))
        rows.append(cells)
    assert rows, f"empty table {tab.get('id')}"
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def eqn_rows(tab):
    out = []
    for tr in tab.find_all("tr", class_="ltx_equation"):
        maths = [tex_of(m) for m in tr.find_all("math")]
        assert maths, f"equation row without math: {tr.get('id')}"
        tag = tr.find("span", class_="ltx_tag_equation")
        tex = " ".join(maths)
        if tag is not None:
            tex += f" \\qquad {line(tag)}"
        out.append(f"$$\n{tex}\n$$")
    return out


def figure_box(fig):
    """Text-box figure (svg with foreignobject): render its content as a blockquote."""
    content = fig.find("span", class_="ltx_foreignobject_content")
    assert content is not None, f"figure without text box: {fig.get('id')}"
    lines = []
    for el in content.find_all(["span"], recursive=True):
        cl = classes(el)
        if "ltx_p" in cl and not el.find_parent("span", class_="ltx_item"):
            lines.append(line(el))
        elif "ltx_item" in cl:
            body = "".join(
                inline(c)
                for c in el.children
                if not (isinstance(c, bs4.Tag) and "ltx_tag_item" in classes(c))
            )
            lines.append("- " + WS.sub(" ", body).strip())
    lines = [ln for ln in lines if ln]
    assert lines, f"figure box produced no text: {fig.get('id')}"
    return "\n>\n".join("> " + ln for ln in lines)


HEADING = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}
PASS = {
    "ltx_para",
    "ltx_logical-block",
    "ltx_flex_figure",
    "ltx_flex_cell",
    "ltx_section",
    "ltx_subsection",
    "ltx_subsubsection",
    "ltx_appendix",
    "ltx_abstract",
    "ltx_bibliography",
}


def blocks(node, out):
    for c in node.children:
        if isinstance(c, bs4.NavigableString):
            assert not str(c).strip() or isinstance(c, bs4.Comment), f"stray text: {str(c)[:80]!r}"
            continue
        cl = classes(c)
        if c.name in HEADING and "ltx_title" in cl:
            out.append(f"{HEADING[c.name]} {line(c)}")
        elif "ltx_authors" in cl:
            out.append("    ".join(line(p) for p in c.find_all(class_="ltx_personname")))
        elif "ltx_pagination" in cl or "ltx_rule" in cl:
            continue
        elif (
            c.name == "table"
            and "ltx_tabular" in cl
            and not c.get_text(strip=True)
            and not c.find("math")
        ):
            print(f"skipped empty layout table {c.get('id')}", file=sys.stderr)
            continue
        elif c.name == "table" and "ltx_tabular" in cl:
            out.append(table_md(c))
        elif c.name == "p" or "ltx_p" in cl:
            t = line(c)
            if t:
                out.append(t)
        elif "ltx_equationgroup" in cl or "ltx_equation" in cl:
            out.extend(eqn_rows(c))
        elif c.name == "figure" and "ltx_table" in cl:
            cap = c.find("figcaption")
            tabs = c.find_all("table", class_="ltx_tabular")
            assert cap is not None and len(tabs) >= 1, (
                f"table figure {c.get('id')}: {len(tabs)} tables"
            )
            assert not any(t.find_parent("table") for t in tabs), f"nested table in {c.get('id')}"
            if len(tabs) > 1:
                print(
                    f"{c.get('id')}: {len(tabs)} side-by-side panels, emitted in sequence",
                    file=sys.stderr,
                )
            out.append(line(cap))
            out.extend(table_md(t) for t in tabs)
        elif c.name == "figure" and "ltx_figure" in cl:
            cap = c.find("figcaption")
            assert cap is not None
            out.append(figure_box(c))
            out.append(line(cap))
        elif c.name == "ul" and "ltx_biblist" in cl:
            for li in c.find_all("li", class_="ltx_bibitem"):
                parts = []
                for ch in li.children:
                    if isinstance(ch, bs4.Tag) and "ltx_bib_cited" in classes(ch):
                        continue  # "Cited by: §1" back-references
                    parts.append(inline(ch))
                    if isinstance(ch, bs4.Tag) and "ltx_tag_bibitem" in classes(ch):
                        parts.append(" ")
                out.append("- " + WS.sub(" ", "".join(parts)).strip())
        elif c.name in ("ul", "ol") or "ltx_itemize" in cl or "ltx_enumerate" in cl:
            for li in c.find_all(["li"], recursive=False):
                out.append("- " + line(li))
        elif c.name in ("section", "div") and (set(cl) & PASS):
            blocks(c, out)
        else:
            raise AssertionError(f"unhandled block element <{c.name} class={cl} id={c.get('id')}>")


def main():
    src, dst = sys.argv[1], sys.argv[2]
    soup = bs4.BeautifulSoup(Path(src).read_text(encoding="utf-8"), "html.parser")
    arts = soup.find_all("article")
    assert len(arts) == 1, len(arts)
    n_ext = 0
    for a in arts[0].find_all("a", class_="ltx_bib_external"):
        href = a.get("href")
        assert href and href.startswith("http"), f"bad external link {a}"
        a.string = href
        n_ext += 1
    print(f"replaced {n_ext} bibliography link labels with their URLs", file=sys.stderr)
    for a in arts[0].find_all(["cite", "a"]):
        a.unwrap()
    out = []
    blocks(arts[0], out)
    text = "\n\n".join(out) + "\n"
    Path(dst).write_text(text, encoding="utf-8")
    print(f"wrote {dst}: {len(out)} blocks, {len(text)} chars")


main()
