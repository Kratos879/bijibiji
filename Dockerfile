FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
RUN useradd -m kejing && mkdir /app/data && chown kejing:kejing /app/data
USER kejing
ENV KEJING_DATA=/app/data
EXPOSE 8766
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8766"]
