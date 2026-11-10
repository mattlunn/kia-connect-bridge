FROM python:3.15-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /bin/uv

# The environment belongs to the bridge user, so entrypoint.sh can install a different
# library version into it at startup.
RUN useradd --system --uid 1000 bridge && mkdir /app /data && chown bridge /app /data
USER bridge

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_CACHE_DIR=/tmp/uv-cache

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache

COPY kia_connect_bridge ./kia_connect_bridge
COPY entrypoint.sh ./

ENV PATH="/app/.venv/bin:$PATH" DATA_DIR=/data
VOLUME /data
EXPOSE 8000

# Leaves time for entrypoint.sh to install HYUNDAI_KIA_CONNECT_API_VERSION.
HEALTHCHECK --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

ENTRYPOINT ["./entrypoint.sh"]
CMD ["uvicorn", "kia_connect_bridge.app:main", "--factory", "--host", "0.0.0.0", "--port", "8000"]
