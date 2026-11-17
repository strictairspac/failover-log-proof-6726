from fastapi import APIRouter, Depends, HTTPException
from src.config.database import get_db
from src.middlewares.auth import current_user, admin
from src.schemas.node import NodeInput
from src.services.node_service import list_nodes, save_node
from src.controllers.actions import audit
router = APIRouter()
@router.get('/nodes')
def listing(db=Depends(get_db), user=Depends(current_user)): return list_nodes(db)
@router.post('/nodes', status_code=201)
def create(data: NodeInput, db=Depends(get_db), user=Depends(admin)):
    out = save_node(db, data); audit(db, user, 'node:create'); db.commit(); return out
@router.put('/nodes/{node_id}')
def update(node_id: int, data: NodeInput, db=Depends(get_db), user=Depends(admin)):
    out = save_node(db, data, node_id)
    if out is None: raise HTTPException(404, '节点不存在')
    audit(db, user, f'node:update:{node_id}'); db.commit(); return out
