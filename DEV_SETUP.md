## NEYRA dev setup

### Start the stack

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
cp mobile/.env.example mobile/.env
docker compose up --build
```

### Restart safely (keep your database)

Restarting containers **does not delete** the Postgres volume as long as you don’t use `-v`.

- **Safe restart (recommended)**:

```bash
docker compose down
docker compose up --build
```

On Windows/PowerShell, you can also run:

```powershell
.\scripts\dev_restart.ps1
```

### Reset the dev database (destructive)

`docker compose down -v` **deletes the Postgres volume** (`postgres_data`) and wipes all dev data, including user profiles.

- **Destructive reset (only when you intentionally want a clean DB)**:

```bash
docker compose down -v
docker compose up --build
```

On Windows/PowerShell, prefer the guarded script:

```powershell
.\scripts\dev_reset_db.ps1
```

It requires typing exactly:

```text
RESET NEYRA DB
```

