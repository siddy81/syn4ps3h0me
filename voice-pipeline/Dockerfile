FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      libsndfile1 \
      libasound2 \
      portaudio19-dev \
      ffmpeg \
      alsa-utils \
      pulseaudio-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && python -c "import openwakeword.utils as u; u.download_models()"

COPY app /app/app

CMD ["python", "-m", "app.main"]
