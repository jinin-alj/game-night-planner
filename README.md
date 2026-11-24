# Game Night Planner

I created a small web app that my board game friend group uses to keep track of the games we own between us and to plan our game nights. It suggests what to play based on who's coming, how much time we have, what we like, and what we haven't played in a while.

**Live:** https://jaoaljayyousieu2024ui.z28.web.core.windows.net

> **IMPORTANT:** the services sleep when nobody uses them, so the first visit after a while can take up to a minute and shows "starting up, try again in a moment". Reload after a minute and it works.

> **NEVER commit `.env`.** It holds the local passwords and is gitignored. The Azure passwords only live in GitHub Actions secrets.

## What it does

The app is split into two services, each with its own container and its own database:

- **Library** (`services/library/`): the games we own, who owns each one, player range and play time.
- **Group** (`services/group/`): members of the group, guests we invite, game nights, everyone's ratings of the games (on a scale of 1 to 10), what was played on each night, and the night planner.

Group asks library for data over HTTP (`GET /games/fit` and `GET /games/{id}`); it never touches library's database. If library is down, group keeps working for its own data and answers the night plan, ratings and plays with a clear 503 ("library is unavailable, try again later"). The UI (`ui/`) is static HTML, CSS and JavaScript that calls both services from the browser.

### How a night plan is built

1. How many players? Players = members coming + guests. Group asks library for the games that fit that many players in the time we have.
2. Every game gets a score: the average rating of the members coming + recency points (when's the last time we played this game?).
   - A member's rating is their own score. If nobody in the group has played the game yet it counts as 10, and if it was played but they haven't rated it, it counts as 5 (keeping it neutral).
   - Recency points: 1 point per full week since the game was last played, maximum 5. A game that was never played gets 5.
3. The planner fills the available time starting from the highest score, skipping games that don't fit in the time that's left.

Guests count as players, but their opinions don't count in the ratings.

## Run everything locally (one command)

You need Docker Desktop (on Apple Silicon, turn on "Use Rosetta for x86_64/amd64 emulation" in its settings, because the SQL Server image only exists for Intel/AMD).

```bash
cp .env.example .env
docker compose up --build
```

- UI: http://localhost:8080
- Library: http://localhost:8001 (for example http://localhost:8001/health)
- Group: http://localhost:8002

Compose starts SQL Server, runs `db/init.sql` once (it creates `library_db` and `group_db` with one user each, and is safe to run again), then starts both services, which apply their migrations on startup, and nginx serving `ui/`. Stop with `docker compose down`. **Never use `docker compose down -v`**, it deletes the database volume.

To see partial failure: `docker compose stop library`, then plan a night in the UI or call `curl -i -X PUT localhost:8002/ratings ...`; group answers 503 while `/members` keeps working. `docker compose start library` brings it back.

## Run a single service

Each service is its own Python project. With the compose SQL Server running (`docker compose up -d sqlserver db-init`):

```bash
cd services/library
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
set -a; source ../../.env; set +a
export DATABASE_URL="mssql://library_user:${LIBRARY_DB_PASSWORD}@localhost:1433/library_db"
python app.py
```

For group, use `group_user`, `${GROUP_DB_PASSWORD}` and `group_db`, and set `LIBRARY_URL=http://localhost:8001` if library runs on your machine too.

## Configuration

Every setting is an environment variable.

| Variable | Service | Default | What it does |
|---|---|---|---|
| `PORT` | both | `8000` | The port the service listens on. A value that isn't a number between 1 and 65535 falls back to 8000. |
| `DATABASE_URL` | both | none (secret) | `mssql://user:password@host:1433/database`. The service refuses to start without it. |
| `CORS_ORIGIN` | both | `http://localhost:8080` | The only web address allowed to call the service from a browser (the UI). |
| `APP_VERSION` | both | `dev` | The commit the image was built from, shown by `/health`. CD sets it to the commit SHA. |
| `LIBRARY_URL` | group | `http://library:8000` | Base URL of the library service. |
| `LIBRARY_TIMEOUT_S` | group | `2` | Seconds to wait for library before giving up. Anything that isn't a positive number falls back to 2. |

## Database and migrations

Each service has numbered migrations in `services/<name>/migrations/`. On startup the service waits for its database (retrying with growing pauses while an Azure database wakes up), then applies every file it hasn't recorded in its `schema_migrations` table yet, each in one transaction with its record. A second boot applies nothing. Applied migrations are never edited; a change is always a new file (ADR-7).

- library: `001_init.sql` (games)
- group: `001_init.sql` (members, nights, night_attendees, night_guests, ratings, plays), `002_night_date_as_date.sql` (turns `night_date` from text into a real `DATE`, keeping every night)

Library loads `library/seed.json` only when its games table is empty, so restarts never duplicate games.

## API

All requests and responses are JSON.

**Library** (port 8001 locally)

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | 200 `{"status":"ok","db":"ok","version":...}` when the service can read and write its own database, 503 otherwise |
| GET | `/games` | List all games |
| POST | `/games` | Add a game (`title`, `owner`, `min_players`, `max_players`, `playtime_minutes`) |
| GET | `/games/fit?players=4&minutes=120` | Games that fit 4 players in 120 minutes (called by group) |
| GET | `/games/{id}` | One game's id and title, or 404 (called by group) |

**Group** (port 8002 locally)

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Same as library, for group's own database only |
| GET | `/members` | List members, active and archived |
| POST | `/members` | Add a member (`name`) |
| POST | `/members/{id}/archive` | Archive a member who left (their history stays) |
| POST | `/members/{id}/reactivate` | Bring an archived member back |
| POST | `/nights` | Create a night (`night_date`, `available_minutes`, `attendee_ids`, optional `guest_names`) |
| GET | `/nights/{id}` | A night with its attendees and guests |
| POST | `/nights/{id}/plays` | Log a game played that night (`game_id`) |
| GET | `/nights/{id}/plan` | Suggested games for the night, best first |
| PUT | `/ratings` | Save or update a rating (`member_id`, `game_id`, `score` 1-10) |
| GET | `/reminders` | Games members played but haven't rated yet |

### Errors

| Status | When |
|---|---|
| 400 | Invalid input, e.g. a score of 11, a date that doesn't exist, text over 100 characters, or a missing field. The response says what's wrong. |
| 404 | Unknown member, night, game or URL |
| 503 | Group couldn't reach library (down, too slow or erroring), or `/health` can't use the database |
| 500 | Unexpected error. The real error is printed in the service log. |

Every request is logged as one line: method, path, status and duration, for example `GET /health 200 15ms`.

## Tests and coverage

The tests run against a real SQL Server (ADR-4 and ADR-9), so start it first with `docker compose up -d sqlserver db-init`. Each test empties its service's tables first, so **running the tests wipes the data you created locally**.

```bash
cd services/library
set -a; source ../../.env; set +a
export DATABASE_URL="mssql://library_user:${LIBRARY_DB_PASSWORD}@localhost:1433/library_db"
ruff check .
pytest --cov=library --cov=database --cov-report=term-missing --cov-fail-under=70
```

For group: `DATABASE_URL="mssql://group_user:${GROUP_DB_PASSWORD}@localhost:1433/group_db"` and `--cov=group --cov=database`. Group's tests replace library with a pretend library, so they don't need library running. In CI the coverage was 88.7% for library and 90.3% for group.

## How deployment works

- **CI** (`.github/workflows/ci.yml`) runs on every push to a branch and every pull request: for each service, ruff, pytest against SQL Server started from `docker-compose.yml`, the 70% coverage gate, and a Docker build.
- **CD** (`.github/workflows/deploy.yml`) runs on every push to main, which only happens through merged pull requests. It runs CI first (which also pushes both images to GHCR tagged with the commit SHA), signs in to Azure as a managed identity through OpenID Connect, points both Container Apps at the new images with their settings and secrets, uploads `ui/` with the Azure addresses in `config.js` to the storage website, and fails the run if `/health` on either service doesn't return 200 within a few minutes.

Azure resources, all in `rg-jaoaljayyous-ieu2024` (francecentral): storage account `jaoaljayyousieu2024ui` (UI), Container Apps environment `jaoaljayyous-ieu2024-env` with `jaoaljayyous-ieu2024-library` and `jaoaljayyous-ieu2024-group` (0 to 1 replica), its Log Analytics workspace, SQL server `jaoaljayyous-ieu2024-sql` with `jaoaljayyous-ieu2024-library-db` and `jaoaljayyous-ieu2024-group-db` (serverless, free offer), and the managed identity `jaoaljayyous-ieu2024-github`.

## Initial Azure setup (done once, by hand)

Run in bash (zsh breaks some of these commands), signed in with `az login` to the Azure for Students subscription. Passwords are read with `read -s` so they are never typed into a command or saved in the history; type each `read` line on its own.

```bash
PREFIX=jaoaljayyous-ieu2024
RG=rg-$PREFIX
LOCATION=francecentral
UI_STORAGE=jaoaljayyousieu2024ui
SQL_SERVER=$PREFIX-sql
GH_REPO=jinin-alj/game-night-planner

# 1. allowed regions, providers and the resource group
az policy assignment list --query "[].parameters.listOfAllowedLocations.value" -o json
for PROVIDER in Microsoft.App Microsoft.OperationalInsights Microsoft.Sql Microsoft.Storage Microsoft.ManagedIdentity; do
  az provider register --namespace $PROVIDER
done
az group create --name $RG --location $LOCATION

# 2. the UI's storage static website
az storage account create --name $UI_STORAGE --resource-group $RG --location $LOCATION --sku Standard_LRS --kind StorageV2
az storage blob service-properties update --account-name $UI_STORAGE --static-website --index-document index.html

# 3. SQL server, firewall for Azure services, two serverless databases on the free offer
read -s -p "SQL admin password: " SQL_ADMIN_PASSWORD; echo
az sql server create --name $SQL_SERVER --resource-group $RG --location $LOCATION --admin-user gnpadmin --admin-password "$SQL_ADMIN_PASSWORD"
az sql server firewall-rule create --resource-group $RG --server $SQL_SERVER --name AllowAzureServices --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
for SERVICE in library group; do
  az sql db create --resource-group $RG --server $SQL_SERVER --name $PREFIX-$SERVICE-db \
    --edition GeneralPurpose --compute-model Serverless --family Gen5 --min-capacity 0.5 --capacity 1 \
    --backup-storage-redundancy Local --use-free-limit true --free-limit-exhaustion-behavior AutoPause
done

# 4. one contained user per database, run from Azure Cloud Shell because my network blocks port 1433
#    (Cloud Shell has no sqlcmd, so download it first)
curl -sSL https://github.com/microsoft/go-sqlcmd/releases/latest/download/sqlcmd-linux-amd64.tar.bz2 | tar -xj -C ~
read -s -p "Azure library_user password: " AZURE_LIBRARY_DB_PASSWORD; echo
read -s -p "Azure group_user password: " AZURE_GROUP_DB_PASSWORD; echo
~/sqlcmd -S $SQL_SERVER.database.windows.net -d $PREFIX-library-db -U gnpadmin -P "$SQL_ADMIN_PASSWORD" -b -Q "CREATE USER library_user WITH PASSWORD = '$AZURE_LIBRARY_DB_PASSWORD'; ALTER ROLE db_ddladmin ADD MEMBER library_user; ALTER ROLE db_datareader ADD MEMBER library_user; ALTER ROLE db_datawriter ADD MEMBER library_user;"
~/sqlcmd -S $SQL_SERVER.database.windows.net -d $PREFIX-group-db -U gnpadmin -P "$SQL_ADMIN_PASSWORD" -b -Q "CREATE USER group_user WITH PASSWORD = '$AZURE_GROUP_DB_PASSWORD'; ALTER ROLE db_ddladmin ADD MEMBER group_user; ALTER ROLE db_datareader ADD MEMBER group_user; ALTER ROLE db_datawriter ADD MEMBER group_user;"

# 5. Container Apps environment (also creates the Log Analytics workspace) and the two apps with a placeholder image
az extension add --name containerapp --upgrade
az containerapp env create --name $PREFIX-env --resource-group $RG --location $LOCATION
for SERVICE in library group; do
  az containerapp create --name $PREFIX-$SERVICE --resource-group $RG --environment $PREFIX-env \
    --image mcr.microsoft.com/k8se/quickstart:latest --target-port 8000 --ingress external \
    --min-replicas 0 --max-replicas 1 --cpu 0.25 --memory 0.5Gi
done

# 6. the pipeline's identity: Contributor on this resource group only, trusted for runs on main of this repository
az identity create --name $PREFIX-github --resource-group $RG --location $LOCATION
PRINCIPAL_ID=$(az identity show --name $PREFIX-github --resource-group $RG --query principalId -o tsv)
RG_ID=$(az group show --name $RG --query id -o tsv)
az role assignment create --assignee-object-id $PRINCIPAL_ID --assignee-principal-type ServicePrincipal --role Contributor --scope $RG_ID
az identity federated-credential create --name github-main --identity-name $PREFIX-github --resource-group $RG \
  --issuer https://token.actions.githubusercontent.com --subject "repo:${GH_REPO}:ref:refs/heads/main" --audiences api://AzureADTokenExchange
# GitHub sends the subject with numeric ids, so that form is registered too
az identity federated-credential create --name github-main-numeric-ids --identity-name $PREFIX-github --resource-group $RG \
  --issuer https://token.actions.githubusercontent.com --subject "repo:jinin-alj@197924644/game-night-planner@1409407912:ref:refs/heads/main" --audiences api://AzureADTokenExchange

# 7. read access for grading
for PROFESSOR in amartini@faculty.ie.edu bserra@faculty.ie.edu; do
  az role assignment create --assignee $PROFESSOR --role Reader --scope $RG_ID
done
```

Then in GitHub, **Settings → Secrets and variables → Actions**:

- Repository secrets: `AZURE_CLIENT_ID` (the identity's client id), `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `LIBRARY_DB_PASSWORD`, `GROUP_DB_PASSWORD` (the Azure user passwords).
- Repository variables: `PREFIX`, `RESOURCE_GROUP`, `UI_STORAGE`, `UI_ORIGIN` (the website address without a trailing slash).

From then on only the pipeline changes anything. Logs: `az containerapp logs show --name jaoaljayyous-ieu2024-group --resource-group rg-jaoaljayyous-ieu2024 --type console --tail 50`.

## Project structure

```
services/library/    library service: app.py, config.py, database.py (connection + migration runner), library/ (routes, service, repository, seed.json), migrations/, tests/, Dockerfile, requirements*.txt
services/group/      group service: same layout, plus group/library_client.py (the HTTP calls to library)
ui/                  static UI: index.html, style.css, app.js, config.js (local addresses, replaced at deploy)
db/init.sql          creates the local databases and users, run by the db-init compose service
docker-compose.yml   SQL Server, db-init, library, group and nginx for the UI
.github/workflows/   ci.yml (every push and PR) and deploy.yml (main only)
system.schema.json   the provided schema for system.yaml
ADR.md               architecture decisions 1-10
AI_USAGE.md          log of how I used AI
```

## Known limitations

- There's no login. Anyone who has the address can change data; it's meant for our group only.
- The first visit after a quiet period is slow while Azure wakes the services and the database up (ADR-8 and ADR-10).
- Winners aren't tracked yet (see ADR-5).
- Two games can have the same title on purpose, since two people in the group can each own a copy.
- The reminders list asks library for one title per reminder, which is fine for our group's size (ADR-6).
- The images are built for Intel/AMD (what Azure runs). To run one from GHCR on an Apple Silicon Mac, add `--platform linux/amd64`.

## Maintenance

- Locally, to start from an empty database, run `docker compose down -v` (this deletes all local data) and then `docker compose up --build`.
- Errors and one line per request are printed to the terminal, `docker compose logs <service>`, or on Azure with `az containerapp logs show`.
- A schema change is always a new numbered file in `migrations/`, never an edit to an applied one.

## AI disclosure

I used AI assistants (Claude and Cursor) as described in AI_USAGE.md, including for drafting parts of this README, the ADRs and the infrastructure files. I reviewed every file, and I can explain each line.

## Author

Jinin AlJayyousi, IE University, October-November 2026
