FROM python:3.12-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r orchestrator/workflow_server/requirements.txt || true
CMD ["python", "-m", "orchestrator.workflow_server"]
