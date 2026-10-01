"""Discord-бот: принимает жалобы из Mini App и показывает их в канале с кнопками.

Запускается в отдельном потоке внутри основного процесса (bot.py).
Переменные окружения:
    DISCORD_BOT_TOKEN  — токен бота (Discord Developer Portal → Bot → Token)
    DISCORD_CHANNEL_ID — ID канала, куда падают жалобы
"""

import asyncio
import logging
import os
import threading

import discord
from discord.ext import commands

from . import notify
from .moderation import (
    ban_user,
    close_active_chats,
    resolve_report,
    set_discord_sender,
)

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0") or 0)

# Discord ID модераторов, которым жалобы уходят в личку (видят только они).
# Если не заданы — фолбэк: общий канал DISCORD_CHANNEL_ID.
ADMIN_IDS = {
    int(x) for x in os.getenv("DISCORD_ADMIN_IDS", "").replace(" ", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

_channel = None


# --------------------------------------------------------------------------
# Кнопки модерации
# --------------------------------------------------------------------------

class ReportView(discord.ui.View):
    def __init__(self, report_id: int, accused_tg: int):
        super().__init__(timeout=None)
        self.report_id = report_id
        self.accused_tg = accused_tg

    async def _check(self, interaction: discord.Interaction) -> bool:
        if ADMIN_IDS:
            ok = interaction.user.id in ADMIN_IDS
            deny = "⛔ Разбирать жалобы может только модератор."
        else:
            perms = interaction.user.guild_permissions
            ok = perms.administrator or perms.manage_guild
            deny = "⛔ Разбирать жалобы может только модератор с правами администратора."
        if not ok:
            await interaction.response.send_message(deny, ephemeral=True)
        return ok

    @discord.ui.button(label="Забанить", style=discord.ButtonStyle.danger, emoji="⛔")
    async def ban_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        reason = f"жалоба #{self.report_id} через Discord"
        close_active_chats(self.accused_tg)
        ban_user(self.accused_tg, reason)
        notify.push(self.accused_tg, f"⛔ Ты заблокирован модератором.\nПричина: {reason}")
        resolve_report(self.report_id, "banned")

        await interaction.response.edit_message(
            content=f"⛔ **Забанен** — жалоба #{self.report_id} закрыта "
                    f"(модератор: {interaction.user})",
            view=None,
        )

    @discord.ui.button(label="Принято", style=discord.ButtonStyle.success, emoji="✅")
    async def ok_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        resolve_report(self.report_id, "done")
        await interaction.response.edit_message(
            content=f"✅ **Принято к сведению** — жалоба #{self.report_id} закрыта "
                    f"(модератор: {interaction.user})",
            view=None,
        )

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.secondary, emoji="❌")
    async def dismiss_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check(interaction):
            return
        resolve_report(self.report_id, "dismissed")
        await interaction.response.edit_message(
            content=f"❌ **Отклонена** — жалоба #{self.report_id} закрыта "
                    f"(модератор: {interaction.user})",
            view=None,
        )


# --------------------------------------------------------------------------
# Отправка жалобы (вызывается из потока Flask/бэкенда)
# --------------------------------------------------------------------------

def _build_embed(d: dict) -> tuple[str, discord.Embed]:
    content = "🚨 **Новая жалоба** " + (d.get("mention") or "")
    embed = discord.Embed(title=f"Жалоба #{d['report_id']}", color=0xE74C3C)
    embed.add_field(name="Кто пожаловался", value=d["reporter_label"], inline=True)
    embed.add_field(name="На кого", value=d["accused_label"], inline=True)
    embed.add_field(name="Чат", value=f"#{d['chat_id']}", inline=True)
    embed.add_field(name="Причина", value=d["reason"], inline=False)
    embed.add_field(name="Доказательства", value=d["evidence"] or "—", inline=False)
    embed.set_footer(text="Разбор — кнопками ниже")
    return content, embed


async def _send_report(d: dict):
    """Отправляет жалобу: ЛС модераторам (видят только они) → фолбэк в канал."""
    global _channel
    content, embed = _build_embed(d)

    # 1) ЛИЧНЫЕ СООБЩЕНИЯ модераторам — видит только тот, кому отправлено
    delivered = False
    for uid in sorted(ADMIN_IDS):
        try:
            user = await bot.fetch_user(uid)
            await user.send(
                embed=embed,
                view=ReportView(d["report_id"], d["accused_tg"]),
            )
            delivered = True
        except Exception as exc:
            logger.warning("Не удалось отправить ЛС %s: %s", uid, exc)
    if delivered:
        logger.info("Жалоба #%s отправлена в ЛС модераторам", d["report_id"])
        return
    if ADMIN_IDS:
        logger.warning("ЛС недоступны — пробуем канал")

    # 2) ФОЛБЭК: общий канал (если ЛС не заданы или закрыты)
    if not CHANNEL_ID:
        logger.warning("DISCORD_ADMIN_IDS и DISCORD_CHANNEL_ID не заданы — "
                       "жалоба #%s только в БД", d["report_id"])
        return
    if _channel is None:
        _channel = await bot.fetch_channel(CHANNEL_ID)
    await _channel.send(content=content, embed=embed,
                        view=ReportView(d["report_id"], d["accused_tg"]))


def submit_report(d: dict):
    """Вызывается из другого потока — ставит отправку в event loop бота."""
    asyncio.run_coroutine_threadsafe(_send_report(d), bot.loop)


@bot.event
async def on_ready():
    logger.info("Discord-бот запущен: %s", bot.user)
    set_discord_sender(submit_report)


def _run():
    if not BOT_TOKEN:
        return
    if not CHANNEL_ID:
        logger.warning("DISCORD_CHANNEL_ID не задан — жалобы не будут отправлены")
        return
    try:
        bot.run(BOT_TOKEN)  # блокирует поток, создаёт свой event loop
    except Exception:
        logger.exception("Discord-бот упал")


def start():
    """Запуск бота в фоновом потоке."""
    if not BOT_TOKEN:
        logger.info("DISCORD_BOT_TOKEN не задан — Discord-бот отключён "
                    "(работает webhook, если задан)")
        return
    threading.Thread(target=_run, daemon=True, name="discord-bot").start()
