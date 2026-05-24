import asyncio
import csv
import os
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
from aiogram import Bot, Dispatcher, Router
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

REPORT_ENABLED = os.getenv("REPORT_ENABLED", "true").lower() == "true"
REPORT_INTERVAL_HOURS = int(os.getenv("REPORT_INTERVAL_HOURS", "2"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN mancante. Inseriscilo nel file .env oppure nelle variabili ambiente.")

Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
Path("exports").mkdir(exist_ok=True)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ==================================================
# MESSAGGI
# ==================================================

WELCOME_MESSAGE = """<b>BENVENUTO NEL MIO CANALE 🏆</b>

📌 In primis ti assicuro che tutte le promo che vedrai qui, non le troverai da nessuna altra parte!

Riceverai bonus periodici, quote maggiorate, premi continui solo per la nostra rete, oltre alle mie analisi. 🎁🎁

Se invece vuoi accedere a tutte le analisi in maniera <b>GRATUITA</b>, contatta la mia assistenza, che ti spiegherà come entrare 👇"""

FOLLOWUP_MESSAGE = """<b>Hai già letto il messaggio fissato? 🏆</b>

Ricordati di seguire le istruzioni nel canale.

Per qualsiasi dubbio puoi contattare l'assistenza qui sotto 👇"""


def welcome_keyboard() -> InlineKeyboardMarkup:
    buttons = []

    if ASSISTANCE_LINK:
        buttons.append([
            InlineKeyboardButton(
                text="💬 Contatta assistenza",
                url=ASSISTANCE_LINK
            )
        ])

    if CHANNEL_INVITE_LINK:
        buttons.append([
            InlineKeyboardButton(
                text="📌 Apri il canale",
                url=CHANNEL_INVITE_LINK
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def start_keyboard() -> InlineKeyboardMarkup:
    buttons = []

    if CHANNEL_INVITE_LINK:
        buttons.append([
            InlineKeyboardButton(
                text="🏆 Richiedi accesso al canale",
                url=CHANNEL_INVITE_LINK
            )
        ])

    if ASSISTANCE_LINK:
        buttons.append([
            InlineKeyboardButton(
                text="💬 Assistenza",
                url=ASSISTANCE_LINK
            )
        ])

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

        await db.execute("""
        CREATE TABLE IF NOT EXISTS admin_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at TEXT,
            total_approved INTEGER,
            today_approved INTEGER,
            last_2h_approved INTEGER,
            dm_sent INTEGER,
            dm_failed INTEGER,
            followup_sent INTEGER
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


async def update_dm_status(user_id: int, chat_id: int | str, dm_sent: int, dm_error: str | None):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
        UPDATE approved_users
        SET dm_sent = ?,
            dm_error = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND chat_id = ?
        """, (dm_sent, dm_error, user_id, str(chat_id)))
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
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    last_2h = (now - timedelta(hours=2)).isoformat()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        total_cursor = await db.execute("""
        SELECT COUNT(*)
        FROM approved_users
        WHERE approved_date IS NOT NULL
          AND approved_date != ''
        """)
        total = (await total_cursor.fetchone())[0]

        today_cursor = await db.execute("""
        SELECT COUNT(*)
        FROM approved_users
        WHERE approved_date >= ?
        """, (today_start,))
        today = (await today_cursor.fetchone())[0]

        last_2h_cursor = await db.execute("""
        SELECT COUNT(*)
        FROM approved_users
        WHERE approved_date >= ?
        """, (last_2h,))
        last_2h_count = (await last_2h_cursor.fetchone())[0]

        dm_sent_cursor = await db.execute("""
        SELECT COUNT(*)
        FROM approved_users
        WHERE dm_sent = 1
        """)
        dm_sent = (await dm_sent_cursor.fetchone())[0]

        dm_failed_cursor = await db.execute("""
        SELECT COUNT(*)
        FROM approved_users
        WHERE dm_sent = 0
          AND dm_error IS NOT NULL
        """)
        dm_failed = (await dm_failed_cursor.fetchone())[0]

        followup_sent_cursor = await db.execute("""
        SELECT COUNT(*)
        FROM approved_users
        WHERE followup_sent = 1
        """)
        followup_sent = (await followup_sent_cursor.fetchone())[0]

        by_chat_cursor = await db.execute("""
        SELECT chat_title, COUNT(*)
        FROM approved_users
        WHERE approved_date >= ?
        GROUP BY chat_title
        ORDER BY COUNT(*) DESC
        """, (today_start,))
        by_chat = await by_chat_cursor.fetchall()

        return {
            "total": total,
            "today": today,
            "last_2h": last_2h_count,
            "dm_sent": dm_sent,
            "dm_failed": dm_failed,
            "followup_sent": followup_sent,
            "by_chat": by_chat
        }


async def save_admin_report(stats: dict):
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
        INSERT INTO admin_reports (
            sent_at,
            total_approved,
            today_approved,
            last_2h_approved,
            dm_sent,
            dm_failed,
            followup_sent
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            stats["total"],
            stats["today"],
            stats["last_2h"],
            stats["dm_sent"],
            stats["dm_failed"],
            stats["followup_sent"],
        ))

        await db.commit()


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
# REPORT ADMIN
# ==================================================

async def build_report_text():
    stats = await get_stats()

    text = f"""<b>📊 Report ZiolelloBet</b>

<b>Entrati ultime 2 ore:</b> {stats["last_2h"]}
<b>Entrati oggi:</b> {stats["today"]}
<b>Entrati totali:</b> {stats["total"]}

<b>DM benvenuto inviati:</b> {stats["dm_sent"]}
<b>DM falliti:</b> {stats["dm_failed"]}
<b>Follow-up inviati:</b> {stats["followup_sent"]}

<b>Dettaglio canali/gruppi oggi:</b>"""

    if stats["by_chat"]:
        for chat_title, count in stats["by_chat"]:
            title = chat_title or "Chat senza nome"
            text += f"\n• {title}: <b>{count}</b>"
    else:
        text += "\n• Nessun ingresso registrato oggi."

    text += """

<i>Nota: il report conta gli utenti approvati automaticamente dal bot.</i>"""

    return text


async def send_admin_report():
    if not ADMIN_IDS:
        print("[REPORT] Nessun ADMIN_IDS impostato.")
        return

    stats = await get_stats()
    text = await build_report_text()

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            print(f"[REPORT SENT] Admin {admin_id}")

        except TelegramForbiddenError:
            print(f"[REPORT FAILED] Admin {admin_id}: bot bloccato o chat non avviata")

        except Exception as e:
            print(f"[REPORT ERROR] Admin {admin_id}: {e}")

    await save_admin_report(stats)


# ==================================================
# UTILITY
# ==================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def send_private_welcome(user_id: int) -> tuple[bool, str | None]:
    try:
        await bot.send_message(
            chat_id=user_id,
            text=WELCOME_MESSAGE,
            reply_markup=welcome_keyboard(),
            parse_mode=ParseMode.HTML,
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
            await bot.send_message(
                chat_id=user_id,
                text=WELCOME_MESSAGE,
                reply_markup=welcome_keyboard(),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            return True, None

        except Exception as retry_error:
            return False, f"RETRY_FAILED: {str(retry_error)}"

    except Exception as e:
        return False, f"UNKNOWN_ERROR: {str(e)}"


# ==================================================
# HANDLER START
# ==================================================

@router.message(CommandStart())
async def start_handler(message: Message):
    first_name = message.from_user.first_name or ""

    text = f"""<b>Ciao {first_name} 🏆</b>

Questo è il bot ufficiale per l'accesso al canale.

Per entrare, clicca il bottone qui sotto e richiedi l'accesso.

Dopo l'approvazione riceverai tutte le istruzioni in privato."""

    await message.answer(
        text,
        reply_markup=start_keyboard(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


@router.message(Command("help"))
async def help_handler(message: Message):
    await message.answer(
        """<b>Comandi disponibili</b>

/start - Avvia il bot
/help - Aiuto

Comandi admin:
/stats - Statistiche complete
/report - Invia report immediato agli admin
/export - Esporta utenti CSV""",
        parse_mode=ParseMode.HTML
    )


# ==================================================
# HANDLER CHAT JOIN REQUEST
# ==================================================

@router.chat_join_request()
async def join_request_handler(join_request: ChatJoinRequest):
    user = join_request.from_user
    chat = join_request.chat

    request_date = datetime.utcnow().isoformat()
    approved_date = datetime.utcnow().isoformat()

    followup_due_at = None
    if FOLLOWUP_ENABLED:
        followup_due_at = (
            datetime.utcnow() + timedelta(minutes=FOLLOWUP_DELAY_MINUTES)
        ).isoformat()

    await save_event(
        event_type="chat_join_request_received",
        user_id=user.id,
        chat_id=chat.id,
        payload=f"user={user.id}; chat={chat.id}"
    )

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
        await bot.approve_chat_join_request(
            chat_id=chat.id,
            user_id=user.id
        )

        await save_event(
            event_type="chat_join_request_approved",
            user_id=user.id,
            chat_id=chat.id,
            payload="approved"
        )

        print(f"[APPROVED] {user.id}")

    except TelegramBadRequest as e:
        await save_event(
            event_type="approval_failed",
            user_id=user.id,
            chat_id=chat.id,
            payload=str(e)
        )
        print(f"[APPROVAL ERROR] {e}")
        return

    except Exception as e:
        await save_event(
            event_type="approval_failed",
            user_id=user.id,
            chat_id=chat.id,
            payload=str(e)
        )
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

    if dm_sent:
        print(f"[DM SENT] {user.id}")
    else:
        print(f"[DM FAILED] {user.id}: {dm_error}")


# ==================================================
# ADMIN: STATS
# ==================================================

@router.message(Command("stats"))
async def stats_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Non hai il permesso di usare questo comando.")
        return

    text = await build_report_text()

    await message.answer(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True
    )


# ==================================================
# ADMIN: REPORT
# ==================================================

@router.message(Command("report"))
async def report_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Non hai il permesso di usare questo comando.")
        return

    await send_admin_report()
    await message.answer("✅ Report inviato agli admin.")


# ==================================================
# ADMIN: EXPORT CSV
# ==================================================

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
            "user_id",
            "username",
            "first_name",
            "last_name",
            "chat_id",
            "chat_title",
            "request_date",
            "approved_date",
            "dm_sent",
            "dm_error",
            "followup_sent",
            "created_at"
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

    await message.answer_document(
        FSInputFile(filepath),
        caption="Export utenti approvati CSV"
    )


# ==================================================
# FOLLOW-UP LOOP
# ==================================================

async def followup_worker():
    if not FOLLOWUP_ENABLED:
        print("[FOLLOWUP] Worker disattivato")
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
                        parse_mode=ParseMode.HTML,
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
# REPORT LOOP
# ==================================================

async def report_worker():
    if not REPORT_ENABLED:
        print("[REPORT] Worker disattivato")
        return

    print(f"[REPORT] Worker attivo — ogni {REPORT_INTERVAL_HOURS} ore")

    while True:
        try:
            await asyncio.sleep(REPORT_INTERVAL_HOURS * 60 * 60)
            await send_admin_report()

        except Exception as e:
            print(f"[REPORT WORKER ERROR] {e}")
            await asyncio.sleep(60)


# ==================================================
# MAIN
# ==================================================

async def main():
    await init_db()

    print("Bot avviato in polling...")
    print("Assicurati che il bot sia admin del canale/gruppo.")
    print("Assicurati che il link abbia richiesta approvazione attiva.")

    asyncio.create_task(followup_worker())
    asyncio.create_task(report_worker())

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())