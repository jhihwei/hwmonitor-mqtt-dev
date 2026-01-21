# syntax=docker/dockerfile:1
FROM python:3.11-slim

# 更小鏡像 & 安裝依賴
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 可選：timezone（若要）
# RUN ln -snf /usr/share/zoneinfo/Asia/Taipei /etc/localtime && echo Asia/Taipei > /etc/timezone

# 安裝必要套件與硬體監控工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    intel-gpu-tools \
    pciutils \
    procps \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir psutil paho-mqtt python-dotenv

# 複製程式
WORKDIR /app
COPY agent_sender_async.py /app/agent.py

# 預設執行
CMD ["python", "/app/agent.py"]
