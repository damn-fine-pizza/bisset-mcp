FROM python:3.12-slim

WORKDIR /app

# Support two services: workflow_server (default) or mcp_server
ARG SERVICE=workflow_server

COPY claude/ /app/

# Install shared requirements + service-specific requirements
RUN pip install --no-cache-dir \
        fastapi \
        uvicorn[standard] \
        httpx \
    && pip install --no-cache-dir -r requirements.txt 2>/dev/null || true

ENV PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/workflow.db \
    WORKFLOW_SERVER_PORT=8765

# Create the data directory for the SQLite volume mount
RUN mkdir -p /data

# The SERVICE arg selects which module to run; the compose file overrides CMD
# per service using the command: key.
CMD ["sh", "-c", \
     "if [ \"$SERVICE\" = 'mcp_server' ]; then python -m orchestrator.mcp_server; \
      else uvicorn orchestrator.workflow_server.app:app \
           --host 0.0.0.0 --port ${WORKFLOW_SERVER_PORT:-8765}; fi"]
