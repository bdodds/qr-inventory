# QR Inventory

## Running it

Requires Docker Desktop.

```
docker compose up --build -d
```

Then open http://localhost:8000

This starts three containers:
- **app** - the Python app (port 8000)
- **db** - PostgreSQL 16, data stored in a named Docker volume (`pgdata`) so it survives container restarts and rebuilds
- **backup** - dumps the database to `./backups/` on a schedule

Stop everything with `docker compose down` (this keeps the `pgdata` volume; add `-v` to also wipe it).

View logs: `docker compose logs -f app` (or `db`, `backup`).

## Credentials

Defaults live in `docker-compose.yml` (db/user/password all `inventory`). To override, create a `.env` file next to `docker-compose.yml`:

```
DB_NAME=inventory
DB_USER=inventory
DB_PASSWORD=some-other-password
```

## Backups

The `backup` service runs `pg_dump` on a loop and writes gzip'd, timestamped dumps to `./backups/` (a real folder in this directory, not just inside Docker), e.g. `backups/inventory-20260729-220644.sql.gz`.

Defaults: every 24 hours, 14 days of history kept. Override in `.env`:

```
BACKUP_INTERVAL_SECONDS=3600
BACKUP_RETENTION_DAYS=30
```

**Restoring a backup:**

```
gunzip -c backups/inventory-20260729-220644.sql.gz | docker compose exec -T db psql -U inventory -d inventory
```

(Stop the `app` service first if you're restoring over an in-use database.)

I'm not a fan of how I've implemented this, I'll fix it later (along with everything else wrong with this, I assume)
