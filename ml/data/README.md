# Datasets

All data used for training and evaluation is public Bugzilla data from the Eclipse and Mozilla
projects, published by two research groups. Raw files are **not** committed (`ml/data/raw/` and
`ml/data/processed/` are git-ignored); `ml/data/download.sh` fetches them, pinned to exact
commits, and writes SHA-256 checksums to `ml/data/raw/SHA256SUMS`.

Downloaded and verified on **2026-11-23**.

## Sources

| # | Dataset | Used for | Source (pinned) | Licence |
|---|---|---|---|---|
| 1 | **Eclipse and Mozilla Defect Tracking Dataset** - A. Lamkanfi, J. Pérez, S. Demeyer, *MSR 2013*, pp. 203-206, doi:10.1109/MSR.2013.6624028 | severity labels, assignee history, product, component, resolution | https://github.com/ansymo/msr2013-bug_dataset @ `f5084232f88b1b92d60c8492be5f0737fac320f7` (files `data/v02/{eclipse,mozilla}/{reports,severity,assigned_to,component,product}.json`) | No licence file in the repository (checked via the GitHub API). The authors publish it for research and ask to be cited. |
| 2 | **BugRepo** (LogPAI, CUHK) - free-text bug reports for duplicate detection; the data used by Q. Meng et al., *Combining Retrieval and Classification*, arXiv:2404.14877 (2024), footnote in Sec. IV-B | report title + description, duplicate links, creation time | https://github.com/logpai/bugrepo @ `76d33067f91813690e01ae37b4790e631c5081f4` (EclipsePlatform, JDT, Firefox, MozillaCore, Thunderbird) | No licence file in the repository. README: "bug reports that are publicly available for research purposes". |

Meng et al. did not publish a separate replication package (their paper says code will follow);
the paper's only data link is BugRepo, so BugRepo is the benchmark we evaluate on.

## How the two sources are combined (`python -m ml.data.prepare`)

Dataset 1 has severity and assignee **histories** but only the title; dataset 2 has the full
description but no severity or assignee. Both are keyed by the Bugzilla bug id, so they are
joined on it:

| Ecosystem | Products | Reports in BugRepo | Joined with MSR 2013 |
|---|---|---:|---:|
| Eclipse | Platform, JDT | 130,452 | 121,908 |
| Mozilla | Core, Firefox, Thunderbird | 353,434 | 326,245 |

Per bug we keep: id, product, component, title, description, cleaned text
(`ml/common/text.py`), creation time, final resolution, initial and final severity, final
assignee and the number of assignee changes, and the duplicate link.

### Privacy

Assignee e-mail addresses are replaced by salted SHA-256 pseudonyms (`dev_<10 hex>`) during
preparation; no address is stored in processed data, models or results. Shared inbox and
placeholder accounts (`*-inbox@`, `nobody@`, `general@*`, empty) are treated as "no developer".

## Labels and filtering

**Severity** (final value after triage, i.e. what triagers settled on):

| Bugzilla | Ours |
|---|---|
| blocker, critical | Critical |
| major | High |
| normal | Medium |
| minor, trivial | Low |
| enhancement | *dropped* (feature request, not a defect) |

**Assignment**: only bugs resolved `FIXED` with a personal final assignee (the fixer). Developer
classes are developers with at least **50** fixes in the training period
(`ml/assignment/data.py:MIN_FIXES`); test bugs fixed by anyone else are counted as "not
covered" and reported separately.

**Duplicates**: BugRepo's `Duplicated_issue` links, grouped into clusters (union of links).

## Splits (no leakage)

Every task uses a **time-based** split: reports are ordered by creation time; the newest 20% are
the test set and are only used by the `evaluate` scripts.

* Severity: the older 80% is used for 10-fold stratified CV (hyper-parameters) and the final fit.
* Assignment: the newest 10% of the training period is the validation set (early stopping).
* Duplicates: the 10% just before the test period chooses the semantic weight; at test time a
  query may only retrieve reports created before it.

Exact sizes and date ranges are written into each `docs/results/*.json` file.

## Synthetic data

Only `ml/tests/` uses synthetic data (a few hand-written sentences), to unit-test code paths.
No reported metric comes from synthetic data.
