# SUMMARY: Public research log (link-commentable)

**Last updated:** 26-11-16 (Google Doc created and shared; entries blocked on the Google Docs connector)

Julian wants a research log that anyone with the link can comment on, without having to maintain it by hand alongside the repo.

**The doc:** [Research Log – BlueDot Technical AI Safety Project](https://docs.google.com/document/d/1foNERlByg2XP0skNTYstDExaZpIFwBivshpkliqlv7k/edit). Drive file ID: `1foNERlByg2XP0skNTYstDExaZpIFwBivshpkliqlv7k`. Shared as anyone-with-link = commenter. It contains a title, a one-sentence intro, a "Current status" section and an empty "Log" heading. Entries go at the bottom, in chronological order. [verified: read back via Drive connector 26-11-16]

- [decided] One Google Doc, per Julian's chat message transcribed in the LOG. Earlier options (a Claude Doc, one Google Doc per entry, a public GitHub repo) are no longer being pursued.
- [concluded] Entries are a curated digest drafted by an agent from the repo LOG/SUMMARY pairs, not a mirror of the LOGs. Julian approves each entry before it's added. Entry text gets the `docs/procedures/outward_text.md` pass.
- [concluded] Appending to the doc needs the **Google Docs connector** (in-place edits). The Google Drive connector alone can only create files, share them, and read them with comments. I initially said a single Google Doc couldn't be appended to, but that only applied to the connectors in that session. The Docs connector was not enabled on 26-11-16.
- Reading comments back into the repo works with Drive `read_file_content` + `includeComments`.

Open: Julian enables the Google Docs connector. After that, define the `!publish` step (which could become a procedure file) and decide how often entries come out and who the commenters are.

- LOG: `convos/julian/26-11-16_public_research_log_LOG.md`
