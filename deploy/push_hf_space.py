"""
Upload the twin API (code + the run-time data files) to a PRIVATE Hugging Face Docker Space.

The data files are not in git (DKASC / Copernicus terms). Keep the Space PRIVATE: its files are
then not downloadable by the public; the website reaches the API through the Vercel proxy, which
sends a read token. Publishing measured DKASC series still needs DKASC's consent (> 5,000 cells).

Before running:
  1. Create a Hugging Face account, then a Space: SDK = Docker, visibility = Private.
  2. Create an access token with WRITE permission (Settings -> Access Tokens).
  3. In this terminal:   $env:HF_TOKEN = "<your write token>"      (PowerShell; the token is not stored anywhere)
Run (from the project folder):
  .venv\\Scripts\\pip install huggingface_hub
  .venv\\Scripts\\python deploy\\push_hf_space.py <hf-username>/<space-name>
"""
import os
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "Dockerfile", "requirements-runtime.txt",
    "data/clean/station_5min.parquet", "data/clean/weather_model_5min.parquet", "data/clean/ml_predictions_5min.parquet",
    "data/clean/health_daily.parquet", "data/clean/health_events.csv", "data/clean/model_comparison_2025.json",
    "data/era5/era5_hourly_site_utc.csv", "models_store/friend_v1/run_summary.json",
    "scripts/__init__.py", "scripts/run_twin.py",
]
FOLDERS = ["backend", "config"]
SPACE_README = """---
title: Yulara Station Twin API
emoji: ☀️
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---
Digital shadow of Yulara 1 – Desert Gardens (DKA Solar Centre data, used with attribution). API only;
the website is deployed separately. Interactive docs at /docs.
"""


def main():
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        sys.exit("usage: python deploy/push_hf_space.py <hf-username>/<space-name>")
    repo = sys.argv[1]
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("Set HF_TOKEN in this terminal first (a WRITE token).")
    missing = [f for f in FILES if not (ROOT / f).exists()]
    if missing:
        sys.exit(f"missing files (run the pipeline first): {missing}")
    api = HfApi(token=token)
    info = api.repo_info(repo, repo_type="space")
    if not info.private:
        sys.exit(f"{repo} is PUBLIC: its files would be downloadable. Make it private first (Space settings).")
    with tempfile.TemporaryDirectory() as tmp:
        readme = Path(tmp) / "README.md"
        readme.write_text(SPACE_README, encoding="utf-8")
        api.upload_file(path_or_fileobj=str(readme), path_in_repo="README.md", repo_id=repo, repo_type="space")
    for f in FILES:
        print("uploading", f)
        api.upload_file(path_or_fileobj=str(ROOT / f), path_in_repo=f, repo_id=repo, repo_type="space")
    for d in FOLDERS:
        print("uploading", d + "/")
        api.upload_folder(folder_path=str(ROOT / d), path_in_repo=d, repo_id=repo, repo_type="space",
                          ignore_patterns=["**/__pycache__/**", "*.pyc"])
    user, name = repo.split("/")
    print(f"\nDone. The Space builds itself (~5 min). API base URL for Vercel (TWIN_API_URL):\n"
          f"  https://{user.lower()}-{name.lower().replace('_', '-')}.hf.space")


if __name__ == "__main__":
    main()
