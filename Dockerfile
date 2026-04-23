# LarkMentor v4 · Production container
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
# Install node for @larksuite/cli + lark-mcp (npx runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates tini \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @larksuite/cli 2>&1 | tail -3 || true \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
COPY . .

# Pre-install 22 skills (best-effort)
RUN npx skills add larksuite/cli -y -g 2>&1 | tail -3 || echo "skills add skipped"

EXPOSE 8001 8002 8767
ENV LARKMENTOR_HOME=/data/larkmentor
ENV LARKMENTOR_USE_V3_MAIN_CHAIN=1
VOLUME ["/data"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "run_services.sh"]
