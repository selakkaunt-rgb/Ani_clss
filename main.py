# -*- coding: utf-8 -*-
"""
Ani_Class — Telegram anime bot (aiogram 3 + Neon Postgres + Render).

Hammasi bitta faylda: config, texts, database, keyboards, handlers, main.

Muhit o'zgaruvchilari (Render -> Environment):
    BOT_TOKEN     — BotFather tokeni
    OWNER_ID      — owner Telegram ID si
    DATABASE_URL  — Neon Postgres ulanish manzili
    AI_API_KEY    — (ixtiyoriy) AI xizmati kaliti
    PORT          — Render o'zi beradi (/health uchun)
"""

import asyncio
import html
import logging
import os
import random
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import aiohttp
import asyncpg
from aiohttp import web
from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ======================================================================
# 1. CONFIG
# ======================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
PORT = int(os.getenv("PORT", "8080"))

try:
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
except ValueError:
    OWNER_ID = 0

PAGE_SIZE = 8                 # sahifalashda bir sahifadagi anime soni
EPISODES_PER_PAGE = 20        # bir sahifadagi qism tugmalari soni
SPAM_LIMIT = 8                # SPAM_WINDOW soniyada nechta so'rov mumkin
SPAM_WINDOW = 5
SPAM_MUTE_SECONDS = 20
BROADCAST_RATE = 25           # sekundiga xabar soni
TRACE_MOE_URL = "https://api.trace.moe/search"

VIP_PLANS: Dict[str, Dict[str, Any]] = {
    "3_month": {"days": 90, "price_key": "price_3_month", "default": 50000,
                "label_uz": "VIP +3 oy", "label_ru": "VIP +3 мес."},
    "6_month": {"days": 180, "price_key": "price_6_month", "default": 100000,
                "label_uz": "VIP +6 oy", "label_ru": "VIP +6 мес."},
    "3_year": {"days": 1095, "price_key": "price_3_year", "default": 500000,
               "label_uz": "VIP +3 yil", "label_ru": "VIP +3 года"},
}

DEFAULT_SETTINGS = {
    "card_info": "Karta ma'lumoti hali kiritilmagan. Owner panelidan kiriting.",
    "price_3_month": "50000",
    "price_6_month": "100000",
    "price_3_year": "500000",
    "main_channel_url": "",
    "privacy_url": "https://telegra.ph/",
    "offer_url": "https://telegra.ph/",
    "developer_info_uz": "👨‍💻 Dasturchi: ma'lumot tez orada qo'shiladi.",
    "developer_info_ru": "👨‍💻 Разработчик: информация скоро будет добавлена.",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("anizone")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def esc(value: Any) -> str:
    """Foydalanuvchi matnini HTML uchun xavfsiz qilish."""
    return html.escape(str(value if value is not None else ""), quote=False)


def clean_text(value: str, max_len: int = 200) -> str:
    """Foydalanuvchi kiritgan matnni tozalash: boshqaruv belgilari va uzunlik."""
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value or "")
    return value.strip()[:max_len]


def split_text(text: str, limit: int = 3800) -> List[str]:
    """Uzun matnni qatorlar bo'yicha bo'lish (Telegram limiti 4096)."""
    parts: List[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts or [""]


# ======================================================================
# 2. TEXTS (uz / ru)
# ======================================================================

TEXTS: Dict[str, Dict[str, str]] = {
    "uz": {
        # --- umumiy ---
        "choose_lang": "🌐 Tilni tanlang / Выберите язык:",
        "lang_changed": "✅ Til o'zgartirildi.",
        "placeholder": "Quyidagilardan birini tanlang...",
        "back": "Orqaga",
        "back_home": "🏠 Orqaga",
        "cancel": "❌ Bekor qilish",
        "cancelled": "Bekor qilindi.",
        "error": "⚠️ Xatolik yuz berdi. Keyinroq urinib ko'ring.",
        "banned": "🚫 Siz botdan foydalanishdan bloklangansiz.",
        "spam": "⏳ Juda tez-tez so'rov yuboryapsiz. Biroz kuting.",
        "not_found": "😕 Hech narsa topilmadi.",
        "main_menu": "🏠 Asosiy menyu",
        # --- /start ---
        "welcome": "Xush kelibsiz! {name} 👋",
        "welcome_italic": ("<i>AniZone — eng katta va boy anime bazasiga ega qulay yordamchingiz. "
                           "Bu yerda siz o'zingizga maqbul animelarni yuqori tezlikda va "
                           "uzilishlarsiz tomosha qilishingiz mumkin.</i>"),
        "welcome_start": "Boshlash uchun pastdagi tugmalardan foydalaning:",
        # --- pastki menyu ---
        "btn_search": "🔍 Anime Izlash",
        "btn_guide": "💬 Qo'llanma",
        "btn_vip": "💎 VIP",
        "btn_ai": "✨ AI",
        "btn_settings": "⚙️ Sozlamalar",
        "btn_about": "👁 Bot haqida",
        "btn_channels": "📢 Kanallarimiz",
        "btn_guide_inline": "📖 Qo'llanma",
        # --- qidiruv ---
        "search_title": "🔍 <b>Anime Izlash Bo'limi</b>\nQidiruv turini tanlang:",
        "s_random": "🎞 Tasodifiy anime",
        "s_by_name": "📋 Nom orqali",
        "s_by_code": "💬 Kod orqali",
        "s_top": "👑 Top",
        "s_newest": "🆕 Eng Yangi",
        "s_oldest": "🕰 Eng eski",
        "s_by_genre": "🔖 Janr orqali",
        "s_by_image": "🎬 Rasm orqali",
        "s_all": "🎬 Barcha animelar",
        "ask_name": "📋 Anime nomini yozing:",
        "ask_code": "💬 Anime kodini (ID) yozing:",
        "bad_code": "❗ Kod faqat raqamlardan iborat bo'lishi kerak.",
        "ask_image": ("🎬 Anime skrinshotini yuboring.\n"
                      "Men uni trace.moe orqali aniqlayman va bazadan qidiraman."),
        "image_searching": "🔎 Qidirilmoqda...",
        "image_not_anime": "❗ Iltimos, rasm (skrinshot) yuboring.",
        "image_found_db": "✅ Rasm bo'yicha topildi: <b>{title}</b> (o'xshashlik {sim}%)",
        "image_found_nodb": ("🔎 Rasm bo'yicha taxminiy anime: <b>{title}</b> "
                             "(o'xshashlik {sim}%)\n😕 Lekin u bizning bazada yo'q."),
        "image_fail": "😕 Rasm bo'yicha anime aniqlanmadi.",
        "choose_genre": "🔖 Janrni tanlang:",
        "no_genres": "😕 Hozircha janrlar yo'q.",
        "results_title": "📃 <b>{title}</b>\nTopildi: {total} ta",
        "page_info": "Sahifa {page}/{pages}",
        "prev": "⬅️ Oldingi",
        "next": "Keyingi ➡️",
        "title_name": "Nom bo'yicha: {q}",
        "title_top": "👑 Top animelar",
        "title_newest": "🆕 Eng yangi animelar",
        "title_oldest": "🕰 Eng eski animelar",
        "title_genre": "Janr: {q}",
        "title_all": "🎬 Barcha animelar",
        # --- anime kartasi ---
        "anime_card": ("🎬 <b>{name}</b>\n\n"
                       "📅 Yil: {year}\n🔖 Janr: {genre}\n🎙 Dublyaj: {studio}\n"
                       "🆔 Kod: <code>{id}</code>\n📺 Qismlar: {count}\n👁 Ko'rishlar: {views}"),
        "vip_badge": "💎 VIP anime",
        "episodes_title": "📺 Qismni tanlang:",
        "no_episodes": "😕 Bu animeda hali qismlar yo'q.",
        "episode_caption": "🎬 <b>{name}</b>\n📺 {num}-qism",
        "vip_only_anime": "💎 Bu anime faqat VIP foydalanuvchilar uchun.\nVIP olish uchun «💎 VIP» bo'limiga o'ting.",
        "vip_only_episode": "💎 Bu qism faqat VIP foydalanuvchilar uchun.",
        "episode_missing": "😕 Qism topilmadi.",
        # --- qo'llanma ---
        "guide_title": "📖 <b>AniZone Bot — Foydalanuvchi Qo'llanmasi</b>",
        "guide_intro": ("AniZone botidan foydalanish juda oddiy! Quyida botning asosiy buyruqlari, "
                        "anime qidirish va tomosha qilish tartibi ko'rsatilgan."),
        "guide_tugmalar": "<b>1. Tugmalar</b>",
        "guide_search": "<b>Anime Izlash</b> - O'zingizga kerak bo'lgan Animeni <b>9 xil</b> usul bilan izlash imkonini beradi",
        "guide_guide": "<b>Qo'llanma</b> - Botni ishlatish bo'yicha qo'llanma",
        "guide_vip": ("<b>VIP</b> - Botdagi cheklovlarni olib tashlash va botdagi maxsus "
                      "imkoniyatlarga ega bo'lish uchun VIP statusini xarid qilish"),
        "guide_ai": ("<b>AI</b> - biror anime haqida AI bilan suhbatlashish yoki biror animeni "
                     "topishga qiynalsangiz AI bo'limiga kirishingiz mumkin"),
        "guide_settings": ("<b>Sozlamalar</b> - Botdagi shaxsiy profilingiz va botning qo'shimcha "
                           "imkoniyatlarini o'zgartirish imkonini beradi"),
        "guide_about": "<b>Bot haqida</b> - Bot va Dasturchi haqida ma'lumotlar",
        "guide_channels": "<b>Kanallarimiz</b> - Bizning barcha kanallarimiz ro'yxati",
        # --- VIP ---
        "vip_active": "💝 VIP: ✅ Faol",
        "vip_inactive": "💝 VIP: ❌ Faol emas",
        "vip_until": "⏳ Tugash sanasi: <b>{date}</b>",
        "vip_what": ("❓ <b>VIP NIMA BERADI:</b>\n"
                     "✨ Reklamasiz foydalanish\n"
                     "✨ Homiy kanallarsiz foydalanish\n"
                     "✨ Cheksiz tomosha qilish\n"
                     "✨ Botning maxsus premium funksiyalaridan foydalanish\n"
                     "✨ AI rejimida erkin foydalanish\n"
                     "✨ Botni 24/7 qo'llab-quvvatlash"),
        "vip_thanks": "👍 VIP xarid qilish orqali siz botning rivojlanishiga hissa qo'shasiz",
        "vip_links": "<a href=\"{privacy}\">Maxfiylik siyosati</a> | <a href=\"{offer}\">Ommaviy oferta</a>",
        "vip_pay": "💳 Iltimos, to'lovni amalga oshiring:\n\n<b>{plan}</b> — {price} UZS\n\n{card}",
        "vip_send_check": "📸 To'lovdan keyin chekni (rasm) yuboring.",
        "vip_check_wrong": "❗ Iltimos, chekni rasm ko'rinishida yuboring.",
        "vip_check_sent": "✅ Chek adminga yuborildi. Tasdiqlanishini kuting.",
        "vip_pending": "⏳ Sizning oldingi to'lovingiz hali ko'rib chiqilmoqda.",
        "vip_approved": "🎉 To'lovingiz tasdiqlandi! VIP faollashtirildi.\n⏳ Tugash sanasi: <b>{date}</b>",
        "vip_rejected": "❌ To'lovingiz rad etildi. Savollar bo'lsa, qo'llab-quvvatlashga yozing.",
        "vip_expired": "⌛️ VIP muddatingiz tugadi. Yangilash uchun «💎 VIP» bo'limiga o'ting.",
        # --- AI ---
        "ai_title": ("🤖 <b>AI yordamchi</b>\n"
                     "Siz anime haqida savollar berishingiz mumkin. Men sizga anime tavsiyalari, "
                     "janrlar haqida ma'lumotlar va boshqa savollaringizga javob beraman.\n\n"
                     "Savolingizni yozing:"),
        "ai_thinking": "🤔 O'ylayapman...",
        "ai_unavailable": "😕 AI xizmati hozircha ulanmagan yoki band. Keyinroq urinib ko'ring.",
        "ai_limit": "⏳ Bepul foydalanuvchilar uchun AI kunlik limiti tugadi ({limit} ta). 💎 VIP da cheklov yo'q.",
        # --- sozlamalar ---
        "settings_title": "⚙️ <b>SHAXSIY SOZLAMALAR</b>",
        "set_nick": "👤 Nikingiz: {nick}",
        "set_menu": "🔘 Menyu turi: {mode} ✅",
        "set_menu_inline": "Inline Menu",
        "set_menu_reply": "Pastki menyu",
        "set_memory_on": "AI Xotira: Yoniq 🟢",
        "set_memory_off": "AI Xotira: O'chiq 🔴",
        "set_lang": "Til",
        "ask_nick": "👤 Yangi nikingizni yozing (2-24 belgi):",
        "bad_nick": "❗ Nik 2 dan 24 gacha belgidan iborat bo'lishi kerak.",
        "nick_saved": "✅ Nik saqlandi: {nick}",
        "menu_switched_inline": "✅ Menyu turi: Inline Menu",
        "menu_switched_reply": "✅ Menyu turi: Pastki menyu",
        # --- bot haqida / kanallar ---
        "about": ("🤖 <b>AniZone — Sevimli animelaringiz olami!</b>\n\n"
                  "AniZone — bu O'zbekistondagi anime ixlosmandlari uchun maxsus yaratilgan, "
                  "eng katta va qulay Telegram botdir. Bu yerda siz xohlagan animengizni yuqori "
                  "sifatda hamda bepul tomosha qilishingiz mumkin.\n\n"
                  "<b>Asosiy imkoniyatlarimiz:</b>\n"
                  "• 🎬 <b>Katta baza:</b> Minglab anime va filmlar to'plami (doimiy yangilanib boradi).\n"
                  "• 🎙 <b>O'zbekcha dublyaj:</b> Professional va sifatli dublyajlar.\n"
                  "• ⚡ <b>Tezkor izlash:</b> Nomi, janri yoki rasm (skrinshot) orqali soniyalar ichida topish.\n"
                  "• 🤖 <b>AI Yordamchi:</b> Kayfiyatingizga mos anime tavsiya qiluvchi aqlli tizim.\n"
                  "• 💎 <b>VIP Obuna:</b> Reklamasiz va eng birinchilardan bo'lib ko'rish imkoni."),
        "channels_title": "📢 <b>Rasmiy kanallarimiz:</b>",
        "btn_main_channel": "📢 Asosiy kanal",
        "no_channels": "Kanallar hali qo'shilmagan.",
        # --- majburiy obuna ---
        "sub_required": "📢 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:",
        "sub_check": "✅ Obunani tekshirish",
        "sub_not_yet": "❗ Siz hali barcha kanallarga obuna bo'lmagansiz.",
        "sub_ok": "✅ Rahmat! Endi botdan foydalanishingiz mumkin.",
    },
    "ru": {
        "choose_lang": "🌐 Tilni tanlang / Выберите язык:",
        "lang_changed": "✅ Язык изменён.",
        "placeholder": "Выберите один из вариантов...",
        "back": "Назад",
        "back_home": "🏠 Назад",
        "cancel": "❌ Отмена",
        "cancelled": "Отменено.",
        "error": "⚠️ Произошла ошибка. Попробуйте позже.",
        "banned": "🚫 Вы заблокированы в боте.",
        "spam": "⏳ Слишком частые запросы. Подождите немного.",
        "not_found": "😕 Ничего не найдено.",
        "main_menu": "🏠 Главное меню",
        "welcome": "Добро пожаловать! {name} 👋",
        "welcome_italic": ("<i>AniZone — ваш удобный помощник с самой большой и богатой базой аниме. "
                           "Здесь вы можете смотреть подходящие вам аниме с высокой скоростью и "
                           "без перебоев.</i>"),
        "welcome_start": "Чтобы начать, воспользуйтесь кнопками ниже:",
        "btn_search": "🔍 Поиск аниме",
        "btn_guide": "💬 Руководство",
        "btn_vip": "💎 VIP",
        "btn_ai": "✨ AI",
        "btn_settings": "⚙️ Настройки",
        "btn_about": "👁 О боте",
        "btn_channels": "📢 Наши каналы",
        "btn_guide_inline": "📖 Руководство",
        "search_title": "🔍 <b>Раздел поиска аниме</b>\nВыберите тип поиска:",
        "s_random": "🎞 Случайное аниме",
        "s_by_name": "📋 По названию",
        "s_by_code": "💬 По коду",
        "s_top": "👑 Топ",
        "s_newest": "🆕 Новинки",
        "s_oldest": "🕰 Старые",
        "s_by_genre": "🔖 По жанру",
        "s_by_image": "🎬 По картинке",
        "s_all": "🎬 Все аниме",
        "ask_name": "📋 Напишите название аниме:",
        "ask_code": "💬 Напишите код (ID) аниме:",
        "bad_code": "❗ Код должен состоять только из цифр.",
        "ask_image": ("🎬 Отправьте скриншот из аниме.\n"
                      "Я определю его через trace.moe и найду в базе."),
        "image_searching": "🔎 Поиск...",
        "image_not_anime": "❗ Пожалуйста, отправьте картинку (скриншот).",
        "image_found_db": "✅ Найдено по картинке: <b>{title}</b> (сходство {sim}%)",
        "image_found_nodb": ("🔎 Предположительное аниме: <b>{title}</b> (сходство {sim}%)\n"
                             "😕 Но его нет в нашей базе."),
        "image_fail": "😕 Не удалось определить аниме по картинке.",
        "choose_genre": "🔖 Выберите жанр:",
        "no_genres": "😕 Жанров пока нет.",
        "results_title": "📃 <b>{title}</b>\nНайдено: {total}",
        "page_info": "Страница {page}/{pages}",
        "prev": "⬅️ Назад",
        "next": "Далее ➡️",
        "title_name": "По названию: {q}",
        "title_top": "👑 Топ аниме",
        "title_newest": "🆕 Новые аниме",
        "title_oldest": "🕰 Старые аниме",
        "title_genre": "Жанр: {q}",
        "title_all": "🎬 Все аниме",
        "anime_card": ("🎬 <b>{name}</b>\n\n"
                       "📅 Год: {year}\n🔖 Жанр: {genre}\n🎙 Озвучка: {studio}\n"
                       "🆔 Код: <code>{id}</code>\n📺 Серии: {count}\n👁 Просмотры: {views}"),
        "vip_badge": "💎 VIP аниме",
        "episodes_title": "📺 Выберите серию:",
        "no_episodes": "😕 В этом аниме пока нет серий.",
        "episode_caption": "🎬 <b>{name}</b>\n📺 {num}-серия",
        "vip_only_anime": "💎 Это аниме только для VIP-пользователей.\nПерейдите в раздел «💎 VIP».",
        "vip_only_episode": "💎 Эта серия только для VIP-пользователей.",
        "episode_missing": "😕 Серия не найдена.",
        "guide_title": "📖 <b>AniZone Bot — Руководство пользователя</b>",
        "guide_intro": ("Пользоваться AniZone очень просто! Ниже описаны основные кнопки бота, "
                        "порядок поиска и просмотра аниме."),
        "guide_tugmalar": "<b>1. Кнопки</b>",
        "guide_search": "<b>Поиск аниме</b> - позволяет искать нужное аниме <b>9 способами</b>",
        "guide_guide": "<b>Руководство</b> - инструкция по использованию бота",
        "guide_vip": ("<b>VIP</b> - покупка VIP-статуса для снятия ограничений и получения "
                      "особых возможностей бота"),
        "guide_ai": ("<b>AI</b> - поговорить с AI о каком-либо аниме или обратиться в раздел AI, "
                     "если трудно найти нужное аниме"),
        "guide_settings": ("<b>Настройки</b> - позволяют изменить личный профиль и "
                           "дополнительные возможности бота"),
        "guide_about": "<b>О боте</b> - информация о боте и разработчике",
        "guide_channels": "<b>Наши каналы</b> - список всех наших каналов",
        "vip_active": "💝 VIP: ✅ Активен",
        "vip_inactive": "💝 VIP: ❌ Не активен",
        "vip_until": "⏳ Действует до: <b>{date}</b>",
        "vip_what": ("❓ <b>ЧТО ДАЁТ VIP:</b>\n"
                     "✨ Использование без рекламы\n"
                     "✨ Использование без спонсорских каналов\n"
                     "✨ Неограниченный просмотр\n"
                     "✨ Особые премиум-функции бота\n"
                     "✨ Свободное использование режима AI\n"
                     "✨ Поддержка бота 24/7"),
        "vip_thanks": "👍 Покупая VIP, вы вносите вклад в развитие бота",
        "vip_links": "<a href=\"{privacy}\">Политика конфиденциальности</a> | <a href=\"{offer}\">Публичная оферта</a>",
        "vip_pay": "💳 Пожалуйста, произведите оплату:\n\n<b>{plan}</b> — {price} UZS\n\n{card}",
        "vip_send_check": "📸 После оплаты отправьте чек (фото).",
        "vip_check_wrong": "❗ Пожалуйста, отправьте чек в виде фото.",
        "vip_check_sent": "✅ Чек отправлен администратору. Ожидайте подтверждения.",
        "vip_pending": "⏳ Ваш предыдущий платёж ещё на рассмотрении.",
        "vip_approved": "🎉 Ваш платёж подтверждён! VIP активирован.\n⏳ Действует до: <b>{date}</b>",
        "vip_rejected": "❌ Ваш платёж отклонён. Если есть вопросы, напишите в поддержку.",
        "vip_expired": "⌛️ Срок вашего VIP истёк. Для продления перейдите в раздел «💎 VIP».",
        "ai_title": ("🤖 <b>AI помощник</b>\n"
                     "Вы можете задавать вопросы об аниме. Я дам рекомендации, информацию о "
                     "жанрах и отвечу на другие вопросы.\n\n"
                     "Напишите свой вопрос:"),
        "ai_thinking": "🤔 Думаю...",
        "ai_unavailable": "😕 Сервис AI пока не подключён или занят. Попробуйте позже.",
        "ai_limit": "⏳ Дневной лимит AI для бесплатных пользователей исчерпан ({limit}). В 💎 VIP лимита нет.",
        "settings_title": "⚙️ <b>ЛИЧНЫЕ НАСТРОЙКИ</b>",
        "set_nick": "👤 Ваш ник: {nick}",
        "set_menu": "🔘 Тип меню: {mode} ✅",
        "set_menu_inline": "Inline меню",
        "set_menu_reply": "Нижнее меню",
        "set_memory_on": "AI Память: Вкл 🟢",
        "set_memory_off": "AI Память: Выкл 🔴",
        "set_lang": "Язык",
        "ask_nick": "👤 Напишите новый ник (2-24 символа):",
        "bad_nick": "❗ Ник должен содержать от 2 до 24 символов.",
        "nick_saved": "✅ Ник сохранён: {nick}",
        "menu_switched_inline": "✅ Тип меню: Inline меню",
        "menu_switched_reply": "✅ Тип меню: Нижнее меню",
        "about": ("🤖 <b>AniZone — мир ваших любимых аниме!</b>\n\n"
                  "AniZone — самый большой и удобный Telegram-бот, созданный специально для "
                  "любителей аниме Узбекистана. Здесь вы можете смотреть любое аниме в высоком "
                  "качестве и бесплатно.\n\n"
                  "<b>Наши основные возможности:</b>\n"
                  "• 🎬 <b>Большая база:</b> тысячи аниме и фильмов (постоянно пополняется).\n"
                  "• 🎙 <b>Узбекская озвучка:</b> профессиональная и качественная озвучка.\n"
                  "• ⚡ <b>Быстрый поиск:</b> по названию, жанру или картинке (скриншоту) за секунды.\n"
                  "• 🤖 <b>AI помощник:</b> умная система, подбирающая аниме под настроение.\n"
                  "• 💎 <b>VIP подписка:</b> без рекламы и возможность смотреть одним из первых."),
        "channels_title": "📢 <b>Наши официальные каналы:</b>",
        "btn_main_channel": "📢 Основной канал",
        "no_channels": "Каналы пока не добавлены.",
        "sub_required": "📢 Чтобы пользоваться ботом, подпишитесь на каналы ниже:",
        "sub_check": "✅ Проверить подписку",
        "sub_not_yet": "❗ Вы ещё не подписались на все каналы.",
        "sub_ok": "✅ Спасибо! Теперь вы можете пользоваться ботом.",
    },
}

LANGS = ("uz", "ru")


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Matnni tilga qarab olish. Topilmasa o'zbekchasi, u ham bo'lmasa kalit."""
    lang = lang if lang in TEXTS else "uz"
    template = TEXTS[lang].get(key) or TEXTS["uz"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


def all_langs_text(key: str) -> set:
    """Pastki menyu tugmalarini har ikki tilda ushlash uchun."""
    return {TEXTS[lang][key] for lang in LANGS if key in TEXTS[lang]}


def fmt_date(dt: Optional[datetime]) -> str:
    if not dt:
        return "—"
    local = dt.astimezone(timezone(timedelta(hours=5)))
    return local.strftime("%d.%m.%Y %H:%M")


# ======================================================================
# 3. DATABASE (Neon Postgres, asyncpg) — hamma so'rovlar parametrli
# ======================================================================

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id       BIGINT PRIMARY KEY,
    username      TEXT,
    full_name     TEXT,
    nick          TEXT,
    lang          TEXT,
    menu_mode     TEXT NOT NULL DEFAULT 'reply',
    ai_memory     BOOLEAN NOT NULL DEFAULT TRUE,
    is_banned     BOOLEAN NOT NULL DEFAULT FALSE,
    vip_until     TIMESTAMPTZ,
    ai_count      INTEGER NOT NULL DEFAULT 0,
    ai_count_date DATE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS animes (
    id         BIGINT PRIMARY KEY,
    name       TEXT NOT NULL,
    year       TEXT,
    genre      TEXT,
    studio     TEXT,
    photo_id   TEXT,
    is_vip     BOOLEAN NOT NULL DEFAULT FALSE,
    views      INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS episodes (
    id         BIGSERIAL PRIMARY KEY,
    anime_id   BIGINT NOT NULL REFERENCES animes(id) ON DELETE CASCADE,
    number     INTEGER NOT NULL,
    file_id    TEXT NOT NULL,
    anime_name TEXT,
    is_vip     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (anime_id, number)
);

CREATE TABLE IF NOT EXISTS vip (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    plan          TEXT NOT NULL,
    price         INTEGER NOT NULL,
    check_file_id TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at    TIMESTAMPTZ,
    decided_by    BIGINT
);

CREATE TABLE IF NOT EXISTS channels (
    id         BIGSERIAL PRIMARY KEY,
    chat_id    BIGINT NOT NULL,
    title      TEXT,
    url        TEXT,
    kind       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (chat_id, kind)
);

CREATE TABLE IF NOT EXISTS admins (
    user_id  BIGINT PRIMARY KEY,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS logs (
    id         BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor_id   BIGINT,
    action     TEXT NOT NULL,
    details    TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS ai_memory (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_episodes_anime ON episodes(anime_id, number);
CREATE INDEX IF NOT EXISTS idx_animes_created ON animes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_animes_name ON animes(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_vip_status ON vip(status);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_memory_user ON ai_memory(user_id, id DESC);
"""


class Database:
    """asyncpg ustiga o'ralgan qatlam. Ulanish uzilsa qayta ulanadi."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None
        self._lock = asyncio.Lock()

    # ---------------- ulanish ----------------
    async def connect(self) -> None:
        async with self._lock:
            if self.pool is not None:
                return
            self.pool = await asyncpg.create_pool(
                self.dsn,
                min_size=1,
                max_size=5,
                command_timeout=30,
                max_inactive_connection_lifetime=120,
            )
            log.info("Baza ulandi")

    async def reconnect(self) -> None:
        async with self._lock:
            if self.pool is not None:
                try:
                    await self.pool.close()
                except Exception:  # noqa: BLE001
                    pass
                self.pool = None
        for attempt in range(1, 6):
            try:
                await self.connect()
                return
            except Exception as exc:  # noqa: BLE001
                log.error("Bazaga qayta ulanish %s/5 xato: %s", attempt, exc)
                await asyncio.sleep(min(2 * attempt, 10))
        raise ConnectionError("Bazaga ulanib bo'lmadi")

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _run(self, method: str, query: str, *args: Any) -> Any:
        """So'rovni bajarish; ulanish xatosida bir marta qayta urinish."""
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            try:
                if self.pool is None:
                    await self.connect()
                assert self.pool is not None
                async with self.pool.acquire() as conn:
                    return await getattr(conn, method)(query, *args)
            except (asyncpg.PostgresConnectionError, asyncpg.InterfaceError,
                    ConnectionError, OSError, asyncio.TimeoutError) as exc:
                last_exc = exc
                log.warning("Baza ulanish xatosi (%s): %s", attempt + 1, exc)
                await self.reconnect()
        raise last_exc or RuntimeError("DB xato")

    async def fetch(self, query: str, *args: Any) -> List[asyncpg.Record]:
        return await self._run("fetch", query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Optional[asyncpg.Record]:
        return await self._run("fetchrow", query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self._run("fetchval", query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        return await self._run("execute", query, *args)

    async def init_schema(self) -> None:
        for statement in SCHEMA_SQL.split(";"):
            statement = statement.strip()
            if statement:
                await self.execute(statement)
        for key, value in DEFAULT_SETTINGS.items():
            await self.execute(
                "INSERT INTO settings(key, value) VALUES($1, $2) ON CONFLICT (key) DO NOTHING",
                key, value,
            )
        log.info("Baza jadvallari tayyor")

    # ---------------- sozlamalar ----------------
    async def get_setting(self, key: str) -> str:
        value = await self.fetchval("SELECT value FROM settings WHERE key=$1", key)
        if value is None:
            return DEFAULT_SETTINGS.get(key, "")
        return value

    async def set_setting(self, key: str, value: str) -> None:
        await self.execute(
            "INSERT INTO settings(key, value) VALUES($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
            key, value,
        )

    async def get_price(self, plan: str) -> int:
        info = VIP_PLANS[plan]
        raw = await self.get_setting(info["price_key"])
        try:
            return int(raw)
        except (TypeError, ValueError):
            return info["default"]

    # ---------------- foydalanuvchilar ----------------
    async def upsert_user(self, user_id: int, username: Optional[str], full_name: str) -> bool:
        """Yangi foydalanuvchi bo'lsa True qaytaradi."""
        row = await self.fetchrow(
            """
            INSERT INTO users(user_id, username, full_name, nick)
            VALUES($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE
                SET username=EXCLUDED.username,
                    full_name=EXCLUDED.full_name,
                    last_active=NOW()
            RETURNING (xmax = 0) AS inserted
            """,
            user_id, username, clean_text(full_name, 100), clean_text(full_name, 24),
        )
        return bool(row["inserted"]) if row else False

    async def get_user(self, user_id: int) -> Optional[asyncpg.Record]:
        return await self.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)

    async def set_lang(self, user_id: int, lang: str) -> None:
        await self.execute("UPDATE users SET lang=$1 WHERE user_id=$2", lang, user_id)

    async def set_nick(self, user_id: int, nick: str) -> None:
        await self.execute("UPDATE users SET nick=$1 WHERE user_id=$2", nick, user_id)

    async def set_menu_mode(self, user_id: int, mode: str) -> None:
        await self.execute("UPDATE users SET menu_mode=$1 WHERE user_id=$2", mode, user_id)

    async def set_ai_memory(self, user_id: int, value: bool) -> None:
        await self.execute("UPDATE users SET ai_memory=$1 WHERE user_id=$2", value, user_id)
        if not value:
            await self.execute("DELETE FROM ai_memory WHERE user_id=$1", user_id)

    async def set_banned(self, user_id: int, banned: bool) -> None:
        await self.execute("UPDATE users SET is_banned=$1 WHERE user_id=$2", banned, user_id)

    async def all_user_ids(self) -> List[int]:
        rows = await self.fetch("SELECT user_id FROM users WHERE is_banned=FALSE")
        return [r["user_id"] for r in rows]

    async def find_user(self, ref: str) -> Optional[asyncpg.Record]:
        ref = ref.strip().lstrip("@")
        if ref.isdigit():
            return await self.get_user(int(ref))
        return await self.fetchrow("SELECT * FROM users WHERE LOWER(username)=LOWER($1)", ref)

    # ---------------- VIP ----------------
    async def is_vip(self, user_id: int) -> bool:
        until = await self.fetchval("SELECT vip_until FROM users WHERE user_id=$1", user_id)
        return bool(until and until > now_utc())

    async def grant_vip(self, user_id: int, days: int) -> datetime:
        """VIP muddatini uzaytirish (faol bo'lsa ustiga qo'shadi)."""
        current = await self.fetchval("SELECT vip_until FROM users WHERE user_id=$1", user_id)
        base = current if current and current > now_utc() else now_utc()
        new_until = base + timedelta(days=days)
        await self.execute("UPDATE users SET vip_until=$1 WHERE user_id=$2", new_until, user_id)
        return new_until

    async def revoke_vip(self, user_id: int) -> None:
        await self.execute("UPDATE users SET vip_until=NULL WHERE user_id=$1", user_id)

    async def expired_vip_users(self) -> List[int]:
        """Muddati tugagan va hali tozalanmagan VIP foydalanuvchilar."""
        rows = await self.fetch(
            "UPDATE users SET vip_until=NULL WHERE vip_until IS NOT NULL AND vip_until <= NOW() "
            "RETURNING user_id"
        )
        return [r["user_id"] for r in rows]

    async def create_vip_request(self, user_id: int, plan: str, price: int, check_file_id: str) -> int:
        return await self.fetchval(
            "INSERT INTO vip(user_id, plan, price, check_file_id) VALUES($1,$2,$3,$4) RETURNING id",
            user_id, plan, price, check_file_id,
        )

    async def get_vip_request(self, req_id: int) -> Optional[asyncpg.Record]:
        return await self.fetchrow("SELECT * FROM vip WHERE id=$1", req_id)

    async def has_pending_request(self, user_id: int) -> bool:
        val = await self.fetchval(
            "SELECT 1 FROM vip WHERE user_id=$1 AND status='pending' LIMIT 1", user_id)
        return bool(val)

    async def decide_vip_request(self, req_id: int, status: str, decided_by: int) -> bool:
        """Faqat pending bo'lsa o'zgartiradi (ikki marta bosishdan himoya)."""
        row = await self.fetchrow(
            "UPDATE vip SET status=$1, decided_at=NOW(), decided_by=$2 "
            "WHERE id=$3 AND status='pending' RETURNING id",
            status, decided_by, req_id,
        )
        return row is not None

    # ---------------- anime ----------------
    async def anime_exists(self, anime_id: int) -> bool:
        return bool(await self.fetchval("SELECT 1 FROM animes WHERE id=$1", anime_id))

    async def next_anime_id(self) -> int:
        val = await self.fetchval("SELECT COALESCE(MAX(id), 0) + 1 FROM animes")
        return int(val)

    async def add_anime(self, anime_id: int, name: str, year: str, genre: str,
                        studio: str, photo_id: str, is_vip: bool) -> None:
        await self.execute(
            "INSERT INTO animes(id, name, year, genre, studio, photo_id, is_vip) "
            "VALUES($1,$2,$3,$4,$5,$6,$7)",
            anime_id, name, year, genre, studio, photo_id, is_vip,
        )

    async def get_anime(self, anime_id: int) -> Optional[asyncpg.Record]:
        return await self.fetchrow("SELECT * FROM animes WHERE id=$1", anime_id)

    async def update_anime_field(self, anime_id: int, field: str, value: Any) -> None:
        allowed = {"name", "year", "genre", "studio", "photo_id", "is_vip"}
        if field not in allowed:
            raise ValueError("Ruxsat etilmagan maydon")
        await self.execute(f"UPDATE animes SET {field}=$1 WHERE id=$2", value, anime_id)
        if field == "name":
            await self.execute("UPDATE episodes SET anime_name=$1 WHERE anime_id=$2", value, anime_id)
        if field == "is_vip":
            await self.execute("UPDATE episodes SET is_vip=$1 WHERE anime_id=$2", value, anime_id)

    async def delete_anime(self, anime_id: int) -> None:
        await self.execute("DELETE FROM animes WHERE id=$1", anime_id)

    async def inc_views(self, anime_id: int) -> None:
        await self.execute("UPDATE animes SET views=views+1 WHERE id=$1", anime_id)

    async def search_by_name(self, q: str, limit: int, offset: int) -> Tuple[List[asyncpg.Record], int]:
        pattern = f"%{q.lower()}%"
        total = await self.fetchval("SELECT COUNT(*) FROM animes WHERE LOWER(name) LIKE $1", pattern)
        rows = await self.fetch(
            "SELECT * FROM animes WHERE LOWER(name) LIKE $1 ORDER BY name LIMIT $2 OFFSET $3",
            pattern, limit, offset)
        return rows, int(total)

    async def search_by_genre(self, genre: str, limit: int, offset: int) -> Tuple[List[asyncpg.Record], int]:
        pattern = f"%{genre.lower()}%"
        total = await self.fetchval("SELECT COUNT(*) FROM animes WHERE LOWER(genre) LIKE $1", pattern)
        rows = await self.fetch(
            "SELECT * FROM animes WHERE LOWER(genre) LIKE $1 ORDER BY name LIMIT $2 OFFSET $3",
            pattern, limit, offset)
        return rows, int(total)

    async def list_animes(self, order: str, limit: int, offset: int) -> Tuple[List[asyncpg.Record], int]:
        orders = {
            "top": "views DESC, id DESC",
            "newest": "created_at DESC, id DESC",
            "oldest": "created_at ASC, id ASC",
            "all": "name ASC",
        }
        order_sql = orders.get(order, orders["all"])
        total = await self.fetchval("SELECT COUNT(*) FROM animes")
        rows = await self.fetch(
            f"SELECT * FROM animes ORDER BY {order_sql} LIMIT $1 OFFSET $2", limit, offset)
        return rows, int(total)

    async def random_anime(self) -> Optional[asyncpg.Record]:
        return await self.fetchrow("SELECT * FROM animes ORDER BY RANDOM() LIMIT 1")

    async def all_genres(self) -> List[str]:
        rows = await self.fetch("SELECT genre FROM animes WHERE genre IS NOT NULL AND genre <> ''")
        found: Dict[str, str] = {}
        for row in rows:
            for part in re.split(r"[,/|]", row["genre"]):
                part = part.strip()
                if part and part.lower() not in found:
                    found[part.lower()] = part
        return sorted(found.values(), key=str.lower)

    async def recent_animes(self, hours: int = 24) -> List[asyncpg.Record]:
        return await self.fetch(
            "SELECT * FROM animes WHERE created_at >= NOW() - ($1 * INTERVAL '1 hour') "
            "ORDER BY created_at ASC", hours)

    async def find_anime_by_title_fuzzy(self, title_variants: List[str]) -> Optional[asyncpg.Record]:
        """trace.moe nomlarini bazadagi anime bilan moslashtirish."""
        for title in title_variants:
            title = clean_text(title, 120).lower()
            if len(title) < 2:
                continue
            row = await self.fetchrow(
                "SELECT * FROM animes WHERE LOWER(name)=$1 OR LOWER(name) LIKE $2 "
                "OR $1 LIKE '%' || LOWER(name) || '%' ORDER BY views DESC LIMIT 1",
                title, f"%{title}%")
            if row:
                return row
        return None

    # ---------------- qismlar ----------------
    async def episode_exists(self, anime_id: int, number: int) -> bool:
        return bool(await self.fetchval(
            "SELECT 1 FROM episodes WHERE anime_id=$1 AND number=$2", anime_id, number))

    async def next_episode_number(self, anime_id: int) -> int:
        val = await self.fetchval(
            "SELECT COALESCE(MAX(number), 0) + 1 FROM episodes WHERE anime_id=$1", anime_id)
        return int(val)

    async def add_episode(self, anime_id: int, number: int, file_id: str,
                          anime_name: str, is_vip: bool) -> None:
        await self.execute(
            "INSERT INTO episodes(anime_id, number, file_id, anime_name, is_vip) "
            "VALUES($1,$2,$3,$4,$5)", anime_id, number, file_id, anime_name, is_vip)

    async def get_episode(self, anime_id: int, number: int) -> Optional[asyncpg.Record]:
        return await self.fetchrow(
            "SELECT * FROM episodes WHERE anime_id=$1 AND number=$2", anime_id, number)

    async def list_episodes(self, anime_id: int) -> List[asyncpg.Record]:
        return await self.fetch(
            "SELECT number, is_vip FROM episodes WHERE anime_id=$1 ORDER BY number", anime_id)

    async def count_episodes(self, anime_id: int) -> int:
        return int(await self.fetchval(
            "SELECT COUNT(*) FROM episodes WHERE anime_id=$1", anime_id))

    async def delete_episode(self, anime_id: int, number: int) -> bool:
        row = await self.fetchrow(
            "DELETE FROM episodes WHERE anime_id=$1 AND number=$2 RETURNING id", anime_id, number)
        return row is not None

    # ---------------- kanallar ----------------
    async def add_channel(self, chat_id: int, title: str, url: str, kind: str) -> None:
        await self.execute(
            "INSERT INTO channels(chat_id, title, url, kind) VALUES($1,$2,$3,$4) "
            "ON CONFLICT (chat_id, kind) DO UPDATE SET title=EXCLUDED.title, url=EXCLUDED.url",
            chat_id, title, url, kind)

    async def remove_channel(self, channel_row_id: int) -> None:
        await self.execute("DELETE FROM channels WHERE id=$1", channel_row_id)

    async def list_channels(self, kind: str) -> List[asyncpg.Record]:
        return await self.fetch("SELECT * FROM channels WHERE kind=$1 ORDER BY id", kind)

    async def get_channel(self, channel_row_id: int) -> Optional[asyncpg.Record]:
        return await self.fetchrow("SELECT * FROM channels WHERE id=$1", channel_row_id)

    # ---------------- adminlar ----------------
    async def is_admin_db(self, user_id: int) -> bool:
        return bool(await self.fetchval("SELECT 1 FROM admins WHERE user_id=$1", user_id))

    async def add_admin(self, user_id: int) -> None:
        await self.execute(
            "INSERT INTO admins(user_id) VALUES($1) ON CONFLICT DO NOTHING", user_id)

    async def remove_admin(self, user_id: int) -> None:
        await self.execute("DELETE FROM admins WHERE user_id=$1", user_id)

    async def list_admins(self) -> List[int]:
        rows = await self.fetch("SELECT user_id FROM admins ORDER BY added_at")
        return [r["user_id"] for r in rows]

    # ---------------- loglar ----------------
    async def add_log(self, actor_id: Optional[int], action: str, details: str = "") -> None:
        try:
            await self.execute(
                "INSERT INTO logs(actor_id, action, details) VALUES($1,$2,$3)",
                actor_id, action[:60], details[:500])
        except Exception as exc:  # noqa: BLE001
            log.error("Log yozishda xato: %s", exc)

    async def recent_logs(self, limit: int = 30) -> List[asyncpg.Record]:
        return await self.fetch("SELECT * FROM logs ORDER BY id DESC LIMIT $1", limit)

    # ---------------- AI ----------------
    async def ai_usage_today(self, user_id: int) -> int:
        row = await self.fetchrow(
            "SELECT ai_count, ai_count_date FROM users WHERE user_id=$1", user_id)
        if not row or row["ai_count_date"] != now_utc().date():
            return 0
        return int(row["ai_count"])

    async def ai_usage_inc(self, user_id: int) -> None:
        await self.execute(
            "UPDATE users SET ai_count = CASE WHEN ai_count_date = CURRENT_DATE "
            "THEN ai_count + 1 ELSE 1 END, ai_count_date = CURRENT_DATE WHERE user_id=$1",
            user_id)

    async def ai_history(self, user_id: int, limit: int = 10) -> List[Dict[str, str]]:
        rows = await self.fetch(
            "SELECT role, content FROM ai_memory WHERE user_id=$1 ORDER BY id DESC LIMIT $2",
            user_id, limit)
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def ai_remember(self, user_id: int, role: str, content: str) -> None:
        await self.execute(
            "INSERT INTO ai_memory(user_id, role, content) VALUES($1,$2,$3)",
            user_id, role, content[:2000])
        await self.execute(
            "DELETE FROM ai_memory WHERE user_id=$1 AND id NOT IN "
            "(SELECT id FROM ai_memory WHERE user_id=$1 ORDER BY id DESC LIMIT 20)", user_id)

    # ---------------- statistika ----------------
    async def stats(self) -> Dict[str, int]:
        return {
            "users": int(await self.fetchval("SELECT COUNT(*) FROM users")),
            "vip": int(await self.fetchval(
                "SELECT COUNT(*) FROM users WHERE vip_until > NOW()")),
            "animes": int(await self.fetchval("SELECT COUNT(*) FROM animes")),
            "episodes": int(await self.fetchval("SELECT COUNT(*) FROM episodes")),
            "today": int(await self.fetchval(
                "SELECT COUNT(*) FROM users WHERE created_at >= date_trunc('day', NOW())")),
            "banned": int(await self.fetchval("SELECT COUNT(*) FROM users WHERE is_banned")),
        }


db = Database(DATABASE_URL)


# ======================================================================
# 4. UTILS: rollar, xabar yuborish yordamchilari, obuna tekshiruvi, spam
# ======================================================================

def is_owner(user_id: int) -> bool:
    return bool(OWNER_ID) and user_id == OWNER_ID


async def is_admin(user_id: int) -> bool:
    """Admin yoki owner ekanini HAR SAFAR tekshiradi."""
    if is_owner(user_id):
        return True
    try:
        return await db.is_admin_db(user_id)
    except Exception as exc:  # noqa: BLE001
        log.error("is_admin xato: %s", exc)
        return False


def user_link(user_id: int, username: Optional[str], name: str = "") -> str:
    if username:
        return f"@{esc(username)}"
    label = esc(name) or str(user_id)
    return f'<a href="tg://user?id={user_id}">{label}</a> (ID: <code>{user_id}</code>)'


def vip_active(user_row: Optional[asyncpg.Record]) -> bool:
    if not user_row:
        return False
    until = user_row["vip_until"]
    return bool(until and until > now_utc())


async def safe_delete(message: Optional[Message]) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        pass


async def smart_send(event: Any, text: str, reply_markup: Any = None) -> Optional[Message]:
    """Callback bo'lsa xabarni tahrirlaydi (iloji bo'lmasa yangisini yuboradi),
    Message bo'lsa yangi xabar yuboradi."""
    if isinstance(event, CallbackQuery):
        msg = event.message
        if msg is None:
            return None
        try:
            if msg.photo or msg.video or msg.document:
                raise TelegramBadRequest(method=None, message="media message")  # type: ignore[arg-type]
            return await msg.edit_text(text, reply_markup=reply_markup)  # type: ignore[return-value]
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return msg  # type: ignore[return-value]
            await safe_delete(msg)  # type: ignore[arg-type]
            return await msg.answer(text, reply_markup=reply_markup)
        except Exception as exc:  # noqa: BLE001
            log.warning("smart_send xato: %s", exc)
            return await msg.answer(text, reply_markup=reply_markup)
    if isinstance(event, Message):
        return await event.answer(text, reply_markup=reply_markup)
    return None


async def answer_cb(cb: CallbackQuery, text: str = "", alert: bool = False) -> None:
    try:
        await cb.answer(text, show_alert=alert)
    except Exception:  # noqa: BLE001
        pass


async def send_media_safe(bot: Bot, chat_id: int, file_id: str, caption: str,
                          protect: bool = True, reply_markup: Any = None) -> bool:
    """Videoni yuboradi; video bo'lmasa hujjat sifatida urinadi. protect_content=True."""
    try:
        await bot.send_video(chat_id, file_id, caption=caption,
                             protect_content=protect, reply_markup=reply_markup)
        return True
    except TelegramBadRequest:
        try:
            await bot.send_document(chat_id, file_id, caption=caption,
                                    protect_content=protect, reply_markup=reply_markup)
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("Media yuborib bo'lmadi: %s", exc)
            return False


# ---------------- spam himoyasi ----------------
class RateLimiter:
    def __init__(self, limit: int, window: int, mute: int):
        self.limit = limit
        self.window = window
        self.mute = mute
        self.hits: Dict[int, deque] = defaultdict(deque)
        self.muted_until: Dict[int, float] = {}

    def check(self, user_id: int) -> str:
        """'ok' | 'muted' | 'just_muted'."""
        now = time.monotonic()
        until = self.muted_until.get(user_id, 0)
        if until > now:
            return "muted"
        dq = self.hits[user_id]
        while dq and now - dq[0] > self.window:
            dq.popleft()
        dq.append(now)
        if len(dq) > self.limit:
            self.muted_until[user_id] = now + self.mute
            dq.clear()
            return "just_muted"
        return "ok"

    def cleanup(self) -> None:
        now = time.monotonic()
        for uid in [u for u, v in self.muted_until.items() if v < now]:
            self.muted_until.pop(uid, None)
        for uid in [u for u, dq in self.hits.items() if not dq]:
            self.hits.pop(uid, None)


rate_limiter = RateLimiter(SPAM_LIMIT, SPAM_WINDOW, SPAM_MUTE_SECONDS)


# ---------------- majburiy obuna ----------------
_sub_cache: Dict[int, Tuple[float, List[int]]] = {}
SUB_CACHE_TTL = 30


async def missing_subscriptions(bot: Bot, user_id: int, use_cache: bool = True) -> List[asyncpg.Record]:
    """Foydalanuvchi obuna bo'lmagan majburiy kanallar ro'yxati."""
    channels = await db.list_channels("sub")
    if not channels:
        return []
    if use_cache:
        cached = _sub_cache.get(user_id)
        if cached and time.monotonic() - cached[0] < SUB_CACHE_TTL:
            return [c for c in channels if c["id"] in cached[1]]
    missing: List[asyncpg.Record] = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch["chat_id"], user_id)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                missing.append(ch)
        except Exception as exc:  # noqa: BLE001
            # Bot kanalda admin emas yoki kanal topilmadi — foydalanuvchini bloklamaymiz
            log.warning("Obuna tekshirish xato (kanal %s): %s", ch["chat_id"], exc)
    _sub_cache[user_id] = (time.monotonic(), [c["id"] for c in missing])
    return missing


def drop_sub_cache(user_id: int) -> None:
    _sub_cache.pop(user_id, None)


# ---------------- trace.moe ----------------
async def trace_moe_lookup(image_bytes: bytes) -> Optional[Dict[str, Any]]:
    """Skrinshot bo'yicha anime aniqlash. Natija: {titles: [...], similarity: float}."""
    try:
        timeout = aiohttp.ClientTimeout(total=40)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{TRACE_MOE_URL}?anilistInfo",
                data=image_bytes,
                headers={"Content-Type": "image/jpeg"},
            ) as resp:
                if resp.status != 200:
                    log.warning("trace.moe status %s", resp.status)
                    return None
                payload = await resp.json()
    except Exception as exc:  # noqa: BLE001
        log.error("trace.moe xato: %s", exc)
        return None
    results = payload.get("result") or []
    if not results:
        return None
    best = results[0]
    info = best.get("anilist") or {}
    titles: List[str] = []
    if isinstance(info, dict):
        names = info.get("title") or {}
        for key in ("romaji", "english", "native"):
            if names.get(key):
                titles.append(names[key])
        for syn in info.get("synonyms") or []:
            titles.append(syn)
    elif isinstance(best.get("filename"), str):
        titles.append(re.sub(r"\.[^.]+$", "", best["filename"]))
    if not titles:
        return None
    return {"titles": titles, "similarity": float(best.get("similarity") or 0)}


# ---------------- AI (almashtirish oson) ----------------
# AI xizmatini almashtirish uchun faqat ask_ai() funksiyasini o'zgartiring.
# Hozir OpenAI-mos (chat/completions) API bilan ishlaydi:
#   AI_API_URL  (standart: https://api.openai.com/v1/chat/completions)
#   AI_MODEL    (standart: gpt-4o-mini)
AI_API_URL = os.getenv("AI_API_URL", "https://api.openai.com/v1/chat/completions")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_FREE_DAILY = int(os.getenv("AI_FREE_DAILY", "10"))
AI_SYSTEM_PROMPT = {
    "uz": ("Sen AniZone anime botining yordamchisisan. Faqat anime, manga va shu mavzudagi "
           "tavsiyalar haqida o'zbek tilida qisqa va aniq javob ber."),
    "ru": ("Ты помощник аниме-бота AniZone. Отвечай кратко и по делу только про аниме, "
           "мангу и рекомендации по этой теме, на русском языке."),
}


async def ask_ai(messages: List[Dict[str, str]]) -> Optional[str]:
    if not AI_API_KEY:
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                AI_API_URL,
                json={"model": AI_MODEL, "messages": messages, "max_tokens": 700},
                headers={"Authorization": f"Bearer {AI_API_KEY}"},
            ) as resp:
                if resp.status != 200:
                    log.warning("AI status %s: %s", resp.status, (await resp.text())[:200])
                    return None
                payload = await resp.json()
        return payload["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001
        log.error("AI xato: %s", exc)
        return None


# ======================================================================
# 5. KEYBOARDS
# ======================================================================

# ---- admin klaviatura tugma nomlari (filtrlarda ishlatiladi) ----
BTN_A_CHANNELS = "📢 Kanallarni Sozlash"
BTN_A_BROADCAST = "💬 Xabar Yuborish"
BTN_A_SETTINGS = "⚙️ Asosiy Sozlamalar"
BTN_A_ANIME = "🏠 Anime"
BTN_A_STATS = "📊 Statistika"
BTN_A_LOGS = "📋 Loglarni ko'rish"
BTN_A_UPLOAD = "✈️ Anime Yuklash"
BTN_A_EPISODE = "💎 Qism Qo'shish"
BTN_A_EDIT = "🔒 Anime Tahrirlash"
BTN_A_POST = "🕊 Post Tayyorlash"
BTN_A_AUTOPOST = "⏰ Avto Post"
BTN_A_BACK = "❌ Admin Panel"


def reply_main_kb(lang: str) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=t(lang, "btn_search")))
    kb.row(KeyboardButton(text=t(lang, "btn_guide")),
           KeyboardButton(text=t(lang, "btn_vip")),
           KeyboardButton(text=t(lang, "btn_ai")))
    kb.row(KeyboardButton(text=t(lang, "btn_settings")),
           KeyboardButton(text=t(lang, "btn_about")))
    kb.row(KeyboardButton(text=t(lang, "btn_channels")))
    return kb.as_markup(resize_keyboard=True, input_field_placeholder=t(lang, "placeholder"))


def inline_main_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=t(lang, "btn_search"), callback_data="menu:search"))
    kb.row(InlineKeyboardButton(text=t(lang, "btn_guide"), callback_data="menu:guide"),
           InlineKeyboardButton(text=t(lang, "btn_vip"), callback_data="menu:vip"),
           InlineKeyboardButton(text=t(lang, "btn_ai"), callback_data="menu:ai"))
    kb.row(InlineKeyboardButton(text=t(lang, "btn_settings"), callback_data="menu:settings"),
           InlineKeyboardButton(text=t(lang, "btn_about"), callback_data="menu:about"))
    kb.row(InlineKeyboardButton(text=t(lang, "btn_channels"), callback_data="menu:channels"))
    return kb.as_markup()


def start_inline_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=t(lang, "btn_guide_inline"), callback_data="menu:guide"))
    return kb.as_markup()


def lang_kb(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data=f"lang:{prefix}:uz"),
           InlineKeyboardButton(text="🇷🇺 Русский", callback_data=f"lang:{prefix}:ru"))
    return kb.as_markup()


def back_kb(lang: str, cb: str = "home") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=t(lang, "back_home"), callback_data=cb))
    return kb.as_markup()


def search_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=t(lang, "s_random"), callback_data="search:random"))
    kb.row(InlineKeyboardButton(text=t(lang, "s_by_name"), callback_data="search:by_name"),
           InlineKeyboardButton(text=t(lang, "s_by_code"), callback_data="search:by_code"))
    kb.row(InlineKeyboardButton(text=t(lang, "s_top"), callback_data="search:top"),
           InlineKeyboardButton(text=t(lang, "s_newest"), callback_data="search:newest"),
           InlineKeyboardButton(text=t(lang, "s_oldest"), callback_data="search:oldest"))
    kb.row(InlineKeyboardButton(text=t(lang, "s_by_genre"), callback_data="search:by_genre"),
           InlineKeyboardButton(text=t(lang, "s_by_image"), callback_data="search:by_image"))
    kb.row(InlineKeyboardButton(text=t(lang, "s_all"), callback_data="search:all"))
    kb.row(InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home"))
    return kb.as_markup()


def results_kb(lang: str, rows: List[asyncpg.Record], page: int, pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for row in rows:
        badge = "💎 " if row["is_vip"] else "🎬 "
        kb.row(InlineKeyboardButton(text=f"{badge}{row['name']}"[:60],
                                    callback_data=f"anime:{row['id']}"))
    if pages > 1:
        nav: List[InlineKeyboardButton] = []
        if page > 1:
            nav.append(InlineKeyboardButton(text=t(lang, "prev"), callback_data=f"pg:{page - 1}"))
        nav.append(InlineKeyboardButton(text=t(lang, "page_info", page=page, pages=pages),
                                        callback_data="noop"))
        if page < pages:
            nav.append(InlineKeyboardButton(text=t(lang, "next"), callback_data=f"pg:{page + 1}"))
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text=t(lang, "back_home"), callback_data="menu:search"))
    return kb.as_markup()


def genres_kb(lang: str, genres: List[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    buttons = [InlineKeyboardButton(text=g[:30], callback_data=f"genre:{i}")
               for i, g in enumerate(genres[:60])]
    for i in range(0, len(buttons), 2):
        kb.row(*buttons[i:i + 2])
    kb.row(InlineKeyboardButton(text=t(lang, "back_home"), callback_data="menu:search"))
    return kb.as_markup()


def anime_kb(lang: str, anime_id: int, has_eps: bool, locked: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if locked:
        kb.row(InlineKeyboardButton(text=t(lang, "btn_vip"), callback_data="menu:vip"))
    elif has_eps:
        kb.row(InlineKeyboardButton(text="📺 " + t(lang, "episodes_title").replace("📺 ", "")[:40],
                                    callback_data=f"eps:{anime_id}:1"))
    kb.row(InlineKeyboardButton(text=t(lang, "back_home"), callback_data="menu:search"))
    return kb.as_markup()


def episodes_kb(lang: str, anime_id: int, episodes: List[asyncpg.Record], page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    pages = max(1, (len(episodes) + EPISODES_PER_PAGE - 1) // EPISODES_PER_PAGE)
    page = min(max(page, 1), pages)
    chunk = episodes[(page - 1) * EPISODES_PER_PAGE: page * EPISODES_PER_PAGE]
    buttons = [InlineKeyboardButton(
        text=f"{'💎' if e['is_vip'] else ''}{e['number']}",
        callback_data=f"ep:{anime_id}:{e['number']}") for e in chunk]
    for i in range(0, len(buttons), 5):
        kb.row(*buttons[i:i + 5])
    if pages > 1:
        nav: List[InlineKeyboardButton] = []
        if page > 1:
            nav.append(InlineKeyboardButton(text=t(lang, "prev"), callback_data=f"eps:{anime_id}:{page - 1}"))
        nav.append(InlineKeyboardButton(text=t(lang, "page_info", page=page, pages=pages),
                                        callback_data="noop"))
        if page < pages:
            nav.append(InlineKeyboardButton(text=t(lang, "next"), callback_data=f"eps:{anime_id}:{page + 1}"))
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text=t(lang, "back_home"), callback_data=f"anime:{anime_id}"))
    return kb.as_markup()


async def vip_kb(lang: str) -> InlineKeyboardMarkup:
    """Tugmalar tartibi: 3 yil, 6 oy, 3 oy (narxlar owner paneldan o'zgaradi)."""
    kb = InlineKeyboardBuilder()
    for plan in ("3_year", "6_month", "3_month"):
        price = await db.get_price(plan)
        label = VIP_PLANS[plan][f"label_{lang}"]
        kb.row(InlineKeyboardButton(text=f"{label} — {price:,} UZS",
                                    callback_data=f"vip_buy:{plan}"))
    kb.row(InlineKeyboardButton(text=t(lang, "back_home"), callback_data="home"))
    return kb.as_markup()


def settings_kb(lang: str, user: asyncpg.Record) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    nick = user["nick"] or user["full_name"] or "—"
    mode = t(lang, "set_menu_inline") if user["menu_mode"] == "inline" else t(lang, "set_menu_reply")
    memory = t(lang, "set_memory_on") if user["ai_memory"] else t(lang, "set_memory_off")
    kb.row(InlineKeyboardButton(text=t(lang, "set_nick", nick=nick)[:60], callback_data="set:nick"))
    kb.row(InlineKeyboardButton(text=t(lang, "set_menu", mode=mode), callback_data="set:menu"))
    kb.row(InlineKeyboardButton(text=memory, callback_data="set:memory"))
    kb.row(InlineKeyboardButton(text=t(lang, "set_lang"), callback_data="set:lang"))
    kb.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="home"))
    return kb.as_markup()


def channels_kb(lang: str, url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if url:
        kb.row(InlineKeyboardButton(text=t(lang, "btn_main_channel"), url=url))
    kb.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="home"))
    return kb.as_markup()


def sub_kb(lang: str, channels: List[asyncpg.Record]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ch in channels:
        if ch["url"]:
            kb.row(InlineKeyboardButton(text=f"📢 {ch['title'] or 'Kanal'}"[:50], url=ch["url"]))
    kb.row(InlineKeyboardButton(text=t(lang, "sub_check"), callback_data="sub:check"))
    return kb.as_markup()


def ai_back_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=t(lang, "back"), callback_data="home"))
    return kb.as_markup()


def admin_panel_kb(owner: bool) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    if owner:
        kb.row(KeyboardButton(text=BTN_A_CHANNELS))
        kb.row(KeyboardButton(text=BTN_A_BROADCAST), KeyboardButton(text=BTN_A_SETTINGS))
        kb.row(KeyboardButton(text=BTN_A_ANIME))
        kb.row(KeyboardButton(text=BTN_A_STATS), KeyboardButton(text=BTN_A_LOGS))
    else:
        kb.row(KeyboardButton(text=BTN_A_BROADCAST))
        kb.row(KeyboardButton(text=BTN_A_ANIME))
    return kb.as_markup(resize_keyboard=True)


def admin_anime_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=BTN_A_UPLOAD), KeyboardButton(text=BTN_A_EPISODE))
    kb.row(KeyboardButton(text=BTN_A_EDIT), KeyboardButton(text=BTN_A_POST))
    kb.row(KeyboardButton(text=BTN_A_AUTOPOST))
    kb.row(KeyboardButton(text=BTN_A_BACK))
    return kb.as_markup(resize_keyboard=True)


def anime_card_text(lang: str, anime: asyncpg.Record, ep_count: int) -> str:
    text = t(lang, "anime_card",
             name=esc(anime["name"]), year=esc(anime["year"] or "—"),
             genre=esc(anime["genre"] or "—"), studio=esc(anime["studio"] or "—"),
             id=anime["id"], count=ep_count, views=anime["views"])
    if anime["is_vip"]:
        text = f"{t(lang, 'vip_badge')}\n\n{text}"
    return text


# ======================================================================
# 6. FSM HOLATLAR
# ======================================================================

class SearchSt(StatesGroup):
    by_name = State()
    by_code = State()
    by_image = State()


class AiSt(StatesGroup):
    chatting = State()


class SettingsSt(StatesGroup):
    nick = State()


class VipSt(StatesGroup):
    waiting_check = State()


class UploadSt(StatesGroup):
    id_manual = State()
    name = State()
    year = State()
    genre = State()
    studio = State()
    photo = State()


class EpisodeSt(StatesGroup):
    anime_id = State()
    number = State()
    video = State()


class EditSt(StatesGroup):
    anime_id = State()
    field_value = State()
    del_episode = State()


class PostSt(StatesGroup):
    query = State()


class BroadcastSt(StatesGroup):
    content = State()
    confirm = State()


class ChannelSt(StatesGroup):
    add = State()
    main_url = State()


class OwnerSt(StatesGroup):
    edit_setting = State()
    vip_give_user = State()
    vip_give_days = State()
    vip_revoke_user = State()
    admin_add = State()
    admin_remove = State()
    ban_user = State()
    unban_user = State()


# ======================================================================
# 7. MIDDLEWARE: foydalanuvchi, ban, spam, til, majburiy obuna
# ======================================================================

class GateMiddleware(BaseMiddleware):
    """Har bir xabar va callback uchun: foydalanuvchini yozish, ban, spam,
    til tanlash va majburiy obunani tekshirish."""

    async def __call__(self, handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
                       event: Any, data: Dict[str, Any]) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        # Faqat shaxsiy chat
        chat = event.chat if isinstance(event, Message) else (
            event.message.chat if isinstance(event, CallbackQuery) and event.message else None)
        if chat is not None and chat.type != "private":
            return None

        bot: Bot = data["bot"]
        uid = tg_user.id
        owner_or_admin = await is_admin(uid)

        # Spam (admin va owner uchun o'chirilgan)
        if not owner_or_admin:
            verdict = rate_limiter.check(uid)
            if verdict != "ok":
                user_row = await db.get_user(uid)
                lang = (user_row["lang"] if user_row else None) or "uz"
                if verdict == "just_muted":
                    await self._notify(event, t(lang, "spam"))
                    await db.add_log(uid, "spam_mute", f"user={uid}")
                elif isinstance(event, CallbackQuery):
                    await answer_cb(event)
                return None

        try:
            await db.upsert_user(uid, tg_user.username, tg_user.full_name)
            user = await db.get_user(uid)
        except Exception as exc:  # noqa: BLE001
            log.error("Middleware baza xatosi: %s", exc)
            return None
        if user is None:
            return None

        lang = user["lang"] or "uz"
        data["user"] = user
        data["lang"] = lang

        # Ban
        if user["is_banned"] and not is_owner(uid):
            await self._notify(event, t(lang, "banned"))
            return None

        # Til tanlanmagan bo'lsa
        if not user["lang"]:
            if isinstance(event, CallbackQuery) and (event.data or "").startswith("lang:"):
                return await handler(event, data)
            await self._notify(event, t("uz", "choose_lang"), lang_kb("set"))
            return None

        # Majburiy obuna (VIP, admin va owner ozod)
        if not owner_or_admin and not vip_active(user):
            cb_data = (event.data or "") if isinstance(event, CallbackQuery) else ""
            if not (cb_data.startswith("sub:") or cb_data.startswith("lang:")):
                missing = await missing_subscriptions(bot, uid)
                if missing:
                    await self._notify(event, t(lang, "sub_required"), sub_kb(lang, missing))
                    return None

        return await handler(event, data)

    @staticmethod
    async def _notify(event: Any, text: str, markup: Any = None) -> None:
        try:
            if isinstance(event, Message):
                await event.answer(text, reply_markup=markup)
            elif isinstance(event, CallbackQuery):
                if markup is None:
                    await event.answer(text, show_alert=True)
                elif event.message:
                    await event.message.answer(text, reply_markup=markup)
                    await event.answer()
        except Exception as exc:  # noqa: BLE001
            log.warning("Middleware notify xato: %s", exc)


# ======================================================================
# 8. FOYDALANUVCHI HANDLERLARI
# ======================================================================

user_router = Router(name="user")
user_router.message.filter(F.chat.type == "private")

LIST_MODES = {"name", "genre", "top", "newest", "oldest", "all"}


async def get_lang(user_id: int) -> str:
    row = await db.get_user(user_id)
    return (row["lang"] if row and row["lang"] else "uz")


async def show_main_menu(event: Any, user: asyncpg.Record, lang: str, text: Optional[str] = None) -> None:
    """Foydalanuvchining menyu turiga qarab asosiy menyuni ko'rsatadi."""
    text = text or t(lang, "main_menu")
    if user["menu_mode"] == "inline":
        await smart_send(event, text, inline_main_kb(lang))
    else:
        msg = event.message if isinstance(event, CallbackQuery) else event
        if isinstance(event, CallbackQuery):
            await safe_delete(event.message)  # type: ignore[arg-type]
        await msg.answer(text, reply_markup=reply_main_kb(lang))


async def send_welcome(message: Message, user: asyncpg.Record, lang: str) -> None:
    name = esc(user["nick"] or message.chat.full_name or "")
    await message.answer(t(lang, "welcome", name=name), reply_markup=(
        reply_main_kb(lang) if user["menu_mode"] != "inline" else ReplyKeyboardRemove()))
    await message.answer(f"{t(lang, 'welcome_italic')}\n\n{t(lang, 'welcome_start')}",
                         reply_markup=start_inline_kb(lang))
    if user["menu_mode"] == "inline":
        await message.answer(t(lang, "main_menu"), reply_markup=inline_main_kb(lang))


# ---------------- /start, til ----------------
@user_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await state.clear()
    await send_welcome(message, user, lang)


@user_router.callback_query(F.data.startswith("lang:"))
async def cb_language(cb: CallbackQuery, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    if len(parts) != 3 or parts[2] not in LANGS:
        await answer_cb(cb)
        return
    mode, new_lang = parts[1], parts[2]
    await db.set_lang(cb.from_user.id, new_lang)
    user = await db.get_user(cb.from_user.id)
    await answer_cb(cb, t(new_lang, "lang_changed"))
    if user is None or cb.message is None:
        return
    if mode == "set":
        await safe_delete(cb.message)  # type: ignore[arg-type]
        await state.clear()
        await send_welcome(cb.message, user, new_lang)  # type: ignore[arg-type]
    else:
        await smart_send(cb, f"{t(new_lang, 'settings_title')}", settings_kb(new_lang, user))
        if user["menu_mode"] != "inline":
            await cb.message.answer(t(new_lang, "main_menu"), reply_markup=reply_main_kb(new_lang))


@user_router.callback_query(F.data == "sub:check")
async def cb_sub_check(cb: CallbackQuery, user: asyncpg.Record, lang: str) -> None:
    drop_sub_cache(cb.from_user.id)
    missing = await missing_subscriptions(cb.bot, cb.from_user.id, use_cache=False)  # type: ignore[arg-type]
    if missing:
        await answer_cb(cb, t(lang, "sub_not_yet"), alert=True)
        return
    await answer_cb(cb, t(lang, "sub_ok"))
    await safe_delete(cb.message)  # type: ignore[arg-type]
    if cb.message:
        await send_welcome(cb.message, user, lang)  # type: ignore[arg-type]


@user_router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await answer_cb(cb)


@user_router.callback_query(F.data == "home")
async def cb_home(cb: CallbackQuery, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await state.clear()
    await answer_cb(cb)
    await show_main_menu(cb, user, lang)


# ---------------- asosiy menyu (pastki tugmalar + inline) ----------------
async def open_section(event: Any, state: FSMContext, user: asyncpg.Record, lang: str, section: str) -> None:
    await state.clear()
    if isinstance(event, CallbackQuery):
        await answer_cb(event)
    if section == "search":
        await smart_send(event, t(lang, "search_title"), search_kb(lang))
    elif section == "guide":
        await show_guide(event, lang)
    elif section == "vip":
        await show_vip(event, user, lang)
    elif section == "ai":
        await start_ai(event, state, lang)
    elif section == "settings":
        await smart_send(event, t(lang, "settings_title"), settings_kb(lang, user))
    elif section == "about":
        dev = await db.get_setting(f"developer_info_{lang}")
        await smart_send(event, f"{t(lang, 'about')}\n\n{esc(dev)}", back_kb(lang))
    elif section == "channels":
        url = await db.get_setting("main_channel_url")
        text = t(lang, "channels_title") if url else t(lang, "no_channels")
        if isinstance(event, CallbackQuery):
            await smart_send(event, text, channels_kb(lang, url))
        else:
            await event.answer(text, reply_markup=channels_kb(lang, url))


@user_router.callback_query(F.data.startswith("menu:"))
async def cb_menu(cb: CallbackQuery, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    section = (cb.data or "").split(":", 1)[1]
    await open_section(cb, state, user, lang, section)


def _menu_filter(key: str) -> Any:
    return F.text.in_(all_langs_text(key))


@user_router.message(_menu_filter("btn_search"))
async def msg_search(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await open_section(message, state, user, lang, "search")


@user_router.message(_menu_filter("btn_guide"))
async def msg_guide(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await open_section(message, state, user, lang, "guide")


@user_router.message(_menu_filter("btn_vip"))
async def msg_vip(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await open_section(message, state, user, lang, "vip")


@user_router.message(_menu_filter("btn_ai"))
async def msg_ai(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await open_section(message, state, user, lang, "ai")


@user_router.message(_menu_filter("btn_settings"))
async def msg_settings(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await open_section(message, state, user, lang, "settings")


@user_router.message(_menu_filter("btn_about"))
async def msg_about(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await open_section(message, state, user, lang, "about")


@user_router.message(_menu_filter("btn_channels"))
async def msg_channels(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await open_section(message, state, user, lang, "channels")


# ---------------- qo'llanma ----------------
async def show_guide(event: Any, lang: str) -> None:
    text = "\n".join([
        t(lang, "guide_title"), "",
        t(lang, "guide_intro"), "",
        t(lang, "guide_tugmalar"),
        "• " + t(lang, "guide_search"),
        "• " + t(lang, "guide_guide"),
        "• " + t(lang, "guide_vip"),
        "• " + t(lang, "guide_ai"),
        "• " + t(lang, "guide_settings"),
        "• " + t(lang, "guide_about"),
        "• " + t(lang, "guide_channels"),
    ])
    chunks = split_text(text)
    target = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await safe_delete(event.message)  # type: ignore[arg-type]
    for i, chunk in enumerate(chunks):
        markup = back_kb(lang) if i == len(chunks) - 1 else None
        await target.answer(chunk, reply_markup=markup)


# ---------------- qidiruv ----------------
@user_router.callback_query(F.data.startswith("search:"))
async def cb_search(cb: CallbackQuery, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    kind = (cb.data or "").split(":", 1)[1]
    await answer_cb(cb)
    await state.clear()
    if kind == "random":
        anime = await db.random_anime()
        if not anime:
            await smart_send(cb, t(lang, "not_found"), back_kb(lang, "menu:search"))
            return
        await show_anime(cb, anime, user, lang)
    elif kind == "by_name":
        await state.set_state(SearchSt.by_name)
        await smart_send(cb, t(lang, "ask_name"), back_kb(lang, "menu:search"))
    elif kind == "by_code":
        await state.set_state(SearchSt.by_code)
        await smart_send(cb, t(lang, "ask_code"), back_kb(lang, "menu:search"))
    elif kind == "by_image":
        await state.set_state(SearchSt.by_image)
        await smart_send(cb, t(lang, "ask_image"), back_kb(lang, "menu:search"))
    elif kind == "by_genre":
        genres = await db.all_genres()
        if not genres:
            await smart_send(cb, t(lang, "no_genres"), back_kb(lang, "menu:search"))
            return
        await state.update_data(genres=genres)
        await smart_send(cb, t(lang, "choose_genre"), genres_kb(lang, genres))
    elif kind in ("top", "newest", "oldest", "all"):
        await state.update_data(list_mode=kind, list_q="")
        await render_list(cb, state, lang, 1)


async def render_list(event: Any, state: FSMContext, lang: str, page: int) -> None:
    data = await state.get_data()
    mode = data.get("list_mode")
    q = data.get("list_q", "")
    if mode not in LIST_MODES:
        await smart_send(event, t(lang, "not_found"), back_kb(lang, "menu:search"))
        return
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    if mode == "name":
        rows, total = await db.search_by_name(q, PAGE_SIZE, offset)
        title = t(lang, "title_name", q=esc(q))
    elif mode == "genre":
        rows, total = await db.search_by_genre(q, PAGE_SIZE, offset)
        title = t(lang, "title_genre", q=esc(q))
    else:
        rows, total = await db.list_animes(mode, PAGE_SIZE, offset)
        title = t(lang, f"title_{mode}")
    if total == 0:
        await smart_send(event, t(lang, "not_found"), back_kb(lang, "menu:search"))
        return
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        page = pages
        rows, _ = (await db.search_by_name(q, PAGE_SIZE, (page - 1) * PAGE_SIZE) if mode == "name"
                   else await db.search_by_genre(q, PAGE_SIZE, (page - 1) * PAGE_SIZE) if mode == "genre"
                   else await db.list_animes(mode, PAGE_SIZE, (page - 1) * PAGE_SIZE))
    text = t(lang, "results_title", title=title, total=total)
    await smart_send(event, text, results_kb(lang, rows, page, pages))


@user_router.callback_query(F.data.startswith("pg:"))
async def cb_page(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await answer_cb(cb)
    try:
        page = int((cb.data or "").split(":", 1)[1])
    except ValueError:
        return
    await render_list(cb, state, lang, page)


@user_router.callback_query(F.data.startswith("genre:"))
async def cb_genre(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await answer_cb(cb)
    data = await state.get_data()
    genres: List[str] = data.get("genres") or await db.all_genres()
    try:
        idx = int((cb.data or "").split(":", 1)[1])
        genre = genres[idx]
    except (ValueError, IndexError):
        await smart_send(cb, t(lang, "not_found"), back_kb(lang, "menu:search"))
        return
    await state.update_data(list_mode="genre", list_q=genre, genres=genres)
    await render_list(cb, state, lang, 1)


@user_router.message(SearchSt.by_name, F.text)
async def msg_search_name(message: Message, state: FSMContext, lang: str) -> None:
    q = clean_text(message.text or "", 80)
    if len(q) < 1:
        await message.answer(t(lang, "ask_name"))
        return
    await state.set_state(None)
    await state.update_data(list_mode="name", list_q=q)
    await render_list(message, state, lang, 1)


@user_router.message(SearchSt.by_code, F.text)
async def msg_search_code(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or len(raw) > 12:
        await message.answer(t(lang, "bad_code"))
        return
    anime = await db.get_anime(int(raw))
    if not anime:
        await message.answer(t(lang, "not_found"), reply_markup=back_kb(lang, "menu:search"))
        return
    await state.clear()
    await show_anime(message, anime, user, lang)


@user_router.message(SearchSt.by_image, F.photo)
async def msg_search_image(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    status = await message.answer(t(lang, "image_searching"))
    try:
        buf = await message.bot.download(message.photo[-1])  # type: ignore[union-attr]
        image_bytes = buf.read() if buf else b""
    except Exception as exc:  # noqa: BLE001
        log.error("Rasm yuklab olishda xato: %s", exc)
        image_bytes = b""
    result = await trace_moe_lookup(image_bytes) if image_bytes else None
    await safe_delete(status)
    if not result:
        await message.answer(t(lang, "image_fail"), reply_markup=back_kb(lang, "menu:search"))
        return
    sim = round(result["similarity"] * 100, 1)
    anime = await db.find_anime_by_title_fuzzy(result["titles"])
    await state.clear()
    if anime:
        await message.answer(t(lang, "image_found_db", title=esc(anime["name"]), sim=sim))
        await show_anime(message, anime, user, lang)
    else:
        await message.answer(
            t(lang, "image_found_nodb", title=esc(result["titles"][0]), sim=sim),
            reply_markup=back_kb(lang, "menu:search"))


@user_router.message(SearchSt.by_image)
async def msg_search_image_wrong(message: Message, lang: str) -> None:
    await message.answer(t(lang, "image_not_anime"))


# ---------------- anime kartasi, qismlar ----------------
async def show_anime(event: Any, anime: asyncpg.Record, user: asyncpg.Record, lang: str) -> None:
    await db.inc_views(anime["id"])
    count = await db.count_episodes(anime["id"])
    locked = bool(anime["is_vip"]) and not vip_active(user) and not await is_admin(user["user_id"])
    text = anime_card_text(lang, anime, count)
    if locked:
        text += "\n\n" + t(lang, "vip_only_anime")
    markup = anime_kb(lang, anime["id"], count > 0, locked)
    chat_id = user["user_id"]
    bot: Bot = event.bot
    if isinstance(event, CallbackQuery):
        await safe_delete(event.message)  # type: ignore[arg-type]
    if anime["photo_id"]:
        try:
            await bot.send_photo(chat_id, anime["photo_id"], caption=text,
                                 reply_markup=markup, protect_content=True)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("Anime rasmini yuborib bo'lmadi: %s", exc)
    await bot.send_message(chat_id, text, reply_markup=markup, protect_content=True)


@user_router.callback_query(F.data.startswith("anime:"))
async def cb_anime(cb: CallbackQuery, user: asyncpg.Record, lang: str) -> None:
    await answer_cb(cb)
    try:
        anime_id = int((cb.data or "").split(":", 1)[1])
    except ValueError:
        return
    anime = await db.get_anime(anime_id)
    if not anime:
        await smart_send(cb, t(lang, "not_found"), back_kb(lang, "menu:search"))
        return
    await show_anime(cb, anime, user, lang)


@user_router.callback_query(F.data.startswith("eps:"))
async def cb_episodes(cb: CallbackQuery, user: asyncpg.Record, lang: str) -> None:
    await answer_cb(cb)
    try:
        _, anime_id_s, page_s = (cb.data or "").split(":")
        anime_id, page = int(anime_id_s), int(page_s)
    except ValueError:
        return
    anime = await db.get_anime(anime_id)
    if not anime:
        await smart_send(cb, t(lang, "not_found"), back_kb(lang, "menu:search"))
        return
    if anime["is_vip"] and not vip_active(user) and not await is_admin(user["user_id"]):
        await answer_cb(cb, t(lang, "vip_only_anime"), alert=True)
        return
    episodes = await db.list_episodes(anime_id)
    if not episodes:
        await answer_cb(cb, t(lang, "no_episodes"), alert=True)
        return
    text = f"🎬 <b>{esc(anime['name'])}</b>\n{t(lang, 'episodes_title')}"
    await smart_send(cb, text, episodes_kb(lang, anime_id, episodes, page))


@user_router.callback_query(F.data.startswith("ep:"))
async def cb_episode(cb: CallbackQuery, user: asyncpg.Record, lang: str) -> None:
    try:
        _, anime_id_s, num_s = (cb.data or "").split(":")
        anime_id, number = int(anime_id_s), int(num_s)
    except ValueError:
        await answer_cb(cb)
        return
    anime = await db.get_anime(anime_id)
    episode = await db.get_episode(anime_id, number)
    if not anime or not episode:
        await answer_cb(cb, t(lang, "episode_missing"), alert=True)
        return
    privileged = vip_active(user) or await is_admin(user["user_id"])
    if (anime["is_vip"] or episode["is_vip"]) and not privileged:
        await answer_cb(cb, t(lang, "vip_only_episode"), alert=True)
        return
    await answer_cb(cb)
    caption = t(lang, "episode_caption", name=esc(anime["name"]), num=number)
    ok = await send_media_safe(cb.bot, user["user_id"], episode["file_id"], caption, protect=True)  # type: ignore[arg-type]
    if not ok:
        await cb.message.answer(t(lang, "error"))  # type: ignore[union-attr]


# ---------------- VIP ----------------
async def show_vip(event: Any, user: asyncpg.Record, lang: str) -> None:
    active = vip_active(user)
    lines = [t(lang, "vip_active") if active else t(lang, "vip_inactive")]
    if active:
        lines.append(t(lang, "vip_until", date=fmt_date(user["vip_until"])))
    lines += ["", t(lang, "vip_what"), "", t(lang, "vip_thanks"), "",
              t(lang, "vip_links", privacy=await db.get_setting("privacy_url"),
                offer=await db.get_setting("offer_url"))]
    markup = await vip_kb(lang)
    text = "\n".join(lines)
    if isinstance(event, CallbackQuery):
        await smart_send(event, text, markup)
    else:
        await event.answer(text, reply_markup=markup, disable_web_page_preview=True)


@user_router.callback_query(F.data.startswith("vip_buy:"))
async def cb_vip_buy(cb: CallbackQuery, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    await answer_cb(cb)
    plan = (cb.data or "").split(":", 1)[1]
    if plan not in VIP_PLANS:
        return
    if await db.has_pending_request(user["user_id"]):
        await smart_send(cb, t(lang, "vip_pending"), back_kb(lang, "menu:vip"))
        return
    price = await db.get_price(plan)
    card = esc(await db.get_setting("card_info"))
    await state.set_state(VipSt.waiting_check)
    await state.update_data(plan=plan, price=price)
    text = (t(lang, "vip_pay", plan=VIP_PLANS[plan][f"label_{lang}"], price=f"{price:,}", card=card)
            + "\n\n" + t(lang, "vip_send_check"))
    await smart_send(cb, text, back_kb(lang, "menu:vip"))


@user_router.message(VipSt.waiting_check, F.photo)
async def msg_vip_check(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    data = await state.get_data()
    plan, price = data.get("plan"), data.get("price")
    if plan not in VIP_PLANS or not price:
        await state.clear()
        await message.answer(t(lang, "error"))
        return
    file_id = message.photo[-1].file_id  # type: ignore[index]
    req_id = await db.create_vip_request(user["user_id"], plan, int(price), file_id)
    await state.clear()
    caption = (f"💳 <b>Yangi VIP to'lov</b> #{req_id}\n\n"
               f"👤 {user_link(user['user_id'], user['username'], user['full_name'] or '')}\n"
               f"📦 Tarif: <b>{VIP_PLANS[plan]['label_uz']}</b>\n"
               f"💰 Narx: <b>{int(price):,} UZS</b>")
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"vipok:{req_id}"),
           InlineKeyboardButton(text="❌ Rad etish", callback_data=f"vipno:{req_id}"))
    try:
        await message.bot.send_photo(OWNER_ID, file_id, caption=caption,  # type: ignore[union-attr]
                                     reply_markup=kb.as_markup())
    except Exception as exc:  # noqa: BLE001
        log.error("Chekni owner'ga yuborib bo'lmadi: %s", exc)
    await db.add_log(user["user_id"], "vip_request", f"req={req_id} plan={plan}")
    await message.answer(t(lang, "vip_check_sent"))


@user_router.message(VipSt.waiting_check)
async def msg_vip_check_wrong(message: Message, lang: str) -> None:
    await message.answer(t(lang, "vip_check_wrong"))


# ---------------- AI ----------------
async def start_ai(event: Any, state: FSMContext, lang: str) -> None:
    await state.set_state(AiSt.chatting)
    if isinstance(event, CallbackQuery):
        await smart_send(event, t(lang, "ai_title"), ai_back_kb(lang))
    else:
        await event.answer(t(lang, "ai_title"), reply_markup=ai_back_kb(lang))


@user_router.message(AiSt.chatting, F.text)
async def msg_ai_chat(message: Message, user: asyncpg.Record, lang: str) -> None:
    question = clean_text(message.text or "", 1000)
    if not question:
        return
    uid = user["user_id"]
    privileged = vip_active(user) or await is_admin(uid)
    if not privileged and await db.ai_usage_today(uid) >= AI_FREE_DAILY:
        await message.answer(t(lang, "ai_limit", limit=AI_FREE_DAILY))
        return
    status = await message.answer(t(lang, "ai_thinking"))
    msgs: List[Dict[str, str]] = [{"role": "system", "content": AI_SYSTEM_PROMPT.get(lang, AI_SYSTEM_PROMPT["uz"])}]
    if user["ai_memory"]:
        msgs += await db.ai_history(uid, 10)
    msgs.append({"role": "user", "content": question})
    answer = await ask_ai(msgs)
    await safe_delete(status)
    if not answer:
        await message.answer(t(lang, "ai_unavailable"))
        return
    await db.ai_usage_inc(uid)
    if user["ai_memory"]:
        await db.ai_remember(uid, "user", question)
        await db.ai_remember(uid, "assistant", answer)
    for chunk in split_text(esc(answer)):
        await message.answer(chunk, reply_markup=ai_back_kb(lang))


# ---------------- sozlamalar ----------------
@user_router.callback_query(F.data.startswith("set:"))
async def cb_settings(cb: CallbackQuery, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    action = (cb.data or "").split(":", 1)[1]
    await answer_cb(cb)
    uid = user["user_id"]
    if action == "nick":
        await state.set_state(SettingsSt.nick)
        await smart_send(cb, t(lang, "ask_nick"), back_kb(lang, "menu:settings"))
    elif action == "lang":
        await smart_send(cb, t(lang, "choose_lang"), lang_kb("chg"))
    elif action == "memory":
        await db.set_ai_memory(uid, not user["ai_memory"])
        fresh = await db.get_user(uid)
        await smart_send(cb, t(lang, "settings_title"), settings_kb(lang, fresh))  # type: ignore[arg-type]
    elif action == "menu":
        new_mode = "reply" if user["menu_mode"] == "inline" else "inline"
        await db.set_menu_mode(uid, new_mode)
        fresh = await db.get_user(uid)
        await smart_send(cb, t(lang, "settings_title"), settings_kb(lang, fresh))  # type: ignore[arg-type]
        if cb.message:
            if new_mode == "inline":
                await cb.message.answer(t(lang, "menu_switched_inline"), reply_markup=ReplyKeyboardRemove())
                await cb.message.answer(t(lang, "main_menu"), reply_markup=inline_main_kb(lang))
            else:
                await cb.message.answer(t(lang, "menu_switched_reply"), reply_markup=reply_main_kb(lang))


@user_router.message(SettingsSt.nick, F.text)
async def msg_nick(message: Message, state: FSMContext, user: asyncpg.Record, lang: str) -> None:
    nick = clean_text(message.text or "", 24)
    if len(nick) < 2:
        await message.answer(t(lang, "bad_nick"))
        return
    await db.set_nick(user["user_id"], nick)
    await state.clear()
    fresh = await db.get_user(user["user_id"])
    await message.answer(t(lang, "nick_saved", nick=esc(nick)))
    await message.answer(t(lang, "settings_title"), reply_markup=settings_kb(lang, fresh))  # type: ignore[arg-type]


# ======================================================================
# 9. ADMIN PANELI (/admin) — Anime va Xabar Yuborish
# ======================================================================

from aiogram.filters import BaseFilter  # noqa: E402
from aiogram.types import ErrorEvent  # noqa: E402


class IsAdminFilter(BaseFilter):
    """Admin/owner huquqi HAR SO'ROVDA bazadan tekshiriladi."""
    async def __call__(self, event: Any) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and await is_admin(user.id)


class IsOwnerFilter(BaseFilter):
    async def __call__(self, event: Any) -> bool:
        user = getattr(event, "from_user", None)
        return bool(user) and is_owner(user.id)


admin_router = Router(name="admin")
admin_router.message.filter(F.chat.type == "private", IsAdminFilter())
admin_router.callback_query.filter(IsAdminFilter())

_episode_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_broadcast_running = False


def type_kb(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💎 VIP", callback_data=f"{prefix}:vip"),
           InlineKeyboardButton(text="🆓 Oddiy", callback_data=f"{prefix}:normal"))
    return kb.as_markup()


def mode_kb(prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✍️ O'zim kiritaman", callback_data=f"{prefix}:manual"),
           InlineKeyboardButton(text="🔢 Ketma-ket", callback_data=f"{prefix}:auto"))
    return kb.as_markup()


async def show_admin_panel(message: Message, state: FSMContext, text: str = "🚀 Admin panelga xush kelibsiz!") -> None:
    await state.clear()
    await message.answer(text, reply_markup=admin_panel_kb(is_owner(message.from_user.id)))  # type: ignore[union-attr]


# ---- umumiy: /admin, /cancel, panel tugmalari (state handlerlardan OLDIN) ----
@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await show_admin_panel(message, state)


@admin_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await show_admin_panel(message, state, "Bekor qilindi.")


@admin_router.message(F.text == BTN_A_BACK)
async def btn_admin_back(message: Message, state: FSMContext) -> None:
    await show_admin_panel(message, state)


@admin_router.message(F.text == BTN_A_ANIME)
async def btn_anime_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🏠 Anime bo'limi", reply_markup=admin_anime_kb())


# ---------------- Anime Yuklash ----------------
@admin_router.message(F.text == BTN_A_UPLOAD)
async def btn_upload(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Anime turini tanlang:\n(Bekor qilish: /cancel)", reply_markup=type_kb("au_type"))


@admin_router.callback_query(F.data.startswith("au_type:"))
async def cb_upload_type(cb: CallbackQuery, state: FSMContext) -> None:
    await answer_cb(cb)
    is_vip = (cb.data or "").endswith(":vip")
    await state.clear()
    await state.update_data(is_vip=is_vip)
    await smart_send(cb, "ID turini tanlang:", mode_kb("au_id"))


@admin_router.callback_query(F.data.startswith("au_id:"))
async def cb_upload_idmode(cb: CallbackQuery, state: FSMContext) -> None:
    await answer_cb(cb)
    mode = (cb.data or "").split(":", 1)[1]
    await state.update_data(id_mode=mode)
    if mode == "manual":
        await state.set_state(UploadSt.id_manual)
        await smart_send(cb, "Anime ID sini yozing (faqat raqam, takrorlanmasin):")
    else:
        await state.set_state(UploadSt.name)
        await smart_send(cb, "ID avtomatik (ketma-ket) beriladi.\n\n📋 Anime nomini yozing:")


@admin_router.message(UploadSt.id_manual, F.text)
async def msg_upload_id(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0 or len(raw) > 12:
        await message.answer("❗ ID faqat musbat raqam bo'lishi kerak. Qayta yozing:")
        return
    if await db.anime_exists(int(raw)):
        await message.answer("❗ Bu ID band. Boshqa ID yozing:")
        return
    await state.update_data(anime_id=int(raw))
    await state.set_state(UploadSt.name)
    await message.answer("📋 Anime nomini yozing:")


@admin_router.message(UploadSt.name, F.text)
async def msg_upload_name(message: Message, state: FSMContext) -> None:
    name = clean_text(message.text or "", 120)
    if not name:
        await message.answer("❗ Nom bo'sh bo'lmasin:")
        return
    await state.update_data(name=name)
    await state.set_state(UploadSt.year)
    await message.answer("📅 Yilini yozing:")


@admin_router.message(UploadSt.year, F.text)
async def msg_upload_year(message: Message, state: FSMContext) -> None:
    await state.update_data(year=clean_text(message.text or "", 20))
    await state.set_state(UploadSt.genre)
    await message.answer("🔖 Janrini yozing (bir nechta bo'lsa vergul bilan: Action, Drama):")


@admin_router.message(UploadSt.genre, F.text)
async def msg_upload_genre(message: Message, state: FSMContext) -> None:
    await state.update_data(genre=clean_text(message.text or "", 120))
    await state.set_state(UploadSt.studio)
    await message.answer("🎙 Dublyaj studiyasini yozing:")


@admin_router.message(UploadSt.studio, F.text)
async def msg_upload_studio(message: Message, state: FSMContext) -> None:
    await state.update_data(studio=clean_text(message.text or "", 120))
    await state.set_state(UploadSt.photo)
    await message.answer("🖼 Anime rasmini yuboring:")


@admin_router.message(UploadSt.photo, F.photo)
async def msg_upload_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photo_id = message.photo[-1].file_id  # type: ignore[index]
    try:
        anime_id = data.get("anime_id") if data.get("id_mode") == "manual" else await db.next_anime_id()
        if await db.anime_exists(anime_id):
            await message.answer("❗ Bu ID band bo'lib qoldi. Jarayonni qayta boshlang.")
            await state.clear()
            return
        await db.add_anime(anime_id, data["name"], data.get("year", ""), data.get("genre", ""),
                           data.get("studio", ""), photo_id, bool(data.get("is_vip")))
    except asyncpg.UniqueViolationError:
        await message.answer("❗ ID band. Jarayonni qayta boshlang.")
        await state.clear()
        return
    await state.clear()
    await db.add_log(message.from_user.id, "anime_add", f"id={anime_id} name={data['name']}")  # type: ignore[union-attr]
    await message.answer(
        f"✅ Anime qo'shildi!\n\n🆔 Kod: <code>{anime_id}</code>\n🎬 {esc(data['name'])}\n"
        f"{'💎 VIP' if data.get('is_vip') else '🆓 Oddiy'}",
        reply_markup=admin_anime_kb())


@admin_router.message(UploadSt.photo)
async def msg_upload_photo_wrong(message: Message) -> None:
    await message.answer("❗ Iltimos, rasm yuboring.")


# ---------------- Qism Qo'shish ----------------
def done_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ Tugatish", callback_data="ea_done"))
    return kb.as_markup()


@admin_router.message(F.text == BTN_A_EPISODE)
async def btn_episode(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Qism turini tanlang:\n(Bekor qilish: /cancel)", reply_markup=type_kb("ea_type"))


@admin_router.callback_query(F.data.startswith("ea_type:"))
async def cb_episode_type(cb: CallbackQuery, state: FSMContext) -> None:
    await answer_cb(cb)
    await state.clear()
    await state.update_data(is_vip=(cb.data or "").endswith(":vip"))
    await state.set_state(EpisodeSt.anime_id)
    await smart_send(cb, "Qaysi animega qism qo'shamiz? Anime kodini (ID) yozing:")


@admin_router.message(EpisodeSt.anime_id, F.text)
async def msg_episode_anime(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    anime = await db.get_anime(int(raw)) if raw.isdigit() and len(raw) <= 12 else None
    if not anime:
        await message.answer("❗ Bunday anime topilmadi. Kodni qayta yozing:")
        return
    await state.update_data(anime_id=anime["id"], anime_name=anime["name"])
    await state.set_state(None)
    await message.answer(f"🎬 <b>{esc(anime['name'])}</b>\nRaqam turini tanlang:", reply_markup=mode_kb("ea_num"))


@admin_router.callback_query(F.data.startswith("ea_num:"))
async def cb_episode_mode(cb: CallbackQuery, state: FSMContext) -> None:
    await answer_cb(cb)
    data = await state.get_data()
    if not data.get("anime_id"):
        await smart_send(cb, "Jarayon topilmadi. Qaytadan boshlang.")
        return
    mode = (cb.data or "").split(":", 1)[1]
    await state.update_data(num_mode=mode)
    if mode == "manual":
        await state.set_state(EpisodeSt.number)
        await smart_send(cb, "Qism raqamini yozing (masalan 37):")
    else:
        nxt = await db.next_episode_number(data["anime_id"])
        await state.set_state(EpisodeSt.video)
        await smart_send(cb, f"Videolarni birin-ketin yuboring. Keyingi qism: <b>{nxt}</b>.\n"
                             "Tugatish uchun tugmani bosing yoki /done yozing.", done_kb())


@admin_router.message(EpisodeSt.number, F.text)
async def msg_episode_number(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (0 < int(raw) < 100000):
        await message.answer("❗ Qism raqami musbat son bo'lishi kerak:")
        return
    data = await state.get_data()
    if await db.episode_exists(data["anime_id"], int(raw)):
        await message.answer(f"❗ {raw}-qism allaqachon bor. Boshqa raqam yozing:")
        return
    await state.update_data(number=int(raw))
    await state.set_state(EpisodeSt.video)
    await message.answer(f"🎞 {raw}-qism videosini yuboring:", reply_markup=done_kb())


@admin_router.message(EpisodeSt.video, F.video | F.document)
async def msg_episode_video(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    file_id = message.video.file_id if message.video else message.document.file_id  # type: ignore[union-attr]
    anime_id = data["anime_id"]
    uid = message.from_user.id  # type: ignore[union-attr]
    async with _episode_locks[uid]:
        try:
            if data.get("num_mode") == "auto":
                number = await db.next_episode_number(anime_id)
            else:
                number = int(data["number"])
                if await db.episode_exists(anime_id, number):
                    await message.answer(f"❗ {number}-qism allaqachon bor.")
                    return
            await db.add_episode(anime_id, number, file_id, data.get("anime_name", ""), bool(data.get("is_vip")))
        except asyncpg.UniqueViolationError:
            await message.answer("❗ Bu raqam band bo'lib qoldi.")
            return
    await db.add_log(uid, "episode_add", f"anime={anime_id} ep={number}")
    await message.answer(f"✅ {number}-qism qo'shildi")
    if data.get("num_mode") == "manual":
        await state.set_state(EpisodeSt.number)
        await message.answer("Keyingi qism raqamini yozing (tugatish: /done):", reply_markup=done_kb())


@admin_router.message(EpisodeSt.video)
async def msg_episode_video_wrong(message: Message) -> None:
    await message.answer("❗ Iltimos, video yuboring (yoki /done).")


@admin_router.callback_query(F.data == "ea_done")
async def cb_episode_done(cb: CallbackQuery, state: FSMContext) -> None:
    await answer_cb(cb)
    await state.clear()
    if cb.message:
        await cb.message.answer("✅ Qism qo'shish tugadi.", reply_markup=admin_anime_kb())


@admin_router.message(Command("done"))
async def cmd_done(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("✅ Tugadi.", reply_markup=admin_anime_kb())


# ---------------- admin uchun anime topish (ID yoki nom) ----------------
async def resolve_anime(message: Message, text: str, flow: str) -> Optional[asyncpg.Record]:
    text = clean_text(text, 80)
    if text.isdigit() and len(text) <= 12:
        anime = await db.get_anime(int(text))
        if anime:
            return anime
    rows, total = await db.search_by_name(text, 8, 0)
    if total == 0:
        await message.answer("😕 Anime topilmadi. Nom yoki ID ni qayta yozing:")
        return None
    if total == 1:
        return rows[0]
    kb = InlineKeyboardBuilder()
    for row in rows:
        kb.row(InlineKeyboardButton(text=f"{row['name']} (ID {row['id']})"[:60],
                                    callback_data=f"pick:{flow}:{row['id']}"))
    await message.answer(f"Topildi: {total} ta. Birini tanlang:", reply_markup=kb.as_markup())
    return None


# ---------------- Anime Tahrirlash ----------------
EDIT_FIELDS = {"name": "nomini", "year": "yilini", "genre": "janrini",
               "studio": "dublyaj studiyasini", "photo": "rasmini"}


def edit_menu_kb(anime_id: int, is_vip: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✏️ Nomi", callback_data=f"ae:name:{anime_id}"),
           InlineKeyboardButton(text="📅 Yili", callback_data=f"ae:year:{anime_id}"))
    kb.row(InlineKeyboardButton(text="🔖 Janri", callback_data=f"ae:genre:{anime_id}"),
           InlineKeyboardButton(text="🎙 Studiyasi", callback_data=f"ae:studio:{anime_id}"))
    kb.row(InlineKeyboardButton(text="🖼 Rasmi", callback_data=f"ae:photo:{anime_id}"))
    kb.row(InlineKeyboardButton(
        text="🆓 Oddiyga o'tkazish" if is_vip else "💎 VIP ga o'tkazish",
        callback_data=f"ae:vip:{anime_id}"))
    kb.row(InlineKeyboardButton(text="🗑 Qismni o'chirish", callback_data=f"ae:delep:{anime_id}"))
    kb.row(InlineKeyboardButton(text="🗑 Animeni o'chirish", callback_data=f"ae:delask:{anime_id}"))
    return kb.as_markup()


async def send_edit_menu(target: Message, anime_id: int) -> None:
    anime = await db.get_anime(anime_id)
    if not anime:
        await target.answer("😕 Anime topilmadi.", reply_markup=admin_anime_kb())
        return
    count = await db.count_episodes(anime_id)
    text = "🔒 <b>Anime tahrirlash</b>\n\n" + anime_card_text("uz", anime, count)
    await target.answer(text, reply_markup=edit_menu_kb(anime_id, bool(anime["is_vip"])))


@admin_router.message(F.text == BTN_A_EDIT)
async def btn_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(EditSt.anime_id)
    await message.answer("Tahrirlanadigan anime ID si yoki nomini yozing:\n(Bekor qilish: /cancel)")


@admin_router.message(EditSt.anime_id, F.text)
async def msg_edit_find(message: Message, state: FSMContext) -> None:
    anime = await resolve_anime(message, message.text or "", "edit")
    if anime:
        await state.clear()
        await send_edit_menu(message, anime["id"])


@admin_router.callback_query(F.data.startswith("pick:"))
async def cb_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await answer_cb(cb)
    try:
        _, flow, id_s = (cb.data or "").split(":")
        anime_id = int(id_s)
    except ValueError:
        return
    await state.clear()
    if not cb.message:
        return
    if flow == "edit":
        await send_edit_menu(cb.message, anime_id)  # type: ignore[arg-type]
    elif flow == "post":
        anime = await db.get_anime(anime_id)
        if anime:
            await send_post(cb.bot, cb.from_user.id, anime, protect=False)  # type: ignore[arg-type]
            await offer_post_channels(cb.message, state, anime["id"])  # type: ignore[arg-type]


@admin_router.callback_query(F.data.startswith("ae:"))
async def cb_edit_action(cb: CallbackQuery, state: FSMContext) -> None:
    try:
        _, action, id_s = (cb.data or "").split(":")
        anime_id = int(id_s)
    except ValueError:
        await answer_cb(cb)
        return
    anime = await db.get_anime(anime_id)
    if not anime:
        await answer_cb(cb, "Anime topilmadi", alert=True)
        return
    await answer_cb(cb)
    uid = cb.from_user.id
    msg = cb.message
    if msg is None:
        return
    if action in EDIT_FIELDS:
        await state.set_state(EditSt.field_value)
        await state.update_data(edit_id=anime_id, edit_field=action)
        what = "rasmini yuboring" if action == "photo" else "qiymatini yozing"
        await msg.answer(f"Yangi {EDIT_FIELDS[action]} {what}:\n(Bekor qilish: /cancel)")
    elif action == "vip":
        new_value = not anime["is_vip"]
        await db.update_anime_field(anime_id, "is_vip", new_value)
        await db.add_log(uid, "anime_vip_toggle", f"id={anime_id} vip={new_value}")
        await send_edit_menu(msg, anime_id)  # type: ignore[arg-type]
    elif action == "delep":
        await state.set_state(EditSt.del_episode)
        await state.update_data(edit_id=anime_id)
        await msg.answer("O'chiriladigan qism raqamini yozing (qolgan qismlar raqami o'zgarmaydi):")
    elif action == "delask":
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="✅ Ha, o'chirish", callback_data=f"ae:delyes:{anime_id}"),
               InlineKeyboardButton(text="❌ Yo'q", callback_data=f"ae:delno:{anime_id}"))
        await msg.answer(f"⚠️ <b>{esc(anime['name'])}</b> va uning barcha qismlari o'chiriladi. Ishonchingiz komilmi?",
                         reply_markup=kb.as_markup())
    elif action == "delyes":
        await db.delete_anime(anime_id)
        await db.add_log(uid, "anime_delete", f"id={anime_id} name={anime['name']}")
        await smart_send(cb, f"🗑 «{esc(anime['name'])}» o'chirildi.")
    elif action == "delno":
        await smart_send(cb, "Bekor qilindi.")


@admin_router.message(EditSt.field_value, F.photo)
async def msg_edit_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("edit_field") != "photo":
        await message.answer("❗ Bu maydon uchun matn yozing.")
        return
    await db.update_anime_field(data["edit_id"], "photo_id", message.photo[-1].file_id)  # type: ignore[index]
    await db.add_log(message.from_user.id, "anime_edit", f"id={data['edit_id']} field=photo")  # type: ignore[union-attr]
    await state.clear()
    await message.answer("✅ Rasm yangilandi.")
    await send_edit_menu(message, data["edit_id"])


@admin_router.message(EditSt.field_value, F.text)
async def msg_edit_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    field = data.get("edit_field")
    if field == "photo":
        await message.answer("❗ Iltimos, rasm yuboring.")
        return
    value = clean_text(message.text or "", 120)
    if not value:
        await message.answer("❗ Qiymat bo'sh bo'lmasin:")
        return
    await db.update_anime_field(data["edit_id"], field, value)
    await db.add_log(message.from_user.id, "anime_edit", f"id={data['edit_id']} field={field}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer("✅ Yangilandi.")
    await send_edit_menu(message, data["edit_id"])


@admin_router.message(EditSt.del_episode, F.text)
async def msg_edit_del_episode(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    if not raw.isdigit():
        await message.answer("❗ Qism raqamini faqat son bilan yozing:")
        return
    ok = await db.delete_episode(data["edit_id"], int(raw))
    await state.clear()
    if ok:
        await db.add_log(message.from_user.id, "episode_delete", f"anime={data['edit_id']} ep={raw}")  # type: ignore[union-attr]
        await message.answer(f"🗑 {raw}-qism o'chirildi.")
    else:
        await message.answer(f"😕 {raw}-qism topilmadi.")
    await send_edit_menu(message, data["edit_id"])


# ---------------- Post Tayyorlash ----------------
def channel_handle(url: str) -> str:
    """https://t.me/anizone_anime -> @anizone_anime (aks holda havolaning o'zi)."""
    m = re.match(r"^https?://t\.me/([A-Za-z0-9_]{4,})/?$", (url or "").strip())
    return f"@{m.group(1)}" if m else (url or "").strip()


def build_post_text(anime: asyncpg.Record, main_url: str, ep_count: int = 0) -> str:
    line = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
    lines = [
        "✨ <b>YANGI Anime</b> ✨",
        line,
        f"🎞 <b>Nomi:</b> {esc(anime['name'])}",
        f"🗓 <b>Yili:</b> {esc(anime['year'] or '—')}",
        f"📂 <b>Janri:</b> {esc(anime['genre'] or '—')}",
        f"💎 <b>Qismlar:</b> {ep_count}",
        f"🎙 <b>Ovoz berdi:</b> {esc(anime['studio'] or '—')}",
        line,
        f"🔑 <b>Kodi:</b> <code>{anime['id']}</code>",
    ]
    if main_url:
        lines.append(f"🚀 <b>Kanalimiz:</b> {esc(channel_handle(main_url))}")
    return "\n".join(lines)


async def send_post(bot: Bot, chat_id: int, anime: asyncpg.Record, protect: bool = False) -> bool:
    main_url = await db.get_setting("main_channel_url")
    ep_count = await db.count_episodes(anime["id"])
    text = build_post_text(anime, main_url, ep_count)
    try:
        if anime["photo_id"]:
            await bot.send_photo(chat_id, anime["photo_id"], caption=text, protect_content=protect)
        else:
            await bot.send_message(chat_id, text, protect_content=protect)
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("Post yuborib bo'lmadi (chat %s): %s", chat_id, exc)
        return False


@admin_router.message(F.text == BTN_A_POST)
async def btn_post(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PostSt.query)
    await message.answer("Post uchun anime nomi yoki ID sini yozing:\n(Bekor qilish: /cancel)")


@admin_router.message(PostSt.query, F.text)
async def msg_post_query(message: Message, state: FSMContext) -> None:
    anime = await resolve_anime(message, message.text or "", "post")
    if anime:
        await state.clear()
        await send_post(message.bot, message.chat.id, anime)  # type: ignore[arg-type]
        await offer_post_channels(message, state, anime["id"])


def postchan_kb(channels: List[asyncpg.Record], selected: List[int]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ch in channels:
        mark = "✅" if ch["id"] in selected else "⬜️"
        kb.row(InlineKeyboardButton(text=f"{mark} {ch['title'] or ch['chat_id']}"[:60],
                                    callback_data=f"pp:t:{ch['id']}"))
    kb.row(InlineKeyboardButton(text="📤 Yuborish", callback_data="pp:send"),
           InlineKeyboardButton(text="❌ Bekor", callback_data="pp:cancel"))
    return kb.as_markup()


async def offer_post_channels(target: Message, state: FSMContext, anime_id: int) -> None:
    """Post tayyor bo'lgach, post kanallarini tanlash uchun ko'rsatadi."""
    channels = await db.list_channels("post")
    if not channels:
        await target.answer("ℹ️ Post kanallari qo'shilmagan. Owner «📢 Kanallarni Sozlash» orqali qo'shsa, "
                            "postni to'g'ridan-to'g'ri kanalga yuborish mumkin bo'ladi.")
        return
    await state.update_data(pp_anime=anime_id, pp_selected=[])
    await target.answer("📤 Postni qaysi kanallarga yuboramiz?", reply_markup=postchan_kb(channels, []))


@admin_router.callback_query(F.data.startswith("pp:"))
async def cb_post_channels(cb: CallbackQuery, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    data = await state.get_data()
    anime_id = data.get("pp_anime")
    selected: List[int] = list(data.get("pp_selected", []))
    if action == "cancel":
        await answer_cb(cb)
        await state.update_data(pp_anime=None, pp_selected=[])
        await smart_send(cb, "Bekor qilindi.")
        return
    if not anime_id:
        await answer_cb(cb, "Jarayon topilmadi. Postni qaytadan tayyorlang.", alert=True)
        return
    channels = await db.list_channels("post")
    if action == "t" and len(parts) == 3 and parts[2].isdigit():
        cid = int(parts[2])
        if cid in selected:
            selected.remove(cid)
        else:
            selected.append(cid)
        await state.update_data(pp_selected=selected)
        await answer_cb(cb)
        try:
            await cb.message.edit_reply_markup(reply_markup=postchan_kb(channels, selected))  # type: ignore[union-attr]
        except TelegramBadRequest:
            pass
        return
    if action == "send":
        if not selected:
            await answer_cb(cb, "Hech bo'lmasa bitta kanal tanlang", alert=True)
            return
        anime = await db.get_anime(anime_id)
        if not anime:
            await answer_cb(cb, "Anime topilmadi", alert=True)
            return
        await answer_cb(cb, "Yuborilmoqda...")
        ok = fail = 0
        for ch in [c for c in channels if c["id"] in selected]:
            if await send_post(cb.bot, ch["chat_id"], anime, protect=False):  # type: ignore[arg-type]
                ok += 1
            else:
                fail += 1
            await asyncio.sleep(0.6)
        await state.update_data(pp_anime=None, pp_selected=[])
        await db.add_log(cb.from_user.id, "post_send", f"anime={anime_id} ok={ok} fail={fail}")
        await smart_send(cb, f"✅ Post yuborildi.\nKanalga yetdi: {ok}\nXato: {fail}")


# ---------------- Avto Post ----------------
def autopost_kb(channels: List[asyncpg.Record], selected: List[int]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ch in channels:
        mark = "✅" if ch["id"] in selected else "⬜️"
        kb.row(InlineKeyboardButton(text=f"{mark} {ch['title'] or ch['chat_id']}"[:60],
                                    callback_data=f"ap:t:{ch['id']}"))
    kb.row(InlineKeyboardButton(text="📤 Yuborish", callback_data="ap:send"),
           InlineKeyboardButton(text="❌ Bekor", callback_data="ap:cancel"))
    return kb.as_markup()


@admin_router.message(F.text == BTN_A_AUTOPOST)
async def btn_autopost(message: Message, state: FSMContext) -> None:
    await state.clear()
    animes = await db.recent_animes(24)
    if not animes:
        await message.answer("😕 Oxirgi 24 soat ichida anime qo'shilmagan.")
        return
    channels = await db.list_channels("post")
    if not channels:
        await message.answer("😕 Post kanallari yo'q. Owner «📢 Kanallarni Sozlash» orqali qo'shishi kerak.")
        return
    await state.update_data(ap_selected=[])
    names = "\n".join(f"• {esc(a['name'])} (ID {a['id']})" for a in animes[:30])
    await message.answer(f"⏰ <b>Avto Post</b>\nOxirgi 24 soatda qo'shilgan animelar: {len(animes)} ta\n\n{names}\n\n"
                         "Qaysi kanallarga yuboramiz?", reply_markup=autopost_kb(channels, []))


@admin_router.callback_query(F.data.startswith("ap:"))
async def cb_autopost(cb: CallbackQuery, state: FSMContext) -> None:
    parts = (cb.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    data = await state.get_data()
    selected: List[int] = list(data.get("ap_selected", []))
    channels = await db.list_channels("post")
    if action == "cancel":
        await answer_cb(cb)
        await state.clear()
        await smart_send(cb, "Bekor qilindi.")
        return
    if action == "t" and len(parts) == 3 and parts[2].isdigit():
        cid = int(parts[2])
        if cid in selected:
            selected.remove(cid)
        else:
            selected.append(cid)
        await state.update_data(ap_selected=selected)
        await answer_cb(cb)
        try:
            await cb.message.edit_reply_markup(reply_markup=autopost_kb(channels, selected))  # type: ignore[union-attr]
        except TelegramBadRequest:
            pass
        return
    if action == "send":
        if not selected:
            await answer_cb(cb, "Hech bo'lmasa bitta kanal tanlang", alert=True)
            return
        await answer_cb(cb, "Yuborilmoqda...")
        animes = await db.recent_animes(24)
        targets = [c for c in channels if c["id"] in selected]
        ok = fail = 0
        for anime in animes:
            for ch in targets:
                if await send_post(cb.bot, ch["chat_id"], anime, protect=False):  # type: ignore[arg-type]
                    ok += 1
                else:
                    fail += 1
                await asyncio.sleep(0.6)
        await state.clear()
        await db.add_log(cb.from_user.id, "autopost", f"animes={len(animes)} channels={len(targets)} ok={ok} fail={fail}")
        await smart_send(cb, f"✅ Avto post tugadi.\nYuborildi: {ok}\nXato: {fail}")


# ---------------- Xabar Yuborish (broadcast) ----------------
def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✅ Yuborish", callback_data="bc:go"),
           InlineKeyboardButton(text="❌ Bekor", callback_data="bc:no"))
    return kb.as_markup()


@admin_router.message(F.text == BTN_A_BROADCAST)
async def btn_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BroadcastSt.content)
    await message.answer("💬 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring "
                         "(matn, rasm, video — istalgan).\n(Bekor qilish: /cancel)")


@admin_router.message(BroadcastSt.content)
async def msg_broadcast_content(message: Message, state: FSMContext) -> None:
    await state.update_data(bc_chat=message.chat.id, bc_msg=message.message_id)
    await state.set_state(BroadcastSt.confirm)
    try:
        await message.bot.copy_message(message.chat.id, message.chat.id, message.message_id)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        log.warning("Preview xato: %s", exc)
    await message.answer("Shu xabar barcha foydalanuvchilarga yuboriladi. Tasdiqlaysizmi?",
                         reply_markup=broadcast_confirm_kb())


@admin_router.callback_query(F.data.startswith("bc:"))
async def cb_broadcast(cb: CallbackQuery, state: FSMContext) -> None:
    global _broadcast_running
    action = (cb.data or "").split(":", 1)[1]
    data = await state.get_data()
    if action == "no" or not data.get("bc_msg"):
        await answer_cb(cb)
        await state.clear()
        await smart_send(cb, "Bekor qilindi.")
        return
    if _broadcast_running:
        await answer_cb(cb, "Boshqa xabar yuborilmoqda, kuting", alert=True)
        return
    await answer_cb(cb)
    await state.clear()
    await smart_send(cb, "🚀 Yuborish boshlandi. Tugagach natija yuboriladi.")
    asyncio.create_task(run_broadcast(cb.bot, cb.from_user.id, data["bc_chat"], data["bc_msg"]))  # type: ignore[arg-type]


async def run_broadcast(bot: Bot, admin_id: int, from_chat: int, msg_id: int) -> None:
    """Sekundiga ~25 ta; bloklaganlar o'tkazib yuboriladi; oxirida natija."""
    global _broadcast_running
    _broadcast_running = True
    sent = blocked = failed = 0
    try:
        user_ids = await db.all_user_ids()
        await db.add_log(admin_id, "broadcast_start", f"users={len(user_ids)}")
        for i, uid in enumerate(user_ids, start=1):
            try:
                await bot.copy_message(uid, from_chat, msg_id)
                sent += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
                try:
                    await bot.copy_message(uid, from_chat, msg_id)
                    sent += 1
                except Exception:  # noqa: BLE001
                    failed += 1
            except TelegramForbiddenError:
                blocked += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                log.warning("Broadcast xato (user %s): %s", uid, exc)
            if i % BROADCAST_RATE == 0:
                await asyncio.sleep(1)
        total = len(user_ids)
    except Exception as exc:  # noqa: BLE001
        log.exception("Broadcast to'xtadi: %s", exc)
        total = sent + blocked + failed
    finally:
        _broadcast_running = False
    await db.add_log(admin_id, "broadcast_done", f"sent={sent} blocked={blocked} failed={failed}")
    try:
        await bot.send_message(
            admin_id,
            f"📬 <b>Xabar yuborish tugadi</b>\n\n👥 Jami: {total}\n✅ Yetdi: {sent}\n"
            f"🚫 Bloklagan: {blocked}\n⚠️ Xato: {failed}")
    except Exception:  # noqa: BLE001
        pass


# ======================================================================
# 10. OWNER PANELI
# ======================================================================

owner_router = Router(name="owner")
owner_router.message.filter(F.chat.type == "private", IsOwnerFilter())
owner_router.callback_query.filter(IsOwnerFilter())

SETTING_LABELS = {
    "card_info": "💳 Karta ma'lumoti",
    "price_3_month": "💰 VIP 3 oy narxi",
    "price_6_month": "💰 VIP 6 oy narxi",
    "price_3_year": "💰 VIP 3 yil narxi",
    "developer_info_uz": "👨‍💻 Dasturchi (o'zbekcha)",
    "developer_info_ru": "👨‍💻 Dasturchi (ruscha)",
    "privacy_url": "🔗 Maxfiylik siyosati havolasi",
    "offer_url": "🔗 Ommaviy oferta havolasi",
}


# ---------------- Statistika, Loglar ----------------
@owner_router.message(F.text == BTN_A_STATS)
async def btn_stats(message: Message, state: FSMContext) -> None:
    await state.clear()
    s = await db.stats()
    await message.answer(
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{s['users']}</b>\n"
        f"💎 VIP foydalanuvchilar: <b>{s['vip']}</b>\n"
        f"🎬 Animelar: <b>{s['animes']}</b>\n"
        f"📺 Qismlar: <b>{s['episodes']}</b>\n"
        f"🆕 Bugungi yangi foydalanuvchilar: <b>{s['today']}</b>\n"
        f"🚫 Banlanganlar: <b>{s['banned']}</b>")


@owner_router.message(F.text == BTN_A_LOGS)
async def btn_logs(message: Message, state: FSMContext) -> None:
    await state.clear()
    rows = await db.recent_logs(30)
    if not rows:
        await message.answer("Loglar bo'sh.")
        return
    lines = ["📋 <b>Oxirgi loglar</b>", ""]
    for r in rows:
        when = fmt_date(r["created_at"])
        lines.append(f"<code>{when}</code> | {r['actor_id'] or '-'} | <b>{esc(r['action'])}</b> {esc(r['details'] or '')}")
    for chunk in split_text("\n".join(lines)):
        await message.answer(chunk)


# ---------------- Kanallarni Sozlash ----------------
async def channels_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Majburiy obuna kanali", callback_data="ch:add:sub"))
    kb.row(InlineKeyboardButton(text="➕ Post kanali", callback_data="ch:add:post"))
    kb.row(InlineKeyboardButton(text="🔗 Asosiy kanal havolasi", callback_data="ch:main"))
    for kind, label in (("sub", "Majburiy"), ("post", "Post")):
        for ch in await db.list_channels(kind):
            kb.row(InlineKeyboardButton(text=f"🗑 {label}: {ch['title'] or ch['chat_id']}"[:60],
                                        callback_data=f"ch:del:{ch['id']}"))
    return kb.as_markup()


@owner_router.message(F.text == BTN_A_CHANNELS)
async def btn_channels(message: Message, state: FSMContext) -> None:
    await state.clear()
    main_url = await db.get_setting("main_channel_url")
    await message.answer(
        "📢 <b>Kanallarni Sozlash</b>\n\n"
        f"Asosiy kanal: {esc(main_url) if main_url else 'kiritilmagan'}\n"
        "Kanalni o'chirish uchun 🗑 tugmasini bosing.",
        reply_markup=await channels_menu_kb(), disable_web_page_preview=True)


@owner_router.callback_query(F.data.startswith("ch:"))
async def cb_channels(cb: CallbackQuery, state: FSMContext) -> None:
    await answer_cb(cb)
    parts = (cb.data or "").split(":")
    action = parts[1]
    if action == "add" and len(parts) == 3 and parts[2] in ("sub", "post"):
        await state.set_state(ChannelSt.add)
        await state.update_data(kind=parts[2])
        await cb.message.answer(  # type: ignore[union-attr]
            "Kanaldan istalgan xabarni shu yerga forward qiling yoki @username / ID (-100...) yozing.\n"
            "⚠️ Bot kanalda ADMIN bo'lishi shart.\n(Bekor qilish: /cancel)")
    elif action == "main":
        await state.set_state(ChannelSt.main_url)
        await cb.message.answer("Asosiy kanal havolasini yozing (masalan https://t.me/kanal):")  # type: ignore[union-attr]
    elif action == "del" and len(parts) == 3 and parts[2].isdigit():
        row = await db.get_channel(int(parts[2]))
        if row:
            await db.remove_channel(row["id"])
            drop_all_sub_cache()
            await db.add_log(cb.from_user.id, "channel_remove", f"chat={row['chat_id']} kind={row['kind']}")
        await smart_send(cb, "🗑 Kanal olib tashlandi.", await channels_menu_kb())


def drop_all_sub_cache() -> None:
    _sub_cache.clear()


@owner_router.message(ChannelSt.add)
async def msg_channel_add(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    kind = data.get("kind", "sub")
    bot: Bot = message.bot  # type: ignore[assignment]
    chat = None
    origin = getattr(message, "forward_origin", None)
    if origin is not None and getattr(origin, "chat", None) is not None:
        chat = origin.chat
    elif message.text:
        ref = message.text.strip()
        if ref.lstrip("-").isdigit():
            ref_val: Any = int(ref)
        else:
            ref_val = ref if ref.startswith("@") else f"@{ref.split('/')[-1]}"
        try:
            chat = await bot.get_chat(ref_val)
        except Exception as exc:  # noqa: BLE001
            await message.answer(f"❗ Kanal topilmadi: {esc(exc)}")
            return
    if chat is None:
        await message.answer("❗ Kanal aniqlanmadi. Forward qiling yoki @username yozing.")
        return
    try:
        me = await bot.get_chat_member(chat.id, bot.id)
        if me.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            await message.answer("❗ Bot bu kanalda admin emas. Avval botni kanalga admin qiling.")
            return
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"❗ Botning kanaldagi huquqini tekshirib bo'lmadi: {esc(exc)}")
        return
    url = f"https://t.me/{chat.username}" if chat.username else ""
    if not url:
        try:
            url = await bot.export_chat_invite_link(chat.id)
        except Exception:  # noqa: BLE001
            url = ""
    if not url and kind == "sub":
        await message.answer("❗ Kanal havolasini olib bo'lmadi (maxfiy kanal uchun botga 'taklif havolasi' huquqini bering).")
        return
    await db.add_channel(chat.id, chat.title or str(chat.id), url, kind)
    drop_all_sub_cache()
    await db.add_log(message.from_user.id, "channel_add", f"chat={chat.id} kind={kind}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer(f"✅ Kanal qo'shildi: {esc(chat.title)}", reply_markup=await channels_menu_kb())


@owner_router.message(ChannelSt.main_url, F.text)
async def msg_main_url(message: Message, state: FSMContext) -> None:
    url = clean_text(message.text or "", 200)
    if not url.startswith("http"):
        await message.answer("❗ Havola http yoki https bilan boshlanishi kerak:")
        return
    await db.set_setting("main_channel_url", url)
    await db.add_log(message.from_user.id, "main_channel_set", url)  # type: ignore[union-attr]
    await state.clear()
    await message.answer("✅ Asosiy kanal havolasi saqlandi.")


# ---------------- Asosiy Sozlamalar ----------------
def owner_settings_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=SETTING_LABELS["card_info"], callback_data="os:edit:card_info"))
    kb.row(InlineKeyboardButton(text="💰 3 oy", callback_data="os:edit:price_3_month"),
           InlineKeyboardButton(text="💰 6 oy", callback_data="os:edit:price_6_month"),
           InlineKeyboardButton(text="💰 3 yil", callback_data="os:edit:price_3_year"))
    kb.row(InlineKeyboardButton(text="➕ VIP berish", callback_data="os:vipgive"),
           InlineKeyboardButton(text="➖ VIP o'chirish", callback_data="os:viprevoke"))
    kb.row(InlineKeyboardButton(text="👮 Admin qo'shish", callback_data="os:admadd"),
           InlineKeyboardButton(text="👮 Admin olib tashlash", callback_data="os:admrem"))
    kb.row(InlineKeyboardButton(text="🚫 Ban", callback_data="os:ban"),
           InlineKeyboardButton(text="♻️ Unban", callback_data="os:unban"))
    kb.row(InlineKeyboardButton(text="👨‍💻 Dasturchi (uz)", callback_data="os:edit:developer_info_uz"),
           InlineKeyboardButton(text="👨‍💻 Dasturchi (ru)", callback_data="os:edit:developer_info_ru"))
    kb.row(InlineKeyboardButton(text="🔗 Maxfiylik", callback_data="os:edit:privacy_url"),
           InlineKeyboardButton(text="🔗 Oferta", callback_data="os:edit:offer_url"))
    return kb.as_markup()


@owner_router.message(F.text == BTN_A_SETTINGS)
async def btn_owner_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    admins = await db.list_admins()
    admin_text = ", ".join(f"<code>{a}</code>" for a in admins) or "yo'q"
    prices = []
    for plan in ("3_month", "6_month", "3_year"):
        prices.append(f"{VIP_PLANS[plan]['label_uz']}: {await db.get_price(plan):,} UZS")
    await message.answer(
        "⚙️ <b>Asosiy Sozlamalar</b>\n\n"
        f"💳 Karta: {esc(await db.get_setting('card_info'))}\n"
        f"💰 Narxlar:\n" + "\n".join(prices) + f"\n\n👮 Adminlar: {admin_text}",
        reply_markup=owner_settings_kb())


async def _resolve_user_ref(message: Message) -> Optional[asyncpg.Record]:
    user = await db.find_user(clean_text(message.text or "", 64))
    if not user:
        await message.answer("😕 Foydalanuvchi topilmadi (u botga kamida bir marta /start bosgan bo'lishi kerak). "
                             "ID yoki @username ni qayta yozing:")
    return user


@owner_router.callback_query(F.data.startswith("os:"))
async def cb_owner_settings(cb: CallbackQuery, state: FSMContext) -> None:
    await answer_cb(cb)
    parts = (cb.data or "").split(":")
    action = parts[1]
    msg = cb.message
    if msg is None:
        return
    await state.clear()
    if action == "edit" and len(parts) == 3 and parts[2] in SETTING_LABELS:
        await state.set_state(OwnerSt.edit_setting)
        await state.update_data(setting_key=parts[2])
        await msg.answer(f"{SETTING_LABELS[parts[2]]} uchun yangi qiymatni yozing:\n(Bekor qilish: /cancel)")
    elif action == "vipgive":
        await state.set_state(OwnerSt.vip_give_user)
        await msg.answer("VIP beriladigan foydalanuvchi ID si yoki @username ni yozing:")
    elif action == "viprevoke":
        await state.set_state(OwnerSt.vip_revoke_user)
        await msg.answer("VIP o'chiriladigan foydalanuvchi ID si yoki @username ni yozing:")
    elif action == "admadd":
        await state.set_state(OwnerSt.admin_add)
        await msg.answer("Admin qilinadigan foydalanuvchi ID si yoki @username ni yozing:")
    elif action == "admrem":
        await state.set_state(OwnerSt.admin_remove)
        admins = ", ".join(f"<code>{a}</code>" for a in await db.list_admins()) or "yo'q"
        await msg.answer(f"Adminlar: {admins}\nOlib tashlanadigan admin ID sini yozing:")
    elif action == "ban":
        await state.set_state(OwnerSt.ban_user)
        await msg.answer("Ban qilinadigan foydalanuvchi ID si yoki @username ni yozing:")
    elif action == "unban":
        await state.set_state(OwnerSt.unban_user)
        await msg.answer("Banni olib tashlash uchun foydalanuvchi ID si yoki @username ni yozing:")


@owner_router.message(OwnerSt.edit_setting, F.text)
async def msg_edit_setting(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    key = data.get("setting_key", "")
    value = clean_text(message.text or "", 500)
    if key.startswith("price_"):
        if not value.isdigit() or int(value) <= 0:
            await message.answer("❗ Narx faqat musbat son bo'lishi kerak:")
            return
    elif key.endswith("_url") and not value.startswith("http"):
        await message.answer("❗ Havola http yoki https bilan boshlanishi kerak:")
        return
    elif not value:
        await message.answer("❗ Qiymat bo'sh bo'lmasin:")
        return
    await db.set_setting(key, value)
    await db.add_log(message.from_user.id, "setting_change", f"{key}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer("✅ Saqlandi.")


@owner_router.message(OwnerSt.vip_give_user, F.text)
async def msg_vip_give_user(message: Message, state: FSMContext) -> None:
    user = await _resolve_user_ref(message)
    if not user:
        return
    await state.update_data(target=user["user_id"])
    await state.set_state(OwnerSt.vip_give_days)
    await message.answer("Necha kunlik VIP beramiz? (masalan 30):")


@owner_router.message(OwnerSt.vip_give_days, F.text)
async def msg_vip_give_days(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or not (0 < int(raw) <= 3650):
        await message.answer("❗ Kunlar soni 1 dan 3650 gacha bo'lishi kerak:")
        return
    data = await state.get_data()
    target = data["target"]
    until = await db.grant_vip(target, int(raw))
    await db.add_log(message.from_user.id, "vip_give", f"user={target} days={raw}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer(f"✅ VIP berildi. Tugash sanasi: {fmt_date(until)}")
    lang = await get_lang(target)
    try:
        await message.bot.send_message(target, t(lang, "vip_approved", date=fmt_date(until)))  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


@owner_router.message(OwnerSt.vip_revoke_user, F.text)
async def msg_vip_revoke(message: Message, state: FSMContext) -> None:
    user = await _resolve_user_ref(message)
    if not user:
        return
    await db.revoke_vip(user["user_id"])
    await db.add_log(message.from_user.id, "vip_revoke", f"user={user['user_id']}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer(f"✅ {user['user_id']} dan VIP olib tashlandi.")


@owner_router.message(OwnerSt.admin_add, F.text)
async def msg_admin_add(message: Message, state: FSMContext) -> None:
    user = await _resolve_user_ref(message)
    if not user:
        return
    await db.add_admin(user["user_id"])
    await db.add_log(message.from_user.id, "admin_add", f"user={user['user_id']}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer(f"✅ {user['user_id']} admin qilindi.")


@owner_router.message(OwnerSt.admin_remove, F.text)
async def msg_admin_remove(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("❗ Admin ID sini raqam bilan yozing:")
        return
    await db.remove_admin(int(raw))
    await db.add_log(message.from_user.id, "admin_remove", f"user={raw}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer(f"✅ {raw} adminlikdan olindi.")


@owner_router.message(OwnerSt.ban_user, F.text)
async def msg_ban(message: Message, state: FSMContext) -> None:
    user = await _resolve_user_ref(message)
    if not user:
        return
    if is_owner(user["user_id"]):
        await message.answer("❗ Ownerni ban qilib bo'lmaydi.")
        return
    await db.set_banned(user["user_id"], True)
    await db.add_log(message.from_user.id, "ban", f"user={user['user_id']}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer(f"🚫 {user['user_id']} ban qilindi.")


@owner_router.message(OwnerSt.unban_user, F.text)
async def msg_unban(message: Message, state: FSMContext) -> None:
    user = await _resolve_user_ref(message)
    if not user:
        return
    await db.set_banned(user["user_id"], False)
    await db.add_log(message.from_user.id, "unban", f"user={user['user_id']}")  # type: ignore[union-attr]
    await state.clear()
    await message.answer(f"♻️ {user['user_id']} bandan chiqarildi.")


# ---------------- VIP to'lovni tasdiqlash / rad etish ----------------
@owner_router.callback_query(F.data.regexp(r"^vip(ok|no):\d+$"))
async def cb_vip_decision(cb: CallbackQuery) -> None:
    action, req_id_s = (cb.data or "").split(":")
    req_id = int(req_id_s)
    req = await db.get_vip_request(req_id)
    if not req:
        await answer_cb(cb, "So'rov topilmadi", alert=True)
        return
    approve = action == "vipok"
    if not await db.decide_vip_request(req_id, "approved" if approve else "rejected", cb.from_user.id):
        await answer_cb(cb, "Bu so'rov allaqachon ko'rib chiqilgan", alert=True)
        return
    await answer_cb(cb)
    lang = await get_lang(req["user_id"])
    if approve:
        days = VIP_PLANS.get(req["plan"], {"days": 30})["days"]
        until = await db.grant_vip(req["user_id"], days)
        await db.add_log(cb.from_user.id, "vip_approve", f"req={req_id} user={req['user_id']} until={until:%Y-%m-%d}")
        note = f"✅ Tasdiqlandi ({fmt_date(until)} gacha)"
        user_text = t(lang, "vip_approved", date=fmt_date(until))
    else:
        await db.add_log(cb.from_user.id, "vip_reject", f"req={req_id} user={req['user_id']}")
        note = "❌ Rad etildi"
        user_text = t(lang, "vip_rejected")
    try:
        await cb.bot.send_message(req["user_id"], user_text)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        log.warning("VIP natijasini foydalanuvchiga yuborib bo'lmadi: %s", exc)
    if cb.message:
        try:
            await cb.message.edit_caption(caption=f"{cb.message.caption or ''}\n\n{note}", reply_markup=None)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


# ======================================================================
# 11. FON VAZIFALARI, /health, ISHGA TUSHIRISH
# ======================================================================

async def vip_expiry_loop(bot: Bot) -> None:
    """Muddati tugagan VIP larni avtomatik o'chiradi va xabar beradi."""
    while True:
        try:
            for uid in await db.expired_vip_users():
                lang = await get_lang(uid)
                await db.add_log(None, "vip_expired", f"user={uid}")
                try:
                    await bot.send_message(uid, t(lang, "vip_expired"))
                except Exception:  # noqa: BLE001
                    pass
            rate_limiter.cleanup()
        except Exception as exc:  # noqa: BLE001
            log.error("VIP tekshiruv xatosi: %s", exc)
        await asyncio.sleep(300)


async def health(_: web.Request) -> web.Response:
    return web.Response(text="OK")


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Health server %s portda ishlayapti", PORT)
    return runner


async def on_error(event: ErrorEvent) -> bool:
    log.error("Handler xatosi: %s", event.exception, exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Xatolik / Ошибка", show_alert=True)
        elif update.message:
            await update.message.answer("⚠️ Xatolik yuz berdi. Keyinroq urinib ko'ring.")
    except Exception:  # noqa: BLE001
        pass
    return True


async def main() -> None:
    missing = [n for n, v in (("BOT_TOKEN", BOT_TOKEN), ("OWNER_ID", OWNER_ID),
                              ("DATABASE_URL", DATABASE_URL)) if not v]
    if missing:
        log.critical("Muhit o'zgaruvchilari yo'q: %s", ", ".join(missing))
        raise SystemExit(1)

    await start_web_server()  # Render portni darrov ko'rishi uchun birinchi

    while True:  # baza ulanmasa bot to'xtamaydi, qayta urinadi
        try:
            await db.connect()
            await db.init_schema()
            break
        except Exception as exc:  # noqa: BLE001
            log.error("Baza ulanishi xato: %s. 5 soniyadan keyin qayta uriniladi.", exc)
            await asyncio.sleep(5)

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(GateMiddleware())
    dp.callback_query.outer_middleware(GateMiddleware())
    dp.include_router(admin_router)
    dp.include_router(owner_router)
    dp.include_router(user_router)
    dp.errors.register(on_error)

    asyncio.create_task(vip_expiry_loop(bot))
    await db.add_log(None, "bot_start", "")

    while True:  # polling uzilsa qayta ulanadi
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            break
        except Exception as exc:  # noqa: BLE001
            log.error("Polling to'xtadi: %s. 5 soniyadan keyin qayta uriniladi.", exc)
            await asyncio.sleep(5)

    await bot.session.close()
    await db.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot to'xtatildi")
