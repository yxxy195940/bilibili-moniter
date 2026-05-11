"""SQLite 持久化 — 记录已监控视频 & 已推送评论，防重复"""
import aiosqlite
import logging
import time

logger = logging.getLogger(__name__)

DB_PATH = "data/monitor.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_videos (
    aid         INTEGER PRIMARY KEY,
    bvid        TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    pubdate     INTEGER NOT NULL,
    initialized INTEGER NOT NULL DEFAULT 0,
    added_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS seen_comments (
    rpid        INTEGER PRIMARY KEY,
    aid         INTEGER NOT NULL,
    pushed_at   INTEGER NOT NULL
);
"""


async def init_db():
    """建表（首次运行）"""
    import os
    os.makedirs("data", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()
    logger.info("Database ready: %s", DB_PATH)


# ── 视频 ────────────────────────────────────────────────────────────

async def video_exists(aid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM tracked_videos WHERE aid=?", (aid,))
        return await cur.fetchone() is not None


async def add_video(video: dict, initialized: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO tracked_videos VALUES (?,?,?,?,?,?)",
            (video["aid"], video["bvid"], video["title"],
             video["pubdate"], initialized, int(time.time())),
        )
        await db.commit()


async def set_video_initialized(aid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tracked_videos SET initialized=1 WHERE aid=?", (aid,)
        )
        await db.commit()


async def get_videos_by_state(initialized: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM tracked_videos WHERE initialized=? ORDER BY pubdate DESC",
            (initialized,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ── 评论 ────────────────────────────────────────────────────────────

async def is_comment_seen(rpid: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM seen_comments WHERE rpid=?", (rpid,))
        return await cur.fetchone() is not None


async def mark_comment_seen(rpid: int, aid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_comments VALUES (?,?,?)",
            (rpid, aid, int(time.time())),
        )
        await db.commit()


async def bulk_mark_seen(rpids: list[int], aid: int):
    """批量标记已见，用于初始化阶段"""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT OR IGNORE INTO seen_comments VALUES (?,?,?)",
            [(r, aid, now) for r in rpids],
        )
        await db.commit()
