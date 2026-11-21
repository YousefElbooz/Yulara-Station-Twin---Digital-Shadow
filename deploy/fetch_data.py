"""
Start-up step on the server: download the run-time data from a PRIVATE Hugging Face dataset.

The data is not in git (DKASC / Copernicus terms), so the container fetches it when it starts.
  HF_DATASET  e.g. YosefElbooz/yulara-twin-data
  HF_TOKEN    a Hugging Face READ token (set as a secret in the host's settings, never in code)
Files that already exist are kept, so a warm restart does not download again.
Only the standard library is used.
"""
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_files import RUNTIME_DATA  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main():
    repo, token = os.environ.get("HF_DATASET"), os.environ.get("HF_TOKEN")
    todo = [f for f in RUNTIME_DATA if not (ROOT / f).exists()]
    if not todo:
        print("data: all files present")
        return
    if not repo or not token:
        sys.exit("data missing and HF_DATASET / HF_TOKEN not set")
    for f in todo:
        url = f"https://huggingface.co/datasets/{repo}/resolve/main/{f}"
        dest = ROOT / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        for attempt in range(1, 4):
            try:
                t0 = time.time()
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "yulara-twin"})
                with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as out:
                    while chunk := r.read(1 << 20):
                        out.write(chunk)
                tmp.replace(dest)
                print(f"data: {f} ({dest.stat().st_size / 1e6:.1f} MB, {time.time() - t0:.1f} s)", flush=True)
                break
            except Exception as ex:  # noqa: BLE001
                print(f"data: {f} attempt {attempt} failed: {type(ex).__name__}: {ex}", flush=True)
                if attempt == 3:
                    sys.exit(1)
                time.sleep(5 * attempt)


if __name__ == "__main__":
    main()
