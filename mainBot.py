"""Telegram-бот Ағаш базар (aiogram 3)."""
import asyncio
import logging
import os
import sys
from datetime import date

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

import config
from model import services
from model.services import esc, money

log = logging.getLogger("bot")
dp = Dispatcher(storage=MemoryStorage())

BTN_PROFIT = "📊 Бүгінгі пайда"
BTN_ORDERS = "🧾 Бүгінгі заказдар"
BTN_EXPENSES = "💸 Шығындар"
BTN_STOCK = "📦 Склад"
BTN_DEBTS = "💳 Қарыздар"
BTN_NOTIFY = "🔔 Хабарламалар"
BTN_HELP = "❓ Көмек"

MAIN_KB = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text=BTN_PROFIT)],
    [KeyboardButton(text=BTN_ORDERS), KeyboardButton(text=BTN_EXPENSES)],
    [KeyboardButton(text=BTN_STOCK), KeyboardButton(text=BTN_DEBTS)],
    [KeyboardButton(text=BTN_NOTIFY), KeyboardButton(text=BTN_HELP)],
])


class Registration(StatesGroup):
    name = State()


async def db(func, *args):
    """Запросы к базе синхронные — выполняем их в отдельном потоке, чтобы бот не подвисал."""
    return await asyncio.to_thread(func, *args)


async def send_long(message: Message, title: str, blocks: list, empty="Жоқ"):
    """Telegram пропускает максимум 4096 символов — режем на части."""
    if not blocks:
        await message.answer(f"{title}\n\n{empty}")
        return
    chunk = title
    for block in blocks:
        if len(chunk) + len(block) + 2 > 3900:
            await message.answer(chunk)
            chunk = ""
        chunk += ("\n\n" if chunk else "") + block
    if chunk:
        await message.answer(chunk)


async def registered(message: Message) -> bool:
    if await db(services.get_tg_user, message.from_user.id):
        return True
    await message.answer("Сіз жүйеге тіркелмегенсіз. /start басыңыз.")
    return False


# ---------------------------------------------------------------- регистрация

@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    user = await db(services.get_tg_user, message.from_user.id)
    if user:
        await message.answer(f"Сәлеметсіз бе, {esc(user.name)}! Ағаш базарға қош келдіңіз 🌴", reply_markup=MAIN_KB)
        return
    if config.BOT_ALLOWED_IDS and message.from_user.id not in config.BOT_ALLOWED_IDS:
        await message.answer(f"Бұл ботқа рұқсат жоқ.\nСіздің ID: <code>{message.from_user.id}</code> — "
                             f"оны әкімшіге жіберіңіз.")
        return
    await state.set_state(Registration.name)
    await message.answer("Сәлеметсіз бе! Ағаш базарға қош келдіңіз 🌴\n\nАты-жөніңізді жазыңыз:",
                         reply_markup=ReplyKeyboardRemove())


@dp.message(Registration.name, F.text)
async def registration_name(message: Message, state: FSMContext):
    name = message.text.strip()[:100]
    if not name or name.startswith("/"):
        await message.answer("Аты-жөніңізді мәтінмен жазыңыз:")
        return
    await db(services.register_tg_user, name, message.chat.id, message.from_user.id)
    await state.clear()
    await message.answer(f"Рақмет, {esc(name)}! Сіз тіркелдіңіз ✅", reply_markup=MAIN_KB)


# ---------------------------------------------------------------- отчёты

@dp.message(Command("profit", ignore_case=True))
@dp.message(F.text.in_({BTN_PROFIT, "Бүгінгі пайда"}))
async def profit(message: Message):
    if not await registered(message):
        return
    report = await db(services.day_report, date.today())
    await message.answer(services.format_report(report, html=True), reply_markup=MAIN_KB)


@dp.message(Command("orders", "getOrdersToday", ignore_case=True))
@dp.message(F.text == BTN_ORDERS)
async def orders_today(message: Message):
    if not await registered(message):
        return
    orders = await db(services.list_orders, "", date.today())
    blocks = [f"🕒 {esc(o.createAt[11:16])} · <b>{esc(o.nameProduct)}</b> × {o.count}\n"
              f"{money(o.summa)} ₸, {esc(services.payment_label(o))} — {esc(o.fioSeller)}" for o in reversed(orders)]
    total = sum(o.summa for o in orders)
    await send_long(message, f"<b>🧾 Бүгінгі заказдар: {len(orders)} шт, {money(total)} ₸</b>", blocks)


@dp.message(Command("expenses", "getExpenses", ignore_case=True))
@dp.message(F.text == BTN_EXPENSES)
async def expenses_today(message: Message):
    if not await registered(message):
        return
    expenses = await db(services.list_expenses, "", date.today())
    blocks = [f"<b>{esc(e.name)}</b>: {money(e.summa)} ₸" + (f"\n{esc(e.description)}" if e.description else "")
              for e in expenses]
    total = sum(e.summa for e in expenses)
    await send_long(message, f"<b>💸 Бүгінгі шығындар: {money(total)} ₸</b>", blocks)


@dp.message(Command("products", "getProducts", ignore_case=True))
@dp.message(F.text == BTN_STOCK)
async def stock(message: Message):
    if not await registered(message):
        return
    products = await db(services.list_products)
    lines = [f"{'⚪️' if (p.quantity or 0) <= 0 else '🟢'} <b>{esc(p.name)}</b> — {p.quantity or 0} шт, "
             f"{money(p.price)} ₸" for p in products]
    # по 20 товаров в блоке, чтобы сообщение было компактным
    blocks = ["\n".join(lines[i:i + 20]) for i in range(0, len(lines), 20)]
    await send_long(message, f"<b>📦 Склад: {len(products)} товар</b>", blocks)


@dp.message(Command("debts", "getDebts", ignore_case=True))
@dp.message(F.text == BTN_DEBTS)
async def debts(message: Message):
    if not await registered(message):
        return
    items = await db(services.list_debts)
    blocks = [f"<b>{esc(d.nameCustomer)}</b> {esc(d.phoneNumberCustomer)}\n"
              f"{esc(d.nameProduct)} × {d.count} — <b>{money(d.summa)} ₸</b>\n"
              f"{esc((d.createAt or '')[:10])}, сатушы: {esc(d.fioSeller)}" for d in items]
    total = sum(d.summa for d in items)
    await send_long(message, f"<b>💳 Қарыздар: {money(total)} ₸</b>", blocks)


# ---------------------------------------------------------------- уведомления и помощь

@dp.message(F.text == BTN_NOTIFY)
async def toggle_notify(message: Message):
    if not await registered(message):
        return
    if await db(services.is_subscribed, message.from_user.id):
        await db(services.unsubscribe, message.from_user.id)
        await message.answer("🔕 Хабарламалар өшірілді")
    else:
        await subscribe(message)


@dp.message(Command("subscribe", "subscribeEvent", ignore_case=True))
async def subscribe(message: Message):
    if not await registered(message):
        return
    name = message.from_user.username or message.from_user.full_name
    if await db(services.subscribe, name, message.chat.id, message.from_user.id):
        await message.answer("🔔 Хабарламалар қосылды: кассадағы әрекеттер осында келеді")
    else:
        await message.answer("Сіз хабарламаларға жазылғансыз")


@dp.message(Command("unsubscribe", "unSubscribeEvent", ignore_case=True))
async def unsubscribe(message: Message):
    if not await registered(message):
        return
    ok = await db(services.unsubscribe, message.from_user.id)
    await message.answer("🔕 Хабарламалар өшірілді" if ok else "Сіз жазылмағансыз")


@dp.message(Command("help", ignore_case=True))
@dp.message(F.text == BTN_HELP)
async def help_cmd(message: Message):
    await message.answer(esc(config.HELP_TEXT))


@dp.errors()
async def on_error(event: ErrorEvent):
    log.exception("Ошибка в обработчике", exc_info=event.exception)
    message = event.update.message
    if message:
        await message.answer("⚠️ Қате орын алды. Кейінірек қайталап көріңіз.")
    return True


# Запуск из кассы: `mainBot.py --with-kassa`. Касса держит открытым канал stdin бота;
# когда касса закрывается (или падает), канал закрывается — и бот останавливается.
WITH_KASSA = "--with-kassa" in sys.argv


async def stop_when_kassa_closes():
    await asyncio.to_thread(sys.stdin.buffer.read)  # ждёт, пока касса не закроет канал
    log.info("Касса закрыта — останавливаю бота")
    try:
        await dp.stop_polling()
    except RuntimeError:
        os._exit(0)  # опрос ещё не успел начаться


async def main():
    config.LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(config.LOG_DIR / "bot.log", encoding="utf-8")]
        + ([logging.StreamHandler()] if sys.stderr else []),
    )
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан в файле .env")
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        # Telegram разрешает в меню только строчные латинские буквы, цифры и "_"
        await bot.set_my_commands([
            BotCommand(command="start", description="Бастау"),
            BotCommand(command="profit", description="Бүгінгі пайда"),
            BotCommand(command="orders", description="Бүгінгі заказдар"),
            BotCommand(command="expenses", description="Бүгінгі шығындар"),
            BotCommand(command="products", description="Склад"),
            BotCommand(command="debts", description="Қарыздар"),
            BotCommand(command="subscribe", description="Хабарламаларды қосу"),
            BotCommand(command="unsubscribe", description="Хабарламаларды өшіру"),
            BotCommand(command="help", description="Көмек"),
        ])
    except Exception:
        log.exception("Не удалось установить меню команд — бот продолжит работу")
    if WITH_KASSA:
        asyncio.create_task(stop_when_kassa_closes())
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Bot is running!")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
