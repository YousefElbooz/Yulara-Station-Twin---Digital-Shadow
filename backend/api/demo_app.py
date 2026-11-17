"""
The same API, with the twin in the demo profile (config/twin.yaml -> runtime.demo): speed mode from a
chosen real moment, so the demo shows a real outage and its alarm within a few minutes.

  .venv\Scripts\python -m uvicorn backend.api.demo_app:app --port 8000
"""
import os

os.environ["TWIN_PROFILE"] = "demo"

from backend.api.app import app  # noqa: E402,F401
