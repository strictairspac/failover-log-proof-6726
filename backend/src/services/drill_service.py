from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import Scenario, Drill
from src.services.node_service import list_nodes
from src.utils.serialize import record

def create_drill(db, payload):
    scenario = db.get(Scenario, payload.scenario_id)
    if not scenario: raise HTTPException(404, '故障剧本不存在')
    pending = db.scalars(select(Drill.id).where(Drill.status.in_(['queued','running']))).all()
    if len(pending) >= 20: raise HTTPException(429, '队列配额20已满，请稍后重试')
    obj = Drill(scenario_id=scenario.id, label=payload.label, status='queued',
                snapshot={'nodes': list_nodes(db), 'scenario': record(scenario)})
    db.add(obj); db.flush(); return obj

def list_drills(db): return [record(d) for d in db.scalars(select(Drill).order_by(Drill.id.desc()).limit(100))]
def get_drill(db, drill_id):
    obj = db.get(Drill, drill_id)
    if obj is None: raise HTTPException(404, '演练不存在')
    return obj
