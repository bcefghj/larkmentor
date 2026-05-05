# Agent-Pilot v9 · Multi-stage production container

# Stage 1: Python dependencies
FROM python:3.12-slim AS python-deps
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Node.js tools (Feishu CLI)
FROM node:20-slim AS node-deps
RUN npm install -g @larksuite/cli 2>/dev/null || true

# Stage 3: Production image
FROM python:3.12-slim AS production
LABEL maintainer="Agent-Pilot Team"
LABEL version="9.0.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    tini ca-certificates curl \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy Python deps
COPY --from=python-deps /install /usr/local

# Copy Node.js (for Feishu CLI)
COPY --from=node-deps /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node-deps /usr/local/bin/node /usr/local/bin/node
RUN ln -sf /usr/local/lib/node_modules/.bin/* /usr/local/bin/ 2>/dev/null || true

# App code
WORKDIR /app
COPY . .

ENV AGENT_PILOT_HOME=/data/agent-pilot
ENV AGENT_PILOT_DEMO_MODE=false
ENV PATH=/usr/local/bin:$PATH

VOLUME ["/data"]

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')" || exit 1

EXPOSE 8001 8002 8767

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "run_services.sh"]
