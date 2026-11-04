FROM python:3.12-slim
WORKDIR /opt/callback
RUN pip install --no-cache-dir uv==0.11.8
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY services ./services
COPY fixtures ./fixtures
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENV EXECUTOR_CONFIG_PATH=/run/callback/config.json
USER 1000:1000
CMD ["/opt/callback/.venv/bin/uvicorn", "services.executor.app:app", "--host", "0.0.0.0", "--port", "8081", "--no-access-log"]
