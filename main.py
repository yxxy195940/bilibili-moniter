"""程序入口 — 启动监控 + Telegram Bot 命令处理"""
import asyncio
import logging
import os
import sys

import yaml
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src import storage as db
from src.bilibili_api import BilibiliAPI
from src.monitor import Monitor
from src.notifier import TelegramNotifier

# ── 日志配置 ────────────────────────────────────────────────────────
os.makedirs("data", exist_ok=True)  # 确保 data/ 目录存在（日志文件需要）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

load_dotenv()


def load_config() -> dict:
    with open("config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 权限检查辅助 ────────────────────────────────────────────────────

def _authorized(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = ctx.bot_data.get("chat_id", "")
    return chat_id and str(update.effective_chat.id) == chat_id


# ── Telegram Bot 命令 ────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 你好 {user}！\n\n"
        f"🆔 你的 Chat ID 是：<code>{chat_id}</code>\n\n"
        "请将此 ID 填入 .env 文件的 CHAT_ID 字段，然后重启程序。",
        parse_mode="HTML",
    )
    logger.info("/start from chat_id=%s", chat_id)


async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"🆔 Chat ID: <code>{chat_id}</code>", parse_mode="HTML"
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update, ctx):
        return
    cfg = ctx.bot_data["cfg"]
    uid = cfg["uid"]
    interval = cfg["check_interval"]
    video_count = cfg["video_count"]
    init_videos = await db.get_videos_by_state(initialized=1)
    new_videos = await db.get_videos_by_state(initialized=0)

    text = (
        "📊 <b>监控状态</b>\n"
        f"👤 UP主 UID: <code>{uid}</code>\n"
        f"⏱ 轮询间隔: {interval}s\n"
        f"📹 监控视频数: {video_count}\n"
        f"✅ 已初始化视频: {len(init_videos)}\n"
        f"🆕 待初始化视频: {len(new_videos)}\n"
    )
    if init_videos:
        text += "\n<b>已监控视频：</b>\n"
        for v in init_videos[:5]:
            bvid = v["bvid"]
            vtitle = v["title"][:30]
            text += f"• <a href='https://www.bilibili.com/video/{bvid}'>{vtitle}</a>\n"

    await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)


async def cmd_fetch(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /fetch — 立即检查最新视频中 UP主 的新留言并推送（有去重，不会重复推送）。
    """
    if not _authorized(update, ctx):
        await update.message.reply_text("❌ 无权限")
        return

    api: BilibiliAPI = ctx.bot_data["api"]
    notifier: TelegramNotifier = ctx.bot_data["notifier"]
    cfg: dict = ctx.bot_data["cfg"]
    uid: int = cfg["uid"]

    # 1. 获取最新视频
    status_msg = await update.message.reply_text("🔄 正在获取最新视频...")
    videos = await api.get_user_videos(uid, count=1)
    if not videos:
        await status_msg.edit_text("❌ 获取视频列表失败，请检查 Cookie 或稍后重试")
        return

    video = videos[0]
    title_short = video["title"][:35]
    bvid = video["bvid"]
    aid = video["aid"]
    url = f"https://www.bilibili.com/video/{bvid}"

    await status_msg.edit_text(
        f"📹 <a href='{url}'>{title_short}</a>\n⏳ 正在扫描UP主留言...",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # 2. 扫描UP主自己的留言
    all_comments = await api.get_up_own_comments(uid, aid, max_pages=20)

    if not all_comments:
        await status_msg.edit_text(
            f"📹 <a href='{url}'>{title_short}</a>\n\n😶 未找到UP主在该视频下的留言",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    await status_msg.edit_text(
        f"📹 <a href='{url}'>{title_short}</a>\n\n"
        f"✅ 找到 {len(all_comments)} 条UP主留言，推送中...",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # 3. 推送所有留言
    pushed = 0
    for comment in all_comments:
        ok = await notifier.send_comment(video, comment)
        if ok:
            pushed += 1
        await asyncio.sleep(1)

    # 5. 同步确保视频在 DB 中已初始化（以防自动监控未处理过此视频）
    if not await db.video_exists(aid):
        await db.add_video(video, initialized=1)
    else:
        await db.set_video_initialized(aid)

    await update.message.reply_text(f"🎉 推送完成！本次推送 {pushed} 条新UP主留言")
    logger.info("/fetch done: %d new UP主 comments pushed for %s", pushed, bvid)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Bilibili 评论监控 Bot</b>\n\n"
        "/fetch  — 立即拉取最新视频中UP主自己的留言\n"
        "/status — 查看监控状态\n"
        "/id     — 查看 Chat ID\n"
        "/start  — 欢迎消息\n"
        "/help   — 本帮助",
        parse_mode="HTML",
    )


# ── 主程序 ─────────────────────────────────────────────────────────

async def main():
    cfg = load_config()["monitor"]

    token = os.getenv("BOT_TOKEN", "")
    chat_id = os.getenv("CHAT_ID", "")
    sessdata = os.getenv("SESSDATA", "")
    bili_jct = os.getenv("BILI_JCT", "")

    if not token:
        logger.error("BOT_TOKEN 未设置，请检查 .env 文件")
        sys.exit(1)

    # 初始化数据库
    await db.init_db()

    # 构建 Telegram Application
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("fetch", cmd_fetch))

    if not chat_id:
        logger.warning("CHAT_ID 未设置！向 Bot 发送 /id 获取 Chat ID，填入 .env 后重启。")
        await app.run_polling()
        return

    # 初始化推送器 & API，存入 bot_data 供命令处理器使用
    api = BilibiliAPI(
        sessdata=sessdata,
        bili_jct=bili_jct,
        buvid3=os.getenv("BUVID3", ""),
        delay_range=tuple(cfg.get("request_delay", [1.5, 3])),
    )
    notifier = TelegramNotifier(token=token, chat_id=chat_id)

    app.bot_data["api"] = api
    app.bot_data["notifier"] = notifier
    app.bot_data["cfg"] = cfg
    app.bot_data["chat_id"] = chat_id

    monitor = Monitor(
        uid=cfg["uid"],
        api=api,
        notifier=notifier,
        video_count=cfg["video_count"],
        check_interval=cfg["check_interval"],
        active_time=cfg.get("active_time"),
    )

    # 并发运行：Telegram Bot + 监控循环
    async with app:
        await app.start()
        await app.updater.start_polling()
        logger.info("Telegram Bot started (polling)")

        try:
            await monitor.run()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Shutting down...")
        finally:
            monitor.stop()
            await api.close()
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
