# Novelty: comparison with existing issue trackers

Only features stated in each vendor's **official documentation, release notes or changelog**
are marked "Yes". "Not verified" means we found no official statement either way; it does
not mean the feature is missing. Checked in November 2026; vendors change quickly, so the
sources are listed for re-checking.

| Capability | Jira (Atlassian) | Bugzilla | GitHub Issues | Linear | This system |
|---|---|---|---|---|---|
| Possible duplicates shown while a report is being written | Yes – Rovo surfaces potential duplicates during creation [J1] | Yes – suggestions while typing the summary (since 4.0) [B1][B2] | Yes – public preview, up to 3 matches in the form [G1][G2] | Yes, for issues in triage (Triage Intelligence) [L1][L2] | Yes – BM25 + local MiniLM, 600 ms debounce, similarity score |
| Severity / priority suggested automatically | Priority among fields suggested from similar items (Jira) [J1][J2]; priority change suggestions (JSM) [J3] | Not verified | Not verified | Not verified | Yes – Low/Medium/High/Critical with confidence; override is audited |
| Assignee recommendation | Assignee suggestions for service requests (Jira Service Management) [J3] | Not verified | Not verified | Yes – based on historical patterns [L1] | Yes – top 3 with score and reason |
| Explicit cold-start handling for new developers | Not verified | Not verified | Not verified | Not verified | Yes – α = min(1, resolved/N) blend and ε exploration slot (FR-22) |
| Duplicate, severity and assignee steps share state in one pipeline | Not verified | Not verified | Not verified | Not verified | Yes – likely duplicate boosts the original's fixer; Critical skips busy developers |
| Per-step time budgets with documented degradation (bug still saved) | Not verified | Not verified | Not verified | Not verified | Yes – each step degraded independently; Unclassified + notice (NFR-10) |
| AI runs locally, no report text sent to an external AI service | Not verified (cloud AI features) | Not applicable (no AI triage found) | Not verified | Not verified | Yes – CPU models inside the backend (DC-03) |
| Official VS Code extension | Yes – Atlassian for VS Code [J4][J5] | Not verified | Yes – GitHub Pull Requests and Issues [G3] | Not verified | Yes – report, triage, lifecycle, dashboard, admin |
| Self-hosted deployment | Yes – Data Center / Server supported by the VS Code extension [J5] | Yes – open-source, installed by the organisation [B3] | Yes – GitHub Enterprise Server [G4] | No official option found [L3] | Yes – docker compose |
| Published, reproducible evaluation of the AI features | Not verified | Not applicable | Not verified | Not verified | Yes – `docs/results/RESULTS.md` (including the targets that were missed) |

## What is new here

Commercial trackers have started to add individual AI features (duplicate suggestions,
field suggestions, assignee suggestions). What we could not find in any official source is
the combination this project delivers and measures:

1. **Shared state between the three triage tasks** in one pipeline (`TriageContext`):
   the duplicate result and the predicted severity are inputs to the assignment step.
2. **Explicit cold-start handling** for developers without history, with a documented and
   unit-tested formula and exploration.
3. **Inside the IDE, fully local**: the models run on the team's own server on CPU, with
   measured latency (duplicates + severity 160 ms, assignment 145 ms at p95 over HTTP on
   50,000 reports) and documented graceful degradation.
4. **Open, reproducible evaluation** against public datasets with time-based splits, with
   missed targets reported rather than hidden.

## Sources

* [J1] Atlassian, "Rovo AI features in Jira": https://support.atlassian.com/organization-administration/docs/atlassian-intelligence-features-in-jira-software/
* [J2] Atlassian, "Explore AI features": https://support.atlassian.com/organization-administration/docs/understand-atlassian-intelligence-features-in-products/
* [J3] Atlassian, "About suggestions on work items" (Jira Service Management): https://support.atlassian.com/jira-service-management-cloud/docs/about-suggestions-on-issue-view/
* [J4] Visual Studio Marketplace, "Atlassian: Jira, Rovo Dev, Bitbucket": https://marketplace.visualstudio.com/items?itemName=Atlassian.atlascode
* [J5] Atlassian, "Use the Atlassian for VS Code extension": https://support.atlassian.com/bitbucket-cloud/docs/use-the-atlassian-for-vs-code-extension/
* [B1] Bugzilla 4.0 release notes ("Automatic Duplicate Detection When Filing Bugs"): https://www.bugzilla.org/releases/4.0/
* [B2] Bugzilla 4.2.1 release notes: https://www.bugzilla.org/releases/4.2.1/
* [B3] Bugzilla features: https://www.bugzilla.org/about/features
* [G1] GitHub Changelog, "Detecting Duplicate Issues – Public Preview" (2026-06-18): https://github.blog/changelog/2026-06-18-duplicate-detection-and-issue-fields-mcp-support-for-github-issues/
* [G2] GitHub Docs, "Creating an issue": https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-an-issue
* [G3] VS Code Docs, "Work with GitHub in VS Code": https://code.visualstudio.com/docs/sourcecontrol/github
* [G4] GitHub Enterprise Server documentation: https://docs.github.com/en/enterprise-server@3.21/graphql/reference/issues
* [L1] Linear Docs, "Triage Intelligence": https://linear.app/docs/triage-intelligence
* [L2] Linear Docs, "Triage": https://linear.app/docs/triage
* [L3] Linear, "How we built multi-region support for Linear" (Linear runs as a hosted service): https://linear.app/now/how-we-built-multi-region-support-for-linear
