from fastapi import FastAPI

from .config import load_settings

app = FastAPI(title="Forecast Error API")
settings = load_settings()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "first_buy_date": settings.first_buy_date.isoformat(),
        "last_buy_date": settings.last_buy_date.isoformat(),
        "cutoff_local": settings.cutoff_local.strftime("%H:%M"),
        "timezone": "Europe/London",
    }
