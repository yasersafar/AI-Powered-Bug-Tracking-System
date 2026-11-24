# User guide

1. [Install](#1-install)
2. [Your first bug in under 5 minutes](#2-your-first-bug-in-under-5-minutes) (NFR-11)
3. [Everyday use by role](#3-everyday-use-by-role)
4. [Administrator guide](#4-administrator-guide)
5. [Production: TLS and operations](#5-production-tls-and-operations) (NFR-05, NFR-09)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Install

### Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Docker with Compose v2 | Docker Desktop, or Colima on macOS (`brew install colima docker docker-compose`) | PostgreSQL, ntfy, Mailpit, backend |
| Python | 3.11 | Developer tools, seed data, ML training |
| Node.js | 22 | Building the VS Code extension |
| VS Code | 1.100 or newer | The extension |
| make | any | Shortcuts below |

### Start the server

```bash
git clone https://github.com/yasersafar/AI-Powered-Bug-Tracking-System.git
cd AI-Powered-Bug-Tracking-System
make install      # backend/.venv (backend, ML runtime, dev tools) + extension npm packages
make up           # creates .env with fresh secrets, builds and starts db, ntfy, mailpit, backend
make seed         # optional: demo users, 2 projects, 50 bugs (password = SEED_PASSWORD in .env)
```

`make up` waits until every container is healthy. The API answers on
<http://localhost:8000> (interactive docs at <http://localhost:8000/docs>), Mailpit on
<http://localhost:8025>, ntfy on <http://localhost:8080>.

### AI models (once)

The backend works without the models: every bug is then saved as `Unclassified` with a
notice. To enable AI triage, build the models once (about an hour on a laptop CPU):

```bash
make install-ml data model-download train
```

Restart the backend afterwards (`docker compose restart backend`). `GET /api/v1/ai/status`
(or the result page after a submission) shows whether the models are loaded.

### Install the extension

```bash
make package-extension
code --install-extension extension/ai-bug-tracker-0.2.0.vsix
```

Or in VS Code: **Extensions** → `…` → **Install from VSIX…**.

---

## 2. Your first bug in under 5 minutes

Time a new user needs, assuming the server is running and you have an account in a
project (step 2 shows how to get one).

| Step | Do this | You see |
|---|---|---|
| 1 | Click the **Bug Tracker** icon (bug) in the activity bar. If the server is not `http://localhost:8000`, run **Bug Tracker: Set Server URL** first. | "Log in to see the bugs assigned to you." |
| 2 | Click **Log In**, enter e-mail and password. No account? Click **Create Account** (password: 8+ characters, an uppercase letter, a number and a symbol), then ask your Project Manager to add you to the project. | Status bar shows your name; *Project Bugs* lists your projects. |
| 3 | Click **+** (**Report Bug**) at the top of *My Assigned Bugs*. | The Report Bug form. |
| 4 | Choose the project and type a title and a description (at least 20 characters: what happens, what you expected). | After a short pause, **Possible duplicates** lists similar reports with a similarity. |
| 5 | If one of them is your bug, open it and add a comment instead, then click **Discard**: nothing is saved. Otherwise continue. | |
| 6 | Fill in **Steps to reproduce** and **Environment**; optionally components and files (**Add files…**, up to 10 MB each). | |
| 7 | Click **Submit bug**. | "Bug #N submitted" with the predicted severity and three recommended developers with reasons. |

If the AI is unavailable the bug is still saved and the page says
**"AI unavailable – severity set to Unclassified"** with the reason.

---

## 3. Everyday use by role

| Task | Reporter | Developer | Project Manager | Administrator |
|---|---|---|---|---|
| Report a bug, comment, attach files | ✓ | ✓ | ✓ | ✓ |
| Search (**Search Bugs**: words plus `status:` `severity:` `project:` `assignee:me` `reporter:me` `since:` `until:`) | ✓ | ✓ | ✓ | ✓ |
| Verify a fix or reopen it (Resolved → Verified / In progress) | ✓ (own bugs, or as project Reporter/QA) | | | ✓ |
| Start work, mark resolved (as assignee) | | ✓ | ✓ (start) | ✓ |
| Change severity (audited) | | ✓ | ✓ | ✓ |
| Assign a developer (recommended ones are marked) | | | ✓ | ✓ |
| Close (Verified → Closed; Open → Closed as invalid/duplicate) | | | ✓ | ✓ |
| Dashboard (**Open Dashboard**) | ✓ | ✓ | ✓ | ✓ |
| Create projects, add members (**Create Project**, **Add Project Member**) | | | ✓ | ✓ |
| Developer profiles, tracking, AI thresholds (**Admin: Manage Developer Profiles**) | | | | ✓ |

Notes:
* Assigning an Open bug moves it to *In progress* and notifies the developer.
* Every change (fields, status, assignee, severity) is in the bug's **History** with who,
  when (UTC), old and new value.
* Archived projects are read-only.
* **My Profile and Notifications**: change your name and password, switch e-mail or push
  notifications off, and copy your personal ntfy topic. To get push notifications on a
  phone, install the ntfy app, add the team's ntfy server and subscribe to that topic.

---

## 4. Administrator guide

Open **Bug Tracker: Admin: Manage Developer Profiles** (only visible to Administrators).

### Developer profiles (FR-20)

Create a profile for every user with the Developer role: skills, components, languages,
experience level, availability (`Available`, `Limited`, `Unavailable`) and maximum workload.
The recommender compares a new report with these words, so use the same component names as
the bug reports. **Deactivate** keeps the history but removes the developer from
recommendations.

### Developer tracking (FR-21)

Per developer: resolved bugs, average resolution time, reassignments, current workload,
and α, the weight of their history in recommendations (α = min(1, resolved / N)).
Developers with fewer than N resolutions are marked **cold start**.

### AI thresholds and switches (NFR-14)

Changes apply to the next request; no restart is needed.

| Setting | Default | Meaning |
|---|---|---|
| `ai_enabled` | 1 | 0 switches AI triage off (bugs saved as Unclassified). Use for maintenance or the "AI down" demo. |
| `duplicate_min_score` | 0.5 | Lowest similarity shown as a possible duplicate |
| `duplicate_likely_threshold` | 0.8 | Similarity at which a report is a *likely* duplicate (boosts the fixer of the original) |
| `duplicate_top_k` | 3 | Number of duplicate candidates |
| `cold_start_threshold` | 10 | N: resolutions after which a developer is no longer cold start |
| `exploration_rate` | 0.1 | ε: chance that slot 3 goes to the best cold-start developer |
| `availability_bonus` | 0.1 | Added to the profile score of Available developers |
| `duplicate_timeout_ms` / `severity_timeout_ms` / `assignment_timeout_ms` | 1200 / 1200 / 2500 | Time budget per step; a slower step is marked degraded |

### Retraining the recommender on your own history

Once at least two developers have N or more resolutions, train the CNN-LSTM on this
database and restart the backend:

```bash
make train-live
docker compose restart backend
```

Until then, history is measured as the similarity between a new report and the reports each
developer has resolved.

---

## 5. Production: TLS and operations

The development stack binds every port to `127.0.0.1` and uses HTTP. In production, put a
reverse proxy with TLS 1.2+ in front of the backend (NFR-05), for example nginx:

```nginx
server {
    listen 443 ssl;
    server_name bugtracker.example.org;
    ssl_certificate     /etc/ssl/bugtracker/fullchain.pem;
    ssl_certificate_key /etc/ssl/bugtracker/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 11m;            # attachments are limited to 10 MB

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Then set **Bug Tracker: Set Server URL** to `https://bugtracker.example.org` in VS Code.

Operations:
* Health: `GET /health`; Docker restarts the backend automatically (`restart: unless-stopped`, NFR-09).
* Scale: `WEB_CONCURRENCY` sets the number of worker processes (about 1.6 GB each with
  a 50,000-report index); `ML_THREADS` the inference threads per step.
* Secrets: generated by `make env` into `.env` (git-ignored); keep a backup of it.
* Backups: the `pgdata` volume (`docker compose exec db pg_dump …`) and the `attachments`
  volume.
* Upgrades: the backend runs `alembic upgrade head` on start.

---

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Status bar shows **Bug Tracker offline** | The server is not reachable. Check `make ps`; click the status bar to retry. Your form text is kept and nothing is sent later automatically. |
| "AI unavailable – severity set to Unclassified" | The models are not built, still loading (about 15 s after start), switched off (`ai_enabled = 0`), or a step was too slow. `GET /api/v1/ai/status` shows which. A Developer or PM can set the severity by hand. |
| "Too many login attempts" | 10 logins per minute per address are allowed; wait a minute. |
| No duplicates are suggested | Duplicates are only searched in the same project, and only matches above `duplicate_min_score` are shown. |
| No push notifications on the phone | Subscribe to your own topic (**My Profile → Copy my ntfy topic**) on the team's ntfy server, not on ntfy.sh. |
