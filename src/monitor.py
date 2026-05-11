"""核心监控逻辑 — 只推送 UP主自己在最新视频下的留言"""
import asyncio
import logging
import time
from datetime import datetime

from . import storage as db
from .bilibili_api import BilibiliAPI
from .notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(
        self,
        uid: int,
        api: BilibiliAPI,
        notifier: TelegramNotifier,
        video_count: int = 5,
        check_interval: int = 180,
        active_time: dict = None,
    ):
        self.uid = uid
        self.api = api
        self.notifier = notifier
        self.video_count = video_count
        self.check_interval = check_interval
        self.active_time = active_time
        self._running = False
        self.consecutive_failures = 0
        self.max_retries_before_notify = 3

    # ── 主循环 ───────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        logger.info("Monitor started | uid=%s interval=%ds", self.uid, self.check_interval)
        
        status_msg = f"监控已启动 🚀\nUID: {self.uid}\n轮询间隔: {self.check_interval}s\n"
        if self.active_time:
            status_msg += f"活跃时间: {self.active_time.get('start')} - {self.active_time.get('end')}\n"
        status_msg += "说明：只推送 UP主自己在最新视频下的留言"
        
        await self.notifier.send_status(status_msg)

        while self._running:
            if self._is_outside_active_time():
                logger.debug("Outside active time, skip cycle. Sleep %ds", self.check_interval)
                await asyncio.sleep(self.check_interval)
                continue

            start = time.monotonic()
            success = False
            try:
                await self._cycle()
                success = True
            except Exception as e:
                logger.exception("Cycle error: %s", e)
            
            elapsed = time.monotonic() - start
            
            if success:
                if self.consecutive_failures > 0:
                    logger.info("Recovered from failures.")
                    await self.notifier.send_status("✅ 监控恢复正常")
                self.consecutive_failures = 0
                sleep_for = max(0, self.check_interval - elapsed)
            else:
                self.consecutive_failures += 1
                # 指数退避：如果设为 180s，失败后 180, 360, 720... 最大限制比如 3600s
                backoff_time = min(3600, self.check_interval * (2 ** (self.consecutive_failures - 1)))
                sleep_for = max(0, backoff_time - elapsed)
                
                if self.consecutive_failures == self.max_retries_before_notify:
                    await self.notifier.send_status(
                        f"⚠️ <b>监控连续失败 {self.consecutive_failures} 次</b>\n"
                        f"已启用指数退避 ({int(sleep_for)}s 后重试)。\n"
                        f"可能遇到反爬或网络错误，请检查服务器日志。"
                    )
            
            logger.debug("Cycle done in %.1fs, sleep %.1fs", elapsed, sleep_for)
            await asyncio.sleep(sleep_for)

    def _is_outside_active_time(self) -> bool:
        if not self.active_time:
            return False
        start_str = self.active_time.get("start")
        end_str = self.active_time.get("end")
        if not start_str or not end_str:
            return False
            
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            return not (start_str <= current_time <= end_str)
        except Exception as e:
            logger.error("Failed to parse active_time: %s", e)
            return False

    def stop(self):
        self._running = False

    # ── 单次轮询 ─────────────────────────────────────────────────────

    async def _cycle(self):
        """
        一次完整检查：
        1. 拉取最新视频列表
        2. 只处理最新一个视频
        3. 新视频：静默初始化（标记 UP主已有留言为 seen，不推送）
        4. 已知视频：拉取 UP主新留言并推送
        """
        videos = await self.api.get_user_videos(self.uid, self.video_count)
        if not videos:
            logger.warning("No videos returned, skip cycle")
            return

        # 只处理最新一个视频
        latest = videos[0]
        aid = latest["aid"]

        if not await db.video_exists(aid):
            # ── 新视频：静默初始化 UP主留言缓存 ──
            logger.info("New video: [%s] %s", latest["bvid"], latest["title"])
            await db.add_video(latest, initialized=0)

            # 只获取并标记 UP主自己的留言（不推送）
            up_comments = await self.api.get_up_own_comments(self.uid, aid)
            if up_comments:
                rpids = [c["rpid"] for c in up_comments]
                await db.bulk_mark_seen(rpids, aid)
                logger.info(
                    "Video initialized, %d UP主 comment(s) marked seen (not pushed)",
                    len(rpids),
                )
            else:
                logger.info("Video initialized, no UP主 comments found yet")

            await db.set_video_initialized(aid)

        else:
            # ── 已知视频：推送 UP主新留言 ──
            await self._push_new_up_comments(latest)

    async def _push_new_up_comments(self, video: dict):
        """
        拉取 UP主在该视频下的所有留言，过滤已推送的，推送新的。
        使用 seen_comments 表去重。
        """
        aid = video["aid"]
        up_comments = await self.api.get_up_own_comments(self.uid, aid)
        new_count = 0

        for comment in up_comments:
            rpid = comment["rpid"]
            if await db.is_comment_seen(rpid):
                continue  # 已推送过，跳过

            ok = await self.notifier.send_comment(video, comment)
            if ok:
                await db.mark_comment_seen(rpid, aid)
                new_count += 1
                await asyncio.sleep(1)  # 推送间隔，避免 TG 限速

        if new_count:
            logger.info("[%s] Pushed %d new UP主 comment(s)", video["bvid"], new_count)
        else:
            logger.debug("[%s] No new UP主 comments", video["bvid"])
