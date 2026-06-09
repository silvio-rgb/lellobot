import asyncio
import csv
import os
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    ChatJoinRequest,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
from dotenv import load_dotenv


# ==================================================
# CONFIG
# ==================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/bot.sqlite")

ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

CHANNEL_INVITE_LINK = os.getenv("CHANNEL_INVITE_LINK", "")
ASSISTANCE_LINK = os.getenv("ASSISTANCE_LINK", "")

FOLLOWUP_ENABLED = os.getenv("FOLLOWUP_ENABLED", "true").lower() == "true"
FOLLOWUP_DELAY_MINUTES = int(os.getenv("FOLLOWUP_DELAY_MINUTES", "10"))

# FOTO (file_id telegram) — se vuoi metterlo in Render env:
# WELCOME_PHOTO_FILE_ID=AgACAg....
WELCOME_PHOTO_FILE_ID = os.getenv("WELCOME_PHOTO_FILE_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN mancante. Inseriscilo nel file .env oppure nelle variabili ambiente.")

Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
Path("exports").mkdir(exist_ok=True)

# ✅ aiogram >= 3.7: parse_mode nel DefaultBotProperties
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
router = Router()
dp.include_router(router)


# ==================================================
# MESSAGGI
# ==================================================

WELCOME_MESSAGE = """<b>BENVENUTO NEL MIO CANALE 🏆</b>

📌In primis ti assicuro che tutte le promo che vedrai qui, non le troverai da nessuna altra parte!

Riceverai bonus periodici, quote maggiorate, premi continui solo per la nostra rete, oltre alle mie analisi.
<b>TUTTI I BONUS SONO REAL CASH</b>

Se invece vuoi accedere a tutte le analisi in maniera <b>GRATUITA</b>, contatta la mia assistenza, che ti spiegherà come entrare 👇

<b>TI RICORDO CHE A BREVE PARTIRÀ LA SCALATA DEI MONDIALI 🏆</b>
<b>DA 20,00€ ——&gt; 1000,00€ 🔝</b>

<b>I PRIMI 6 STEP IN CASO DI PERDITA SONO RIMBORSATI 🎁</b>"""

FOLLOWUP_MESSAGE = """<b>Hai già letto il messaggio fissato? 🏆</b>

Ricordati di seguire le istruzioni nel canale.

Per qualsiasi dubbio puoi contattare l'assistenza qui sotto 👇"""


def welcome_keyboard() -> InlineKeyboardMarkup:
    buttons = []

    if ASSISTANCE_LINK:
        buttons.append([InlineKeyboardButton(text="💬 Contatta assistenza", url=ASSISTANCE_LINK)])

    if CHANNEL_INVITE_LINK:
        buttons.append([InlineKeyboardButton(text="📌 Apri il canale", url=CHANNEL_INVITE_LINK)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def start_keyboard() -> InlineKeyboardMarkup:
    buttons = []

    if CHANNEL_INVITE_LINK:
        buttons.append([InlineKeyboardButton(text="🏆 Richiedi accesso al canale", url=CHANNEL_INVITE_LINK)])

    if ASSISTANCE_LINK:
        buttons.append([InlineKeyboardButton(text="💬 Assistenza", url=ASSISTANCE_LINK)])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================================================
# DATABASE
# ==================================================

async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS approved_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            chat_id TEXT NOT NULL,
            chat_title TEXT,
            request_date TEXT,
            approved_date TEXT,
            dm_sent INTEGER DEFAULT 0,
            dm_error TEXT,
            followup_sent INTEGER DEFAULT 0,
            followup_due_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, chat_id)
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id INTEGER,
            chat_id TEXT,
            payload TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        await db.commit()


async def save_event(event_type: str, user_id=None, chat_id=None, payload: str = ""):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
        INSERT INTO bot_events (event_type, user_id, chat_id, payload)
        VALUES (?, ?, ?, ?)
        """, (event_type, user_id, str(chat_id) if chat_id else None, payload))
        await db.commit()


async def save_or_update_user(
    user_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    chat_id: int | str,
    chat_title: str | None,
    request_date: str,
    approved_date: str,
    dm_sent: int,
    dm_error: str | None,
    followup_due_at: str | None,
):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
        INSERT INTO approved_users (
            user_id,
            username,
            first_name,
            last_name,
            chat_id,
            chat_title,
            request_date,
            approved_date,
            dm_sent,
            dm_error,
            followup_sent,
            followup_due_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(user_id, chat_id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            chat_title = excluded.chat_title,
            approved_date = excluded.approved_date,
            dm_sent = excluded.dm_sent,
            dm_error = excluded.dm_error,
            followup_due_at = excluded.followup_due_at,
            updated_at = CURRENT_TIMESTAMP
        """, (
            user_id,
            username,
            first_name,
            last_name,
            str(chat_id),
            chat_title,
            request_date,
            approved_date,
            dm_sent,
            dm_error,
            followup_due_at
        ))
        await db.commit()


async def get_due_followups():
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT *
        FROM approved_users
        WHERE dm_sent = 1
          AND followup_sent = 0
          AND followup_due_at IS NOT NULL
          AND followup_due_at <= ?
        LIMIT 100
        """, (now,))
        return await cursor.fetchall()


async def mark_followup_sent(user_id: int, chat_id: str):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
        UPDATE approved_users
        SET followup_sent = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND chat_id = ?
        """, (user_id, str(chat_id)))
        await db.commit()


async def get_stats():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        total = (await (await db.execute("SELECT COUNT(*) FROM approved_users")).fetchone())[0]
        dm_sent = (await (await db.execute("SELECT COUNT(*) FROM approved_users WHERE dm_sent = 1")).fetchone())[0]
        dm_failed = (await (await db.execute("""
            SELECT COUNT(*)
            FROM approved_users
            WHERE dm_sent = 0 AND dm_error IS NOT NULL
        """)).fetchone())[0]
        return {"total": total, "dm_sent": dm_sent, "dm_failed": dm_failed}


async def get_all_users():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
        SELECT
            user_id,
            username,
            first_name,
            last_name,
            chat_id,
            chat_title,
            request_date,
            approved_date,
            dm_sent,
            dm_error,
            followup_sent,
            created_at
        FROM approved_users
        ORDER BY approved_date DESC
        """)
        return await cursor.fetchall()


# ==================================================
# UTILITY
# ==================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def send_private_welcome(user_id: int) -> tuple[bool, str | None]:
    """
    ✅ UNICO MESSAGGIO:
    - se c'è la foto -> send_photo con caption + tastiera
    - altrimenti -> send_message + tastiera
    """
    try:
        if WELCOME_PHOTO_FILE_ID:
            await bot.send_photo(
                chat_id=user_id,
                photo=WELCOME_PHOTO_FILE_ID,
                caption=WELCOME_MESSAGE,
                reply_markup=welcome_keyboard(),
                disable_notification=True
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=WELCOME_MESSAGE,
                reply_markup=welcome_keyboard(),
                disable_web_page_preview=True
            )
        return True, None

    except TelegramForbiddenError:
        return False, "FORBIDDEN: utente non ha avviato il bot o ha bloccato il bot"

    except TelegramBadRequest as e:
        return False, f"BAD_REQUEST: {str(e)}"

    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        try:
            if WELCOME_PHOTO_FILE_ID:
                await bot.send_photo(
                    chat_id=user_id,
                    photo=WELCOME_PHOTO_FILE_ID,
                    caption=WELCOME_MESSAGE,
                    reply_markup=welcome_keyboard(),
                    disable_notification=True
                )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=WELCOME_MESSAGE,
                    reply_markup=welcome_keyboard(),
                    disable_web_page_preview=True
                )
            return True, None
        except Exception as retry_error:
            return False, f"RETRY_FAILED: {str(retry_error)}"

    except Exception as e:
        return False, f"UNKNOWN_ERROR: {str(e)}"


# ==================================================
# START + PHOTOID
# ==================================================

@router.message(CommandStart())
async def start_handler(message: Message):
    first_name = message.from_user.first_name or ""
    text = f"""<b>Ciao {first_name} 🏆</b>

Questo è il bot ufficiale per l'accesso al canale.

Per entrare, clicca il bottone qui sotto e richiedi l'accesso.

Dopo l'approvazione riceverai tutte le istruzioni in privato.

<b>Per prendere il FILE_ID di una foto</b>:
scrivi /photoid e poi inviami la foto qui in chat privata.
"""
    await message.answer(text, reply_markup=start_keyboard(), disable_web_page_preview=True)


PHOTOID_WAITING: set[int] = set()

@router.message(Command("photoid"))
async def photoid_command(message: Message):
    if message.chat.type != "private":
        await message.answer("Scrivimi in privato e usa /photoid lì.")
        return
    PHOTOID_WAITING.add(message.from_user.id)
    await message.answer("Ok ✅ Ora inviami la foto (come FOTO) e ti mando il FILE_ID.")

@router.message(F.photo)
async def photoid_receiver(message: Message):
    if message.chat.type != "private":
        return
    uid = message.from_user.id
    if uid not in PHOTOID_WAITING:
        return
    PHOTOID_WAITING.discard(uid)
    file_id = message.photo[-1].file_id
    await message.answer(f"FILE_ID:\n<code>{file_id}</code>")


@router.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        """<b>Comandi disponibili</b>

/start - Avvia il bot
/help - Aiuto
/photoid - Ottieni file_id foto (in privato)

Comandi admin:
/stats - Statistiche
/export - Esporta utenti CSV"""
    )


# ==================================================
# JOIN REQUEST
# ==================================================

@router.chat_join_request()
async def join_request_handler(join_request: ChatJoinRequest):
    user = join_request.from_user
    chat = join_request.chat

    request_date = datetime.utcnow().isoformat()
    approved_date = datetime.utcnow().isoformat()

    followup_due_at = None
    if FOLLOWUP_ENABLED:
        followup_due_at = (datetime.utcnow() + timedelta(minutes=FOLLOWUP_DELAY_MINUTES)).isoformat()

    await save_event("chat_join_request_received", user.id, chat.id, f"user={user.id}; chat={chat.id}")
    print(f"[JOIN REQUEST] {user.id} @{user.username} -> {chat.title}")

    await save_or_update_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        chat_id=chat.id,
        chat_title=chat.title,
        request_date=request_date,
        approved_date="",
        dm_sent=0,
        dm_error=None,
        followup_due_at=followup_due_at
    )

    try:
        await bot.approve_chat_join_request(chat_id=chat.id, user_id=user.id)
        await save_event("chat_join_request_approved", user.id, chat.id, "approved")
        print(f"[APPROVED] {user.id}")
    except TelegramBadRequest as e:
        await save_event("approval_failed", user.id, chat.id, str(e))
        print(f"[APPROVAL ERROR] {e}")
        return
    except Exception as e:
        await save_event("approval_failed", user.id, chat.id, str(e))
        print(f"[APPROVAL UNKNOWN ERROR] {e}")
        return

    dm_sent, dm_error = await send_private_welcome(user.id)

    await save_or_update_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        chat_id=chat.id,
        chat_title=chat.title,
        request_date=request_date,
        approved_date=approved_date,
        dm_sent=1 if dm_sent else 0,
        dm_error=dm_error,
        followup_due_at=followup_due_at
    )

    print(f"[DM SENT] {user.id}" if dm_sent else f"[DM FAILED] {user.id}: {dm_error}")


# ==================================================
# ADMIN: STATS / EXPORT
# ==================================================

@router.message(Command("stats"))
async def stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Non hai il permesso di usare questo comando.")
        return
    stats = await get_stats()
    text = f"""<b>Statistiche bot</b>

Utenti approvati: <b>{stats["total"]}</b>
DM inviati: <b>{stats["dm_sent"]}</b>
DM falliti: <b>{stats["dm_failed"]}</b>"""
    await message.answer(text)


@router.message(Command("export"))
async def export_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Non hai il permesso di usare questo comando.")
        return

    rows = await get_all_users()
    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)

    filename = f"approved_users_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = export_dir / filename

    with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = [
            "user_id", "username", "first_name", "last_name", "chat_id", "chat_title",
            "request_date", "approved_date", "dm_sent", "dm_error", "followup_sent", "created_at"
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({
                "user_id": row["user_id"],
                "username": row["username"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "chat_id": row["chat_id"],
                "chat_title": row["chat_title"],
                "request_date": row["request_date"],
                "approved_date": row["approved_date"],
                "dm_sent": row["dm_sent"],
                "dm_error": row["dm_error"],
                "followup_sent": row["followup_sent"],
                "created_at": row["created_at"],
            })

    await message.answer_document(FSInputFile(filepath), caption="Export utenti approvati CSV")


# ==================================================
# FOLLOW-UP LOOP
# ==================================================

async def followup_worker():
    if not FOLLOWUP_ENABLED:
        return

    print("[FOLLOWUP] Worker attivo")

    while True:
        try:
            rows = await get_due_followups()
            for row in rows:
                user_id = row["user_id"]
                chat_id = row["chat_id"]

                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=FOLLOWUP_MESSAGE,
                        reply_markup=welcome_keyboard(),
                        disable_web_page_preview=True
                    )
                    await mark_followup_sent(user_id, chat_id)
                    print(f"[FOLLOWUP SENT] {user_id}")

                except TelegramForbiddenError:
                    print(f"[FOLLOWUP FAILED] {user_id}: forbidden")
                    await mark_followup_sent(user_id, chat_id)

                except Exception as e:
                    print(f"[FOLLOWUP ERROR] {user_id}: {e}")

        except Exception as e:
            print(f"[FOLLOWUP WORKER ERROR] {e}")

        await asyncio.sleep(60)


# ==================================================
# MAIN
# ==================================================

async def main():
    await init_db()
    print("Bot avviato in polling...")
    asyncio.create_task(followup_worker())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
