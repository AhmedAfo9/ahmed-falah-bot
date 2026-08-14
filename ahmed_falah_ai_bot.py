import logging
import os
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

# ضع التوكن في متغير بيئة BOT_TOKEN على Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "491527447"))

WAITING_MESSAGE = "تم إرسال رسالتك إلى المشرف، سيتم الرد عليك في حال الرد ورؤية الرسالة"
PENDING_MESSAGE = "يرجى الانتظار، رسالتك في انتظار الرد"

# يربط رقم رسالة المشرف برسالة المستخدم الأصلية.
admin_message_to_user = {}
# يحتفظ بالمستخدمين الذين لديهم رسالة بانتظار رد المشرف.
pending_users = set()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("ahmed_falah_ai_bot")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يرد على أمر /start برسالة ترحيبية."""
    if update.effective_chat and update.effective_chat.id != ADMIN_CHAT_ID:
        await update.message.reply_text(
            "مرحباً بك! أرسل رسالتك وسيتم تحويلها إلى المشرف."
        )


async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يستقبل رسائل المستخدمين، ويرسلها للمشرف مع نص الرسالة، ويمنع التكرار أثناء الانتظار."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if message is None or user is None or chat is None:
        return
    if chat.type != ChatType.PRIVATE or chat.id == ADMIN_CHAT_ID:
        return

    user_id = chat.id
    if user_id in pending_users:
        await message.reply_text(PENDING_MESSAGE)
        return

    username = f"@{user.username}" if user.username else "غير متوفر"
    full_name = user.full_name or "غير معروف"

    # نص الرسالة
    message_text = message.text or message.caption or "[رسالة بدون نص - ربما صورة أو ملف]"

    details = (
        "📩 رسالة جديدة من مستخدم\n"
        "━━━━━━━━━━━━━━━\n"
        f"👤 الاسم: {full_name}\n"
        f"🆔 المعرف: {username}\n"
        f"🔢 Chat ID: {user_id}\n"
        "━━━━━━━━━━━━━━━\n"
        f"💬 الرسالة:\n{message_text}\n"
        "━━━━━━━━━━━━━━━\n"
        "↩️ للرد: اعمل Reply على هذه الرسالة"
    )

    try:
        info_message = await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=details,
        )
    except Exception:
        logger.exception("تعذر إرسال رسالة المستخدم إلى المشرف")
        await message.reply_text("حدث خطأ مؤقت أثناء إرسال رسالتك، يرجى المحاولة لاحقاً")
        return

    # إذا كانت الرسالة تحتوي على وسائط (صورة، فيديو، ملف، صوت) نحولها أيضاً
    if not message.text:
        try:
            forwarded_message = await context.bot.forward_message(
                chat_id=ADMIN_CHAT_ID,
                from_chat_id=chat.id,
                message_id=message.message_id,
            )
            admin_message_to_user[forwarded_message.message_id] = user_id
        except Exception:
            pass

    admin_message_to_user[info_message.message_id] = user_id
    pending_users.add(user_id)

    await message.reply_text(WAITING_MESSAGE)


async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يوصل رد المشرف إلى المستخدم عند استخدام Reply على الرسالة المحولة."""
    message = update.effective_message
    chat = update.effective_chat

    if message is None or chat is None or chat.id != ADMIN_CHAT_ID:
        return
    if message.reply_to_message is None:
        return

    target_user_id = admin_message_to_user.get(message.reply_to_message.message_id)
    if target_user_id is None:
        return

    try:
        await context.bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=ADMIN_CHAT_ID,
            message_id=message.message_id,
        )
    except Exception:
        logger.exception("تعذر إيصال رد المشرف إلى المستخدم %s", target_user_id)
        await message.reply_text("تعذر إيصال الرد إلى المستخدم؛ ربما قام بحظر البوت.")
        return

    pending_users.discard(target_user_id)
    await message.reply_text("✅ تم إرسال ردك إلى المستخدم بنجاح")

    # نحذف خرائط الرسائل المرتبطة بهذا الطلب من الذاكرة.
    for admin_message_id, uid in list(admin_message_to_user.items()):
        if uid == target_user_id:
            del admin_message_to_user[admin_message_id]


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("حدث خطأ أثناء معالجة تحديث: %s", context.error, exc_info=context.error)


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("لم يتم تعيين BOT_TOKEN")

    application = Application.builder().token(BOT_TOKEN).build()

    # أمر /start
    application.add_handler(CommandHandler("start", start_command))

    # يجب تسجيل معالج المشرف أولاً لأنه يلتقط رسائل المشرف التي تستخدم Reply.
    application.add_handler(
        MessageHandler(filters.Chat(ADMIN_CHAT_ID) & filters.REPLY, handle_admin_reply)
    )
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.Chat(ADMIN_CHAT_ID) & ~filters.COMMAND, handle_user_message)
    )
    application.add_error_handler(error_handler)

    logger.info("Ahmed Falah AI Bot يعمل الآن")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
