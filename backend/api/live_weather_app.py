"""
The same API, starting in live-weather mode: the real time now at Yulara, live Open-Meteo weather, and the
calibrated physics' expected power (no plant feed yet). Can also be switched from the site's settings panel.

  .venv\Scripts\python -m uvicorn backend.api.live_weather_app:app --port 8000
"""
import os

os.environ["TWIN_PROFILE"] = "live-weather"

from backend.api.app import app  # noqa: E402,F401
