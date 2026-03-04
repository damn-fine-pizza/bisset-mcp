"""Run workflow_server with uvicorn."""
import uvicorn
import os

if __name__ == '__main__':
    port = int(os.environ.get('WORKFLOW_PORT', '8765'))
    uvicorn.run('orchestrator.workflow_server.app:app', host='127.0.0.1', port=port, reload=True)
