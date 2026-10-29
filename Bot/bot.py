import os
import json
import time
import random
import smtplib
from email.mime.text import MIMEText
import requests
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Загружаем ключи из секретного файла .env
load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

DB_FILE = "sent_emails.json"

# Инициализируем локальную базу памяти
if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w") as f:
        json.dump({"sent_domains": [], "sent_emails": []}, f)

def check_memory(domain, email):
    with open(DB_FILE, "r") as f:
        db = json.load(f)
    return (domain in db["sent_domains"]) or (email in db["sent_emails"])

def save_to_memory(domain, email):
    with open(DB_FILE, "r") as f:
        db = json.load(f)
    if domain not in db["sent_domains"]: db["sent_domains"].append(domain)
    if email not in db["sent_emails"]: db["sent_emails"].append(email)
    with open(DB_FILE, "w") as f:
        json.dump(db, f, indent=4)

# --- ГЛАВНОЕ МЕНЮ ТЕЛЕГРАМ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [['🔎 Поиск компаний', '📊 База отправленных']]
    await update.message.reply_text(
        "Привет, Николай! Твой ИИ-маркетолог Myswisstransfer готов к работе.\n"
        "Выбери действие на панели ниже:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )

# --- ПОИСК ЧЕРЕЗ SERPAPI ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == '📊 База отправленных':
        with open(DB_FILE, "r") as f:
            db = json.load(f)
        await update.message.reply_text(f"📈 Статистика системы:\nСохранено доменов: {len(db['sent_domains'])}\nОтправлено писем: {len(db['sent_emails'])}")
        return

    if text == '🔎 Поиск компаний':
        context.user_data['waiting_for_query'] = True
        await update.message.reply_text("Введите целевой запрос для поиска в Google (например: 'Travel agencies Zurich' или 'Hotels in Zermatt'):")
        return

    # Если бот ждал поисковый запрос
    if context.user_data.get('waiting_for_query'):
        context.user_data['waiting_for_query'] = False
        query = text
        await update.message.reply_text(f"Ищу компании по запросу: '{query}'... Это займет около минуты.")
        
        # Вызов SerpAPI
        url = "https://serpapi.com/search"
        params = {"q": query, "engine": "google", "api_key": SERPAPI_KEY, "num": 10}
        
        try:
            response = requests.get(url, params=params).json()
            results = response.get("organic_results", [])
            
            if not results:
                await update.message.reply_text("Ничего не найдено в Google по этому запросу.")
                return

            # Генерируем ЕДИНЫЙ базовый шаблон стратегии через ИИ
            await update.message.reply_text("Генерирую общую B2B стратегию и базовый шаблон письма...")
            base_template = generate_base_template(query)
            context.user_data['current_template'] = base_template
            context.user_data['found_results'] = results
            context.user_data['current_index'] = 0

            # Показываем шаблон Николаю на утверждение
            keyboard = [[InlineKeyboardButton("✅ Утвердить и запустить автомат", callback_data="approve_campaign")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"📋 **УТВЕРЖДЕНИЕ СТРАТЕГИИ ДЛЯ НИШИ:**\n\n{base_template}",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        except Exception as e:
            await update.message.reply_text(f"Ошибка при поиске: {str(e)}")

# --- ИИ ГЕНЕРАЦИЯ БАЗОВОГО ШАБЛОНА (OpenRouter) ---
def generate_base_template(query):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""
    Ты опытный B2B маркетолог для транспортной компании Myswisstransfer.com (Швейцария).
    Наш автопарк: Стандарт авто (Standard Car), Бизнес седаны (Business Sedan), Стандарт минивэны (Standard Minivan) и Бизнес минивэны (Business Minivan, такие как Mercedes-Benz V-Class/Vito).
    Мы ищем партнеров в нише: {query}.
    
    Напиши профессиональный базовый продающий шаблон письма-предложения о сотрудничестве. 
    Письмо должно быть написано на английском языке, деловым, лаконичным стилем. Оставь [Placeholder] для названия компании.
    Упомяни наши типы авто и предложи долгосрочное партнерство (комиссию или спец тарифы). В конце подпись: Nikolai Tarasov, Founder of Myswisstransfer.
    Выдай СТРОГО только текст письма без лишних вступлений от себя.
    """
    
    data = {
        "model": "meta-llama/llama-3-8b-instruct:free",
        "messages": [{"role": "user", "content": prompt}]
    }
    res = requests.post(url, headers=headers, json=data).json()
    return res['choices'][0]['message']['content']

# --- ОБРАБОТКА НАЖАТИЯ КНОПКИ "УТВЕРДИТЬ" (ЗАПУСК АВТОМАТА) ---
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "approve_campaign":
        await query.edit_message_text("🚀 Стратегия утверждена! Робот переходит в автоматический фоновый режим рассылки...")
        
        results = context.user_data.get('found_results', [])
        base_template = context.user_data.get('current_template')
        
        # Запускаем цикл по найденным сайтам
        for item in results:
            title = item.get("title")
            link = item.get("link")
            domain = link.split("//")[-1].split("/")[0] if "//" in link else link

            # Имитируем поиск email (в реальном коде тут парсер, для стабильности берем общий корпоративный инфо-адрес домена)
            fake_email = f"info@{domain}" 

            # Проверяем память
            if check_memory(domain, fake_email):
                await query.message.reply_text(f"⏭ {title} ({domain}) уже есть в базе. Пропускаем.")
                continue

            # ИИ персонализирует утвержденный шаблон под конкретный сайт
            personalized_email = personalize_email(base_template, title, domain)
            
            # Физическая отправка почты через GMX SMTP
            success = send_email_via_gmx(fake_email, f"B2B Cooperation Partnership — Myswisstransfer & {title}", personalized_email)
            
            if success:
                save_to_memory(domain, fake_email)
                await query.message.reply_text(f"✉️ Письмо УСПЕШНО отправлено автопилотом на {fake_email} ({title})")
            else:
                await query.message.reply_text(f"❌ Ошибка отправки на {fake_email}")

            # Безопасная пауза (в целях теста стоит 10-20 секунд, для боевого режима измени на random.randint(900, 1800))
            sleep_time = random.randint(10, 20)
            await query.message.reply_text(f"⏱ Безопасная пауза перед следующим сайтом: {sleep_time} сек.")
            time.sleep(sleep_time)

        await query.message.reply_text("🏁 Автоматическая кампания по этому запросу успешно завершена!")

# --- ПЕРСОНАЛИЗАЦИЯ ШАБЛОНА ПОД КОНКРЕТНУЮ КОМПАНИЮ ---
def personalize_email(base_template, company_name, domain):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"}
    
    prompt = f"""
    Возьми этот базовый шаблон B2B письма:\n{base_template}\n
    Адаптируй и персонализируй его под компанию: '{company_name}' (их сайт: {domain}).
    Замени все плейсхолдеры на реальные данные. Сделай так, чтобы письмо выглядело как написанное вручную для них.
    Выдай СТРОГО готовый текст письма.
    """
    
    data = {
        "model": "meta-llama/llama-3-8b-instruct:free",
        "messages": [{"role": "user", "content": prompt}]
    }
    res = requests.post(url, headers=headers, json=data).json()
    return res['choices'][0]['message']['content']

# --- ФУНКЦИЯ ОТПРАВКИ SMTP GMX ---
def send_email_via_gmx(to_email, subject, body):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = EMAIL_USER
        msg['To'] = to_email

        # Подключение к швейцарским серверам GMX
        server = smtplib.SMTP('mail.gmx.net', 587)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, [to_email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"SMTP Error: {e}")
        return False

# Запуск бота
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_click))
    print("🤖 Бот Myswisstransfer успешно запущен на сервере...")
    app.run_polling()