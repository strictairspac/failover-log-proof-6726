from pydantic import BaseModel, Field
from typing import Literal
class NodeInput(BaseModel):
    name: str = Field(min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    role: Literal['leader', 'follower']
    term: int = Field(ge=1, le=1000000)
    log_position: int = Field(ge=0, le=1000000000)
    available: bool = True
    fenced: bool = False
    vote_enabled: bool = True
