# apextran-app — one image, two roles (serve / worker) chosen by `command`.
FROM python:3.12-slim

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install deps first (better layer caching). The service is a uv workspace
# member; copying the whole repo keeps the workspace resolvable.
COPY . /app
RUN uv sync --package apextran-app --extra redis --extra sources --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    APP_HOST=0.0.0.0 \
    APP_PORT=8100

EXPOSE 8100

# Default to the API role; compose overrides `command` for the worker.
CMD ["apextran-app", "serve"]
