import asyncio
import aiohttp
import json
import sqlite3
from urllib.parse import quote
from aiogram.utils.markdown import hbold
from config import SMTP_API_KEY, DB_PATH

MERCURE_URL = "https://mercure.smtp.dev/.well-known/mercure"

async def start_sse_listener(bot):
    """Фоновая задача для прослушивания новых писем через Mercure SSE"""
    headers = {"X-API-KEY": SMTP_API_KEY}
    
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                # 1. Получаем свежий JWT-токен для Mercure
                async with session.get("https://api.smtp.dev/mercure/token", headers=headers) as resp:
                    if resp.status != 200:
                        print(f"[SSE] Ошибка токена: {resp.status}. Реконнект через 10с...")
                        await asyncio.sleep(10)
                        continue
                    token_data = await resp.json()
                    mercure_token = token_data.get('token')

                # 2. Подписываемся на топик аккаунтов
                # Используем более широкий фильтр для стабильности
                topic = quote("/accounts/{id}", safe="")
                url = f"{MERCURE_URL}?topic={topic}"
                
                sse_headers = {
                    "Authorization": f"Bearer {mercure_token}",
                    "Accept": "text/event-stream"
                }
                
                print(f"[SSE] Подключение установлено: {url}")
                
                async with session.get(url, headers=sse_headers, timeout=None) as response:
                    async for line in response.content:
                        line = line.decode('utf-8').strip()
                        
                        # Проверяем, что строка содержит данные
                        if line.startswith("data:"):
                            # Обрезаем 'data:' и парсим JSON
                            try:
                                json_str = line[5:].strip()
                                data = json.loads(json_str)
                                
                                # Нас интересует только тип 'Message' (новое письмо)
                                if isinstance(data, dict) and data.get('@type') == 'Message':
                                    await handle_new_email(bot, data)
                                    
                            except json.JSONDecodeError:
                                continue
                                
            except Exception as e:
                print(f"[SSE] Критическая ошибка: {e}. Переподключение...")
                await asyncio.sleep(5)

async def handle_new_email(bot, msg_data):
    """Логика обработки входящего письма и отправки уведомления"""
    try:
        # Извлекаем адрес получателя, чтобы найти владельца в нашей БД
        recipient = msg_data['to'][0]['address']
        
        # Ищем tg_id пользователя
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            user = conn.execute(
                "SELECT tg_id FROM mail_accounts WHERE address = ?", 
                (recipient,)
            ).fetchone()
        
        if user:
            tg_id = user['tg_id']
            subject = msg_data.get('subject') or "(Без темы)"
            sender = msg_data['from']['address']
            # intro — это короткое превью текста письма от smtp.dev
            preview = msg_data.get('intro') or "Текст письма пуст"
            
            text = (
                f"📩 {hbold('Новое письмо!')}\n\n"
                f"👤 {hbold('От:')} {sender}\n"
                f"📌 {hbold('Тема:')} {subject}\n"
                f"📝 {hbold('Превью:')}\n{preview}"
            )
            
            # Отправляем в Telegram
            await bot.send_message(tg_id, text, parse_mode="HTML")
            print(f"[SUCCESS] Уведомление отправлено для {recipient}")
            
    except Exception as e:
        print(f"[ERROR] Ошибка в handle_new_email: {e}")