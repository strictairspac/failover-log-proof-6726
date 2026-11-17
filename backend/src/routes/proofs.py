from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.config.database import get_db
from src.middlewares.auth import current_user, writable
from src.models.entities import ProofBatch
from src.schemas.proof import ProofBatchInput
from src.services.proof_service import ingest_batch, list_batches, store_status, chain_status
from src.controllers.actions import audit
from src.utils.serialize import record
router = APIRouter()
@router.get('/proofs')
def listing(db=Depends(get_db), user=Depends(current_user)): return list_batches(db)
@router.get('/proofs/status')
def status(db=Depends(get_db), user=Depends(current_user)): return store_status(db)
@router.post('/proofs', status_code=201)
def create(data: ProofBatchInput, db=Depends(get_db), user=Depends(writable)):
    try:
        out = ingest_batch(db, data)
        if not out['deduplicated']:
            audit(db, user, f"proof:ingest:{out['batch']['batch_key']}")
        db.commit()
    except IntegrityError:
        # A concurrent retry persisted the same batch_key first: recover by
        # returning the stored batch instead of duplicating segments.
        db.rollback()
        dup = db.scalar(select(ProofBatch).where(ProofBatch.batch_key == data.batch_key))
        if not dup: raise
        out = {'batch': record(dup), 'deduplicated': True,
               'chain': chain_status(db, data.node_name)}
    return out
