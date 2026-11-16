# Papers

Reference copies of papers as Markdown, for agents to read and grep. Each file starts with an HTML comment giving the source URL, version, license and conversion notes (what was lost, e.g. image-only figures). Filenames: `{arxiv id with version}_{short title}.md`. Image figures are stored next to the paper in `{arxiv id with version}_figures/` and linked from the Markdown with relative paths. Each one also gets a text transcription under its caption, so agents can search it without opening the image.

| File | Paper | Notes |
|------|-------|-------|
| [2502.12206v1_evaluating_the_paperclip_maximizer.md](2502.12206v1_evaluating_the_paperclip_maximizer.md) | He et al. 2025, *Evaluating the Paperclip Maximizer: Are RL-Based Language Models More Likely to Pursue Instrumental Goals?* (arXiv 2502.12206v1) | Introduces InstrumentalEval, a 76-task benchmark for instrumental convergence; code at github.com/yf-he/InstrumentalEval |

How the existing file was made: download the arXiv HTML rendering (`https://arxiv.org/html/{id}`), keep only its `<article>` element, unwrap internal citation links, flatten the SVG text boxes and equation tables, then convert with pandoc (`gfm`, no wrapping). Not every arXiv paper has an HTML rendering; for those, the LaTeX source (`https://arxiv.org/e-print/{id}`) is the next-best input.
