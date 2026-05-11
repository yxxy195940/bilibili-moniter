"""验证动态API数据结构"""
import asyncio, os, urllib.parse, time, httpx
from dotenv import load_dotenv
load_dotenv()

cookies = {
    "SESSDATA": urllib.parse.unquote(os.getenv("SESSDATA", "")),
    "bili_jct": os.getenv("BILI_JCT", ""),
    "buvid3": os.getenv("BUVID3", ""),
    "b_nut": str(int(time.time())),
}
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}


async def main():
    async with httpx.AsyncClient(headers=headers, cookies=cookies, timeout=15) as c:
        r = await c.get(
            "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
            params={"host_mid": 1671203508, "timezone_offset": -480},
        )
        d = r.json()
        print("HTTP:", r.status_code, "| code:", d.get("code"))
        items = d.get("data", {}).get("items", [])
        print("Total items:", len(items))
        count = 0
        for it in items:
            if it.get("type") != "DYNAMIC_TYPE_AV":
                continue
            m = it.get("modules", {})
            arc = m.get("module_dynamic", {}).get("major", {}).get("archive", {})
            auth = m.get("module_author", {})
            bvid = arc.get("bvid", "N/A")
            aid = arc.get("aid", "N/A")
            pub_ts = auth.get("pub_ts", 0)
            title = arc.get("title", "")[:35]
            print(f"  >> bvid={bvid} aid={aid} pub_ts={pub_ts} | {title}")
            count += 1
        print(f"\n找到 {count} 个视频动态")


asyncio.run(main())
