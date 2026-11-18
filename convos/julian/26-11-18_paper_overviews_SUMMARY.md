# SUMMARY: Paper overviews (living indexes into `papers/`)

**Last updated:** 26-11-18 (rules moved to `docs/PAPERS.md` at Julian's request; not yet ratified)

Julian asked for paper summaries that save future sessions from reading whole papers. They should be living (extended whenever a task can't find something in them) and should avoid growing into a copy of the paper. He suggested entries of the form "summary: details at paper lines".

## Current state [concluded: built 26-11-18, not ratified]

- Each paper `papers/{stem}.md` has `papers/{stem}_OVERVIEW.md`, with sections Gist / Setup / Findings / Where to find / Project notes. Both current papers have one.
- Pointer format `[§label lA-B]`: section label plus line range. Julian's "l<lines>" idea gets a section label added, so that shifted line numbers are detectable. The paper name is dropped, since each overview belongs to one paper.
- [verified: 68 pointers OK, 26-11-18] `papers/check_overview_refs.py` checks every pointer against the paper's headings; `--show` prints the pointed lines for checking by eye.
- Paper files are frozen once an overview points into them. Their header comments name the overview.
- Length budget: 1,500 words or 20% of the paper's words, whichever is smaller. Both overviews are currently about 11%.
- Paper claims and our assessments are kept apart: our critiques go only under *Project notes*, tagged, pointing to the topic LOG.
- How future sessions learn the rule:
  - **CLAUDE.md** *Reading Priority* item 6 (always loaded, also by sub-agents).
  - **`docs/PAPERS.md`** holds the full rules as terse bullets, plus how to add a paper; `CLAUDE.md` lists it among its reference files. They first lived in `papers/README.md`. Julian found that too long and asked for something like `docs/CODING.md`, so `papers/README.md` is now only the index.
  - **The top of each overview** points to the rules in two sentences.
  - **Each paper header** points to its overview.
- Limits: compliance can't be enforced, and the checker can't judge meaning. The CLAUDE.md edit is a divergence from the Epistemic Memory template.

## Open (for Julian)

- Ratify or change: the `_OVERVIEW` name (chosen to avoid confusion with LOG/SUMMARY pairs), critiques in *Project notes*, and the CLAUDE.md edit.

- LOG: `convos/julian/26-11-18_paper_overviews_LOG.md` (entry *paper overview convention: design and first two overviews*)
- See also: `convos/julian/26-11-16_rlvr_instrumental_convergence_SUMMARY.md` — the topic that uses both papers; its critiques are summarised in the overviews' *Project notes*.
