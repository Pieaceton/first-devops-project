FROM python:3.12-slim

WORKDIR /app

# Приложение запускается от непривилегированного пользователя.
RUN useradd --create-home --uid 10001 appuser

COPY main.py ./

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"

CMD ["python", "main.py"]
