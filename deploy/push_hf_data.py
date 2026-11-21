"""
Upload the run-time data files to a PRIVATE Hugging Face dataset (created if missing).

Sign in once in a terminal (paste a WRITE token when asked; it is cached on this computer only):
  .venv\\Scripts\\hf auth login
Then (from the project folder):
  .venv\\Scripts\\python deploy\\push_hf_data.py <hf-username>/yulara-twin-data
The script refuses to upload into a public dataset.
"""
import sys
from pathlib import Path

from huggingface_hub import HfApi

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_files import RUNTIME_DATA  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main():
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        sys.exit("usage: python deploy/push_hf_data.py <hf-username>/<dataset-name>")
    repo = sys.argv[1]
    missing = [f for f in RUNTIME_DATA if not (ROOT / f).exists()]
    if missing:
        sys.exit(f"missing files (run the pipeline first): {missing}")
    api = HfApi()   # token from `hf auth login` (or HF_TOKEN)
    api.create_repo(repo, repo_type="dataset", private=True, exist_ok=True)
    if not api.repo_info(repo, repo_type="dataset").private:
        sys.exit(f"{repo} is PUBLIC: make it private first (dataset settings), then run again.")
    for f in RUNTIME_DATA:
        print(f"uploading {f} ({(ROOT / f).stat().st_size / 1e6:.1f} MB)", flush=True)
        api.upload_file(path_or_fileobj=str(ROOT / f), path_in_repo=f, repo_id=repo, repo_type="dataset",
                        commit_message=f"add {f}")
    print(f"\nDone: https://huggingface.co/datasets/{repo} (private)")


if __name__ == "__main__":
    main()
