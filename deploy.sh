#!/bin/bash
set -e

echo "🚀 Starting Deployment for Bilibili Monitor..."

# 1. 确保位于项目目录
cd ~/bilibili-moniter

# 2. 检查并创建虚拟环境
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    PYTHON_CMD="python3"
    for py in python3.12 python3.11 python3.10 python3.9 python3.8; do
        if command -v $py &> /dev/null; then
            PYTHON_CMD=$py
            break
        fi
    done
    echo "Using $PYTHON_CMD for venv..."
    $PYTHON_CMD -m venv .venv
fi

# 3. 激活虚拟环境并安装依赖
echo "📦 Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 4. 重启服务
echo "🔄 Restarting service..."

# 检查是否存在 pm2
if command -v pm2 &> /dev/null; then
    pm2 restart bilibili-moniter || pm2 start main.py --name bilibili-moniter --interpreter .venv/bin/python
else
    # 尝试使用 systemd 重启（需要提前配置好 bilibili-moniter.service）
    echo "⚠️ PM2 not found, trying systemctl..."
    sudo systemctl restart bilibili-moniter || echo "❌ Failed to restart via systemctl. Please setup systemd or install pm2."
fi

echo "✅ Deployment finished successfully!"
