"""The files the running API + twin read (paths relative to the project root). Shared by the upload and fetch scripts."""
RUNTIME_DATA = [
    "data/clean/station_5min.parquet",
    "data/clean/weather_model_5min.parquet",
    "data/clean/ml_predictions_5min.parquet",
    "data/clean/health_daily.parquet",
    "data/clean/health_events.csv",
    "data/clean/model_comparison_2025.json",
    "data/era5/era5_hourly_site_utc.csv",
    "models_store/friend_v1/run_summary.json",
]
