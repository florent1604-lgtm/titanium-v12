"""Route read-only du consensus trois moteurs."""
from fastapi import APIRouter

from core.consensus_engine import status_snapshot


router = APIRouter(tags=["consensus"])


@router.get("/consensus/status")
async def consensus_status():
    """Dernières observations inter-moteurs. Ne décide et n'exécute rien."""
    return status_snapshot()
