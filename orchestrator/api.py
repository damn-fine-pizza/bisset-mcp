from fastapi import APIRouter

router = APIRouter()

@router.get('/api/health')
def health():
    return {'ok': True}

@router.get('/api/info')
def info():
    return {'project': 'BissetMCP', 'note': 'Use MCP tools for workflow operations.'}

