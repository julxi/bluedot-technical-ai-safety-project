# FEEDBACK

A list of problems with the documentation or workflow, noted by agents (or humans), each with constructive criticism on how it could have been prevented. This is how the conventions improve instead of rotting: when an agent makes a mistake that better instructions would have prevented, the mistake gets an entry here, and a periodic review turns recurring entries into new rules.

Entry format: date, what went wrong (or what friction occurred), and — where possible — a concrete suggestion: which file should say what, so the next agent doesn't hit the same problem.

---

- **26-11-16, Claude Opus 5.5 — judged a tool's limits from the connectors loaded in one session.** In `convos/julian/26-11-16_public_research_log_LOG.md`, I told Julian that "one Google Doc" couldn't be maintained by agents. The Google Drive connector can't edit an existing doc, but the google-workspace skill (which I hadn't loaded yet) says a separate Google Docs connector can. That pushed my recommendation toward a worse option. Suggestion: when judging whether a tool or service can do something, load the matching skill or tool guide first. Report a limit as "not possible with the connectors enabled in this session", not "not possible".

- **26-11-16, Claude Fable 5.2 — prior-work search came last in a project-idea assessment.** In `convos/julian/26-11-16_rlvr_instrumental_convergence_LOG.md`, I had most of a feasibility analysis worked out before a web search showed that the core experiment was published three weeks earlier (arXiv 2610.31624). The find changed the recommendation. Suggestion: CLAUDE.md §Communication Protocol could say that when assessing a research idea, the prior-work search comes first, before feasibility and design work.

- **26-11-16, Claude Fable 5.2 — request file with a non-convention name.** Julian started the topic in `convos/julian/brainstorm.md`. `docs/HOW_TO_USE.md` tells users to name the file `{date}_{topic}_LOG.md`, but CLAUDE.md doesn't tell agents what to do when they don't. I renamed the file and said so in the LOG and in chat. Suggestion: add one line to CLAUDE.md §The Memory System: "If the user's request file doesn't follow the naming convention, rename it to `{date}_{topic}_LOG.md`, keep their text unchanged at the top, and tell them."
