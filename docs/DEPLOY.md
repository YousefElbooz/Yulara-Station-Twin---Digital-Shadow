# Deploying the twin for free: Vercel (website) + Render (API) + private Hugging Face dataset (data)

```
 browser ──► https://<project>.vercel.app        static site (Vercel)
              └─ /api/* ──► Vercel function api/proxy.js ──► https://<service>.onrender.com/api/*
                                                              FastAPI + twin loop (Render free web service,
                                                              built from GitHub with deploy/Dockerfile.render)
                                                                 └─ on start: deploy/fetch_data.py downloads the
                                                                    run-time data from a PRIVATE HF dataset (read token)
```

**Why three pieces:**
- The twin is a long-running process, so it runs on Render. Vercel only runs short functions.
- The data (≈ 110 MB, DKASC / Copernicus) must not be in git or in a public image, so it lives in a **private** Hugging Face dataset.
- Hugging Face Docker Spaces and a second private Docker Hub repo both need paid plans now, so they are not used.

**Tested locally on 2026-11-21:**
- anonymous download from the dataset → 401;
- the Render image fetched all 8 files in ≈ 40 s, the twin ran, and `/api/now`, `/scene` and `/station` returned 200;
- ≈ 350 MB RAM (Render free: 512 MB).

## Before you publish

- **DKASC data:** the site shows measured power and sensor series. DKASC asks for **consent above 5,000 cells**. Get their OK before sharing the link.
- **Keep the dataset private.** `push_hf_data.py` creates it private and refuses a public one.
- **Never put tokens in code or git.** Tokens go only into the hosts' environment-variable settings.

## 1. Data → private Hugging Face dataset (done once; repeat after re-running the pipeline)

```powershell
.venv\Scripts\hf.exe auth login
```

```powershell
.venv\Scripts\python deploy\push_hf_data.py YosefElbooz/yulara-twin-data
```

## 2. API → Render (free web service)

On render.com → New → **Web Service** → connect the GitHub repo:

| Setting | Value |
|---|---|
| Language / runtime | **Docker** |
| Dockerfile path | `deploy/Dockerfile.render` (root directory: empty) |
| Instance type | **Free** |
| Health check path | `/api/health` |
| Env `HF_DATASET` | `YosefElbooz/yulara-twin-data` |
| Env `HF_TOKEN` | a Hugging Face **read** token (paste it yourself) |

**Free tier behaviour:** the service sleeps after 15 min without traffic. The next visit wakes it in about 1–2 min: start-up, data download, then the twin warms up. The site shows "waking up" and recovers by itself.

## 3. Website → Vercel

On vercel.com → Add New → **Project** → import the GitHub repo:
- **Root Directory:** `frontend`.
- **Env `TWIN_API_URL`:** `https://<service>.onrender.com`, with no trailing slash.
- `HF_TOKEN` is **not** needed: the Render API is called directly by the proxy.

## Files

| File | Role |
|---|---|
| `deploy/Dockerfile.render` | API image for Render: code only, fetches its data on start |
| `deploy/fetch_data.py`, `deploy/data_files.py` | start-up download of the 8 run-time files (standard library only) |
| `deploy/push_hf_data.py` | uploads those files to the private dataset |
| `Dockerfile`, `.dockerignore` | local all-in-one image with the data copied in (for testing) |
| `requirements-runtime.txt` | the API's run-time packages (no torch or training stack) |
| `frontend/vercel.json`, `frontend/api/proxy.js` | Vercel build + `/api/*` proxy (`TWIN_API_URL`, optional `HF_TOKEN`) |
| `deploy/push_hf_space.py` | the earlier private-Space route (needs HF PRO); kept for reference |
