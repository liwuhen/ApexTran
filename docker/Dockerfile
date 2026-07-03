# NOTE: build context must be the repo ROOT (not docker/), so the COPY paths
# below resolve. Use `docker compose build` from the root, or `make docker-build`.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Update system and install base dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    wget \
    vim \
    sudo \
    procps \
    openssh-client \
    ca-certificates \
    tini

# Install development tools
RUN apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    nodejs \
    npm \
    golang \
    jq \
    htop \
    tree \
    unzip \
    protobuf-compiler \
    zip fd-find gh

# Install pnpm and OpenAI Codex CLI
RUN npm install -g pnpm && npm install -g @openai/codex

WORKDIR /app
# Install Python dependencies first (cached layer)
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY docker/dockerentry.sh ./dockerentry.sh
# Copy the full source and install
COPY backend ./backend
RUN uv sync --no-dev --no-editable && uv pip install "any-llm-sdk[gemini,xai]" && \
    chmod +x /app/dockerentry.sh

WORKDIR /workspace

# Keep in sync with backend/agent/settings.py:DEFAULT_HOME (~/.ApexTran).
VOLUME /root/.ApexTran

ENTRYPOINT ["/usr/bin/tini", "--"]

CMD ["/app/dockerentry.sh"]
