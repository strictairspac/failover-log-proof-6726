from fastapi import APIRouter, Depends
from src.config.database import get_db
from src.middlewares.auth import current_user, writable
from src.schemas.scenario import ScenarioInput
from src.services.scenario_service import list_scenarios, create_scenario
from src.controllers.actions import audit
router = APIRouter()
@router.get('/scenarios')
def listing(db=Depends(get_db), user=Depends(current_user)): return list_scenarios(db)
@router.post('/scenarios', status_code=201)
def create(data: ScenarioInput, db=Depends(get_db), user=Depends(writable)):
    out = create_scenario(db, data); audit(db, user, 'scenario:create'); db.commit(); return out
