# The twin API (FastAPI + the twin loop) as one container, for a Hugging Face Docker Space or any container host.
# Build:  docker build -t yulara-twin .
# Run:    docker run -p 7860:7860 -e ALLOWED_ORIGINS=http://localhost:5173 yulara-twin
# The data files are NOT in git (DKASC / Copernicus terms); they must sit in data/ and models_store/ when building.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 PORT=7860 TWIN_PROFILE=""
# Hugging Face Spaces run the container as user 1000
RUN useradd -m -u 1000 app
WORKDIR /app

COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt

COPY --chown=app backend backend
COPY --chown=app scripts/__init__.py scripts/run_twin.py scripts/
COPY --chown=app config config
# only the files the API and the twin read at run time (about 110 MB)
COPY --chown=app data/clean/station_5min.parquet data/clean/weather_model_5min.parquet data/clean/ml_predictions_5min.parquet \
     data/clean/health_daily.parquet data/clean/health_events.csv data/clean/model_comparison_2025.json data/clean/
COPY --chown=app data/era5/era5_hourly_site_utc.csv data/era5/
COPY --chown=app models_store/friend_v1/run_summary.json models_store/friend_v1/
RUN mkdir -p data/twin && chown -R app:app /app/data

USER app
EXPOSE 7860
CMD ["sh", "-c", "uvicorn backend.api.app:app --host 0.0.0.0 --port ${PORT}"]
