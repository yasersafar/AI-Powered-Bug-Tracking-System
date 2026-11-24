# Supervisor demo (5–7 minutes)

Uses the seed data (`make seed-reset`). Every step below was checked against the seeded
system; similarity values and severities can differ slightly between model builds.

## Before the demo (5 minutes, not part of the timing)

```bash
make up            # wait for "healthy"
make seed-reset    # fresh demo data (deletes everything else in the demo database)
```

* Models built (`make train` once); `http://localhost:8000/api/v1/ai/status` shows `"state": "ready"`.
* Extension installed (`code --install-extension extension/ai-bug-tracker-0.2.0.vsix`).
* Accounts (password = `SEED_PASSWORD` in `.env`):
  `rita@example.com` (Reporter), `pm@example.com` (Project Manager),
  `dana@example.com` (Developer), `admin@example.com` (Administrator).
* Open `docs/results/RESULTS.md` and `docs/diagrams/architecture.png` in tabs.
* Close other VS Code notifications.

## Script

| Time | Who / where | Do | Say |
|---|---|---|---|
| 0:00 | `architecture.png` | Show the diagram. | "A VS Code extension and a FastAPI backend. Three AI steps (duplicates, severity, assignment) run inside the backend on CPU and share one context. No report text leaves our server." |
| 0:45 | VS Code, log in as **rita** | Activity bar → Bug Tracker → Log In. | "Reporters see their projects grouped by status." |
| 1:00 | **Report Bug** (Payments Platform) | Title: `Customer charged twice when pressing Pay two times`. Description: `The customer pays once but the card is charged two times when the Pay button is clicked twice quickly.` Wait a moment. | "While I type, the system checks this project's reports: BM25 finds candidates, a local sentence model re-ranks them." Point at **#33** and **#3** with their similarity and the *likely duplicate* warning. |
| 1:45 | same | Click **Discard** → Discard. | "A duplicate caught before it is stored: nothing was saved." |
| 2:00 | **Report Bug** again | Title: `Refund endpoint returns HTTP 500 for partial captures`. Description: `Refunding a partially captured payment through the payments API fails with an internal server error 500.` Steps: `1. Refund a partially captured payment`. Environment: `payments-api v2.14`. Components: `payments-api`. Submit. | "On submit the shared pipeline runs: duplicate, severity, then assignment." Show the predicted severity with confidence, **Dana Lee – history match** with *fixed the original of this likely duplicate*, and similar report **#1**. "The duplicate result is an input to assignment: that is the shared state." |
| 3:00 | Report Bug again | Title: `OAuth login fails after JWT session expires`. Description: `Users are logged out and the oauth jwt refresh fails on the auth sessions page.` Steps/Environment: anything. Components: `auth`. Submit. | "Cold start: **Leo Novak** has never resolved a bug, so his history weight α is 0, but his profile (oauth, jwt, auth) matches: he is recommended first as *new developer (cold start)*." |
| 3:45 | Log out; log in as **admin** → **Admin: Manage Developer Profiles** | Scroll to *Developer tracking* and *AI thresholds*. Set `ai_enabled` to 0 → Save settings. | "Developers' resolved counts, reassignments, workload and α. Thresholds change at run time without a redeploy. Now I switch the AI off to show graceful degradation." |
| 4:15 | **Report Bug** (as admin, Payments) | Any title/description, Submit. | Show **"AI unavailable – severity set to Unclassified"**: "The bug is still saved; a Developer or PM sets the severity." |
| 4:35 | Admin page | Set `ai_enabled` back to 1 → Save. | |
| 4:45 | Log in as **pm** → open the refund bug from 2:00 | **Assign to** → Dana Lee (recommended) → Assign. | "Assigning starts the work (In progress) and notifies Dana by e-mail, push and in VS Code." Optionally show the mail in Mailpit (`localhost:8025`). |
| 5:15 | same bug | Scroll to **History**. | "Every change: who, when in UTC, old → new value; including the severity predicted by the AI." |
| 5:30 | **Open Dashboard** | Show counts by status and severity, bugs per day, average resolution time. | "Charts are plain SVG with data tables for screen readers." |
| 6:00 | `RESULTS.md` | Scroll the table. | "Every number comes from a script. Met: reassignments −88.9% vs random on Eclipse, latency 160 ms (target 1.5 s), 100 concurrent users. Not met and explained: severity accuracy 75.8% (target 85%), duplicate Recall@5 53–66% (target 80%), and the 50-user latency degradation." |
| 6:45 | | Questions. | |

## If something goes wrong

* **No duplicates appear:** check that the project is *Payments Platform* and the AI status
  is `ready`.
* **Leo is not first:** run `make seed-reset` (earlier demo bugs change the history) and
  make sure `cold_start_threshold` is 10.
* **Login refused with "Too many login attempts":** wait one minute (10 logins per minute).
