C: (transcribed from chat) Can you write summaries of the papers so that in future sessions you don't have to read the whole paper if you only need an overview. I'd like this summary to be living in the sense that whenever you do a task and you can't find the relevant info in the summary you add it to it. Of course one problem might be that the summary ends up as long as the original paper. For that reason I would suggest a style like "<summary>: details <paper> l<lines>". Can you suggest a way to do that and also how you want to make sure that future sessions also use this convention

---

26-11-18, Claude Opus 5.5 — *paper overview convention: design and first two overviews*; I have read CLAUDE.md, README, `papers/README.md`, `docs/CODING.md`, the head of `docs/procedures/sync.md`, the SUMMARY and LOG of the RLVR topic, and both papers in full in this session.

## What I built

- **One overview per paper**, `papers/{paper stem}_OVERVIEW.md`, created for both papers:
  - [2502.12206v1_evaluating_the_paperclip_maximizer_OVERVIEW.md](../../papers/2502.12206v1_evaluating_the_paperclip_maximizer_OVERVIEW.md) (912 words, paper 8,316)
  - [2610.31624v1_questioning_instrumental_convergence_in_rlvr_OVERVIEW.md](../../papers/2610.31624v1_questioning_instrumental_convergence_in_rlvr_OVERVIEW.md) (885 words, paper 7,655)
  - [verified: `wc -w` 26-11-18]
  - Fixed sections: *Gist*, *Setup and method*, *Findings (as the paper states them)*, *Where to find (things the paper does not contain)*, *Project notes (our assessments, not the paper's)*.
- **Pointer format `[§label lA-B]`**, e.g. `[§4.2 l174-176]`. This adapts Julian's proposed "<summary>: details <paper> l<lines>" in two ways:
  - The paper name is dropped, because each overview belongs to exactly one paper.
  - A section label is added. Line numbers alone go stale silently when anything is inserted above them (CLAUDE.md warns about this for LOGs). With the section label, the shift becomes detectable.
- **A checker**, [papers/check_overview_refs.py](../../papers/check_overview_refs.py). For every pointer it checks that the range exists and that the nearest heading above it matches the label. It exits 1 otherwise, and `--show` prints the first pointed line for checking by eye.
  - [verified: run 26-11-18] 68 pointers, all OK, and I read every `--show` line. The first run caught two real problems: the format example in the overview header was flagged (fixed: the checker now ignores inline code), and two pointers started on blank lines (fixed by hand).
  - [verified: script 26-11-18] All 64 decimal numbers in the paper-content sections of the two overviews occur in the paper text.
- **Paper files frozen.** Each paper's header comment got one line naming its overview and saying the file's lines must not change. I added it *before* writing the pointers, so it shifted nothing that is pointed to. The new line also shifted every later line of both papers by one; nothing else in the project pointed to paper line numbers [verified: grep 26-11-18].

## How the convention reaches future sessions

Ordered by how reliably an agent sees it:
1. **CLAUDE.md**, *Reading Priority* item 6. This is the only file every session and every sub-agent loads automatically, so it carries the rule in three sentences: read the overview first, open the paper only at the pointers, add a bullet when the overview lacked something, then run the checker.
2. **`papers/README.md`** holds the full rules (format, growth, paper versus our notes, numbers, length budget, frozen papers, checker, adding a paper). The project README links to it.
3. **The top of every overview** repeats the rules in one paragraph, for an agent that lands there directly.
4. **The header comment of every paper** points to its overview, for an agent that greps straight into a paper.

What this can't guarantee [concluded]:
- An agent that ignores CLAUDE.md, or reads a paper in full out of habit, won't add anything. The rule depends on compliance; the checker only catches stale pointers, not missing additions.
- The checker cannot tell whether a pointed passage says what the bullet claims. Only `--show` plus reading does that.
- CLAUDE.md is the Epistemic Memory template's core file. A local edit is a divergence to carry along if the template is ever updated from upstream. Item 6 is self-contained, so merging it by hand is easy.

## Against the "summary grows into the paper" risk

- **Hard budget:** 1,500 words or 20% of the paper's words, whichever is smaller. Both overviews currently sit at about 11%. When an addition would break the budget, compress first: merge bullets, drop numbers one pointer away, demote rarely used bullets to bare pointers.
- **Growth is driven by questions, not by completeness.** A bullet is added only when a real task failed to find something.
- **Detail stays in the paper.** A bullet is one or two sentences plus a pointer.
- **Our critiques live in the topic LOGs.** The *Project notes* section holds one tagged line per critique and points to the LOG.

## Choices Julian may want to change

- Name `_OVERVIEW` instead of `_SUMMARY`. In this project, a SUMMARY is the partner of a LOG, and the sync procedure treats it that way; a paper summary under the same name would confuse both. [concluded]
- Our critiques sit in the overview's *Project notes* (with pointers to the LOG), rather than only in the LOG. The reason: an agent reading the overview for, say, the 32B IR numbers should also learn that the judge check looks degenerate. The cost is a second place to keep current.
- The CLAUDE.md edit itself (see above).

New observation made while writing the overview, also recorded in the 2610.31624 overview's *Project notes*: the 2610.31624 paper's judge prompt (its Table 9: a continuous 0-1 score) is not the original benchmark's binary judge prompt, so absolute instrumental rates aren't comparable between the two papers. [verified: Table 9 compared with InstrumentalEval `main.py`, 26-11-18]

---

C: (transcribed from chat) I think the description how to use the overview is too long in README.md. I'd suggest something more akin to CODING.md

---

26-11-18, Claude Opus 5.5 — *rules moved to docs/PAPERS.md*; same session as the entry above

I read "akin to CODING.md" as both the layout and the tone, and changed both:
- The rules now live in a new reference file, `docs/PAPERS.md`, read on demand. `CLAUDE.md` keeps the short rule every session needs (*Reading Priority* item 6) and lists `docs/PAPERS.md` among its reference files. This mirrors how `CLAUDE.md` and `docs/CODING.md` split the coding rules.
- The rules are now terse headed bullets: Overviews, Paper files are frozen, Checker, Adding a paper. The paper-conversion how-to moved there from `papers/README.md` too, so that README is now only a two-line intro plus the paper table.
- The usage paragraph at the top of each overview went from about 110 words to two sentences pointing to `docs/PAPERS.md`.
- Nothing in the substance changed: same pointer format, budget, paper-versus-us split and checker. [verified: checker run after the edit, all references OK]

If Julian meant only "shorter, keep it in `papers/README.md`", the content of `docs/PAPERS.md` can move back unchanged.
