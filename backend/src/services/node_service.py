from sqlalchemy import select
from src.models.entities import Node
from src.utils.serialize import record

def list_nodes(db): return [record(n) for n in db.scalars(select(Node).order_by(Node.id))]
def save_node(db, payload, node_id=None):
    node = db.get(Node, node_id) if node_id else Node()
    if node is None: return None
    for k, v in payload.model_dump().items(): setattr(node, k, v)
    db.add(node); db.flush()
    return record(node)
