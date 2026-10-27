# Relay: lab resource booking

Book shared lab instruments and meeting rooms with access rules decided by each lab's professor. Double-booking is impossible: the database enforces it.

- **What and why:** [`spec.md`](spec.md)
- **How, in what order, and status:** [`plan.md`](plan.md)
- **Running it in production:** [`docs/operations.md`](docs/operations.md)
- **10-minute demo walkthrough:** [`docs/demo-script.md`](docs/demo-script.md)

## Run it locally

You need **Docker Desktop** (with WSL 2 on Windows). Nothing else.

```sh
docker compose up --build
```

| What | Where |
|---|---|
| App | http://localhost:5173 |
| API docs (OpenAPI) | http://localhost:8000/api/docs |
| Mailpit (every email the app sends) | http://localhost:8025 |

On start-up the API runs migrations and loads the seed data from [`backend/seed/institute.yaml`](backend/seed/institute.yaml): 14 departments, 30 labs, 104 resources and 134 people, all fictional, built from `instruments_list`.

### Demo accounts

Every seeded account uses the password **`relay-demo-pass`**.

| Who | Email | Shows |
|---|---|---|
| Super admin | `admin@relay.test` | everything, admin pages |
| Professor (PHY, Quantum Materials Lab) | `pooja.rao@relay.test` | inbox, lab settings, reports |
| Department admin (PHY) | `aditya.verma@relay.test` | verification queue, department labs |
| Student (PHY, Quantum Materials Lab) | `priya.joshi@relay.test` | booking own lab's instruments |
| Visitor with one grant | `guest@relay.test` | access requests, a granted Raman booking |
| Awaiting department verification | `new.student@relay.test` | only open resources until verified |

Every lab's professor, HOD and students are listed in `backend/seed/institute.yaml`.

## Share a public demo link

```sh
docker compose --profile public up -d
docker compose logs tunnel        # look for https://<random>.trycloudflare.com
```

Anyone can open that address in a browser and sign in with the demo accounts. It works only while this computer and Docker are running, and the address changes each time the tunnel restarts. Stop sharing with `docker compose stop tunnel`. For a permanent address, deploy `docker-compose.prod.yml` to a server (see `docs/operations.md`).

## Run the backend without Docker

You need a PostgreSQL 16 server with the `btree_gist` and `citext` extensions available. These ship with the standard installers.

```sh
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # bin/ on macOS/Linux
set RELAY_DATABASE_URL=postgresql+psycopg://relay:relay@localhost:5432/relay
set RELAY_COOKIE_SECURE=false
set RELAY_DEV_EXPOSE_TOKENS=true   # local only; never with a public link
alembic upgrade head && python -m scripts.seed
uvicorn app.main:app --reload            # API on :8000
python -m app.worker.main                # background jobs (separate terminal)
```

Then start the frontend in another terminal:

```sh
cd frontend && npm install && npm run dev
```

## Tests

```sh
cd backend
pytest -q                                         # pure logic only: permissions matrix, rules, DST
set RELAY_TEST_DATABASE_URL=postgresql+psycopg://relay:relay@localhost:5432/relay_test
pytest -q                                         # + every DB-backed acceptance test (AC-B*, AC-R*, AC-S*)
cd ../frontend && npx vitest run && npx tsc -b
```

Inside Docker, run `docker compose exec api pytest -q`. The test database `relay_test` is created automatically.

## Layout

```
backend/   FastAPI app (app/), Alembic migration, worker, seed, tests
frontend/  React + Vite + Tailwind; FullCalendar for the week view
deploy/    backup script, Postgres init
docs/      operations runbook, demo script
```
