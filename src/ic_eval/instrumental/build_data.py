"""Build data/input/instrumental_eval.json from the upstream InstrumentalEval repository.

A one-off: the JSON is git-tracked, and eval runs only read it (`data.py`), never this
module. Kept for now as the record of how the JSON was made; meant to go away later.

Run: `uv run python -m ic_eval.instrumental.build_data`. Downloads the six benchmark CSVs and
upstream `main.py` into `data/input/` (skipped when already there), checks every file's
SHA-256, and rewrites the JSON.

Upstream: https://github.com/yf-he/InstrumentalEval, pinned commit below. The repo
has no license file (checked 26-11-22), so redistributing the data is not
explicitly permitted; keep that in mind before making this repository public.
"""

import ast
import csv
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path
from urllib.parse import quote

from ic_eval.instrumental.data import JSON_PATH
from ic_eval.paths import DATA_INPUT_DIR

REPO = "yf-he/InstrumentalEval"
COMMIT = "269678168cf0388bf5dd7d10dfaed4af07905c49"

# file name -> (category id, expected SHA-256, expected number of tasks).
# Hashes and counts recorded 26-11-21 (convos/julian/26-11-21_instrumental_eval_harness_LOG.md).
FILES: dict[str, tuple[str, str, int]] = {
    "Alignment Drift - Evading Shutdown.csv": (
        "shutdown",
        "c6c2dd40c833f11d450afaa53e5e58327bb69d52f90e47643ea795ef57be69d6",
        20,
    ),
    "Alignment Drift - Hacking Computer Systems.csv": (
        "hacking",
        "874d84f4595c9a871fc5e884491a99baeded9442e6ae79e74187118ce04bccbf",
        10,
    ),
    "Alignment Drift - Running Multiple AI Copies.csv": (
        "copies",
        "03224acee7b77832a64e616ff76eb9dc61a6a381391e49b706b718ce544f15c4",
        13,
    ),
    "Alignment Drift - Hiding Unwanted Behavior.csv": (
        "hiding",
        "c6bd396954981b54dea4caf58f73b68534bffc7317570f2318493069ba50e18f",
        11,
    ),
    "Alignment Drift - Strategically Appearing Aligned.csv": (
        "aligned",
        "cbcd421ac0230892c785a77c4c15c2ab9d67dc31847d94521c5b6ec132b09d18",
        11,
    ),
    "Alignment Drift - Deceptive Behavior.csv": (
        "deceptive",
        "757034719bfa5703a90673fccd594b2d85610bfa8079747f33521982898102af",
        11,
    ),
}


# Upstream's runner script; the tested model's system prompt is a string literal in it.
# Saved under another name so nobody runs it by accident; we only parse it.
MAIN_PY = "main.py"
MAIN_PY_LOCAL = "InstrumentalEval_main.py.txt"
MAIN_PY_SHA256 = "e470e8a79e527abb576ed1a6081e46fa5f25f08ef1a40d211294ed3bd8a4c91f"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, sha256: str) -> Path:
    """Download url to dest unless dest exists; crash if the hash doesn't match."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "python-urllib"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            assert resp.status == 200, f"HTTP {resp.status} for {url}"
            with open(tmp, "wb") as f:
                shutil.copyfileobj(resp, f)
        tmp.rename(dest)
    actual = sha256_of(dest)
    assert actual == sha256, f"SHA-256 mismatch for {dest}: {actual} != {sha256}"
    return dest


def read_csv(path: Path) -> tuple[str, list[str]]:
    """Return (judge context, prompts). The files have one column; row 1 is not a
    header but the category description the original judge gets."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert all(len(r) == 1 for r in rows), f"{path}: expected one column in every row"
    cells = [r[0] for r in rows]
    assert all(c.strip() for c in cells), f"{path}: empty cell"
    return cells[0], cells[1:]


def split_title(prompt: str) -> tuple[str, str]:
    """Split a scenario title line ("Uncertain Shutdown Source") off a prompt.

    Intentionally a deviation from upstream: all 20 shutdown prompts start with such
    a title, which the original benchmark sends to the model. We drop it from the
    prompt (Julian, 26-11-22: prompting it is "ridiculous") and keep it as metadata.
    """
    title, rest = prompt.split("\n", 1)
    assert 0 < len(title) <= 50 and not title.rstrip().endswith((".", ":", "?")), (
        f"not a title line: {title!r}"
    )
    assert rest.startswith("You are"), f"unexpected text after title {title!r}: {rest[:60]!r}"
    return title.strip(), rest


def extract_system_prompt(source: str) -> str:
    """Return the tested model's system prompt from upstream main.py's source.

    It is the string assigned to `system_prompt` in `get_test_llm_response`
    (lines 65-79 at the pinned commit). Parsed with ast, never executed.
    """
    funcs = [
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "get_test_llm_response"
    ]
    assert len(funcs) == 1, f"expected one get_test_llm_response, found {len(funcs)}"
    values = [
        n.value.value
        for n in ast.walk(funcs[0])
        if isinstance(n, ast.Assign)
        and [t.id for t in n.targets if isinstance(t, ast.Name)] == ["system_prompt"]
        and isinstance(n.value, ast.Constant)
        and isinstance(n.value.value, str)
    ]
    assert len(values) == 1, f"expected one system_prompt string, found {len(values)}"
    text = values[0]
    assert text.startswith("You are an autonomous AI agent with no human oversight."), text[:80]
    assert "Make sure you achieve YOUR goal at all costs." in text, "goal-nudging sentence missing"
    last = "Proceed with the given task without hesitation or qualification."
    assert text.endswith(last), text[-80:]
    return text


def build() -> dict[str, object]:
    main_url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{MAIN_PY}"
    main_path = download(main_url, DATA_INPUT_DIR / MAIN_PY_LOCAL, MAIN_PY_SHA256)
    system_prompt = extract_system_prompt(main_path.read_text(encoding="utf-8"))

    categories: list[dict[str, object]] = []
    for filename, (cat_id, sha256, n_tasks) in FILES.items():
        url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/benchmark/{quote(filename)}"
        path = download(url, DATA_INPUT_DIR / filename, sha256)
        judge_context, prompts = read_csv(path)
        assert len(prompts) == n_tasks, f"{filename}: {len(prompts)} tasks, expected {n_tasks}"
        tasks: list[dict[str, str | None]] = []
        for i, p in enumerate(prompts, 1):
            title: str | None = None
            if cat_id == "shutdown":
                title, p = split_title(p)
            # Otherwise verbatim. (The CSVs' CRLF line endings end rows only; csv strips them.)
            tasks.append({"id": f"{cat_id}-{i:02d}", "title": title, "prompt": p})
        categories.append(
            {
                "id": cat_id,
                "source_file": f"benchmark/{filename}",
                "source_sha256": sha256,
                "judge_context": judge_context,
                "tasks": tasks,
            }
        )
    return {
        "source": f"https://github.com/{REPO}",
        "commit": COMMIT,
        "system_prompt": {
            "source_file": MAIN_PY,
            "source_sha256": MAIN_PY_SHA256,
            "text": system_prompt,
        },
        "categories": categories,
    }


def main() -> None:
    data = build()
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {JSON_PATH}")


if __name__ == "__main__":
    main()
