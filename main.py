import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from gigachat import GigaChat
import asyncpg

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
GIGACHAT_KEY = os.getenv("GIGACHAT_KEY")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

# Промпт для Нейросети
SYSTEM_PROMPT = """
Ты помощник первичного отделения Движения Первых МБОУ СОШ №9 г. Брянска. 
Твоя задача - отвечать на вопросы школьников, быть дружелюбным и патриотичным.
Ты знаешь следующую информацию:
1. О Движении: Дата основания 20.07.2022. Миссия: Быть с Россией, Быть человеком, Быть вместе, Быть в движении, Быть Первыми.
2. О школе: МБОУ СОШ №9 г. Брянск. Куратор: Седакова Елена Геннадьевна. Председатель Совета: Алексеенкова Дарья. Наставник: Межуева Алина Олеговна.
3. Ценности: Жизнь и достоинство, Патриотизм, Дружба, Добро и справедливость, Мечта, Созидательный труд.
4. Проекты: Зарница 2.0, Первые в профессии, Хранители истории.
5. Контакты: Елена Геннадьевна (@ElenaSedakovaSCH9), Алина Олеговна (@a_kzlva).
Если тебя спрашивают о том, чего нет в этом тексте, отвечай как полезный ассистент.
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

# --- КЛАВИАТУРЫ (INLINE) ---

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

def back_kb(to="main_menu"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=to)]])

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, pool):
    await add_user(pool, message.from_user.id, message.from_user.username)
    photo = FSInputFile("img/main.jpg")
    caption = (
        "👋 **Привет!**\n"
        "Я — цифровой навигатор первичного отделения **МБОУ СОШ №9 г. Брянска**.\n\n"
        "Я здесь, чтобы помочь тебе сориентироваться в событиях и проектах Движения Первых.\n"
        "Подскажу, где найти информацию, напомню о дедлайнах и просто поболтаю!\n\n"
        "👨‍💻 *Разработал:* общественный организатор Артём Карпов @temhdg\n"
        "Поехали? 👇"
    )
    await message.answer_photo(photo=photo, caption=caption, parse_mode="Markdown", reply_markup=main_menu_kb())

# --- НАВИГАЦИЯ ---

@dp.callback_query(F.data == "main_menu")
async def nav_main_menu(callback: types.CallbackQuery):
    # При возврате удаляем старое сообщение и присылаем новое фото меню
    await callback.message.delete()
    photo = FSInputFile("img/main.jpg")
    caption = "Главное меню. Выбери раздел: 👇"
    await callback.message.answer_photo(photo=photo, caption=caption, reply_markup=main_menu_kb())

@dp.callback_query(F.data == "menu_sections")
async def nav_sections(callback: types.CallbackQuery):
    await callback.message.delete()
    caption = "📂 **Меню разделов:**\nВыбери, что тебя интересует:"
    await callback.message.answer(caption, parse_mode="Markdown", reply_markup=sections_kb())

# --- РАЗДЕЛЫ ИНФОРМАЦИИ ---

@dp.callback_query(F.data == "sec_about_movement")
async def section_about(callback: types.CallbackQuery):
    text = (
        "🚀 **Что такое Движение Первых?**\n\n"
        "Движение Первых – единственная общественная организация в стране, где дети и взрослые остаются равноправными участниками. "
        "Это особое пространство для диалога детей, родителей, педагогов и наставников. Здесь каждый имеет возможность реализовать свои идеи и мечты!\n\n"
        "📌 **Миссия Движения:**\n"
        "✅ Быть с Россией\n✅ Быть человеком\n✅ Быть вместе\n✅ Быть в движении\n✅ Быть Первыми\n\n"
        "❤️ **Ценности Движения:**\n"
        "Жизнь и достоинство, Патриотизм, Дружба, Добро и справедливость, Мечта, Созидательный труд, Взаимопомощь, Единство народов России, Историческая память, Служение Отечеству, Крепкая семья.\n\n"
        "🔗 [Подробнее о миссии и ценностях](https://будьвдвижении.рф/mission-values/)"
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="Markdown", link_preview_options=types.LinkPreviewOptions(is_disabled=True), reply_markup=back_kb("menu_sections"))

@dp.callback_query(F.data == "sec_how_to_join")
async def section_join_info(callback: types.CallbackQuery):
    text = (
        "📝 **Как вступить в Движение Первых?**\n\n"
        "1️⃣ Зайди на сайт [id.pervye.ru](https://id.pervye.ru/ref/department/19889)\n"
        "2️⃣ Нажми кнопку **Зарегистрироваться**.\n"
        "3️⃣ **Важно!** Правильно введи личные данные: ФИО, возраст, место проживания, город, школу, почту.\n"
        "4️⃣ **Прикрепись к первичке:** Нажми кнопку «Мое первичное отделение», в списке выбери **МБОУ СОШ №9 г. Брянск** и нажми «Сохранить».\n\n"
        "Готово! Ты в команде! 🎉"
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="Markdown", link_preview_options=types.LinkPreviewOptions(is_disabled=True), reply_markup=back_kb("menu_sections"))

@dp.callback_query(F.data == "sec_projects")
async def section_projects(callback: types.CallbackQuery):
    text = (
        "💡 **Проекты Движения**\n\n"
        "Со всеми проектами можно ознакомиться на официальном сайте: [projects.pervye.ru](https://projects.pervye.ru)\n\n"
        "Там ты найдешь конкурсы, гранты и активности, на которые можно подать заявку прямо сейчас!"
    )
    await callback.message.delete()
    photo = FSInputFile("img/projects.jpg")
    try:
        await callback.message.answer_photo(photo, caption=text, parse_mode="Markdown", reply_markup=back_kb("menu_sections"))
    except:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_kb("menu_sections"))

@dp.callback_query(F.data == "get_calendar")
async def get_calendar_file(callback: types.CallbackQuery):
    try:
        doc = FSInputFile("docs/calendar.pdf")
        await callback.message.answer_document(document=doc, caption="📅 **Календарь событий**\nСкачивай и планируй!", parse_mode="Markdown")
    except:
        await callback.message.answer("⚠️ Файл календаря пока обновляется.", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data == "sec_our_branch")
async def section_branch(callback: types.CallbackQuery):
    text = (
        "🏫 **Наше Первичное отделение**\n\n"
        "Всем привет! Мы первичное отделение **МБОУ СОШ №9 г. Брянска**. Давай знакомиться!\n"
        "Наша школа — уникальное учреждение, школа успеха. Мы верим, что успеха может добиться каждый!\n\n"
        "🏆 Жизнь раздает награды в конце пути. Мы будем упорствовать вместе, пока не добьемся успеха!\n\n"
        "**Наша команда:**\n"
        "👤 **Куратор:** Седакова Елена Геннадьевна\n"
        "👤 **Председатель Совета Первых:** Алексеенкова Дарья\n"
        "👤 **Наставник:** Межуева Алина Олеговна\n\n"
        "Добивайся успеха вместе с нами!"
    )
    await callback.message.delete()
    try:
        photo = FSInputFile("img/team.jpg")
        await callback.message.answer_photo(photo, caption=text, parse_mode="Markdown", reply_markup=back_kb("menu_sections"))
    except:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_kb("menu_sections"))

@dp.callback_query(F.data == "sec_activities")
async def section_activities(callback: types.CallbackQuery):
    text = (
        "📢 **Деятельность первичного отделения**\n\n"
        "Мы создаем условия для самореализации, развиваем лидерские качества и волонтерство.\n\n"
        "**Наши основные направления:**\n"
        "🇷🇺 **Патриотизм:** Акция «Окна Победы», квесты.\n"
        "❤️ **Волонтерство:** Социальные акции, помощь нуждающимся, сбор гумпомощи.\n"
        "⚽ **Спорт и ЗОЖ:** Спортивные мероприятия и акции.\n"
        "🧠 **Образование:** Интеллектуальные игры, квизы, мастер-классы, встречи с профи.\n"
        "🎤 **Культура и медиа:** Творческие проекты, школьное радио «Девяточка»."
    )
    await callback.message.delete()
    try:
        photo = FSInputFile("img/activities.jpg")
        await callback.message.answer_photo(photo, caption=text, parse_mode="Markdown", reply_markup=back_kb("menu_sections"))
    except:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_kb("menu_sections"))

@dp.callback_query(F.data == "sec_contacts")
async def section_contacts(callback: types.CallbackQuery):
    text = (
        "📞 **Наши контакты**\n\n"
        "📲 **Группа Первички:** [vk.ru/pervyedevyatochki](https://vk.ru/pervyedevyatochki)\n"
        "🏫 **Школьная группа:** [vk.ru/sch9bryansk](https://vk.ru/sch9bryansk)\n\n"
        "👤 **Седакова Елена Геннадьевна:** @ElenaSedakovaSCH9\n"
        "👤 **Межуева Алина Олеговна:** @a_kzlva\n\n"
        "🔗 **Канал MAX:** [Перейти](https://max.ru/id3234036720_gos)"
    )
    await callback.message.delete()
    await callback.message.answer(text, parse_mode="Markdown", link_preview_options=types.LinkPreviewOptions(is_disabled=True), reply_markup=back_kb("menu_sections"))

# --- АНКЕТЫ: ВСТУПИТЬ И ИДЕЯ ---

# Вступить
@dp.callback_query(F.data == "join_movement")
async def start_join_form(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("📝 **Анкета вступления**\nВведите ваши ФИО:")
    await state.set_state(JoinState.waiting_for_fio)

@dp.message(JoinState.waiting_for_fio)
async def join_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer("Сколько вам лет?")
    await state.set_state(JoinState.waiting_for_age)

@dp.message(JoinState.waiting_for_age)
async def join_age(message: types.Message, state: FSMContext):
    await state.update_data(age=message.text)
    await message.answer("Из какого вы класса? (Например, 8Б)")
    await state.set_state(JoinState.waiting_for_class)

@dp.message(JoinState.waiting_for_class)
async def join_class(message: types.Message, state: FSMContext):
    await state.update_data(grade=message.text)
    await message.answer("Какое направление вам интересно? (Спорт, Медиа, Волонтерство...)")
    await state.set_state(JoinState.waiting_for_direction)

@dp.message(JoinState.waiting_for_direction)
async def join_direction(message: types.Message, state: FSMContext):
    await state.update_data(direction=message.text)
    await message.answer("Расскажите немного о себе и почему хотите к нам:")
    await state.set_state(JoinState.waiting_for_bio)

@dp.message(JoinState.waiting_for_bio)
async def join_finish(message: types.Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    admin_text = (
        f"✅ **Новая заявка на вступление!**\n"
        f"👤 От: @{message.from_user.username}\n"
        f"📝 ФИО: {data['fio']}\n"
        f"🎂 Возраст: {data['age']}\n"
        f"🏫 Класс: {data['grade']}\n"
        f"🎯 Направление: {data['direction']}\n"
        f"💬 О себе: {message.text}"
    )
    await bot.send_message(ADMIN_GROUP_ID, admin_text)
    await message.answer("✅ Спасибо! Твоя заявка отправлена кураторам. Мы скоро свяжемся с тобой!", reply_markup=back_kb("main_menu"))
    await state.clear()

# Идея
@dp.callback_query(F.data == "send_idea")
async def start_idea(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await callback.message.answer("💡 **Есть идея?**\nОпиши своё предложение или проект, и мы его обязательно рассмотрим:")
    await state.set_state(IdeaState.waiting_for_text)

@dp.message(IdeaState.waiting_for_text)
async def process_idea(message: types.Message, state: FSMContext, bot: Bot):
    admin_text = (
        f"💡 **Новая ИДЕЯ!**\n"
        f"👤 От: @{message.from_user.username}\n"
        f"💬 Суть: {message.text}"
    )
    await bot.send_message(ADMIN_GROUP_ID, admin_text)
    await message.answer("✅ Идея отправлена! Спасибо за инициативу.", reply_markup=back_kb("main_menu"))
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
    await message.answer("🛠 **Панель администратора:**", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# Просмотр мероприятий (для админа и юзера одинаково)
@dp.callback_query(F.data == "list_events")
async def list_events_handler(callback: types.CallbackQuery, pool):
    events = await get_events_db(pool)
    if not events:
        await callback.answer("Мероприятий пока нет.", show_alert=True)
        return
    
    response = "🗓 **АКТУАЛЬНЫЕ МЕРОПРИЯТИЯ:**\n\n"
    kb_list = []
    
    for idx, event in enumerate(events, 1):
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        icon = emojis[idx-1] if idx <= 10 else f"{idx}."
        response += f"{icon} {event['short_text']}\n➖➖➖➖➖➖\n"
        kb_list.append([InlineKeyboardButton(text=f"{icon} Подробнее", callback_data=f"view_event_{event['id']}")])
    
    kb_list.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    
    await callback.message.delete()
    await callback.message.answer(response, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("view_event_"))
async def view_event_detail(callback: types.CallbackQuery, pool):
    event_id = int(callback.data.split("_")[2])
    event = await get_event_by_id(pool, event_id)
    
    if event:
        text = f"📢 **ПОДРОБНОСТИ:**\n\n{event['long_text']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 К списку", callback_data="list_events")]])
        
        await callback.message.delete()
        if event['photo_id']:
            await callback.message.answer_photo(event['photo_id'], caption=text, reply_markup=kb, parse_mode="Markdown")
        else:
            await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.answer("Мероприятие удалено.", show_alert=True)

# Добавление мероприятия
@dp.callback_query(F.data == "add_event")
async def start_add_event(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Введите КРАТКОЕ описание (для списка).")
    await state.set_state(AdminEvent.waiting_for_short)
    await callback.answer()

@dp.message(AdminEvent.waiting_for_short)
async def process_short(message: types.Message, state: FSMContext):
    await state.update_data(short_text=message.text)
    await message.answer("📝 Введите ПОЛНОЕ описание.")
    await state.set_state(AdminEvent.waiting_for_long)

@dp.message(AdminEvent.waiting_for_long)
async def process_long(message: types.Message, state: FSMContext):
    await state.update_data(long_text=message.text)
    await message.answer("🖼 Пришлите фото или напишите 'нет'.")
    await state.set_state(AdminEvent.waiting_for_photo)

@dp.message(AdminEvent.waiting_for_photo)
async def process_photo(message: types.Message, state: FSMContext, pool):
    data = await state.get_data()
    photo_id = message.photo[-1].file_id if message.photo else None
    
    await add_event_db(pool, data['short_text'], data['long_text'], photo_id)
    await message.answer("✅ Мероприятие добавлено! Рассылка запущена...")
    await state.clear()

    # Рассылка о новом мероприятии
    users = await get_all_users(pool)
    for uid in users:
        try:
            msg = f"⚡ **НОВОЕ МЕРОПРИЯТИЕ!**\n\n{data['short_text']}\n\n👉 *Жми кнопку 'Актуальные мероприятия' в меню!*"
            await bot.send_message(uid, msg, parse_mode="Markdown")
        except: pass
    await message.answer("Рассылка завершена.")

# Удаление
@dp.callback_query(F.data == "del_event_menu")
async def del_menu(callback: types.CallbackQuery, pool):
    events = await get_events_db(pool)
    if not events:
        await callback.answer("Нечего удалять.", show_alert=True)
        return
    kb_list = [[InlineKeyboardButton(text=f"❌ {e['short_text'][:15]}...", callback_data=f"del_conf_{e['id']}")] for e in events]
    await callback.message.answer("Выберите, что удалить:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))

@dp.callback_query(F.data.startswith("del_conf_"))
async def del_confirm(callback: types.CallbackQuery, pool):
    eid = int(callback.data.split("_")[2])
    await delete_event_db(pool, eid)
    await callback.answer("Удалено!")
    await callback.message.delete()

# Рассылка (Broadcast)
@dp.callback_query(F.data == "broadcast_msg")
async def start_broadcast(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("✍️ Введите текст сообщения для ВСЕХ пользователей:")
    await state.set_state(BroadcastState.waiting_for_text)
    await callback.answer()

@dp.message(BroadcastState.waiting_for_text)
async def broadcast_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.answer("🖼 Прикрепите фото или напишите 'нет'.")
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
                await bot.send_photo(uid, photo_id, caption=data['text'])
            else:
                await bot.send_message(uid, data['text'])
            count += 1
        except: pass
    
    await message.answer(f"✅ Рассылка завершена. Получили: {count} чел.")
    await state.clear()

# --- НЕЙРОСЕТЬ ---

@dp.callback_query(F.data == "ask_ai")
async def ask_ai_mode(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🤖 **Я на связи!**\nНапиши мне любой вопрос про школу или Движение, и я постараюсь ответить.")

@dp.message()
async def chat_with_ai(message: types.Message):
    if message.chat.type != 'private': return # Не отвечать в группах
    waiting_msg = await message.answer("🤖 Думаю...")
    try:
        with GigaChat(credentials=GIGACHAT_KEY, verify_ssl_certs=False) as giga:
            payload = {"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message.text}]}
            response = giga.chat(payload)
            await waiting_msg.edit_text(response.choices[0].message.content)
    except Exception as e:
        await waiting_msg.edit_text(f"Ошибка нейросети: {e}")

# --- ЗАПУСК ---
async def main():
    pool = await asyncpg.create_pool(dsn=DATABASE_URL)
    await create_tables(pool)
    dp["pool"] = pool
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
