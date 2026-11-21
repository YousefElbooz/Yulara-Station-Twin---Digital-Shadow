# Deploying the twin for free: Vercel (website) + Hugging Face Space (API)

```
 browser ──► https://<project>.vercel.app            (static site, Vercel)
              └─ /api/*  ──► Vercel function api/proxy.js ──(Bearer HF_TOKEN)──► https://<user>-<space>.hf.space/api/*
                                                                                  (private Docker Space: FastAPI + twin loop)
```

**Why two hosts:** the twin is a long-running process (a background loop, SQLite, ≈ 110 MB of data). Vercel only runs short functions, so the API runs in a free Docker Space, and Vercel serves the site and forwards `/api`.

**Tested locally on 2026-11-21:**
- the container answers every endpoint, and `/api/scene` returns 503, not 500, while the twin starts;
- the production build, served through the same proxy, shows live data and the 3D view with no console errors;
- the container uses ≈ 390 MB of RAM.

## Before you publish (important)

- **DKASC data:** the site shows measured power and sensor series. DKASC asks for **consent above 5,000 cells** of their data. Get their written OK before making the link public.
- **Keep the Space private.** `push_hf_space.py` refuses to upload to a public Space.
- **Never upload `.env`** (it holds the CDS key). It is not needed at run time, and the script does not include it.

## 1. API on Hugging Face (once)

1. Create a Hugging Face account → **New Space**:
   - SDK **Docker**, template **Blank**;
   - visibility **Private**;
   - hardware **CPU basic (free)**.
2. Settings → Access Tokens: create a **write** token (for uploading). Later, create a **read** token for Vercel.
3. In PowerShell, from the project folder:

```powershell
.venv\Scripts\pip install huggingface_hub
```

```powershell
$env:HF_TOKEN = "<write token>"
```

```powershell
.venv\Scripts\python deploy\push_hf_space.py <hf-username>/<space-name>
```

4. Wait for the Space to build (≈ 5 min, in the Space's Logs tab). The API is then at `https://<hf-username>-<space-name>.hf.space` (lower case). `/docs` works with the token.

**Updating the API later:** run the same command again.

**Free Space behaviour:** a free Space sleeps after a while without traffic. The first visit after that takes about a minute while it wakes, and the site shows "waking up" and recovers by itself.

## 2. Website on Vercel (once)

1. Push this repository to GitHub (the data files are git-ignored, so only code goes up).
2. On vercel.com → **Add New → Project** → import the GitHub repo:
   - **Root Directory:** `frontend`;
   - **Framework:** Vite (picked up from `frontend/vercel.json`).
3. **Environment Variables:**

   | Name | Value |
   |---|---|
   | `TWIN_API_URL` | `https://<hf-username>-<space-name>.hf.space` (no trailing slash) |
   | `HF_TOKEN` | a Hugging Face **read** token (kept server-side; never reaches the browser) |

4. **Deploy.** Every later push to the branch redeploys automatically.

## Files involved

| File | Role |
|---|---|
| `Dockerfile`, `.dockerignore`, `requirements-runtime.txt` | the API container (no torch or training stack) |
| `deploy/push_hf_space.py` | uploads code + run-time data to the private Space |
| `frontend/vercel.json` | Vite build + rewrite `/api/*` → `/api/proxy?path=*` |
| `frontend/api/proxy.js` | Vercel function: forwards to `TWIN_API_URL` with `Authorization: Bearer HF_TOKEN` |
| `backend/api/app.py` | `ALLOWED_ORIGINS` env (comma-separated) for direct browser access. Not needed with the proxy |

## Test locally the same way

```powershell
docker build -t yulara-twin .
```

```powershell
docker run -p 7860:7860 yulara-twin
```

Then open `http://localhost:7860/docs`.
