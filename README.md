# Shopify Component Toolkit

This repository powers the internal tooling for creating and managing **Components** on Shopify (Mixed Product, Finished Product, Base Product, Ingredient, and Sub Ingredient). The backend is a Flask service that speaks to Shopify via the GraphQL Admin API (version `2025-07`) for uploads, metafield management, and component pricing utilities.

---

## Requirements

- Python 3.11+ (matches Render's current Python runtime)
- A Shopify Admin API access token with the required scopes
- GitHub account with the repository connected to Render

---

## Environment Variables

Copy the provided sample file and keep real values out of Git history:

```powershell
Copy-Item env.example .env
```

Fill in `.env` with the following keys:

- `SHOPIFY_STORE_DOMAIN` – e.g. `acme-shop.myshopify.com`
- `SHOPIFY_API_VERSION` – defaults to `2025-07` if omitted
- `SHOPIFY_ACCESS_TOKEN` – Admin API access token (never commit this)
- `OFFICE_API_URL` – base URL of the Office Order API (e.g. `https://orders-api.bitepromotionsportal.co.uk`)
- `OFFICE_API_KEY` – secret API key for the Office Order API (server-side only; never expose to the browser)

Optional:

- `MAX_UPLOAD_MB` – max artwork/proof upload size in MB (default `500`, matches Office API cap)
- `ORDER_ACCESS_CACHE_TTL_SEC` – seconds to cache order ownership/name for file proxy routes (default `300`)

> **Tip:** In Render, define the same variables under **Service → Environment → Environment Variables**.

---

## Local Development (PowerShell)

```powershell
cd "D:\Work\Shopify App - Test"
python -m venv backend\venv
backend\venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r backend\requirements.txt
Copy-Item env.example .env
# edit .env with your Component store settings
$env:FLASK_APP = "backend.app"
flask run --reload
```

Key behaviours to verify locally:

- Component creation keeps a single shared code system and enforces unique component codes.
- Navigation layout remains consistent with the approved global nav pattern.
- File uploads use the Shopify GraphQL Admin API end-to-end.

---

## Preparing for GitHub

- Secrets are externalised to `.env`; `.gitignore` blocks `.env`, virtual environments, and local credential files.
- Commit the deployment assets (`render.yaml`, `backend/requirements.txt`, `env.example`, documentation).
- Update commit history to remove any previously committed tokens (use Git history rewriting if necessary).

---

## Deploying on Render

1. Push the repository to GitHub.
2. In Render, create a **New Web Service** and connect the GitHub repo.
3. When prompted, Render reads `render.yaml` to configure the service (builds with `pip install -r backend/requirements.txt`, starts `gunicorn app:app --chdir backend --bind 0.0.0.0:$PORT`).
4. Set `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_API_VERSION`, and `SHOPIFY_ACCESS_TOKEN` as environment variables in the service settings (keep tokens hidden).
5. Deploy. After each build, run smoke tests for OAuth, GraphQL file management, Component CRUD, and the nav layout before promoting to production.

Preview instances let you validate Component terminology, nav layout, and pricing tools ahead of go-live.

---

## Operational Notes

- GraphQL uploads stream progress to keep large artwork files stable.
- Every record exposed to users is labelled “Component” (per design direction) with subtype context where relevant.
- Audit logs and troubleshooting rely on the verbose console output in `backend/app.py`; retain these logs during incidents.
- If you need additional dependencies, pin them in `backend/requirements.txt` to keep Render and local environments aligned.

