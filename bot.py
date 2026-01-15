import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from supabase import create_client, Client

# --- 1. НАСТРОЙКА ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Состояния (шаги опроса)
class PulseForm(StatesGroup):
    choosing_index = State()   # Шаг 1: Выбор товара
    choosing_location = State()# Шаг 2: Где цена? (Корзинка/Базар)
    entering_price = State()   # Шаг 3: Ввод цены
    uploading_photo = State()  # Шаг 4: Фото (Опционально)

# --- 2. ЛОГИКА ---

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    # Сохраняем волонтера в базу (если новый)
    data = {"telegram_id": user.id, "full_name": user.full_name}
    supabase.table("users").upsert(data).execute()
    
    await message.answer(
        f"Салют, {user.first_name}! 🚀\n"
        "Я бот проекта ПУЛЬС. Мы собираем реальные цены.\n\n"
        "Нажми /submit, чтобы отправить отчет."
    )

# Начало сбора данных
@dp.message(Command("submit"))
async def cmd_submit(message: types.Message, state: FSMContext):
    # Кнопки выбора товара
    buttons = [
        [types.KeyboardButton(text="🍓 Клубника / Яйцо")],
        [types.KeyboardButton(text="🍛 Плов (Лень)"), types.KeyboardButton(text="🥛 Молоко (Эко)")],
        [types.KeyboardButton(text="🎓 Репетитор")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    
    await message.answer("Что будем оценивать?", reply_markup=keyboard)
    await state.set_state(PulseForm.choosing_index)

# Шаг 1: Выбор товара -> Спрашиваем Локацию
@dp.message(PulseForm.choosing_index)
async def process_index(message: types.Message, state: FSMContext):
    text = message.text
    # Превращаем текст кнопки в код для базы
    slug_map = {
        "🍓 Клубника / Яйцо": "strawberry_egg",
        "🍛 Плов (Лень)": "plov_laziness",
        "🥛 Молоко (Эко)": "milk_eco",
        "🎓 Репетитор": "tutor"
    }
    
    if text not in slug_map:
        await message.answer("Пожалуйста, выбери кнопку ниже.")
        return

    await state.update_data(index_slug=slug_map[text])
    
    # Кнопки локации
    loc_buttons = [
        [types.KeyboardButton(text="🛒 Супермаркет (Korzinka)")],
        [types.KeyboardButton(text="🎪 Базар / Частник")],
        [types.KeyboardButton(text="🚚 Доставка"), types.KeyboardButton(text="🏫 Учебный центр")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=loc_buttons, resize_keyboard=True)
    
    await message.answer("Где зафиксирована цена?", reply_markup=keyboard)
    await state.set_state(PulseForm.choosing_location)

# Шаг 2: Локация -> Спрашиваем Цену
@dp.message(PulseForm.choosing_location)
async def process_location(message: types.Message, state: FSMContext):
    await state.update_data(location_type=message.text)
    
    await message.answer("Введите цену в сумах (просто число, например: 15000)", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(PulseForm.entering_price)

# Шаг 3: Цена -> Спрашиваем Фото (Опционально!)
@dp.message(PulseForm.entering_price)
async def process_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введите только цифры.")
        return
        
    await state.update_data(price=int(message.text))
    
    # Кнопка "Пропустить"
    skip_kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="Пропустить фото ➡️")]], 
        resize_keyboard=True
    )
    
    await message.answer(
        "📸 Есть фото ценника?\n"
        "Это поможет верификации, но **не обязательно**.", 
        reply_markup=skip_kb
    )
    await state.set_state(PulseForm.uploading_photo)

# Шаг 4: Сохранение (С фото или БЕЗ)
@dp.message(PulseForm.uploading_photo)
async def process_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    photo_id = None
    
    # Проверяем: прислали фото или текст "Пропустить"
    if message.photo:
        photo_id = message.photo[-1].file_id # ID фото в телеграме (пока не грузим в Supabase Storage для простоты)
        await message.answer("Фото принято! 📸")
    elif message.text == "Пропустить фото ➡️":
        await message.answer("Без фото? Окей, доверие — золото! 🤝")
    else:
        await message.answer("Пришли фото или нажми кнопку 'Пропустить'.")
        return

    # ОТПРАВКА В SUPABASE
    try:
        submission = {
            "user_id": user_id,
            "index_slug": data['index_slug'],
            "location_type": data['location_type'],
            "price": data['price'],
            "photo_url": photo_id # Сохраняем ID файла телеграма (или null)
        }
        
        supabase.table("submissions").insert(submission).execute()
        
        await message.answer(
            f"✅ **Данные приняты!**\n"
            f"Товар: {data['index_slug']}\n"
            f"Цена: {data['price']} сум\n\n"
            "Спасибо за вклад в экономику! Жми /submit для следующего.",
            reply_markup=types.ReplyKeyboardRemove()
        )
    except Exception as e:
        await message.answer(f"Ошибка сохранения: {e}")
    
    await state.clear()

# Запуск
async def main():
    print("Бот ПУЛЬС запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
