import asyncio
import os
import sqlite3
from io import BytesIO

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from google import genai
from google.genai import types
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_NAME = "ai_assistant.db"
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. Environment variable sifatida BOT_TOKEN ni kiriting.")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY topilmadi. Environment variable sifatida GEMINI_API_KEY ni kiriting.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """
Sen aqlli shaxsiy AI yordamchisan va Telegram orqali foydalanuvchiga yordam berasan.
Asosan o'zbek tilida tabiiy, tushunarli va foydali javob ber.
Foydalanuvchi boshqa tilda yozsa, o'sha tilda javob ber.

Sen quyidagilarda yordam berasan:
- maktab, kollej va universitet darslari
- matematika va masalalar
- ingliz tili va tarjima
- fizika, kimyo, tarix, geografiya
- Python, HTML, CSS, JavaScript va boshqa kodlar
- matn yozish, tahrirlash va qisqartirish
- reja, g'oya va kundalik ishlar
- rasmlardagi matn va masalalarni tushuntirish

Ta'lim savollarida imkon qadar bosqichma-bosqich tushuntir.
Savol noaniq bo'lsa, kerakli aniqlashtiruvchi savol ber.
Ishonching bo'lmagan faktni uydirma qilma.
"""

KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🤖 AI bilan suhbat"), KeyboardButton(text="📚 Dars")],
        [KeyboardButton(text="💻 Kod yordamchisi"), KeyboardButton(text="🌐 Tarjimon")],
        [KeyboardButton(text="📷 Rasm tahlili"), KeyboardButton(text="🧹 Suhbatni tozalash")],
    ],
    resize_keyboard=True,
)


def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.commit()


def save_user(user):
    with db() as conn:
        conn.execute(
            """INSERT INTO users(user_id, username, first_name)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username,
                 first_name=excluded.first_name""",
            (user.id, user.username, user.first_name),
        )
        conn.commit()


def save_message(user_id, role, content):
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        conn.commit()


def get_history(user_id, limit=20):
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return list(reversed([(row["role"], row["content"]) for row in rows]))


def clear_history(user_id):
    with db() as conn:
        conn.execute("DELETE FROM messages WHERE user_id=?", (user_id,))
        conn.commit()


def split_text(text, size=4000):
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


async def ask_ai(history, question):
    contents = []
    for role, text in history:
        contents.append(
            types.Content(
                role="user" if role == "user" else "model",
                parts=[types.Part.from_text(text=text)],
            )
        )
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)],
        )
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.7,
            max_output_tokens=3000,
        ),
    )
    return response.text or "Kechirasiz, hozir javob olishda muammo bo'ldi."


async def analyze_image(image_bytes, mime_type, question):
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            question,
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.5,
            max_output_tokens=3000,
        ),
    )
    return response.text or "Rasmni tahlil qilib bo'lmadi."


@dp.message(CommandStart())
async def start(message: Message):
    save_user(message.from_user)
    await message.answer(
        f"""🤖 Assalomu alaykum, {message.from_user.first_name or 'do‘st'}!

Men sizning aqlli AI yordamchingizman.

📚 Darslarda yordam beraman
🧮 Masalalarni yechaman
💻 Kod yozish va tuzatishda yordam beraman
🌐 Tarjima qilaman
✍️ Matn yozaman va tahrirlayman
📷 Rasmlarni tahlil qilaman
💡 G‘oyalar beraman
💬 Oddiy suhbat qilaman

Savolingizni yozing — boshlaymiz! 🚀""",
        reply_markup=KEYBOARD,
    )


@dp.message(Command("help"))
async def help_command(message: Message):
    await message.answer(
        """🤖 AI YORDAMCHI

Misollar:
📚 Present Perfectni tushuntir
🧮 2x + 7 = 19 ni yech
💻 Python'da class nima?
✍️ Menga rasmiy ariza yoz
🌐 Bu gapni inglizchaga tarjima qil
💡 Startup uchun 5 ta g'oya ber

📷 Rasm yuborib, savolingizni captionga yozishingiz mumkin.

Buyruqlar:
/start — boshlash
/clear — suhbat tarixini tozalash
/help — yordam"""
    )


@dp.message(Command("clear"))
async def clear_command(message: Message):
    clear_history(message.from_user.id)
    await message.answer("🧹 Suhbat tarixi tozalandi.")


@dp.message(F.text == "🧹 Suhbatni tozalash")
async def clear_button(message: Message):
    clear_history(message.from_user.id)
    await message.answer("🧹 Suhbat tarixi tozalandi.")


@dp.message(F.text == "🤖 AI bilan suhbat")
async def ai_button(message: Message):
    await message.answer("🤖 Marhamat! Savolingizni yozing.")


@dp.message(F.text == "📚 Dars")
async def lesson_button(message: Message):
    await message.answer(
        "📚 DARS REJIMI\n\n"
        "Fan va mavzuni yozing.\n\n"
        'Masalan: "Matematika: kvadrat tenglama"\n'
        '"English: Present Perfect"\n'
        '"Python: OOP"'
    )


@dp.message(F.text == "💻 Kod yordamchisi")
async def code_button(message: Message):
    await message.answer(
        "💻 KOD YORDAMCHISI\n\n"
        "Python, HTML, CSS, JavaScript va boshqa tillarda yordam beraman.\n\n"
        "Xato kodni yuboring yoki nima yaratmoqchi ekaningizni yozing."
    )


@dp.message(F.text == "🌐 Tarjimon")
async def translate_button(message: Message):
    await message.answer(
        "🌐 TARJIMON\n\n"
        'Masalan: "Hello, how are you? O‘zbekchaga tarjima qil."'
    )


@dp.message(F.text == "📷 Rasm tahlili")
async def image_button(message: Message):
    await message.answer(
        "📷 Rasmni yuboring va captionga savolingizni yozing.\n\n"
        "Masalan: 'Bu masalani yechib ber.'"
    )


@dp.message(F.photo)
async def photo_handler(message: Message):
    save_user(message.from_user)
    wait = await message.answer("📷 Rasmni tahlil qilyapman...")
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        downloaded = await bot.download_file(file.file_path)
        data = downloaded.read() if hasattr(downloaded, "read") else bytes(downloaded)
        question = message.caption or "Ushbu rasmni tahlil qil va undagi muhim ma'lumotlarni tushuntir."
        answer = await analyze_image(data, "image/jpeg", question)
        parts = split_text(answer)
        await wait.edit_text(parts[0])
        for part in parts[1:]:
            await message.answer(part)
    except Exception as exc:
        print("IMAGE ERROR:", repr(exc))
        await wait.edit_text("❌ Rasmni tahlil qilishda xatolik yuz berdi. API key va Gemini limitlarini tekshiring.")


@dp.message(F.text)
async def text_handler(message: Message):
    text = (message.text or "").strip()
    if not text:
        return

    if text in {
        "🤖 AI bilan suhbat",
        "📚 Dars",
        "💻 Kod yordamchisi",
        "🌐 Tarjimon",
        "📷 Rasm tahlili",
        "🧹 Suhbatni tozalash",
    }:
        return

    save_user(message.from_user)
    wait = await message.answer("🧠 O‘ylayapman...")
    try:
        history = get_history(message.from_user.id, 20)
        answer = await ask_ai(history, text)
        save_message(message.from_user.id, "user", text)
        save_message(message.from_user.id, "assistant", answer)

        parts = split_text(answer)
        await wait.edit_text(parts[0])
        for part in parts[1:]:
            await message.answer(part)
    except Exception as exc:
        print("AI ERROR:", repr(exc))
        await wait.edit_text(
            "❌ AI bilan bog‘lanishda xatolik.\n\n"
            "BOT_TOKEN, GEMINI_API_KEY yoki Gemini limitlarini tekshiring."
        )


WEBHOOK_PATH = "/webhook"


async def on_startup(bot_instance: Bot):
    base_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL")
    if not base_url:
        raise RuntimeError(
            "RENDER_EXTERNAL_URL topilmadi. Render Web Service URLsi mavjud bo‘lishi kerak."
        )

    webhook_url = f"{base_url.rstrip('/')}{WEBHOOK_PATH}"
    await bot_instance.set_webhook(
        url=webhook_url,
        drop_pending_updates=False,
    )
    print(f"✅ Webhook o‘rnatildi: {webhook_url}")


async def on_shutdown(bot_instance: Bot):
    await bot_instance.delete_webhook(drop_pending_updates=False)
    print("🛑 Webhook o‘chirildi.")


async def health(request):
    return web.json_response({"status": "ok", "bot": "AI Telegram Yordamchi"})


def main():
    init_db()
    print(f"🤖 AI Telegram bot ishga tushdi! Model: {MODEL}")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        handle_in_background=True,
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    port = int(os.getenv("PORT", "10000"))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
