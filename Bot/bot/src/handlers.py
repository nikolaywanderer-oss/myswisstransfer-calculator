import asyncio
import csv
import io
import logging
import random
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes, ConversationHandler
from serp import search_companies
from ai import generate_email, parse_subject_body
from mailer import send_email
from db import is_sent, mark_sent, get_all
from email_scraper import find_email
from config import DELAY_MIN, DELAY_MAX

logger = logging.getLogger(__name__)

WAITING_FOR_NICHE = 1

# ─── Helpers ───────────────────────────────────────────────────────────────────

def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Поиск компаний", callback_data="search")],
        [InlineKeyboardButton("📊 База отправленных", callback_data="sent_list")],
    ])


async def _interruptible_sleep(seconds: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Sleep in 10-second chunks; record next-send timestamp; return True if cancelled."""
    deadline = time.time() + seconds
    context.user_data["campaign_next_send_at"] = deadline
    context.user_data["campaign_phase"] = "waiting"
    chunk = 10
    elapsed = 0
    while elapsed < seconds:
        if context.user_data.get("cancel_requested"):
            context.user_data.pop("campaign_next_send_at", None)
            return True
        await asyncio.sleep(min(chunk, seconds - elapsed))
        elapsed += chunk
    context.user_data.pop("campaign_next_send_at", None)
    return context.user_data.get("cancel_requested", False)


async def _show_draft_and_wait(
    message, context: ContextTypes.DEFAULT_TYPE, company: str, subject: str, body: str
) -> tuple[str, str]:
    """Show draft email with Send/Edit buttons; pause campaign until user decides.
    Returns the (subject, body) to actually send — either original or user-edited."""
    context.user_data["draft_subject"] = subject
    context.user_data["draft_body"] = body
    context.user_data["awaiting_edit"] = False
    context.user_data["campaign_phase"] = "reviewing"

    event = asyncio.Event()
    context.user_data["draft_event"] = event

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Отправить", callback_data="draft:send"),
        InlineKeyboardButton("✍️ Редактировать", callback_data="draft:edit"),
    ]])

    await message.reply_text(
        f"📧 <b>Черновик для {company}:</b>\n\n"
        f"<b>Тема:</b> {subject}\n\n"
        f"{body}\n\n"
        f"<i>⏰ Автоотправка через 10 минут без действий.</i>",
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    try:
        await asyncio.wait_for(event.wait(), timeout=600)
    except asyncio.TimeoutError:
        await message.reply_text("⏰ Время ожидания истекло — отправляю оригинал.")

    context.user_data["campaign_phase"] = "sending"
    return (
        context.user_data.get("draft_subject", subject),
        context.user_data.get("draft_body", body),
    )


# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    extra = ""
    if context.user_data.get("campaign_running"):
        extra = "\n\n⚠️ Кампания активна. Используйте /cancel чтобы остановить."
    await update.message.reply_text(
        "👋 Добро пожаловать в MySwissTransfer Outreach Bot!\n\n"
        "Выберите действие:" + extra,
        reply_markup=_main_keyboard(),
    )


# ─── /cancel ──────────────────────────────────────────────────────────────────

async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    records = get_all()

    if not records:
        await update.message.reply_text(
            "📭 <b>База пустая</b> — письма ещё не отправлялись.\n\n"
            "Запустите кампанию через /start.",
            parse_mode="HTML",
        )
        return

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["Domain", "Email", "Company"])
    for r in records:
        writer.writerow([r.get("domain", ""), r.get("email", ""), r.get("company", "")])

    buf.seek(0)
    file_bytes = buf.getvalue().encode("utf-8")
    document = InputFile(io.BytesIO(file_bytes), filename="sent_emails.csv")

    await update.message.reply_document(
        document=document,
        caption=(
            f"📊 <b>Отчёт по рассылке</b>\n\n"
            f"Всего записей: <b>{len(records)}</b>\n"
            f"Формат: CSV (Domain, Email, Company)"
        ),
        parse_mode="HTML",
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("campaign_running"):
        await update.message.reply_text(
            "ℹ️ Нет активной кампании для отмены.",
            reply_markup=_main_keyboard(),
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, остановить", callback_data="cancel:confirm"),
            InlineKeyboardButton("▶️ Нет, продолжить", callback_data="cancel:abort"),
        ]
    ])
    await update.message.reply_text(
        "⚠️ <b>Остановить активную кампанию?</b>\n\n"
        "Письма, уже отправленные, останутся в базе.\n"
        "Оставшиеся в очереди отправлены не будут.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ud = context.user_data

    if not ud.get("campaign_running"):
        total_sent = len(get_all())
        await update.message.reply_text(
            f"📭 <b>Кампания не запущена.</b>\n\n"
            f"📊 Всего отправлено писем (всего времени): <b>{total_sent}</b>\n\n"
            f"Используйте /start чтобы начать новый поиск.",
            parse_mode="HTML",
            reply_markup=_main_keyboard(),
        )
        return

    index     = ud.get("campaign_index", 0)
    total     = ud.get("campaign_total", 0)
    sent      = ud.get("campaign_sent_count", 0)
    company   = ud.get("campaign_current_company", "—")
    phase     = ud.get("campaign_phase", "sending")
    next_at   = ud.get("campaign_next_send_at")

    # Build countdown string
    if phase == "reviewing":
        countdown = "✍️ Ожидание вашего решения по черновику письма (кнопки выше)."
    elif phase == "waiting" and next_at:
        remaining = max(0, int(next_at - time.time()))
        mins, secs = divmod(remaining, 60)
        countdown = f"⏳ Следующая отправка через <b>{mins}:{secs:02d}</b>"
    else:
        countdown = "⚡ Сейчас обрабатывается отправка..."

    progress_bar_filled = int((index / total) * 10) if total else 0
    progress_bar = "█" * progress_bar_filled + "░" * (10 - progress_bar_filled)

    await update.message.reply_text(
        f"📡 <b>Статус кампании</b>\n\n"
        f"[{progress_bar}] {index}/{total}\n\n"
        f"🏢 Текущая компания: <b>{company}</b>\n"
        f"✅ Отправлено: <b>{sent}</b> из <b>{total}</b>\n"
        f"❌ Пропущено/ошибок: <b>{index - sent}</b>\n\n"
        f"{countdown}\n\n"
        f"Используйте /cancel чтобы остановить кампанию.",
        parse_mode="HTML",
    )


async def draft_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    event = context.user_data.get("draft_event")

    if query.data == "draft:send":
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Оригинал подтверждён, отправляю...")
        if event:
            event.set()

    elif query.data == "draft:edit":
        context.user_data["awaiting_edit"] = True
        await query.message.edit_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "✍️ <b>Режим редактирования.</b>\n\n"
            "Скопируйте текст письма выше, внесите правки и отправьте мне исправленную версию.\n\n"
            "<i>Можно включить строку «Тема: …» в начале — иначе тема останется прежней.</i>",
            parse_mode="HTML",
        )


async def receive_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the edited email text sent by the user."""
    edited_text = update.message.text.strip()
    original_subject = context.user_data.get("draft_subject", "")

    # Try to parse a new subject from the edited text
    lines = edited_text.splitlines()
    if lines and lines[0].lower().startswith("тема:"):
        new_subject = lines[0][len("тема:"):].strip()
        body_lines = lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        new_body = "\n".join(body_lines).strip()
        context.user_data["draft_subject"] = new_subject
        context.user_data["draft_body"] = new_body
    elif lines and lines[0].lower().startswith("subject:"):
        new_subject = lines[0][len("subject:"):].strip()
        body_lines = lines[1:]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        new_body = "\n".join(body_lines).strip()
        context.user_data["draft_subject"] = new_subject
        context.user_data["draft_body"] = new_body
    else:
        # No subject line — treat whole message as body, keep original subject
        context.user_data["draft_body"] = edited_text

    context.user_data["awaiting_edit"] = False
    final_subject = context.user_data.get("draft_subject", original_subject)
    final_body = context.user_data.get("draft_body", edited_text)

    await update.message.reply_text(
        f"✅ <b>Правки приняты!</b>\n\n"
        f"<b>Тема:</b> {final_subject}\n\n"
        f"{final_body}\n\n"
        f"<i>Отправляю письмо…</i>",
        parse_mode="HTML",
    )

    event = context.user_data.get("draft_event")
    if event:
        event.set()


async def cancel_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel:confirm":
        if not context.user_data.get("campaign_running"):
            await query.message.edit_text("ℹ️ Кампания уже завершена.")
            return
        context.user_data["cancel_requested"] = True
        await query.message.edit_text(
            "🛑 <b>Команда остановки отправлена.</b>\n"
            "Кампания будет остановлена после текущей паузы (до 10 сек).",
            parse_mode="HTML",
        )

    elif query.data == "cancel:abort":
        await query.message.edit_text(
            "▶️ Кампания продолжается.",
        )


# ─── Menu button callbacks ─────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    query = update.callback_query
    await query.answer()

    if query.data == "search":
        if context.user_data.get("campaign_running"):
            await query.message.reply_text(
                "⚠️ Дождитесь завершения текущей кампании или остановите её через /cancel."
            )
            return None
        await query.message.reply_text(
            "🔍 Введите нишу для поиска компаний.\n\n"
            "Например:\n"
            "• <code>Travel agencies Zurich</code>\n"
            "• <code>Luxury hotels Switzerland</code>\n"
            "• <code>Corporate event planners Geneva</code>",
            parse_mode="HTML",
        )
        return WAITING_FOR_NICHE

    if query.data == "sent_list":
        records = get_all()
        if not records:
            await query.message.reply_text("📭 База пустая — письма ещё не отправлялись.")
            return None
        lines = [f"<b>{i+1}.</b> {r['company']} — {r['domain']}" for i, r in enumerate(records[-30:])]
        text = f"📊 <b>Отправлено: {len(records)} писем</b>\n\n" + "\n".join(lines)
        if len(records) > 30:
            text += f"\n\n<i>…и ещё {len(records) - 30} ранее</i>"
        await query.message.reply_text(text, parse_mode="HTML")
        return None

    if query.data.startswith("approve:"):
        await _run_campaign(query.message, context)
        return None

    return None


# ─── Conversation: niche input ─────────────────────────────────────────────────

async def receive_niche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    niche = update.message.text.strip()
    context.user_data["niche"] = niche

    status_msg = await update.message.reply_text(
        f"⏳ Ищу компании по запросу: <b>{niche}</b>...", parse_mode="HTML"
    )

    results = search_companies(niche, num=10)
    if not results:
        await status_msg.edit_text("❌ Ничего не найдено. Попробуйте другой запрос.")
        return ConversationHandler.END

    new_results = [r for r in results if not is_sent(r["domain"])]
    skipped = len(results) - len(new_results)

    if not new_results:
        await status_msg.edit_text(
            f"⚠️ Найдено {len(results)} сайтов, но все уже есть в базе.\n"
            "Попробуйте другой запрос."
        )
        return ConversationHandler.END

    context.user_data["results"] = new_results

    lines = []
    for i, r in enumerate(new_results):
        email_note = f" — 📧 {r['email']}" if r.get("email") else " — (email не найден в сниппете)"
        lines.append(f"{i+1}. <b>{r['company']}</b> ({r['domain']}){email_note}")

    summary = (
        f"✅ Найдено: <b>{len(results)}</b> сайтов\n"
        f"🆕 Новых: <b>{len(new_results)}</b> | ⏭ Пропущено (уже в базе): <b>{skipped}</b>\n\n"
        + "\n".join(lines)
    )
    await status_msg.edit_text(summary, parse_mode="HTML")

    first = new_results[0]
    await update.message.reply_text("🤖 Генерирую пример письма...")
    try:
        email_text = await generate_email(first["company"], first["domain"], first.get("snippet", ""))
        subject, body = parse_subject_body(email_text)
        context.user_data["template_subject"] = subject
        context.user_data["template_body"] = body
    except Exception as e:
        logger.error("Email generation failed: %s", e)
        await update.message.reply_text(f"❌ Ошибка генерации письма: {e}")
        return ConversationHandler.END

    preview = (
        f"📧 <b>Пример письма для {first['company']}:</b>\n\n"
        f"<b>Тема:</b> {subject}\n\n"
        f"{body}"
    )
    keyboard = [[InlineKeyboardButton("✅ Утвердить и запустить автомат", callback_data="approve:run")]]
    await update.message.reply_text(
        preview,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END


# ─── Campaign runner ───────────────────────────────────────────────────────────

async def _run_campaign(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    results = context.user_data.get("results", [])
    if not results:
        await message.reply_text("❌ Нет данных для кампании. Начните новый поиск.")
        return

    # Set running state and clear any stale cancel/progress fields
    context.user_data.update({
        "campaign_running": True,
        "cancel_requested": False,
        "campaign_total": len(results),
        "campaign_index": 0,
        "campaign_sent_count": 0,
        "campaign_current_company": "—",
        "campaign_phase": "sending",
    })
    context.user_data.pop("campaign_next_send_at", None)

    total = len(results)
    await message.reply_text(
        f"🚀 Запускаю рассылку для <b>{total}</b> компаний.\n"
        f"⏱ Задержка между отправками: 15–30 минут.\n\n"
        f"Используйте /cancel чтобы остановить, /status — проверить прогресс.",
        parse_mode="HTML",
    )

    sent_count = 0
    try:
        for i, result in enumerate(results):
            if context.user_data.get("cancel_requested"):
                break

            domain = result["domain"]
            company = result["company"]

            # Update progress tracking
            context.user_data["campaign_index"] = i + 1
            context.user_data["campaign_current_company"] = company
            context.user_data["campaign_phase"] = "sending"

            if is_sent(domain):
                await message.reply_text(f"⏭ {domain} — уже в базе, пропускаю.")
                continue

            # Use snippet email if found; otherwise scrape the site; final fallback = info@domain
            to_email = result.get("email")
            if not to_email:
                await message.reply_text(f"🔍 Email не найден в сниппете для {domain}, сканирую сайт...")
                to_email = await find_email(result.get("url", f"https://{domain}"), domain)

            try:
                email_text = await generate_email(company, domain, result.get("snippet", ""))
                subject, body = parse_subject_body(email_text)
            except Exception as e:
                await message.reply_text(f"❌ Ошибка генерации для {domain}: {e}")
                continue

            # Show draft and wait for user to approve or edit
            subject, body = await _show_draft_and_wait(message, context, company, subject, body)

            if context.user_data.get("cancel_requested"):
                break

            try:
                await send_email(to_email, subject, body)
                mark_sent(domain, to_email, company)
                sent_count += 1
                context.user_data["campaign_sent_count"] = sent_count
                await message.reply_text(
                    f"✅ <b>{company}</b> ({domain})\n"
                    f"📧 Отправлено на: {to_email}\n"
                    f"📌 Тема: {subject}",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.error("Failed to send email to %s: %s", to_email, e)
                await message.reply_text(f"❌ Не удалось отправить на {to_email}: {e}")
                continue

            # Delay before the next send (skipped after the last one)
            if i < total - 1:
                delay = random.randint(DELAY_MIN, DELAY_MAX)
                mins = delay // 60
                await message.reply_text(
                    f"⏳ Следующая отправка через {mins} мин... (/status — прогресс, /cancel — остановить)"
                )
                cancelled = await _interruptible_sleep(delay, context)
                if cancelled:
                    break

    finally:
        context.user_data.update({
            "campaign_running": False,
            "cancel_requested": False,
            "campaign_phase": "idle",
        })
        context.user_data.pop("campaign_next_send_at", None)

    if context.user_data.get("cancel_requested") is False and sent_count < total:
        # Ended via cancel
        await message.reply_text(
            f"🛑 <b>Кампания остановлена вручную.</b>\n"
            f"✅ Отправлено: <b>{sent_count}</b> из <b>{total}</b>\n\n"
            f"Неотправленные компании не записаны в базу.",
            parse_mode="HTML",
            reply_markup=_main_keyboard(),
        )
    else:
        await message.reply_text(
            f"🎉 Кампания завершена!\n"
            f"✅ Отправлено: <b>{sent_count}</b> из <b>{total}</b>",
            parse_mode="HTML",
            reply_markup=_main_keyboard(),
        )


# ─── Fallback ──────────────────────────────────────────────────────────────────

async def fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("awaiting_edit"):
        await receive_edit(update, context)
        return
    await update.message.reply_text(
        "Используйте меню для навигации:",
        reply_markup=_main_keyboard(),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ Произошла ошибка. Попробуйте ещё раз или начните с /start."
        )
