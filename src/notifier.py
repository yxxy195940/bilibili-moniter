"""Telegram 消息推送封装"""
import logging
import asyncio
from datetime import datetime

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError

logger = logging.getLogger(__name__)


def _fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.bot = Bot(token=token)
        self.chat_id = chat_id

    async def send(self, text: str) -> bool:
        """发送消息，自动处理限速重试"""
        for attempt in range(3):
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                return True
            except RetryAfter as e:
                logger.warning("Telegram rate limit, sleep %.1fs", e.retry_after)
                await asyncio.sleep(e.retry_after + 1)
            except TelegramError as e:
                logger.error("Telegram error: %s", e)
                await asyncio.sleep(2 ** attempt)
        return False

    async def send_comment(self, video: dict, comment: dict) -> bool:
        """推送视频新评论通知"""
        bvid = video["bvid"]
        title = video["title"][:40]
        uname = comment["uname"]
        content = comment["content"][:300]
        ctime = _fmt_time(comment["ctime"])
        url = f"https://www.bilibili.com/video/{bvid}"

        # 区分消息类型
        if comment.get("is_up_self"):
            header = "🎤 UP主亲自留言"
        elif comment.get("is_reply"):
            header = f'↩️ 回复 <b>{comment["reply_to"]}</b>'
        elif comment.get("is_top"):
            header = "📌 置顶评论"
        else:
            header = "💬 新评论"

        text = (
            f"🎬 <b>{title}</b>\n"
            f"{header}\n"
            f"👤 <b>{uname}</b>\n"
            f"📝 {content}\n"
            f"🕐 {ctime}\n"
            f'🔗 <a href="{url}">{bvid}</a>'
        )
        return await self.send(text)

    async def send_status(self, text: str) -> bool:
        """推送系统状态消息"""
        return await self.send(f"ℹ️ <b>[系统]</b> {text}")
