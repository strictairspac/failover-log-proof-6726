from sqlalchemy import select
from src.models.entities import Scenario
from src.utils.serialize import record

def list_scenarios(db): return [record(s) for s in db.scalars(select(Scenario).order_by(Scenario.id))]
def create_scenario(db, payload):
    obj = Scenario(**payload.model_dump()); db.add(obj); db.flush(); return record(obj)
