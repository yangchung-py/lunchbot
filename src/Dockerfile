FROM python:3.9-slim

ENV TZ="Asia/Seoul"
ENV IG_USERNAME=${IG_USERNAME}
ENV IG_PASSWORD=${IG_PASSWORD}

WORKDIR /app

# Git 설치 및 저장소 클론
RUN apt-get update && \
    apt-get install -y git && \
    git clone https://github.com/yangchung-py/lunchbot.git && \
    cp -r lunchbot/src/* . && \
    pip install -r requirements.txt && \
    rm -rf lunchbot && \
    apt-get remove -y git && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 실행
CMD ["python", "-u", "main.py"]
