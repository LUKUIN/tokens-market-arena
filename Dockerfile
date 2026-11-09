# Tokens 交易市场 · AI 版 —— 最小运行镜像
#
# 用途：在没有桌面环境的地方（CI、容器、纯 SSH）跑无头服务。
#   docker build -t tokens-market-arena .
#   docker run --rm -p 8734:8734 tokens-market-arena
#
# 说明：
#   · 镜像里只有源码与标准库，没有 .pyc 成品包；data/ 在首次启动时自行生成。
#   · 容器没有窗口系统，所以固定带 --headless。
#   · 无活动自动收尾默认关闭（TM_IDLE_ABORT=0）：容器里的等待往往意味着
#     Agent 正在思考，不该被当成「没人操作」。需要人类式保护时显式覆盖。
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TM_PORT=8734 \
    TM_IDLE_ABORT=0

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8734

CMD ["python", "run.py", "--headless"]
