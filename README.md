# CollectFlow — Requirements, RBAC, and Operations

CollectFlow is an intelligent collection operations and recovery management platform for agencies serving multiple client portfolios. This implementation uses a Python REST-style server, MySQL 8, and a browser-based interface.

## System requirements from the proposal

- Client portfolio management with per-client data separation
- Collection account management, validation, assignments, and prioritized queues
- Collector workload monitoring and escalation visibility
- Promise-to-pay records with due-date and status monitoring
- Account activity history and follow-up records
- Payment and recovery monitoring
- Operational dashboards and reports for aging, balance, activity, workload, and client performance
- AI-assisted interaction-note summaries that require human review before official use
- Strategy simulation for comparing prioritization approaches
- Audit trail, authentication, authorization, and notifications/follow-up task generation

## Role and access matrix

| Role | Read access | Write/admin access |
| --- | --- | --- |
| System Administrator | All agency modules, users, and audit history | Accounts, assignments, promises, payments, tasks, clients, user lifecycle, delete operations |
| Collection Supervisor | Agency queues, accounts, promises, activities, tasks, clients, reports | Account assignments/status, promises, payments, activities, tasks, clients |
| Collector | Assigned accounts, activity timeline, promises, payments, and own follow-up tasks | Assigned account status, activities, promises, payments, own tasks |
| Client | Own portfolio, account status, collection activity, and reports | None |
| Management | Organization analytics, reports, queue strategy simulation | None |

The server checks a database-backed session and role permission for every API route. Collector and client reads are filtered to their assigned name or linked client portfolio. The interface hides unavailable modules, but server-side checks are authoritative.

## Implemented in this phase

- MySQL persistence for clients, accounts, promises, activities, users, sessions, and audit logs
- PBKDF2-SHA256 password hashing and random, expiring, database-backed sessions
- Admin user creation, role assignment, client portfolio association, and account activation/deactivation
- Supervisor collector assignment and operational escalation/status updates
- MySQL-generated account numbers in `ACC-<year>-<sequence>` format; users do not enter IDs manually
- Collector-owned account status updates, interaction recording, promise/payment entry, and follow-up task completion
- Promise statuses (upcoming, due, fulfilled, broken), with automatic task generation for broken commitments
- Payment records linked to promises, account balance reduction, and fulfilled-PTP detection
- Admin delete controls for accounts, promises, payments, activities, tasks, users, and eligible empty client portfolios; changes are audited
- Auditable login/logout and business/admin mutations
- Server-enforced RBAC on read and write APIs
- Dashboard metrics, account registry, activity timeline, promises, payments, follow-up tasks, clients, reports, strategy simulation, user administration, and audit views
- Persistent Docker Compose deployment with a MySQL health check and named data volume

The interaction-documentation helper creates a structured draft from collector notes and requires review before saving; it is a local template, not an external AI/LLM integration. Broken promises create durable follow-up tasks when promise data is refreshed. Outbound SMS/email notifications and scheduled background execution are not connected. Bulk CSV account import is also not implemented; accounts are currently entered individually.

## Configure MySQL and the initial administrator

Docker and Docker Compose are required for the supported deployment. Create a local environment file and set unique secrets before starting:

```bash
cd /home/diether/Desktop/CollectFlowProject/phase3
cp .env.example .env
```

Edit `.env`. Set strong unique values for `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`, and `COLLECTFLOW_ADMIN_PASSWORD`; do not deploy the example values. The initial administrator username defaults to `admin` and its password is taken from `COLLECTFLOW_ADMIN_PASSWORD`. Passwords are hashed before storage. Demo portfolio seeding is disabled by default; set `COLLECTFLOW_SEED_DEMO_DATA=true` only for a demo environment.

On Ubuntu or Debian, the installer [install_test_environment.sh](install_test_environment.sh) installs Docker Engine, the Compose plugin, Python tooling, and project dependencies; creates a local `.env` with random credentials if needed; starts the app and bundled MySQL; imports the existing SQLite business records; then runs tests and authenticated API smoke checks:

```bash
cd /home/diether/Desktop/CollectFlowProject/phase3
bash install_test_environment.sh
```

The script requests `sudo` for system packages and Docker installation. MySQL 8 runs in its own Compose service; a separate host MySQL install is not required. It does not overwrite an existing `.env`.

## Deploy with Docker Compose

From the `phase3` directory, build and start both the app and MySQL 8:

```bash
docker compose up --build -d
```

Wait until both services report healthy:

```bash
docker compose ps
```

Open <http://localhost:8001> and sign in with `COLLECTFLOW_ADMIN_USERNAME` and `COLLECTFLOW_ADMIN_PASSWORD` from `.env`. Create active Collector users in User Administration before assigning accounts; new account numbers are generated by MySQL when saved. Verify database connectivity with `http://localhost:8001/health`.

The database survives container restarts in the `collectflow_mysql_data` named volume. Inspect service logs with:

```bash
docker compose logs -f collectflow
docker compose logs -f mysql
```

Stop the services without deleting data:

```bash
docker compose down
```

Do not use `docker compose down -v` unless you intend to permanently delete the database volume.

### Import records from the previous SQLite prototype

For an existing SQLite installation, back up `collectflow.db`, start MySQL with Compose, then run the importer inside the app container:

```bash
docker compose exec collectflow python migrate_sqlite_to_mysql.py --source /migration/collectflow.db
```

The importer is idempotent for clients and accounts and skips matching promises and activities. It reports and skips legacy promises that have no matching account, preserving MySQL referential integrity. Legacy user credentials are deliberately excluded because the prototype stored plaintext/demo passwords; create replacement users from User Administration.

## Development and tests

Install dependencies and configure a reachable MySQL database using the same environment variables, then run:

```bash
python3 -m pip install -r requirements.txt
python3 -m unittest test_logic.py test_server.py
python3 server.py
```

The server will initialize the schema, then listen on port 8001. Demo rows are seeded only when `COLLECTFLOW_SEED_DEMO_DATA=true`. It creates the bootstrap administrator only when the `users` table is empty. Create Collector users before assigning accounts to them; the assignment picker includes active Collector-role users only.

## Security and production deployment notes

- Keep `.env` out of version control and restrict access to database backups.
- Use HTTPS in production and set `SESSION_COOKIE_SECURE=true` behind a correctly configured TLS-terminating proxy.
- Change the initial administrator password and remove any unused accounts after bootstrap.
- The built-in Python HTTP server is suitable for this coursework prototype; use a maintained production application server and reverse proxy for public/high-volume deployment.
- Keep the previous SQLite file as a backup until imported records have been verified in MySQL.
