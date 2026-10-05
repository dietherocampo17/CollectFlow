FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
		PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
		&& useradd --create-home --uid 10001 app

COPY --chown=app:app . /app

USER app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
	CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8001/health', timeout=3)"

CMD ["python3", "server.py"]
