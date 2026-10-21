FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* && useradd -m app
COPY pyproject.toml ./
COPY src ./src
# long timeout and retries: some wheels (xgboost pulls a ~200 MB CUDA library) time out on slow links
RUN pip install --no-cache-dir --default-timeout=300 --retries 10 ".[serve,live]"
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"
CMD ["uvicorn", "pulsetrader.serve.app:app", "--host", "0.0.0.0", "--port", "8000"]
