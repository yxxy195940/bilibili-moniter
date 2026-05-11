"""B站 API 封装 — 视频列表 + 评论区"""
import asyncio
import random
import logging
import time
import uuid
import urllib.parse
from typing import Optional

import httpx

from .wbi import WBISigner

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _make_buvid3() -> str:
    """生成伪造 buvid3（B站浏览器指纹Cookie，UUID格式）"""
    raw = uuid.uuid4().hex.upper()
    # 格式: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX infoc
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}infoc"


class BilibiliAPI:
    def __init__(self, sessdata: str, bili_jct: str, delay_range: tuple, buvid3: str = ""):
        self.delay_range = delay_range
        self.wbi = WBISigner()

        cookies = {
            # buvid3：优先使用从浏览器提取的真实值，否则用伪造UUID（可能被412）
            "buvid3": buvid3 if buvid3 else _make_buvid3(),
            "b_nut": str(int(time.time())),
        }
        if sessdata:
            # SESSDATA 从浏览器复制时是 URL 编码格式，必须先解码再设为 Cookie
            # 否则 httpx 会二次编码（%2C → %252C），导致 B站返回 -799
            cookies["SESSDATA"] = urllib.parse.unquote(sessdata)
        if bili_jct:
            cookies["bili_jct"] = bili_jct

        self.client = httpx.AsyncClient(
            headers=_HEADERS,
            cookies=cookies,
            timeout=15,
            follow_redirects=True,
        )

    async def close(self):
        await self.client.aclose()

    async def _delay(self):
        await asyncio.sleep(random.uniform(*self.delay_range))

    async def _get(self, url: str, params: dict, sign: bool = False, max_retries: int = 3) -> Optional[dict]:
        """发起 GET 请求，自带指数退避重试，失败抛出异常"""
        for attempt in range(max_retries + 1):
            try:
                if sign:
                    req_params = await self.wbi.sign(params, self.client)
                else:
                    req_params = params
                resp = await self.client.get(url, params=req_params)
                
                try:
                    body = resp.json()
                except Exception:
                    logger.error("Non-JSON response: HTTP %d | %s", resp.status_code, url)
                    if resp.status_code in [412, 403]:
                        raise RuntimeError(f"IP 疑似被风控 (HTTP {resp.status_code})")
                    if attempt < max_retries:
                        await asyncio.sleep(2 ** attempt * 2)
                        continue
                    raise RuntimeError(f"Non-JSON response: HTTP {resp.status_code}")
                    
                code = body.get("code", -1)
                if code != 0:
                    logger.warning(
                        "API error: HTTP %d code=%s msg=%s | %s",
                        resp.status_code, code, body.get("message"), url,
                    )
                    # 权限不足等业务错误直接抛出，无需重试
                    if code in [-412, -403, -799]:
                        raise RuntimeError(f"B站风控或权限拒绝: code={code}")
                    if attempt < max_retries:
                        await asyncio.sleep(2 ** attempt * 2)
                        continue
                    raise RuntimeError(f"API Error code {code}")
                    
                return body.get("data")
            except Exception as e:
                logger.error("Request failed: %s | %s (attempt %d/%d)", url, e, attempt + 1, max_retries + 1)
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt * 2)
                    continue
                raise
        return None

    # ── 视频列表 ────────────────────────────────────────────────────
    async def get_user_videos(self, uid: int, count: int = 5) -> list[dict]:
        """
        获取 UP 主最新 N 个视频，通过动态 API 实现。
        动态 API 不受 /x/space/arc/search 的 IP 风控影响。
        筛选 type=DYNAMIC_TYPE_AV（视频投稿）的动态条目。
        """
        data = await self._get(
            "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
            params={"host_mid": uid, "timezone_offset": -480},
            sign=False,
        )
        if not data:
            return []

        result = []
        for item in data.get("items", []):
            # 只要视频投稿类型
            if item.get("type") != "DYNAMIC_TYPE_AV":
                continue
            modules = item.get("modules", {})
            archive = modules.get("module_dynamic", {}).get("major", {}).get("archive", {})
            if not archive:
                continue
            author = modules.get("module_author", {})

            bvid = archive.get("bvid", "")
            aid = archive.get("aid", 0)
            # aid 字段有时是字符串
            try:
                aid = int(aid)
            except (ValueError, TypeError):
                aid = 0

            result.append({
                "aid": aid,
                "bvid": bvid,
                "title": archive.get("title", ""),
                "pubdate": int(author.get("pub_ts", 0)),  # 确保是 int
            })

            if len(result) >= count:
                break

        return result

    # ── 评论区 ──────────────────────────────────────────────────────
    async def get_up_own_comments(self, uid: int, aid: int, max_pages: int = 20) -> list[dict]:
        """
        扫描视频评论区，返回 UP 主（uid）自己发表的所有主评论。
        不含楼中楼，翻页直到找完或到达 max_pages。
        """
        found = []
        seen_rpids = set()

        for pn in range(1, max_pages + 1):
            await self._delay()
            data = await self._get(
                "https://api.bilibili.com/x/v2/reply/main",
                params={"type": 1, "oid": aid, "mode": 2, "ps": 20, "pn": pn},
            )
            if not data:
                break
                
            # 置顶评论在 top_replies 里，普通评论在 replies 里
            top_replies = data.get("top_replies") or []
            replies = data.get("replies") or []
            
            all_replies = top_replies + replies
            
            for r in all_replies:
                if r["mid"] == uid:
                    rpid = r["rpid"]
                    if rpid not in seen_rpids:
                        seen_rpids.add(rpid)
                        found.append({
                            "rpid": rpid,
                            "uid": r["mid"],
                            "uname": r["member"]["uname"],
                            "content": r["content"]["message"],
                            "ctime": r["ctime"],
                            "like": r.get("like", 0),
                            "is_up_self": True,
                        })

            if data.get("cursor", {}).get("is_end"):
                break
        return found

