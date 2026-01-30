import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, InputFile
from gigachat import GigaChat
import asyncpg

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_KEY = os.getenv("GIGACHAT_KEY")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID")) # ID группы админов
DATABASE_URL = os.getenv("DATABASE_URL")

# Промпт для Нейросети (Знания бота)
SYSTEM_PROMPT = """
Ты помощник первичного отделения Движения Первых МБОУ СОШ №9 г. Брянска. 
Твоя задача - отвечать на вопросы школьников, быть дружелюбным и патриотичным.
Ты знаешь следующую информацию:
1. О Движении: Дата основания 20.07.2022. Миссия: Быть с Россией, Быть человеком, Быть вместе, Быть в движении, Быть Первыми.
2. О школе: МБОУ СОШ №9 г. Брянск. Куратор: Седакова Елена Геннадьевна. Председатель Совета: Алексеенкова Дарья. Наставник: Межуева Алина Олеговна.
3. Ценности: Жизнь и достоинство, Патриотизм, Дружба, Добро и справедливость, Мечта, Созидательный труд.
4. Проекты: Зарница 2.0, Первые в профессии, Хранители истории.
5. Текущий календарь мероприятий доступен в боте.
Если тебя спрашивают о том, чего нет в этом тексте, отвечай как полезный ассистент, используй свои общие знания, но в контексте школьника.
"""

# --- БАЗА ДАННЫХ ---
async def create_tables(pool):
    async with pool.acquire() as conn:
        # Таблица пользователей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT
            )
        """)
        # Таблица мероприятий
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                short_text TEXT,
                long_text TEXT,
                photo_id TEXT
            )
        """)

async def add_user(pool, user_id, username):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username) VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
        """, user_id, username)

async def get_all_users(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        return [row['user_id'] for row in rows]

async def add_event_db(pool, short_text, long_text, photo_id):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO events (short_text, long_text, photo_id) VALUES ($1, $2, $3)", short_text, long_text, photo_id)

async def get_events_db(pool):
    async with pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM events ORDER BY id DESC")

async def get_event_by_id(pool, event_id):
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM events WHERE id = $1", event_id)

async def delete_event_db(pool, event_id):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM events WHERE id = $1", event_id)


# --- FSM (СОСТОЯНИЯ) ---
class AdminEvent(StatesGroup):
    waiting_for_short = State()
    waiting_for_long = State()
    waiting_for_photo = State()

class JoinState(StatesGroup):
    waiting_for_name = State()
    waiting_for_class = State()
    waiting_for_dir = State()
    waiting_for_bio = State()

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    kb = [
        [types.KeyboardButton(text="🚀 Что такое Движение Первых?")],
        [types.KeyboardButton(text="📝 Как вступить?"), types.KeyboardButton(text="💡 Проекты и Календарь")],
        [types.KeyboardButton(text="🏫 Наша первичка"), types.KeyboardButton(text="📢 Деятельность")],
        [types.KeyboardButton(text="📅 Актуальные мероприятия школы")],
        [types.KeyboardButton(text="📨 Контакты"), types.KeyboardButton(text="✨ Идея / Вступить к нам")],
        [types.KeyboardButton(text="🤖 Спросить робота")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ХЕНДЛЕРЫ (ОБРАБОТЧИКИ) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, pool):
    await add_user(pool, message.from_user.id, message.from_user.username)
    photo = FSInputFile("img/main.jpg")
    caption = (
        "Привет! 👋\n"
        "Я — цифровой навигатор первичного отделения МБОУ «Гимназия №9» г. Брянск.\n\n"
        "Я здесь, чтобы помочь тебе сориентироваться в событиях и проектах Движения Первых.\n"
        "Подскажу, где найти информацию, напомню о дедлайнах и просто поболтаю!\n\n"
        "👨‍💻 *Разработал:* общественный организатор Артём Карпов @temhdg\n"
        "Поехали?"
    )
    await message.answer_photo(photo=photo, caption=caption, parse_mode="Markdown", reply_markup=get_main_keyboard())

# 1. Что такое движение
@dp.message(F.text == "🚀 Что такое Движение Первых?")
async def info_movement(message: types.Message):
    text = (
        "🇷🇺 **Движение Первых** – это пространство для диалога и реализации идей!\n\n"
        "**Наша миссия:**\n"
        "✅ Быть с Россией\n✅ Быть человеком\n✅ Быть вместе\n✅ Быть в движении\n✅ Быть Первыми\n\n"
        "**Наши ценности:** Жизнь, Патриотизм, Дружба, Добро, Мечта, Труд.\n\n"
        "🔗 [Подробнее о миссии](https://будьвдвижении.рф/mission-values/)"
    )
    await message.answer(text, parse_mode="Markdown", link_preview_options=types.LinkPreviewOptions(is_disabled=True))

# 2. Как вступить
@dp.message(F.text == "📝 Как вступить?")
async def info_join(message: types.Message):
    text = (
        "Чтобы стать частью Движения:\n\n"
        "1️⃣ Зайди на сайт [будьвдвижении.рф](https://id.pervye.ru/ref/department/19889)\n"
        "2️⃣ Нажми **Зарегистрироваться**.\n"
        "3️⃣ Заполни данные (ФИО, город, школа).\n"
        "4️⃣ **ВАЖНО:** Нажми «Мое первичное отделение», выбери МБОУ СОШ №9 г. Брянск и нажми Сохранить."
    )
    await message.answer(text, parse_mode="Markdown")

# 3. Проекты и Календарь
@dp.message(F.text == "💡 Проекты и Календарь")
async def info_projects(message: types.Message, bot: Bot):
    text = (
        "Все проекты смотри тут: [projects.pervye.ru](https://projects.pervye.ru)\n"
        "А ниже я прикрепил наш календарь событий! 👇"
    )
    # Отправка файла
    try:
        doc = FSInputFile("docs/calendar.pdf")
        await message.answer_document(document=doc, caption=text, parse_mode="Markdown")
    except:
        await message.answer(text + "\n(Файл календаря пока не загружен, спроси у админа)")

# 4. Наша первичка
@dp.message(F.text == "🏫 Наша первичка")
async def info_branch(message: types.Message):
    photo = FSInputFile("img/team.jpg")
    text = (
        "**МБОУ СОШ №9 г. Брянска — Школа успеха!** 🏆\n\n"
        "Мы утверждаем: неуспешных детей нет. Добьемся успеха вместе!\n\n"
        "👤 **Куратор:** Седакова Елена Геннадьевна\n"
        "👤 **Председатель Совета:** Алексеенкова Дарья\n"
        "👤 **Наставник:** Межуева Алина Олеговна\n\n"
        "🔗 [Группа первички](https://vk.ru/pervyedevyatochki)\n"
        "🔗 [Школьная группа](https://vk.ru/sch9bryansk)"
    )
    await message.answer_photo(photo=photo, caption=text, parse_mode="Markdown")

# 5. Деятельность
@dp.message(F.text == "📢 Деятельность")
async def info_activities(message: types.Message):
    photo = FSInputFile("img/activities.jpg")
    text = (
        "**Чем мы занимаемся?**\n\n"
        "🇷🇺 **Патриотизм:** Акции «Окна Победы», квесты.\n"
        "❤️ **Волонтерство:** Социальные акции, сбор помощи.\n"
        "⚽ **Спорт:** ЗОЖ, соревнования.\n"
        "🧠 **Образование:** Квизы, встречи с профи.\n"
        "🎤 **Медиа:** Радио «Девяточка»."
    )
    await message.answer_photo(photo=photo, caption=text, parse_mode="Markdown")

# 6. Контакты
@dp.message(F.text == "📨 Контакты")
async def info_contacts(message: types.Message):
    await message.answer("Мы ВКонтакте: https://vk.ru/pervyedevyatochki\nГлавный организатор: @temhdg")

# --- ЛОГИКА АДМИНКИ (ДОБАВЛЕНИЕ МЕРОПРИЯТИЯ) ---

@dp.message(Command("panel"))
async def admin_panel(message: types.Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="➕ Добавить мероприятие", callback_data="add_event")],
        [types.InlineKeyboardButton(text="❌ Удалить мероприятие", callback_data="del_event_menu")]
    ])
    await message.answer("🛠 Панель администратора:", reply_markup=kb)

@dp.callback_query(F.data == "add_event")
async def start_add_event(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Шаг 1. Введите КРАТКОЕ описание (для рассылки и списка). Не более 3 предложений.")
    await state.set_state(AdminEvent.waiting_for_short)
    await callback.answer()

@dp.message(AdminEvent.waiting_for_short)
async def process_short(message: types.Message, state: FSMContext):
    await state.update_data(short_text=message.text)
    await message.answer("Шаг 2. Введите ПОЛНОЕ описание мероприятия.")
    await state.set_state(AdminEvent.waiting_for_long)

@dp.message(AdminEvent.waiting_for_long)
async def process_long(message: types.Message, state: FSMContext):
    await state.update_data(long_text=message.text)
    await message.answer("Шаг 3. Пришлите фото (одну) или напишите 'нет'.")
    await state.set_state(AdminEvent.waiting_for_photo)

@dp.message(AdminEvent.waiting_for_photo)
async def process_photo(message: types.Message, state: FSMContext, pool):
    data = await state.get_data()
    photo_id = None
    
    if message.photo:
        photo_id = message.photo[-1].file_id
    elif message.text and message.text.lower() != 'нет':
        await message.answer("Пожалуйста, пришли фото или напиши 'нет'.")
        return

    # Сохраняем в БД
    await add_event_db(pool, data['short_text'], data['long_text'], photo_id)
    await message.answer("✅ Мероприятие сохранено! Начинаю рассылку...")
    await state.clear()

    # Рассылка
    users = await get_all_users(pool)
    count = 0
    for uid in users:
        try:
            msg = f"⚡ **НОВОЕ МЕРОПРИЯТИЕ!**\n\n{data['short_text']}\n\n👉 *Подробности в разделе 'Актуальные мероприятия'* "
            await bot.send_message(uid, msg, parse_mode="Markdown")
            count += 1
        except:
            pass
    await message.answer(f"Рассылка завершена. Отправлено: {count} пользователям.")

# --- ПРОСМОТР МЕРОПРИЯТИЙ (ПОЛЬЗОВАТЕЛЬ) ---

@dp.message(F.text == "📅 Актуальные мероприятия школы")
async def list_events(message: types.Message, pool):
    events = await get_events_db(pool)
    if not events:
        await message.answer("Пока нет актуальных мероприятий.")
        return
    
    response = "🗓 **АКТУАЛЬНЫЕ МЕРОПРИЯТИЯ:**\n\n"
    kb_list = []
    
    for idx, event in enumerate(events, 1):
        # Эмодзи цифр
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        icon = emojis[idx-1] if idx <= 10 else f"{idx}."
        
        response += f"{icon} {event['short_text']}\n➖➖➖➖➖➖\n"
        kb_list.append([types.InlineKeyboardButton(text=f"{icon} Читать подробнее", callback_data=f"view_event_{event['id']}")])
    
    response += "\n👇 **Нажми на кнопку, чтобы узнать подробнее:**"
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb_list)
    await message.answer(response, parse_mode="Markdown", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("view_event_"))
async def view_event_detail(callback: types.CallbackQuery, pool):
    event_id = int(callback.data.split("_")[2])
    event = await get_event_by_id(pool, event_id)
    
    if event:
        text = f"📢 **ПОДРОБНОСТИ:**\n\n{event['long_text']}"
        kb = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔙 Назад к списку", callback_data="back_to_events")]])
        
        if event['photo_id']:
            await callback.message.answer_photo(event['photo_id'], caption=text, reply_markup=kb, parse_mode="Markdown")
        else:
            await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.message.answer("Мероприятие не найдено (возможно, удалено).")
    await callback.answer()

@dp.callback_query(F.data == "back_to_events")
async def back_to_list(callback: types.CallbackQuery):
    await callback.message.delete() # Удаляем подробное сообщение, чтобы не захламлять

# --- УДАЛЕНИЕ МЕРОПРИЯТИЙ (АДМИН) ---
@dp.callback_query(F.data == "del_event_menu")
async def delete_menu(callback: types.CallbackQuery, pool):
    events = await get_events_db(pool)
    if not events:
        await callback.message.answer("Нет мероприятий для удаления.")
        return
    
    kb_list = []
    for event in events:
        kb_list.append([types.InlineKeyboardButton(text=f"❌ Удалить: {event['short_text'][:20]}...", callback_data=f"del_conf_{event['id']}")])
    
    await callback.message.answer("Выберите мероприятие для удаления:", reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_list))
    await callback.answer()

@dp.callback_query(F.data.startswith("del_conf_"))
async def delete_confirm(callback: types.CallbackQuery, pool):
    event_id = int(callback.data.split("_")[2])
    await delete_event_db(pool, event_id)
    await callback.message.answer("🗑 Мероприятие удалено.")
    await callback.answer()


# --- АНКЕТА (ВСТУПИТЬ / ИДЕЯ) ---
@dp.message(F.text == "✨ Идея / Вступить к нам")
async def idea_start(message: types.Message, state: FSMContext):
    await message.answer("Хочешь вступить в команду или предложить идею? \nНапиши свои **ФИО**:")
    await state.set_state(JoinState.waiting_for_name)

@dp.message(JoinState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Из какого ты класса?")
    await state.set_state(JoinState.waiting_for_class)

@dp.message(JoinState.waiting_for_class)
async def process_class(message: types.Message, state: FSMContext):
    await state.update_data(grade=message.text)
    await message.answer("Какое направление тебе интересно? (Медиа, Спорт, Волонтерство и т.д.)")
    await state.set_state(JoinState.waiting_for_dir)

@dp.message(JoinState.waiting_for_dir)
async def process_dir(message: types.Message, state: FSMContext):
    await state.update_data(direction=message.text)
    await message.answer("Напиши свою идею или расскажи немного о себе:")
    await state.set_state(JoinState.waiting_for_bio)

@dp.message(JoinState.waiting_for_bio)
async def process_bio(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    # Отправка в админ чат
    admin_text = (
        f"🆕 **Новая заявка/Идея!**\n"
        f"👤 От: {message.from_user.full_name} (@{message.from_user.username})\n"
        f"📝 ФИО: {data['name']}\n"
        f"🏫 Класс: {data['grade']}\n"
        f"🎯 Направление: {data['direction']}\n"
        f"💬 Текст: {message.text}"
    )
    await bot.send_message(ADMIN_GROUP_ID, admin_text)
    await message.answer("✅ Спасибо! Твоя заявка отправлена кураторам.")
    await state.clear()


# --- GIGACHAT (НЕЙРОСЕТЬ) ---
@dp.message(F.text == "🤖 Спросить робота")
async def ask_robot_intro(message: types.Message):
    await message.answer("Я слушаю! Напиши свой вопрос о Движении, школе или мероприятиях 👇")

@dp.message()
async def chat_with_ai(message: types.Message):
    # Если это не кнопка, считаем это вопросом к ИИ
    waiting_msg = await message.answer("🤖 Думаю...")
    
    try:
        # Инициализация GigaChat
        with GigaChat(credentials=GIGACHAT_KEY, verify_ssl_certs=False) as giga:
            # ИСПРАВЛЕНИЕ: Теперь мы передаем не просто список, а словарь с ключом 'messages'
            payload = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": message.text}
                ]
            }
            response = giga.chat(payload)
            answer_text = response.choices[0].message.content
            
            await waiting_msg.edit_text(answer_text)
    except Exception as e:
        await waiting_msg.edit_text(f"Прости, я немного завис. Попробуй позже. (Ошибка: {e})")
        
# --- ЗАПУСК ---
async def main():
    # Создаем пул соединения с БД
    pool = await asyncpg.create_pool(dsn=DATABASE_URL)
    await create_tables(pool)
    
    # Передаем пул в хендлеры
    dp["pool"] = pool
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
