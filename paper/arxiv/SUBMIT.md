# Publishing the paper: arXiv and Zenodo

This folder is the frozen source of the version published on Zenodo (doi:10.5281/zenodo.23592038, concept DOI
10.5281/zenodo.23592037; cite the concept DOI). The paper's Reproducibility section points here, so it stays. The
manuscript's working copy and its publication records moved to the author's research repository (paper 21) on
2026-10-23; copy any new published version back here.

Status (2026-10-23):
- Zenodo: published 15:11 IST. The file local-screen-small-coding-agent.pdf is main.pdf (sha256
  78c5cbed47af6c72e5d857a077a37dbad532fc4b535029d7ea0cbab72a823e0e).
- arXiv: not submitted and on hold. The author's account has three moderator rejections on earlier papers, and the
  author decides whether to submit.

Everything below is filled in from main.tex. The source package is built by the steps at the end; it does not live in git.

## arXiv

- Licence: CC BY 4.0
- Primary category: cs.SE (Software Engineering). Cross-list: cs.LG.
- Title: What a Local Screen Could Not Tell Us: Measuring a Small Offline Coding Agent Under a Twelve-Hour Budget
- Authors: Carson Rodrigues
- Comments: 11 pages, 3 figures, 5 tables. Code, per-task results and traces: https://github.com/rodriguescarson/gemma-swe-agent
- Report number, journal reference: leave empty. DOI: leave empty (the Zenodo DOI is a separate record; arXiv's DOI field
  is for a published journal version)
- Abstract (1,717 characters; the arXiv limit is 1,920):

In the Gemma 4 Developer Agent competition the model, the tools and the scorer are fixed, and an entry is only an agent configuration: its prompt, its limits and its sampling settings. Entrants choose between configurations the way most agent builders do, by running them on a small public task set before spending a scarce hidden submission. We report what that practice told us over four weeks, from 20 complete runs on the 74 public tasks across two local setups (the scorer's own four-L4 hardware and a single GPU paced to it) and 11 configurations submitted to the hidden set. The local screen was a poor guide. On the scorer's hardware, a change that beat its parent on nine tasks and lost none scored lower on the hidden set. On the paced GPU, three configurations that each solved 28 of 74 locally scored 0.10, 0.10 and 0.17, and the rank correlation between local and hidden scores was +0.49 (exact permutation p = 0.32, seven configurations). Three measurements explain much of this. Between 91 and 97 percent of each task's wall time is the model generating text, so the per-task time cap is a token budget. Solves arrive late, so longer caps buy local solves that a hard twelve-hour limit on the whole run cannot pay for: a public configuration that scored 0.24 for its author ran out of time on both of our attempts. And prompt rules that each fixed one task lost seven tasks when merged. We also ran Google's Harness$^2$ with Gemma as its own harness improver: 23 of 30 improver sessions overflowed the model's 32k context and no change to the harness was adopted. Every reading rule was committed to git before its result, every number is regenerated from saved files, and all code and data are public.

If it goes ahead: the account has five announced papers and three moderator rejections, so the decision is the
author's. The Zenodo record is the citable version either way.

## Zenodo

- Upload type: Publication, Preprint
- Files: main.pdf
- Title, author, abstract: as above. Affiliation: Celabe Research. ORCID 0009-0001-7195-6742.
- Licence: CC BY 4.0
- Keywords: coding agents; evaluation; SWE-bench; small language models; Gemma; benchmark validity; pre-registration
- Related identifiers: "is supplemented by" https://github.com/rodriguescarson/gemma-swe-agent ; once arXiv assigns an id,
  add "is identical to" arXiv:<id>
- Publication date: the day it is published

## Building the source package

```
tectonic -X compile --keep-intermediates --outdir <build> main.tex      # gives <build>/main.bbl
printf '%s\n' '\ifdefined\pdftexversion\pdfoutput=1\fi' | cat - main.tex > <src>/main.tex
cp <build>/main.bbl <src>/ ; cp -R figures tables <src>/
COPYFILE_DISABLE=1 tar -czf arxiv-source.tar.gz -C <src> main.tex main.bbl figures tables
```

Use `printf`, not `echo`: zsh's echo turns the `\f` in `\fi` into a form feed. arXiv runs pdflatex and reads main.bbl
instead of running BibTeX, so test with `\bibliography{refs}` replaced by `\input{main.bbl}`. Tectonic ignores a `.bbl` on
disk when refs.bib is missing, and the citations would then show as [?].
