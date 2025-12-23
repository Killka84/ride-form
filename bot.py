import asyncio
import os
from datetime import datetime
from typing import Iterable, Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ride")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "requests")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
BOT_ALLOWED = {x.strip() for x in (os.getenv("BOT_ALLOWED_IDS") or "").split(",") if x.strip()}

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DB]
col = db[MONGO_COLLECTION]

KBD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Сколько участников?")],
        [KeyboardButton("Последние 5")],
    ],
    resize_keyboard=True,
)


def _is_allowed(user_id: int) -> bool:
    if not BOT_ALLOWED:
        return True
    return str(user_id) in BOT_ALLOWED


async def _count() -> int:
    return await col.count_documents({})


async def _last(limit: int = 5) -> list[dict]:
    cursor = (
        col.find({}, {"phone": 1, "tg": 1, "day": 1, "earliest_time": 1, "start_point": 1, "created_at": 1})
        .sort("created_at", -1)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)


def _fmt_request(doc: dict) -> str:
    sp = doc.get("start_point") or {}
    tg = doc.get("tg") or "-"
    if tg and not str(tg).startswith("@"):
        tg = "@" + str(tg)
    created = doc.get("created_at", "")
    try:
        created_dt = datetime.fromisoformat(created)
        created = created_dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass

    return "\n".join(
        [
            f"id: {doc.get('_id')}",
            f"тел: {doc.get('phone','')}",
            f"tg: {tg}",
            f"дата/время: {doc.get('day','')} {doc.get('earliest_time','')}",
            f"адрес: {sp.get('address','')}",
            f"создано: {created}",
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    await update.message.reply_text("Готово. Доступные действия:", reply_markup=KBD)


async def count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    total = await _count()
    await update.message.reply_text(f"Участников: {total}", reply_markup=KBD)


async def last_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    docs = await _last()
    if not docs:
        await update.message.reply_text("Пока пусто.", reply_markup=KBD)
        return
    text = "\n\n".join(_fmt_request(d) for d in docs)
    await update.message.reply_text(text, reply_markup=KBD)


async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    if not context.args:
        await update.message.reply_text("Укажи id: /delete <id>", reply_markup=KBD)
        return

    rid = context.args[0]
    if not ObjectId.is_valid(rid):
        await update.message.reply_text("Некорректный id.", reply_markup=KBD)
        return

    res = await col.delete_one({"_id": ObjectId(rid)})
    if res.deleted_count:
        await update.message.reply_text("Удалено.", reply_markup=KBD)
    else:
        await update.message.reply_text("Не найдено.", reply_markup=KBD)


async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip().lower()
    if text == "сколько участников?":
        await count_cmd(update, context)
    elif text == "последние 5":
        await last_cmd(update, context)
    else:
        await update.message.reply_text("Команда не понята. Есть /count, /last, /delete <id>.", reply_markup=KBD)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN or BOT_TOKEN")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .concurrent_updates(True)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("count", count_cmd))
    application.add_handler(CommandHandler("last", last_cmd))
    application.add_handler(CommandHandler("delete", delete_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))

    application.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
