# Tokens Trading Market - AI edition: minimal runtime image
#
# Purpose: run the headless service where there is no desktop (CI, containers,
# plain SSH).
#   docker build -t tokens-market-arena .
#   docker run --rm -p 8734:8734 tokens-market-arena
#
# Notes:
#   - The image ships source and the standard library only, no .pyc bundle;
#     data/ is created on first start.
#   - Containers have no window system, so --headless is fixed.
#   - The idle abort is off by default (TM_IDLE_ABORT=0): waiting inside a
#     container usually means the agent is thinking, and that is not "nobody
#     acting". Override it explicitly if you want the human-style guard.
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
