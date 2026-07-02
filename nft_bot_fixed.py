import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, BotCommand, MenuButtonCommands
from aiogram.enums import 8"

DISPLAY_TZ = timezone(timedelta(hours=3))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

state: dict[int, dict] = {}

def truncate_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)

def fmt_time(dt_utc: datetime) -> str:
    return dt_utc.astimezone(DISPLAY_TZ).strftime("%H:%M")

async def is_admin(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)
    except Exception:
        return False

def is_service_message(message: Message) -> bool:
    service_fields = [
        message.new_chat_members,
        message.left_chat_member,
        message.new_chat_title,
        message.new_chat_photo,
        message.delete_chat_photo,
        message.group_chat_created,
        message.pinned_message,
        message.migrate_to_chat_id,
        message.migrate_from_chat_id,
    ]
    return any(service_fields)

async def schedule_winner_check(chat_id: int, leader_minute: datetime):
    target = leader_minute + timedelta(minutes=3)
    now = datetime.now(timezone.utc)
    delay = (target - now).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)

    info = state.get(chat_id)
    if not info:
        return

    if info["leader_minute"] == leader_minute:
        try:
            if info["announce_msg_id"]:
                await bot.delete_message(chat_id, info["announce_msg_id"])
        except Exception:
            pass

        prize = info.get("prize")
        prize_part = f" Приз: {prize}!" if prize else ""
        text = (
            f'🎁 @{info["leader_name"]} продержался(ась) 3 минуты без перебивания '
            f'(с {fmt_time(leader_minute)}) — забирай!{prize_part}'
        )
        await bot.send_message(chat_id, text)
        info["active"] = False
        info["prize"] = None
        info["announce_msg_id"] = None
        info["leader_id"] = None
        info["leader_name"] = None
        info["leader_minute"] = None
        info["task"] = None

@dp.message(CommandStart())
async def start_command(message: Message):
    text = (
        "👋 Привет! Я бот конкурса «Кто продержится 3 минуты».\n\n"
        "🎁 Получите NFT\n"
        "Автор сообщения, после которого не будет новых сообщений 3 минуты, "
        "получает NFT.\n\n"
        "Например: сообщение в 14:25 должно продержаться до 14:28\n"
        "⏱ Секунды не считаем, смотрим только на минуты отправки.\n"
        "Удалённые сообщения участвуют.\n"
        "Сервисные сообщения и сообщения админов не участвуют.\n\n"
        "📋 Команды:\n"
        "/start_giveaway — запустить конкурс в группе\n"
        "/stop_giveaway — остановить конкурс\n"
        "/status — кто сейчас лидирует\n\n"
        "Добавь меня в группу и сделай админом с правом удаления сообщений, "
        "затем вызови /start_giveaway."
    )
    await message.reply(text)

@dp.message(F.chat.type.in_({"group", "supergroup"}), Command("status"))
async def status_giveaway(message: Message):
    chat_id = message.chat.id
    info = state.get(chat_id)

    if not info or not info["active"]:
        await message.reply("Конкурс сейчас не идёт. Запустить: /start_giveaway")
        return

    if info["leader_id"]:
        prize = info.get("prize")
        prize_part = f" | Приз: {prize}" if prize else ""
        await message.reply(
            f'Конкурс идёт. Сейчас лидирует @{info["leader_name"]} '
            f'(сообщение в {fmt_time(info["leader_minute"])}){prize_part}.'
        )
    else:
        await message.reply("Конкурс идёт, но ещё никто не написал — пиши первым!")

@dp.message(F.chat.type.in_({"group", "supergroup"}), Command("start_giveaway"))
async def start_giveaway(message: Message):
    chat_id = message.chat.id
    if not message.from_user or not await is_admin(chat_id, message.from_user.id):
        await message.reply("Только админ может запустить конкурс.")
        return

    info = state.setdefault(chat_id, {
        "active": False,
        "prize": None,
        "leader_id": None,
        "leader_name": None,
        "leader_minute": None,
        "announce_msg_id": None,
        "task": None,
    })
    if info["active"]:
        await message.reply("Конкурс уже идёт.")
        return

    parts = (message.text or "").split(maxsplit=1)
    prize = parts[1].strip() if len(parts) > 1 else None

    info["active"] = True
    info["prize"] = prize
    info["leader_id"] = None
    info["leader_name"] = None
    info["leader_minute"] = None
    info["announce_msg_id"] = None
    info["task"] = None

    prize_line = f"Приз: {prize}\n" if prize else ""
    await message.reply(
        f"🎁 Конкурс запущен!\n"
        f"{prize_line}"
        f"Чьё сообщение продержится 3 минуты без новых сообщений — тот получит приз.\n"
        f"Секунды не считаются, только минуты отправки."
    )

@dp.message(F.chat.type.in_({"group", "supergroup"}), Command("stop_giveaway"))
async def stop_giveaway(message: Message):
    chat_id = message.chat.id
    if not message.from_user or not await is_admin(chat_id, message.from_user.id):
        await message.reply("Только админ может остановить конкурс.")
        return

    info = state.get(chat_id)
    if not info or not info["active"]:
        await message.reply("Конкурс сейчас не идёт.")
        return

    info["active"] = False
    if info["task"]:
        info["task"].cancel()
        info["task"] = None
    if info["announce_msg_id"]:
        try:
            await bot.delete_message(chat_id, info["announce_msg_id"])
        except Exception:
            pass
        info["announce_msg_id"] = None

    await message.reply("⏹ Конкурс остановлен.")

@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_message(message: Message):
    chat_id = message.chat.id

    if is_service_message(message):
        return
    if not message.from_user or message.from_user.is_bot:
        return
    if await is_admin(chat_id, message.from_user.id):
        return

    msg_dt = message.date
    if msg_dt.tzinfo is None:
        msg_dt = msg_dt.replace(tzinfo=timezone.utc)
    else:
        msg_dt = msg_dt.astimezone(timezone.utc)
    minute = truncate_to_minute(msg_dt)

    username = message.from_user.username or message.from_user.full_name

    info = state.setdefault(chat_id, {
        "active": False,
        "prize": None,
        "leader_id": None,
        "leader_name": None,
        "leader_minute": None,
        "announce_msg_id": None,
        "task": None,
    })

    if not info["active"]:
        return

    if info["task"]:
        info["task"].cancel()

    if info["announce_msg_id"]:
        try:
            await bot.delete_message(chat_id, info["announce_msg_id"])
        except Exception:
            pass

    info["leader_id"] = message.from_user.id
    info["leader_name"] = username
    info["leader_minute"] = minute

    sent = await message.reply(f'@{username} перебил(а) в {fmt_time(minute)}')
    info["announce_msg_id"] = sent.message_id

    info["task"] = asyncio.create_task(schedule_winner_check(chat_id, minute))

async def setup_commands():
    await bot.set_my_commands([
        BotCommand(command="start", description="👋 О боте и список команд"),
        BotCommand(command="start_giveaway", description="🎁 Запустить конкурс на NFT"),
        BotCommand(command="stop_giveaway", description="⏹ Остановить конкурс"),
        BotCommand(command="status", description="ℹ️ Статус текущего конкурса"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await bot.set_my_description(
        description=(
            "Конкурс «Кто продержится 3 минуты» 🎁\n"
            "Автор последнего сообщения в чате, после которого 3 минуты "
            "никто не писал, получает NFT.\n"
            "Нажми /start, чтобы узнать правила и команды."
        )
    )
    await bot.set_my_short_description(
        short_description="Бот конкурса на NFT: 3 минуты тишины после твоего сообщения — и оно твоё 🎁"
    )

async def main():
    await setup_commands()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
