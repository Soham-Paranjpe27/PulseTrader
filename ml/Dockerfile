FROM python:3.12-slim
WORKDIR /app
RUN useradd -m app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[serve]"
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"
CMD ["uvicorn", "pulsetrader.serve.app:app", "--host", "0.0.0.0", "--port", "8000"]
