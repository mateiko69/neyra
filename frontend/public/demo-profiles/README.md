# Demo profile photos

## Bundled avatar pool (recommended for seeds / repair)

The app also ships a small set of static JPEGs under **`shared/`**:

- `/demo-profiles/shared/avatar-01.jpg` … `avatar-12.jpg`

The backend maps each demo profile to one of these files deterministically (see `demo_bundled_photo_url` in `backend/app/services/demo_mode.py`).

## Layout (gender = folder only)

Put each profile under **`women/`** or **`men/`**, then `demo_NNN/main.jpg`:

| Example path (under `demo-profiles/`) | Catalog id | Gender |
|--------------------------------------|------------|--------|
| `women/demo_001/main.jpg` | `woman_demo_001` | woman |
| `men/demo_101/main.jpg` | `man_demo_101` | man |

The same folder name may exist under both trees (e.g. `women/demo_001` and `men/demo_001`) — they become **`woman_demo_001`** and **`man_demo_001`** (no duplicate ids).

Legacy **flat** `demo_001/main.jpg` (no `women/` or `men/`) is treated as **woman** only — prefer the nested layout for correct male profiles.

## Public URL

Served from the API at `/demo-profiles/...`, matching the relative path under `public/demo-profiles/`, e.g.:

- `/demo-profiles/women/demo_001/main.jpg`
- `/demo-profiles/men/demo_101/main.jpg`

## Regenerate catalog and reseed (full reset)

`seed_demo_profiles.py` **deletes all demo users** (`is_demo=true`) and related data, then recreates from JSON.

```bash
python backend/scripts/generate_demo_profiles_json.py
python backend/scripts/seed_demo_profiles.py
```

Docker:

```bash
docker compose exec api python scripts/generate_demo_profiles_json.py
docker compose exec api python scripts/seed_demo_profiles.py
```

Demo accounts are labeled in the app and do not represent real people.
