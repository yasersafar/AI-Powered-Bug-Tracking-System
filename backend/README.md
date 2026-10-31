# AI-Powered Bug Tracking System — Backend

FastAPI backend for the capstone project. This part (Part 2) covers the core
API, JWT authentication, and role-based access control.

## Requirements

- Python 3.11+

## Setup

```
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set a real secret key:

```
SECRET_KEY=<a long random value>
```

## Run

```
uvicorn app.main:app --reload
```

Open the interactive docs at http://127.0.0.1:8000/docs

## Test

```
python -m pytest
```

## Roles

`reporter`, `developer`, `project_manager`, `administrator`

## Main endpoints

| Method | Path | Who can use it |
|--------|------|----------------|
| POST | `/auth/register` | anyone |
| POST | `/auth/login` | anyone (returns a JWT) |
| GET | `/projects` | any logged-in user (sees only their projects; admin sees all) |
| POST | `/projects` | project manager, administrator |
| GET | `/projects/{id}` | members of that project, or administrator |
| POST | `/projects/{id}/archive` | project manager, administrator |
| POST | `/projects/{id}/members` | project manager, administrator |
