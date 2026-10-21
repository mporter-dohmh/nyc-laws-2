"""Convert AmLegal XML files to Markdown.

Usage: python scripts/xml_to_md.py OUT_DIR SRC_DIR [SRC_DIR ...]

Each SRC_DIR/<path>/<name>.xml is written to OUT_DIR/SRC_DIR/<path>/<name>.md.
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Tag names AmLegal may use for tables; matched case-insensitively.
TABLE_TAGS = {"table"}
ROW_TAGS = {"tr", "row"}
CELL_TAGS = {"td", "th", "cell", "entry", "col"}
# Elements whose text is dropped: supplement markers such as "[ALP S-015]".
SKIP_TAGS = {"highlighter"}
# Source notes such as "(Added City Record 6/23/2017, eff. 7/23/2017)".
HISTORY_RE = re.compile(
    r"^\((Added|Amended|Repealed|Renumbered|Formerly)\b.*\)$", re.I)

SECTION_RE = re.compile(r"^§+\s*(\S+?)\.?\s+(.*?)\.?$")
TITLE_RE = re.compile(r"^T(\d+)C", re.I)


def local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def raw_text(el, linebreak):
    parts = [el.text or ""]
    for child in el:
        name = local(child.tag)
        if name == "tab":
            parts.append(" ")
        elif name == "linebrk":
            parts.append(linebreak)
        elif name not in TABLE_TAGS and name not in SKIP_TAGS:
            parts.append(raw_text(child, linebreak))
        parts.append(child.tail or "")
    return "".join(parts)


def text_of(el, linebreak=" "):
    """Plain text of an element, with tables and markers skipped."""
    text = " ".join(raw_text(el, linebreak).split())
    # Escape asterisks so "(**)" in the law isn't read as Markdown emphasis
    return text.replace("*", "\\*")


def cell_text(cell):
    paras = [p for p in cell if local(p.tag) == "para"] or [cell]
    texts = (text_of(p, "<br>") for p in paras)
    return "<br>".join(t for t in texts if t).replace("|", "\\|")


def table_md(table):
    rows = []
    for row in table:
        if local(row.tag) in ROW_TAGS:
            cells = [cell_text(c) for c in row if local(c.tag) in CELL_TAGS]
            if cells:
                rows.append(cells)
    if not rows:
        return text_of(table)
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |",
             "|" + " --- |" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def find_title(root):
    for dest in root.iter():
        if local(dest.tag) == "destination":
            m = TITLE_RE.match(dest.get("name", ""))
            if m:
                return f"Title {int(m.group(1))}"
    # Admin Code section numbers start with the title, e.g. "§ 21-976"
    if root.get("source-infobase-name") == "Admin":
        for heading in root.iter("HEADING"):
            m = re.match(r"^§+\s*(\d+)-", text_of(heading))
            if m:
                return f"Title {int(m.group(1))}"
    return None


def section_heading(record, heading):
    """"§ 10-01 Requirements." -> "Section 10-01: Requirements"."""
    # Some HEADINGs hold only the number; the PARA repeats the full heading.
    for el in (heading, record.find("PARA")):
        if el is not None:
            m = SECTION_RE.match(text_of(el))
            if m:
                return f"Section {m.group(1)}: {m.group(2)}"
    m = re.match(r"^§+\s*(\S+?)\.?$", text_of(heading))
    return f"Section {m.group(1)}" if m else text_of(heading)


def record_blocks(record):
    """Body paragraphs and tables of a record without a heading."""
    blocks = []
    for child in record:
        name = local(child.tag)
        if name in TABLE_TAGS:
            blocks.append(table_md(child))
        elif name == "para":
            text = text_of(child)
            if text and not HISTORY_RE.match(text):
                blocks.append(text)
            for t in child.iter():
                if local(t.tag) in TABLE_TAGS:
                    blocks.append(table_md(t))
    return blocks


def convert(root):
    title = find_title(root)
    out = []
    first_heading = True

    def walk(level, style):
        nonlocal first_heading
        for child in level:
            name = local(child.tag)
            if name == "level":
                walk(child, child.get("style-name", ""))
            elif name == "record":
                heading = child.find("HEADING")
                if heading is None:
                    # Body text follows its heading line directly, as in the
                    # sample; later paragraphs and tables get a blank line.
                    for block in record_blocks(child):
                        if out and not out[-1].startswith(("#", "[Record")):
                            out.append("")
                        elif block.startswith("|"):
                            out.append("")
                        out.append(block)
                    continue
                text = text_of(heading)
                if out and not out[-1].startswith(("#", "[Record")):
                    out.append("")
                if first_heading:
                    first_heading = False
                    if title and not text.startswith("Title "):
                        text = f"{title} - {text}"
                    out.append(f"# {text}")
                elif style == "Section" or text.startswith("§"):
                    out.append(f"## {section_heading(child, heading)}")
                    out.append(f"[Record ID: {child.get('id')} | "
                               f"Number: {child.get('number')}]")
                else:
                    out.append(f"## {text}")

    walk(root, "")
    return "\n".join(out) + "\n"


def main(out_dir, *src_dirs):
    out_dir = Path(out_dir)
    failed = 0
    for src in map(Path, src_dirs):
        for path in sorted(src.rglob("*")):
            if not path.is_file() or path.suffix.lower() != ".xml":
                continue
            dest = (out_dir / path).with_suffix(".md")
            try:
                md = convert(ET.parse(path).getroot())
            except ET.ParseError as e:
                print(f"FAILED {path}: {e}", file=sys.stderr)
                failed += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(md, encoding="utf-8")
    if failed:
        sys.exit(f"{failed} file(s) failed to parse")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
