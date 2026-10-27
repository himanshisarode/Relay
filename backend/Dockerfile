FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .
RUN useradd --create-home relay && chown -R relay /app
USER relay

EXPOSE 8000
CMD ["sh", "start.sh"]
