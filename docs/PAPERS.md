# Papers — Reference

Read this before adding a paper to `papers/` or editing an overview. The rule every session needs (read the overview first; extend it when it fails you) lives in CLAUDE.md. This file holds the how-to.

## Overviews

Every paper `papers/{stem}.md` has `papers/{stem}_OVERVIEW.md`, a short living index with line pointers into the paper.

- **Pointer format `[§label lA-B]`.** The label is the start of the paper's heading (`4.2`, `A.3`, `Abstract`, `Appendix B`). A table or figure takes the label of the heading it sits under. Lines are 1-based; Read with `offset=A`. The label is redundant on purpose, so the checker can detect shifted lines.
- **Grow on failure.** When a task made you search the paper, add one bullet: the gist in one or two sentences, then the pointer. Things the paper doesn't contain go under *Where to find*.
- **Paper versus us.** *Setup* and *Findings* hold the paper's claims. Our assessments go only in *Project notes*, tagged, pointing to the topic LOG.
- **Numbers** are copied verbatim, but they are index entries: re-read the number at its pointer before using it.
- **Budget:** at most 1,500 words or 20% of the paper's words (`wc -w`), whichever is smaller. Over budget, compress instead of appending: merge bullets, drop numbers that are one pointer away.
- **Living document:** bump `Last updated`; history goes in the topic LOG.

## Paper files are frozen

Overviews point at line numbers, so don't edit a paper file once it has an overview. If you must (e.g. a re-conversion), run the checker and fix every pointer it reports.

## Checker

`python3 -I papers/check_overview_refs.py` after every edit to an overview or a paper file. It exits 1 on stale or malformed pointers. `--show` prints the first pointed line of each pointer; read the new ones, because the checker verifies sections, not meaning.

## Adding a paper

1. **Convert.** Take the arXiv HTML (`https://arxiv.org/html/{id}`) and keep only its `<article>` element. Unwrap citation links and flatten the SVG text boxes and equation tables. Then convert with pandoc (`gfm`, no wrapping), or, since pandoc isn't installed here, with `python3 -I papers/latexml_to_md.py paper.html out.md`. The script stops on HTML elements it doesn't know, so extend it as needed. No HTML rendering: use the LaTeX source (`https://arxiv.org/e-print/{id}`).
2. **Verify and document.**
   - Check that the numbers in the HTML and the Markdown match.
   - Start the file with an HTML comment holding the source, version, license, conversion notes, and a line naming the overview.
   - Store image figures in `{stem}_figures/`, each with a text transcription under its caption.
3. **Overview.**
   - Finish the paper's header first, because header edits shift the pointers.
   - Write the overview from a full read, copying the sections of an existing one.
   - Run the checker and add a row to `papers/README.md`.
