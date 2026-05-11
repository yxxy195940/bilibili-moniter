"""WBI 签名模块 — B站反爬鉴权"""
import hashlib
import time
import urllib.parse
import logging
from functools import reduce
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# B站 WBI 密钥重排映射表（固定值）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


class WBISigner:
    """WBI 签名器，缓存密钥1小时"""

    def __init__(self):
        self._img_key: Optional[str] = None
        self._sub_key: Optional[str] = None
        self._expires: float = 0

    async def _fetch_keys(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/nav",
            timeout=10,
        )
        data = resp.json()
        wbi = data["data"]["wbi_img"]
        self._img_key = wbi["img_url"].rsplit("/", 1)[1].split(".")[0]
        self._sub_key = wbi["sub_url"].rsplit("/", 1)[1].split(".")[0]
        self._expires = time.time() + 3600
        logger.debug("WBI keys refreshed")

    async def get_keys(self, client: httpx.AsyncClient) -> tuple:
        if not self._img_key or time.time() >= self._expires:
            await self._fetch_keys(client)
        return self._img_key, self._sub_key

    def _mixin_key(self, img_key: str, sub_key: str) -> str:
        orig = img_key + sub_key
        return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]

    async def sign(self, params: dict, client: httpx.AsyncClient) -> dict:
        """对参数字典附加 wts + w_rid 签名"""
        img_key, sub_key = await self.get_keys(client)
        mixin_key = self._mixin_key(img_key, sub_key)

        params = dict(params)
        params["wts"] = int(time.time())
        params = dict(sorted(params.items()))

        # 按 B站规范拼接并 MD5
        qs = "&".join(
            f"{k}={urllib.parse.quote(str(v), safe='')}"
            for k, v in params.items()
        )
        params["w_rid"] = hashlib.md5((qs + mixin_key).encode()).hexdigest()
        return params
