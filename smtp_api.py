import httpx
from config import SMTP_API_KEY

class SMTPDev:
    BASE_URL = "https://api.smtp.dev"
    HEADERS = {"X-API-KEY": SMTP_API_KEY, "Accept": "application/json"}
    
    async def get_domains(self):
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self.BASE_URL}/domains?isActive=true", headers=self.HEADERS)
            data = r.json()
            
            # Если API вернуло словарь с ключом 'member' (как в доке)
            if isinstance(data, dict):
                return data.get('member', [])
            
            # Если API вернуло сразу список (как в твоем случае)
            elif isinstance(data, list):
                return data
                
            return []

    async def create_account(self, address, password):
        async with httpx.AsyncClient() as client:
            data = {"address": address, "password": password}
            r = await client.post(f"{self.BASE_URL}/accounts", json=data, headers=self.HEADERS)
            return r.json() if r.status_code == 201 else None

    async def get_messages(self, account_id):
        async with httpx.AsyncClient() as client:
            # 1. Получаем список ящиков (mailboxes)
            box_r = await client.get(f"{self.BASE_URL}/accounts/{account_id}/mailboxes", headers=self.HEADERS)
            mailboxes = box_r.json()
            
            # Если пришел словарь с 'member', берем его, иначе считаем, что это список
            if isinstance(mailboxes, dict):
                mailboxes = mailboxes.get('member', [])
                
            # Ищем INBOX
            try:
                inbox = next(m for m in mailboxes if m['path'] == 'INBOX')
                inbox_id = inbox['id']
            except StopIteration:
                return [], None # Если инбокс почему-то не найден

            # 2. Получаем сообщения
            msg_r = await client.get(f"{self.BASE_URL}/accounts/{account_id}/mailboxes/{inbox_id}/messages", headers=self.HEADERS)
            messages = msg_r.json()
            
            if isinstance(messages, dict):
                messages = messages.get('member', [])
                
            return messages, inbox_id

    async def get_message_detail(self, account_id, mailbox_id, message_id):
        async with httpx.AsyncClient() as client:
            url = f"{self.BASE_URL}/accounts/{account_id}/mailboxes/{mailbox_id}/messages/{message_id}"
            r = await client.get(url, headers=self.HEADERS)
            return r.json() if r.status_code == 200 else None