import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from gigachat import GigaChat
import asyncpg

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_KEY = os.getenv("GIGACHAT_KEY")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

# --- БАЗА ЗНАНИЙ (ОСНОВА) ---
# Сюда мы добавили информацию из ТВОЕГО календаря
BASE_SYSTEM_PROMPT = """
Ты — умный помощник первичного отделения Движения Первых МБОУ СОШ №9 г. Брянска.
Твоя цель: вовлекать школьников, отвечать на вопросы и быть дружелюбным наставником.

ТВОИ БАЗОВЫЕ ЗНАНИЯ:
1. О Движении: Миссия — "Быть с Россией, Быть человеком, Быть вместе, Быть в движении, Быть Первыми". Ценности: Жизнь, Патриотизм, Дружба, Добро, Мечта, Труд.
2. О школе: Мы — МБОУ СОШ №9 г. Брянск.
   - Куратор: Седакова Елена Геннадьевна (@ElenaSedakovaSCH9)
   - Наставник: Межуева Алина Олеговна (@a_kzlva)
   - Председатель Совета: Алексеенкова Дарья
3. КАЛЕНДАРЬ СОБЫТИЙ (Январь-Февраль):
   - Тема "Культура и Искусство (Звучи)": Исследование музыкальных вкусов, создание школьных плейлистов, "Звуковой дневник".
   - Тема "Книжный клуб": Акции "Книга месяца", "Литературный мем", создание закладок, обсуждение книг (Гайдар "Чук и Гек", Одоевский "Мороз Иванович").
   - Тема "Волонтерство": Акции "День Спасибо" (11 января), "Письмо солдату", Помощь пожилым (уборка), Сбор макулатуры, "Лапа помощи" (животным).
   - Тема "Дипломатия": Изучение традиций стран, решение конфликтов, "Семейный саммит".
   - Важные даты: 27 января (День снятия блокады Ленинграда), 25 января (День студента).

ТВОЯ ЗАДАЧА:
Отвечать на вопросы, используя информацию выше И информацию о ТЕКУЩИХ мероприятиях школы, которую я пришлю ниже.
Если спрашивают о чем-то, чего нет в списке, отвечай вежливо и предлагай обратиться к куратору.
"""

# --- БАЗА ДАННЫХ ---
async def create_tables(pool):
    async with pool.acquire() as conn:
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS events (id SERIAL PRIMARY KEY, short_text TEXT, long_text TEXT, photo_id TEXT)")

async def add_user(pool, user_id, username):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING", user_id, username)

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

class BroadcastState(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()

class JoinState(StatesGroup):
    waiting_for_fio = State()
    waiting_for_age = State()
    waiting_for_class = State()
    waiting_for_direction = State()
    waiting_for_bio = State()

class IdeaState(StatesGroup):
    waiting_for_text = State()

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- КЛАВИАТУРЫ ---

def main_menu_kb():
    kb = [
        [InlineKeyboardButton(text="📂 Меню разделов", callback_data="menu_sections")],
        [InlineKeyboardButton(text="🤖 Спросить робота", callback_data="ask_ai")],
        [InlineKeyboardButton(text="🔥 Актуальные мероприятия", callback_data="list_events"), InlineKeyboardButton(text="📅 Календарь", callback_data="get_calendar")],
        [InlineKeyboardButton(text="✅ Вступить", callback_data="join_movement"), InlineKeyboardButton(text="💡 Идея", callback_data="send_idea")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def sections_kb():
    kb = [
        [InlineKeyboardButton(text="ℹ️ О Движении Первых", callback_data="sec_about_movement")],
        [InlineKeyboardButton(text="📝 Как вступить?", callback_data="sec_how_to_join")],
        [InlineKeyboardButton(text="🧩 Проекты", callback_data="sec_projects")],
        [InlineKeyboardButton(text="🏫 Про нашу первичку", callback_data="sec_our_branch")],
        [InlineKeyboardButton(text="📢 Деятельность", callback_data="sec_activities")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="sec_contacts")],
        [InlineKeyboardButton(text="🔙 На главную", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def back_kb(to="main_menu", text="🔙 Назад"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=to)]])

# Специальная кнопка отмены для форм
def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена / В меню", callback_data="cancel_action")]])

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, pool):
    await add_user(pool, message.from_user.id, message.from_user.username)
    # Используем HTML для форматирования
    photo = FSInputFile("img/main.jpg")
    caption = (
        "👋 <b>Привет!</b>\n"
        "Я — цифровой навигатор первичного отделения <b>МБОУ СОШ №9 г. Брянска</b>.\n\n"
        "Я здесь, чтобы помочь тебе сориентироваться в событиях и проектах Движения Первых.\n"
        "Подскажу, где найти информацию, напомню о дедлайнах и просто поболтаю!\n\n"
        "👨‍💻 <i>Разработал:</i> общественный организатор Артём Карпов @temhdg\n"
        "Поехали? 👇"
    )
    await message.answer_photo(photo=photo, caption=caption, parse_mode="HTML", reply_markup=main_menu_kb())

# --- НАВИГАЦИЯ ---

@dp.callback_query(F.data == "main_menu")
async def nav_main_menu(callback: types.CallbackQuery):
    await callback.message.delete()
    photo = FSInputFile("img/main.jpg")
    caption = "Главное меню. Выбери раздел: 👇"
    await callback.message.answer_photo(photo=photo, caption=caption, reply_markup=main_menu_kb())

@dp.callback_query(F.data == "cancel_action")
async def cancel_handler(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await nav_main_menu(callback)

@dp.callback_query(F.data == "menu_sections")
async def nav_sections(callback: types.CallbackQuery):
    await callback.message.delete()
    caption = "📂 <b>Меню разделов:</b>\nВыбери, что тебя интересует:"
    await callback.message.answer(caption, parse_mode="HTML", reply_markup=sections_kb())

# --- РАЗДЕЛЫ ---

@dp.callback_query(F.data == "sec_about_movement")
async def section_about(callback: types.CallbackQuery):
    text = (
        "🚀 <b>Что такое Движение Первых?</b>\n\n"
        "Движение Первых – единственная общественная организация в стране, где дети и взрослые остаются равноправными участниками. "
        "Это особое пространство для диалога детей, родителей, педагогов и наставников.\n\n"
        "📌 <b>Миссия Движения:</b>\n"
        "✅ Быть с Россией\n✅ Быть человеком\n✅ Быть вместе\n✅ Быть в движении\n✅ Быть Первыми\n\n"
        "❤️ <b>Ценности:</b> Жизнь, Патриотизм, Дружба, Добро, Мечта, Труд.\n\n"
        "<a href='https://будьвдвижении.рф/mission-values/'>🔗 Подробнее на сайте</a>"
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=back_kb("menu_sections"), disable_web_page_preview=True)

@dp.callback_query(F.data == "sec_how_to_join")
async def section_join_info(callback: types.CallbackQuery):
    text = (
        "📝 <b>Как вступить в Движение Первых?</b>\n\n"
        "1️⃣ Зайди на сайт <a href='https://id.pervye.ru/ref/department/19889'>id.pervye.ru</a>\n"
        "2️⃣ Нажми кнопку <b>Зарегистрироваться</b>.\n"
        "3️⃣ <b>Важно!</b> Правильно введи личные данные: ФИО, возраст, место проживания, город, школу, почту.\n"
        "4️⃣ <b>Прикрепись к первичке:</b> Нажми кнопку «Мое первичное отделение», в списке выбери <b>МБОУ СОШ №9 г. Брянск</b> и нажми «Сохранить».\n\n"
        "Готово! Ты в команде! 🎉"
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=back_kb("menu_sections"), disable_web_page_preview=True)

@dp.callback_query(F.data == "sec_projects")
async def section_projects(callback: types.CallbackQuery):
    text = (
        "💡 <b>Проекты Движения</b>\n\n"
        "Со всеми проектами можно ознакомиться на официальном сайте: <a href='https://projects.pervye.ru'>projects.pervye.ru</a>\n\n"
        "Там ты найдешь конкурсы, гранты и активности!"
    )
    await callback.message.delete()
    try:
        photo = FSInputFile("img/projects.jpg")
        await callback.message.answer_photo(photo, caption=text, parse_mode="HTML", reply_markup=back_kb("menu_sections"))
    except:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=back_kb("menu_sections"))

@dp.callback_query(F.data == "get_calendar")
async def get_calendar_file(callback: types.CallbackQuery):
    try:
        doc = FSInputFile("docs/calendar.pdf")
        await callback.message.answer_document(document=doc, caption="📅 <b>Календарь событий</b>\nСкачивай и планируй!", parse_mode="HTML")
    except:
        await callback.answer("⚠️ Файл календаря загружается.", show_alert=True)

@dp.callback_query(F.data == "sec_our_branch")
async def section_branch(callback: types.CallbackQuery):
    text = (
        "🏫 <b>Наше Первичное отделение</b>\n\n"
        "Всем привет! Мы первичное отделение <b>МБОУ СОШ №9 г. Брянска</b>.\n"
        "Мы утверждаем: неуспешных детей нет. Успеха может добиться каждый!\n\n"
        "<b>Наша команда:</b>\n"
        "👤 <b>Куратор:</b> Седакова Елена Геннадьевна\n"
        "👤 <b>Председатель Совета:</b> Алексеенкова Дарья\n"
        "👤 <b>Наставник:</b> Межуева Алина Олеговна\n\n"
        "Добивайся успеха вместе с нами!"
    )
    await callback.message.delete()
    try:
        photo = FSInputFile("img/team.jpg")
        await callback.message.answer_photo(photo, caption=text, parse_mode="HTML", reply_markup=back_kb("menu_sections"))
    except:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=back_kb("menu_sections"))

@dp.callback_query(F.data == "sec_activities")
async def section_activities(callback: types.CallbackQuery):
    text = (
        "📢 <b>Деятельность первичного отделения</b>\n\n"
        "<b>Наши основные направления:</b>\n"
        "🇷🇺 <b>Патриотизм:</b> Акция «Окна Победы», квесты.\n"
        "❤️ <b>Волонтерство:</b> Социальные акции, помощь нуждающимся.\n"
        "⚽ <b>Спорт и ЗОЖ:</b> Спортивные мероприятия.\n"
        "🧠 <b>Образование:</b> Квизы, мастер-классы, встречи с профи.\n"
        "🎤 <b>Культура и медиа:</b> Творческие проекты, школьное радио «Девяточка»."
    )
    await callback.message.delete()
    try:
        photo = FSInputFile("img/activities.jpg")
        await callback.message.answer_photo(photo, caption=text, parse_mode="HTML", reply_markup=back_kb("menu_sections"))
    except:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=back_kb("menu_sections"))

@dp.callback_query(F.data == "sec_contacts")
async def section_contacts(callback: types.CallbackQuery):
    text = (
        "📞 <b>Наши контакты</b>\n\n"
        "📲 <b>Группа Первички:</b> <a href='https://vk.ru/pervyedevyatochki'>vk.ru/pervyedevyatochki</a>\n"
        "🏫 <b>Школьная группа:</b> <a href='https://vk.ru/sch9bryansk'>vk.ru/sch9bryansk</a>\n\n"
        "👤 <b>Седакова Елена Геннадьевна:</b> @ElenaSedakovaSCH9\n"
        "👤 <b>Межуева Алина Олеговна:</b> @a_kzlva\n\n"
        "🔗 <b>Канал MAX:</b> <a href='https://max.ru/id3234036720_gos'>Перейти</a>"
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="HTML", reply_markup=back_kb("menu_sections"), disable_web_page_preview=True)

# --- АНКЕТЫ (ВСТУПИТЬ И ИДЕЯ) ---

@dp.callback_query(F.data == "join_movement")
async def start_join_form(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("📝 <b>Анкета вступления</b>\nВведите ваши ФИО:", parse_mode="HTML", reply_markup=cancel_kb())
    await state.set_state(JoinState.waiting_for_fio)

@dp.message(JoinState.waiting_for_fio)
async def join_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer("Сколько вам лет?", reply_markup=cancel_kb())
    await state.set_state(JoinState.waiting_for_age)

@dp.message(JoinState.waiting_for_age)
async def join_age(message: types.Message, state: FSMContext):
    await state.update_data(age=message.text)
    await message.answer("Из какого вы класса? (Например, 8Б)", reply_markup=cancel_kb())
    await state.set_state(JoinState.waiting_for_class)

@dp.message(JoinState.waiting_for_class)
async def join_class(message: types.Message, state: FSMContext):
    await state.update_data(grade=message.text)
    await message.answer("Какое направление вам интересно? (Спорт, Медиа...)", reply_markup=cancel_kb())
    await state.set_state(JoinState.waiting_for_direction)

@dp.message(JoinState.waiting_for_direction)
async def join_direction(message: types.Message, state: FSMContext):
    await state.update_data(direction=message.text)
    await message.answer("Расскажите немного о себе:", reply_markup=cancel_kb())
    await state.set_state(JoinState.waiting_for_bio)

@dp.message(JoinState.waiting_for_bio)
async def join_finish(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    admin_text = (
        f"✅ <b>Новая заявка на вступление!</b>\n"
        f"👤 От: @{message.from_user.username}\n"
        f"📝 ФИО: {data['fio']}\n"
        f"🎂 Возраст: {data['age']}\n"
        f"🏫 Класс: {data['grade']}\n"
        f"🎯 Направление: {data['direction']}\n"
        f"💬 О себе: {message.text}"
    )
    await bot.send_message(ADMIN_GROUP_ID, admin_text, parse_mode="HTML")
    await message.answer("✅ Спасибо! Заявка отправлена.", reply_markup=back_kb("main_menu", "🏠 В главное меню"))
    await state.clear()

@dp.callback_query(F.data == "send_idea")
async def start_idea(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("💡 <b>Есть идея?</b>\nОпиши её одним сообщением:", parse_mode="HTML", reply_markup=cancel_kb())
    await state.set_state(IdeaState.waiting_for_text)

@dp.message(IdeaState.waiting_for_text)
async def process_idea(message: types.Message, state: FSMContext, bot: Bot):
    admin_text = (
        f"💡 <b>Новая ИДЕЯ!</b>\n"
        f"👤 От: @{message.from_user.username}\n"
        f"💬 Суть: {message.text}"
    )
    await bot.send_message(ADMIN_GROUP_ID, admin_text, parse_mode="HTML")
    await message.answer("✅ Идея отправлена!", reply_markup=back_kb("main_menu", "🏠 В главное меню"))
    await state.clear()

# --- АДМИНКА ---

@dp.message(Command("panel"))
async def admin_panel(message: types.Message):
    if message.chat.id != ADMIN_GROUP_ID:
        return
    kb = [
        [InlineKeyboardButton(text="➕ Добавить мероприятие", callback_data="add_event")],
        [InlineKeyboardButton(text="📢 Рассылка (сообщение всем)", callback_data="broadcast_msg")],
        [InlineKeyboardButton(text="👀 Просмотреть мероприятия", callback_data="list_events")],
        [InlineKeyboardButton(text="❌ Удалить мероприятие", callback_data="del_event_menu")]
    ]
    await message.answer("🛠 <b>Панель администратора:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# Мероприятия
@dp.callback_query(F.data == "list_events")
async def list_events_handler(callback: types.CallbackQuery, pool):
    events = await get_events_db(pool)
    if not events:
        await callback.answer("Мероприятий пока нет.", show_alert=True)
        return
    
    response = "🗓 <b>АКТУАЛЬНЫЕ МЕРОПРИЯТИЯ:</b>\n\n"
    kb_list = []
    
    for idx, event in enumerate(events, 1):
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        icon = emojis[idx-1] if idx <= 10 else f"{idx}."
        # Жирный текст без звездочек
        response += f"{icon} <b>{event['short_text']}</b>\n➖➖➖➖➖➖\n"
        kb_list.append([InlineKeyboardButton(text=f"{icon} Подробнее", callback_data=f"view_event_{event['id']}")])
    
    kb_list.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    await callback.message.delete()
    await callback.message.answer(response, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("view_event_"))
async def view_event_detail(callback: types.CallbackQuery, pool):
    event_id = int(callback.data.split("_")[2])
    event = await get_event_by_id(pool, event_id)
    if event:
        text = f"📢 <b>ПОДРОБНОСТИ:</b>\n\n{event['long_text']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 К списку", callback_data="list_events")]])
        await callback.message.delete()
        if event['photo_id']:
            await callback.message.answer_photo(event['photo_id'], caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.answer("Мероприятие удалено.", show_alert=True)

# Добавление (Админ)
@dp.callback_query(F.data == "add_event")
async def start_add_event(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Введите КРАТКОЕ описание (для списка).", reply_markup=cancel_kb())
    await state.set_state(AdminEvent.waiting_for_short)
    await callback.answer()

@dp.message(AdminEvent.waiting_for_short)
async def process_short(message: types.Message, state: FSMContext):
    await state.update_data(short_text=message.text)
    await message.answer("📝 Введите ПОЛНОЕ описание.", reply_markup=cancel_kb())
    await state.set_state(AdminEvent.waiting_for_long)

@dp.message(AdminEvent.waiting_for_long)
async def process_long(message: types.Message, state: FSMContext):
    await state.update_data(long_text=message.text)
    await message.answer("🖼 Пришлите фото или напишите 'нет'.", reply_markup=cancel_kb())
    await state.set_state(AdminEvent.waiting_for_photo)

@dp.message(AdminEvent.waiting_for_photo)
async def process_photo(message: types.Message, state: FSMContext, pool):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    await add_event_db(pool, data['short_text'], data['long_text'], photo_id)
    await message.answer("✅ Мероприятие добавлено!")
    await state.clear()
    # Рассылка
    users = await get_all_users(pool)
    for uid in users:
        try:
            msg = f"⚡ <b>НОВОЕ МЕРОПРИЯТИЕ!</b>\n\n{data['short_text']}\n\n👉 <i>Жми кнопку 'Актуальные мероприятия' в меню!</i>"
            await bot.send_message(uid, msg, parse_mode="HTML")
        except: pass
    await message.answer("Рассылка завершена.")

# Удаление (Админ)
@dp.callback_query(F.data == "del_event_menu")
async def del_menu(callback: types.CallbackQuery, pool):
    events = await get_events_db(pool)
    if not events:
        await callback.answer("Нечего удалять.", show_alert=True)
        return
    kb_list = [[InlineKeyboardButton(text=f"❌ {e['short_text'][:15]}...", callback_data=f"del_conf_{e['id']}")] for e in events]
    kb_list.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="main_menu")]) # Добавил кнопку возврата
    await callback.message.answer("Выберите, что удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("del_conf_"))
async def del_confirm(callback: types.CallbackQuery, pool):
    eid = int(callback.data.split("_")[2])
    await delete_event_db(pool, eid)
    await callback.answer("Удалено!")
    await callback.message.delete()

# Рассылка (Админ)
@dp.callback_query(F.data == "broadcast_msg")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Введите текст сообщения для ВСЕХ пользователей:", reply_markup=cancel_kb())
    await state.set_state(BroadcastState.waiting_for_text)
    await callback.answer()

@dp.message(BroadcastState.waiting_for_text)
async def broadcast_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("🖼 Прикрепите фото или напишите 'нет'.", reply_markup=cancel_kb())
    await state.set_state(BroadcastState.waiting_for_photo)

@dp.message(BroadcastState.waiting_for_photo)
async def broadcast_finish(message: types.Message, state: FSMContext, pool):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    users = await get_all_users(pool)
    count = 0
    await message.answer("🚀 Начинаю рассылку...")
    for uid in users:
        try:
            if photo_id:
                await bot.send_photo(uid, photo_id, caption=data['text'], parse_mode="HTML")
            else:
                await bot.send_message(uid, data['text'], parse_mode="HTML")
            count += 1
        except: pass
    await message.answer(f"✅ Рассылка завершена. Получили: {count} чел.")
    await state.clear()

# --- НЕЙРОСЕТЬ (УМНАЯ) ---

@dp.callback_query(F.data == "ask_ai")
async def ask_ai_mode(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🤖 <b>Я на связи!</b>\nНапиши мне любой вопрос про школу, Движение или наши мероприятия.", parse_mode="HTML", reply_markup=back_kb())

@dp.message()
async def chat_with_ai(message: types.Message, pool):
    if message.chat.type != 'private': return
    waiting_msg = await message.answer("🤖 <i>Думаю...</i>", parse_mode="HTML")
    
    try:
        # 1. Получаем актуальные школьные мероприятия из БД
        events = await get_events_db(pool)
        events_str = "\n".join([f"- {e['short_text']}: {e['long_text']}" for e in events]) if events else "Пока нет добавленных мероприятий."

        # 2. Формируем полный промпт
        FULL_PROMPT = BASE_SYSTEM_PROMPT + f"\n\nТЕКУЩИЕ МЕРОПРИЯТИЯ ШКОЛЫ ИЗ БАЗЫ ДАННЫХ:\n{events_str}"

        # 3. Отправляем в GigaChat
        with GigaChat(credentials=GIGACHAT_KEY, verify_ssl_certs=False) as giga:
            payload = {
                "messages": [
                    {"role": "system", "content": FULL_PROMPT},
                    {"role": "user", "content": message.text}
                ]
            }
            response = giga.chat(payload)
            await waiting_msg.edit_text(response.choices[0].message.content)
            
    except Exception as e:
        await waiting_msg.edit_text(f"Ошибка: {e}")

# --- ЗАПУСК ---
async def main():
    pool = await asyncpg.create_pool(dsn=DATABASE_URL)
    await create_tables(pool)
    dp["pool"] = pool
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
