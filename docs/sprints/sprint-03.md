# Sprint 3

**Dates:** 09 Oct – 22 Oct 2026
**Sprint goal:** Submit a bug from VS Code and get a severity label, with a fallback when the AI service is down.

## Decisions (15 Oct)

- **Stack:** FastAPI + PostgreSQL 16 (report DC-02 and DC-04 to be updated).
- **Ownership:** Backend = Mohammed A., VS Code extension = Mohammed Naser, ML = Mohammed J., Lead / integration = Yaser.
- **docker-compose** belongs to #11 (Mohammed A.); **#14** is CI only (Yaser).
- All changes to `main` go through a reviewed pull request.
- Issues with an owner and done criteria go to **Ready**; unrefined ideas stay in **Backlog**.

## Sprint Planning

### Coding tasks (priority P0)

| Issue | Title | Owner | Due |
|:--|:--|:--|:--|
| #10 | [FR-05] Bug submission form in VS Code webview | Mohammed Naser | 22 Oct |
| #11 | [FR-05][FR-13] `POST /bugs` endpoint + DB schema + docker-compose | Mohammed A. | 22 Oct |
| #12 | [FR-11] Severity baseline: TF-IDF + voting ensemble | Mohammed J. | 22 Oct |
| #13 | [NFR-10] Fallback to "Unclassified" when AI is down | Mohammed A. | 24 Oct |
| #14 | [Integration] CI on PRs: lint + tests + coverage | Yaser | 17 Oct |

### Jury-feedback tasks

| Issue | Title | Owner | Column |
|:--|:--|:--|:--|
| #1 | Revise FRs: Admin role + developer profile management | Yaser | Ready |
| #2 | Cold-start strategy for new developer profiles | Mohammed J. | Ready |
| #3 | Use case diagrams for all actors | Mohammed Naser | Backlog |
| #4 | Agile workflow doc + sprint plan | Yaser | Backlog |
| #5 | CodeRabbit + Snyk roles | Yaser | Ready |
| #6 | Tech comparison table + finalize stack | Mohammed A. | Ready |
| #7 | ntfy vs ntfy.sh vs email | Mohammed A. | Backlog |
| #8 | Align diagrams with implementation | Yaser | Backlog |
| #9 | Novelty vs existing tools | Mohammed J. | Ready |

### Done so far (15 Oct)

- Project board made public; columns `Backlog → Ready → In progress → In review → Done`.
- All 14 issues assigned to an owner and placed in Sprint 3.
- Coding issues #10–#14 created and set to priority P0.
- Sprint records for Sprints 1–3 written (this folder).

## Stand-up Notes

| Date | Notes |
|:--|:--|
| 15 Oct | Board, owners, and stack confirmed. Next: CI PR (#14), first PR from each member. |
| | |

## Sprint Review (22 Oct)

- **Completed:**
- **Not completed:**
- **Supervisor feedback:**

## Retrospective (22 Oct)

- **What went well:**
- **What to improve:**
- **Action items for Sprint 4:**

## Risks

- No AI module integrated yet; testing starts in November. The severity model (#12) comes first; developer assignment (CNN-LSTM) is the biggest risk.
- The report still says "Flask or FastAPI" and "PostgreSQL or MySQL".
- Cold start (#2) must be designed before the assignment model is built.
- Adding the developer-profile FR changes the FR count from 19 to 20; update the report, README, and use case diagrams together.
