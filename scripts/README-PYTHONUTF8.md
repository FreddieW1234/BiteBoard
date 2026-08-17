# Local Python encoding (Windows)

Render sets `PYTHONUTF8=1` via `render.yaml`. For local shells on Windows:

```powershell
# Permanent (new shells only)
setx PYTHONUTF8 1

# Or per-run
python -X utf8 scripts/set_taxonomy_metafield.py scripts/data/taxonomy.json --allow-missing-handles
```

The app and taxonomy scripts also call `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` as the first executable statement so interpolated Unicode data does not crash on cp1252. Do not rely on `chcp 65001` alone.
