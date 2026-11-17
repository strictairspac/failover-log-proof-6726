from pydantic import BaseModel, Field
class ScenarioInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    fail_primary: bool = True
    fence_primary: bool = True
    max_data_loss: int = Field(ge=0, le=1000000, default=0)
    required_term: int = Field(ge=1, le=1000000, default=7)
