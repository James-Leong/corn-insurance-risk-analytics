FROM python:3.12-slim
RUN pip install --no-cache-dir pipx \
    && PIPX_BIN_DIR=/usr/local/bin pipx install uv==0.6.2
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --extra inference
ENV PATH="/app/.venv/bin:$PATH"
COPY app ./app
COPY data ./data
COPY tools ./tools
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
