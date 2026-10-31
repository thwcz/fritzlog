FROM python:3.12-alpine

RUN apk add --no-cache tzdata

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Berlin

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY fritzlog.py .

RUN addgroup -S app && adduser -S app -G app \
    && mkdir -p /data \
    && chown -R app:app /app /data

VOLUME ["/data"]

CMD ["python", "-u", "fritzlog.py"]
