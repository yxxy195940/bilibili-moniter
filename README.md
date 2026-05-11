# Bilibili 评论监控 Bot — 操作指南

## 项目结构

```
bilibili-moniter/
├── main.py           # 程序入口
├── config.yaml       # 监控配置
├── .env              # 密钥配置（不要提交到Git！）
├── requirements.txt
├── data/             # 运行时生成：数据库 + 日志
└── src/
    ├── wbi.py        # B站WBI签名
    ├── bilibili_api.py  # B站API封装
    ├── storage.py    # SQLite去重
    ├── notifier.py   # Telegram推送
    └── monitor.py    # 监控逻辑
```

---

## 第一步：提取 B站 Cookie

> Cookie 用于模拟登录，避免频率限制。**强烈建议使用小号**。

### 操作步骤

1. 打开 Chrome/Edge 浏览器，访问 [https://www.bilibili.com](https://www.bilibili.com)
2. 登录你的 B 站账号
3. 按 **F12** 打开开发者工具
4. 切换到 **Application（应用程序）** 选项卡
5. 左侧展开 **Storage → Cookies → https://www.bilibili.com**
6. 在 Cookie 列表中找到：
   - `SESSDATA` → 复制其 **Value**
   - `bili_jct` → 复制其 **Value**
7. 将两个值填入项目根目录的 `.env` 文件：

```env
SESSDATA=你复制的SESSDATA值
BILI_JCT=你复制的bili_jct值
```

> ⚠️ Cookie 有效期约 1 个月，过期后需重新提取。

---

## 第二步：获取 Telegram Chat ID

1. 在 Telegram 中搜索并打开你的 Bot（Token 已配置）
2. 发送命令：`/id`
3. Bot 会回复类似：`🆔 Chat ID: 123456789`
4. 将该数字填入 `.env` 文件：

```env
CHAT_ID=123456789
```

**注意**：如果 Bot 没响应，先确认 CHAT_ID 为空时程序处于"Setup模式"（见下方步骤三）。

---

## 第三步：运行程序

### 首次运行（获取 Chat ID）

```powershell
cd d:\Code\project\bilibili-moniter
.\.venv\Scripts\python main.py
```

向 Bot 发送 `/id`，记录 Chat ID，填入 `.env`，然后 **Ctrl+C** 停止。

### 正式运行（监控模式）

`.env` 中 `CHAT_ID` 填好后再次运行：

```powershell
.\.venv\Scripts\python main.py
```

控制台会输出：
```
[INFO] Monitor started | uid=1671203508 interval=180s
[INFO] Telegram Bot started (polling)
```

---

## Bot 命令

| 命令 | 说明 |
|------|------|
| `/start` | 欢迎消息 + 显示 Chat ID |
| `/id` | 显示 Chat ID |
| `/status` | 查看当前监控状态和视频列表 |
| `/help` | 帮助信息 |

---

## 推送消息格式

**新评论通知：**
```
🎬 视频标题
💬 新评论
👤 用户昵称
📝 评论内容...
🕐 2025-05-11 14:30:00
🔗 BV1xxxxxx
```

**楼中楼回复：**
```
🎬 视频标题
↩️ 回复 原评论用户名
👤 回复者昵称
📝 回复内容...
```

---

## 轮询策略说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `check_interval` | 180s (3分钟) | 每轮检查间隔 |
| `comment_pages` | 2 | 每个视频拉取评论页数（每页20条） |
| `request_delay` | 1.5~3s | API请求间随机延迟 |
| `video_count` | 5 | 监控最新N个视频 |

每次轮询约需 15~20s（5个视频 × 2页 × 平均2s延迟），安全合理。

---

## 常见问题

**Q: 评论重复推送？**  
A: 重启后 SQLite 中的去重记录仍然保留，不会重复。若 `data/monitor.db` 被删除才会重置。

**Q: API 返回 -403 鉴权失败？**  
A: WBI 签名过期或 Cookie 失效，检查 `SESSDATA` 是否正确，重新提取。

**Q: Bot 不推送消息？**  
A: 确认 `CHAT_ID` 已填写且正确，查看 `data/monitor.log` 排查错误。

**Q: Cookie 多久过期？**  
A: B站 Cookie 一般 30 天，建议设置提醒定期更新。
