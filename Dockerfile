FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY kia_connect_bridge ./kia_connect_bridge

RUN useradd --system --uid 1000 bridge && mkdir /data && chown bridge /data
USER bridge

ENV PATH="/app/.venv/bin:$PATH" DATA_DIR=/data
VOLUME /data
EXPOSE 8000

HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "kia_connect_bridge.app:main", "--factory", "--host", "0.0.0.0", "--port", "8000"]
