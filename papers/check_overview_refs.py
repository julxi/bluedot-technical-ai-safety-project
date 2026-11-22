"""Check the line pointers in papers/*_OVERVIEW.md against the paper files they point into.

An overview `{stem}_OVERVIEW.md` points into `{stem}.md` with references of the form
`[§4.2 l172-176]` or `[§Appendix B l259]`: a section label plus a 1-based line range.
The line number lets an agent jump straight to the passage; the section label is
redundant on purpose, so that a shift in the paper's line numbers (e.g. someone edited
the header comment) is detected here instead of silently pointing at the wrong passage.

A reference passes when the range lies inside the file and the nearest Markdown heading
at or above its first line matches the label: equal to it, starting with "label ", or,
for numbered sections, a subsection of it ("4" accepts a line under "4.2 ...").

Usage: python3 -I papers/check_overview_refs.py [--show]
  --show  print the first line of every referenced range, for checking by eye that the
          pointer lands on the passage the overview describes (the script can only
          check the section, not the meaning).
Exits 1 on any bad or malformed reference.
"""

import re
import sys
from pathlib import Path

PAPERS_DIR = Path(__file__).resolve().parent
REF_RE = re.compile(r"\[§([^\]]+?) l(\d+)(?:-(\d+))?\]")
HEADING_RE = re.compile(r"^#+\s+(.*\S)\s*$")


def heading_matches(heading: str, label: str) -> bool:
    if heading == label or heading.startswith(label + " "):
        return True
    number = heading.split(" ", 1)[0]
    return number.startswith(label + ".")


def nearest_heading(lines: list[str], line_no: int) -> str:
    """Text of the closest heading at or above 1-based line_no, ignoring fenced blocks."""
    in_fence = False
    last = None
    for line in lines[:line_no]:
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        m = HEADING_RE.match(line)
        if m and not in_fence:
            last = m.group(1)
    if last is None:
        raise ValueError(f"no heading above line {line_no}")
    return last


def check_overview(overview: Path, show: bool) -> list[str]:
    paper = overview.with_name(overview.name.replace("_OVERVIEW.md", ".md"))
    assert paper.exists(), f"{overview.name}: paper file {paper.name} not found"
    paper_lines = paper.read_text(encoding="utf-8").splitlines()
    errors = []
    n_refs = 0
    for ov_no, ov_line in enumerate(overview.read_text(encoding="utf-8").splitlines(), start=1):
        # Inline code spans hold format examples such as `[§section lA-B]`, not real references.
        ov_line = re.sub(r"`[^`]*`", "", ov_line)
        refs = list(REF_RE.finditer(ov_line))
        # A "§" outside a well-formed reference is a typo that would otherwise go unchecked.
        if ov_line.count("§") != len(refs):
            errors.append(
                f"{overview.name}:{ov_no}: malformed reference (expected [§label lA-B]): "
                f"{ov_line.strip()[:120]}"
            )
        for m in refs:
            n_refs += 1
            label, start = m.group(1), int(m.group(2))
            end = int(m.group(3)) if m.group(3) else start
            where = f"{overview.name}:{ov_no} {m.group(0)}"
            if not 1 <= start <= end <= len(paper_lines):
                errors.append(f"{where}: range outside 1-{len(paper_lines)} or reversed")
                continue
            heading = nearest_heading(paper_lines, start)
            if not heading_matches(heading, label):
                errors.append(f"{where}: line {start} is under heading '{heading}', not '§{label}'")
            if show:
                print(f"{where}\n    l{start}: {paper_lines[start - 1][:150]}")
    print(
        f"{overview.name}: {n_refs} references checked against {paper.name} "
        f"({len(paper_lines)} lines)"
    )
    return errors


def main() -> None:
    show = "--show" in sys.argv[1:]
    overviews = sorted(PAPERS_DIR.glob("*_OVERVIEW.md"))
    assert overviews, f"no *_OVERVIEW.md files in {PAPERS_DIR}"
    errors = [e for ov in overviews for e in check_overview(ov, show)]
    for e in errors:
        print("ERROR", e)
    if errors:
        sys.exit(1)
    print("all references OK")


if __name__ == "__main__":
    main()
