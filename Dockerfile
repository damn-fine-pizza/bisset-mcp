FROM python:3.14-slim

WORKDIR /app

# Support two services: workflow_server (default) or mcp_server
ARG SERVICE=workflow_server

COPY orchestrator/ /app/orchestrator/
COPY adapters/ /app/adapters/
COPY requirements.txt /app/

RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx \
    && pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/workflow.db \
    WORKFLOW_SERVER_PORT=8765

RUN mkdir -p /data

CMD ["sh", "-c", \
     "if [ \"$SERVICE\" = 'mcp_server' ]; then python -m orchestrator.mcp_server; \
      else uvicorn orchestrator.workflow_server.app:app \
           --host 0.0.0.0 --port ${WORKFLOW_SERVER_PORT:-8765}; fi"]
