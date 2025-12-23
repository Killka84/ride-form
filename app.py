import os
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ride")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "requests")

app = FastAPI(title="Ride Form API")

# --- Mongo ---
client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB]
col = db[MONGO_COLLECTION]


# --- Models ---
class StartPoint(BaseModel):
    address: str = Field(..., min_length=2, max_length=200)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class RideRequestIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    tg: Optional[str] = Field(default="", max_length=64)
    day: str = Field(..., pattern="^(30|31)$")
    earliest_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    start_point: StartPoint

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        v = (v or "").strip()
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) == 11 and digits.startswith("8"):
            return "+7" + digits[1:]
        if v.startswith("+"):
            return "+" + digits
        return digits

    @field_validator("tg")
    @classmethod
    def normalize_tg(cls, v: str) -> str:
        v = (v or "").strip().replace(" ", "")
        if v.startswith("@"):
            v = v[1:]
        return v


@app.on_event("startup")
async def on_startup():
    # Индексы на будущее
    await col.create_index([("created_at", -1)])
    await col.create_index([("day", 1), ("earliest_time", 1)])
    # Геоиндекс для кластеризации/поиска
    await col.create_index([("start_point.geo", "2dsphere")])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Не палим внутренности клиенту
    return JSONResponse(status_code=500, content={"ok": False, "error": "Server error"})


@app.post("/api/ride-request")
async def create_request(payload: RideRequestIn):
    doc = payload.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()

    # GeoJSON для 2dsphere: [lon, lat]
    lat = doc["start_point"]["lat"]
    lon = doc["start_point"]["lon"]
    doc["start_point"]["geo"] = {"type": "Point", "coordinates": [lon, lat]}

    # мягкая проверка телефона (10–15 цифр)
    digits = "".join(ch for ch in doc["phone"] if ch.isdigit())
    if not (10 <= len(digits) <= 15):
        raise HTTPException(status_code=422, detail="Invalid phone")

    res = await col.insert_one(doc)
    return {"ok": True, "id": str(res.inserted_id)}


@app.get("/api/health")
async def health():
    return {"ok": True}


# --- Static (форма) ---
# Открытие "/" отдаёт static/index.html
app.mount("/", StaticFiles(directory="static", html=True), name="static")
