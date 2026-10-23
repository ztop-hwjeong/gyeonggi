FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/
WORKDIR /app/jobs/docker
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/jobs/docker/src \
    PATH="/app/jobs/docker/.venv/bin:$PATH"
COPY packages/http /app/packages/http
COPY jobs/docker/pyproject.toml jobs/docker/uv.lock ./
RUN uv sync --locked --no-dev
COPY jobs/docker/src ./src

CMD ["prefect", "version"]
