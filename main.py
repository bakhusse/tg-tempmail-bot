import asyncio
import secrets
import string
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.markdown import hbold, hcode
from aiogram.types import WebAppInfo
from datetime import datetime
from aiogram.exceptions import TelegramBadRequest

from config import BOT_TOKEN, WEBMAIL_URL, SMTP_API_KEY
from smtp_api import SMTPDev
import database as db
from states import MailStates
from sse_listener import start_sse_listener

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
api = SMTPDev()

msg_cache = {}

def gen_pass(length=12):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

@dp.message(Command("start"))
@dp.callback_query(F.data == "start_over")
async def start(event: types.Message | types.CallbackQuery):
    user_id = event.from_user.id
    accounts = db.get_user_accounts(user_id)
    kb = InlineKeyboardBuilder()
    
    if accounts:
        kb.row(types.InlineKeyboardButton(text="📬 Мои ящики", callback_data="my_mails"))
    
    kb.row(types.InlineKeyboardButton(text="➕ Создать почту", callback_data="create_step_1"))
    
    text = "Привет! Я бот временной почты."
    if isinstance(event, types.Message):
        await event.answer(text, reply_markup=kb.as_markup())
    else:
        await event.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "create_step_1")
async def choose_domain(callback: types.CallbackQuery):
    domains = await api.get_domains()
    kb = InlineKeyboardBuilder()
    for d in domains:
        kb.row(types.InlineKeyboardButton(text=d['domain'], callback_data=f"dom:{d['domain']}"))
    
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start_over"))
    await callback.message.edit_text("Выбери домен:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("dom:"))
async def ask_name(callback: types.CallbackQuery, state: FSMContext):
    domain = callback.data.split(":")[1]
    await state.update_data(chosen_domain=domain)
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🎲 Рандомное имя", callback_data="skip_name"))
    kb.row(types.InlineKeyboardButton(text="⬅️ Отмена", callback_data="create_step_1"))
    
    await state.set_state(MailStates.waiting_for_name)
    await callback.message.edit_text(f"Выбран домен: {domain}\nНапиши желаемое имя (логин) или нажми кнопку:", reply_markup=kb.as_markup())

@dp.message(MailStates.waiting_for_name)
@dp.callback_query(F.data == "skip_name")
async def finalize_creation(event: types.Message | types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    domain = data.get('chosen_domain')
    if not domain:
        await state.clear()
        return

    if isinstance(event, types.Message):
        name = event.text.strip().lower()
        try:
            await event.delete() 
        except:
            pass
    else:
        name = secrets.token_hex(4)
        
    address = f"{name}@{domain}"
    password = gen_pass()
    
    acc = await api.create_account(address, password)
    if acc:
        db.add_account(event.from_user.id, acc['id'], address, password)
        login_url = f"{WEBMAIL_URL}?_task=login&_action=auth&_user={address}&_pass={password}"
        
        kb = InlineKeyboardBuilder()
        kb.row(types.InlineKeyboardButton(text="🚀 Войти в Webmail", url=login_url))
        kb.row(types.InlineKeyboardButton(text="⬅️ В меню", callback_data="start_over"))
        
        msg_text = f"✅ Почта создана!\n\n📍 Адрес: `{address}`\n🔑 Пароль: `{password}`"
        
        if isinstance(event, types.Message):
            await event.answer(msg_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
        else:
            await event.message.edit_text(msg_text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    
    await state.clear()

@dp.callback_query(F.data == "my_mails")
async def list_my_accounts(callback: types.CallbackQuery):
    accounts = db.get_user_accounts(callback.from_user.id)
    kb = InlineKeyboardBuilder()
    
    for acc in accounts:
        kb.row(types.InlineKeyboardButton(
            text=f"📧 {acc['address']}", 
            callback_data=f"view_acc:{acc['account_id']}"
        ))
    
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="start_over"))
    await callback.message.edit_text("Выберите ящик для просмотра писем:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("view_acc:"))
async def list_messages(callback: types.CallbackQuery):
    account_id = callback.data.split(":")[1]
    
    acc_data = db.get_account_by_id(account_id)
    if not acc_data:
        await callback.answer("Ошибка: аккаунт не найден в базе.")
        return

    messages, mailbox_id = await api.get_messages(account_id)
    kb = InlineKeyboardBuilder()

    login_url = f"{WEBMAIL_URL}?_task=login&_action=auth&_user={acc_data['address']}&_pass={acc_data['password']}"
    
    kb.row(types.InlineKeyboardButton(text="🚀 Войти в Webmail", url=login_url))

    if not messages:
        kb.row(types.InlineKeyboardButton(text="🔄 Обновить", callback_data=f"view_acc:{account_id}"))
        kb.row(types.InlineKeyboardButton(text="🗑 Удалить ящик", callback_data=f"del_acc:{account_id}"))
        kb.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="my_mails"))
        
        text = f"Ящик: {hcode(acc_data['address'])}\n\nПисем пока нет 📭"
        try:
            await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
        except TelegramBadRequest:
            await callback.answer("Обновлено: писем по-прежнему нет")
        return

    for msg in messages:
        subject = msg.get('subject') or "(Без темы)"
        btn_text = (subject[:30] + '..') if len(subject) > 30 else subject
        
        short_id = secrets.token_hex(4) 
        msg_cache[short_id] = {
            "acc_id": account_id,
            "mbox_id": mailbox_id,
            "msg_id": msg['id']
        }

        kb.row(types.InlineKeyboardButton(
            text=f"✉️ {btn_text}", 
            callback_data=f"read:{short_id}"
        ))
    
    kb.row(types.InlineKeyboardButton(text="🔄 Обновить", callback_data=f"view_acc:{account_id}"))
    kb.row(types.InlineKeyboardButton(text="🗑 Удалить ящик", callback_data=f"del_acc:{account_id}"))
    kb.row(types.InlineKeyboardButton(text="⬅️ К списку ящиков", callback_data="my_mails"))

    now = datetime.now().strftime("%H:%M:%S")
    status_text = f"Ящик: {hcode(acc_data['address'])}\nПоследние письма (обновлено в {now}):"
    
    try:
        await callback.message.edit_text(
            status_text, 
            reply_markup=kb.as_markup(),
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" in e.message:
            await callback.answer("Новых писем нет")
        else:
            raise e

@dp.callback_query(F.data.startswith("read:"))
async def read_message(callback: types.CallbackQuery):
    short_id = callback.data.split(":")[1]
    data = msg_cache.get(short_id)
    
    if not data:
        await callback.answer("Данные устарели, вернитесь к списку писем.")
        return

    acc_id, mbox_id, msg_id = data['acc_id'], data['mbox_id'], data['msg_id']
    msg = await api.get_message_detail(acc_id, mbox_id, msg_id)
    
    if not msg:
        await callback.answer("Ошибка при загрузке письма")
        return

    text_content = msg.get('text') or "Содержимое пусто или только в HTML формате."
    if len(text_content) > 3000:
        text_content = text_content[:3000] + "\n... (текст обрезан)"

    response = (
        f"👤 {hbold('От:')} {msg['from']['address']}\n"
        f"🎯 {hbold('Кому:')} {msg['to'][0]['address']}\n"
        f"📌 {hbold('Тема:')} {msg.get('subject', '---')}\n"
        f"📅 {hbold('Дата:')} {msg.get('date', '---')}\n"
        f"{'─' * 20}\n\n"
        f"{text_content}"
    )

    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🗑 Удалить письмо", callback_data=f"del_msg:{short_id}"))
    kb.row(types.InlineKeyboardButton(text="⬅️ Назад к списку", callback_data=f"view_acc:{acc_id}"))
    
    await callback.message.edit_text(response, reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_acc:"))
async def delete_account(callback: types.CallbackQuery):
    acc_id = callback.data.split(":")[1]
    
    async with httpx.AsyncClient() as client:
        headers = {"X-API-KEY": SMTP_API_KEY}
        r = await client.delete(f"https://api.smtp.dev/accounts/{acc_id}", headers=headers)
    
    if r.status_code == 204:
        try:
            db.delete_account_from_db(acc_id) 
            await callback.message.edit_text("✅ Аккаунт полностью удален.")
        except Exception as e:
            await callback.message.edit_text(f"Аккаунт удален в API, но ошибка в БД: {e}")
    else:
        await callback.answer(f"Ошибка сервера: {r.status_code}")

async def main():
    db.init_db()
    asyncio.create_task(start_sse_listener(bot))
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped")
