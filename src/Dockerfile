FROM python:3.9-slim
ENV TZ="Asia/Seoul"
WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .



# Log the current time after container start
CMD ["python","-u","main.py"]
