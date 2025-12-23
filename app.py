import os
import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

logger = logging.getLogger(__name__)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ride")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "requests")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_THREAD_ID = os.getenv("TELEGRAM_THREAD_ID", "").strip()
BOT_DELETE_TOKEN = os.getenv("BOT_DELETE_TOKEN", "").strip()

app = FastAPI(title="Ride Form API")

# --- Mongo ---
client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB]
col = db[MONGO_COLLECTION]


def _telegram_enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _telegram_send_message_sync(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload: dict[str, object] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if TELEGRAM_THREAD_ID:
        try:
            payload["message_thread_id"] = int(TELEGRAM_THREAD_ID)
        except ValueError:
            payload["message_thread_id"] = TELEGRAM_THREAD_ID

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API error HTTP {e.code}: {detail}") from e

    try:
        decoded = json.loads(body.decode("utf-8"))
    except Exception:
        return
    if isinstance(decoded, dict) and decoded.get("ok") is False:
        raise RuntimeError(f"Telegram API error: {decoded}")


async def notify_telegram_new_request(doc: dict, request_id: str) -> None:
    if not _telegram_enabled():
        return

    sp = doc.get("start_point") or {}
    lat = sp.get("lat")
    lon = sp.get("lon")

    map_url = ""
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        map_url = f"https://www.google.com/maps?q={lat},{lon}"

    tg = (doc.get("tg") or "").strip()
    if tg and not tg.startswith("@"):
        tg = "@" + tg

    lines = [
        "Новая заявка",
        f"id: {request_id}",
        f"phone: {doc.get('phone', '')}",
        f"tg: {tg or '-'}",
        f"day: {doc.get('day', '')}",
        f"time: {doc.get('earliest_time', '')}",
        f"start: {sp.get('address', '')}",
    ]
    if map_url:
        lines.append(f"map: {map_url}")

    try:
        await asyncio.to_thread(_telegram_send_message_sync, "\n".join(lines))
    except Exception:
        logger.exception("Telegram notification failed")


# --- Models ---
class StartPoint(BaseModel):
    address: str = Field(..., min_length=2, max_length=200)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class RideRequestIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=5, max_length=32)
    tg: Optional[str] = Field(default="", max_length=64)
    day: str = Field(..., pattern="^(30|31)$")
    earliest_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    people: int = Field(default=1, ge=1, le=10)
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
async def create_request(payload: RideRequestIn, background_tasks: BackgroundTasks):
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
    request_id = str(res.inserted_id)

    if _telegram_enabled():
        background_tasks.add_task(notify_telegram_new_request, doc, request_id)

    return {"ok": True, "id": request_id}


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.delete("/api/ride-request/{request_id}")
async def delete_request(request_id: str, request: Request):
    token = request.headers.get("X-Delete-Token", "")
    if not BOT_DELETE_TOKEN or token != BOT_DELETE_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not ObjectId.is_valid(request_id):
        raise HTTPException(status_code=400, detail="Invalid id")

    res = await col.delete_one({"_id": ObjectId(request_id)})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")

    return {"ok": True, "id": request_id}


@app.get("/api/count")
async def count():
    total = await col.count_documents({})
    people_sum = await col.aggregate(
        [
            {"$project": {"people": {"$ifNull": ["$people", 1]}}},
            {"$group": {"_id": None, "people": {"$sum": "$people"}}},
        ]
    ).to_list(length=1)
    total_people = people_sum[0]["people"] if people_sum else 0
    return {"ok": True, "count": total, "people": total_people}


# --- Static (форма) ---
# Открытие "/" отдаёт static/index.html
app.mount("/", StaticFiles(directory="static", html=True), name="static")
