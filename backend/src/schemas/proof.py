import re
from pydantic import BaseModel, Field, model_validator

HEX64 = r'^[0-9a-f]{64}$'
class SegmentInput(BaseModel):
    position: int = Field(ge=1, le=1000000000)
    term: int = Field(ge=1, le=1000000)
    content: str = Field(min_length=1, max_length=500)
    prev_digest: str = Field(pattern=HEX64)
class ProofBatchInput(BaseModel):
    batch_key: str = Field(min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    node_name: str = Field(min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    committed_position: int = Field(ge=0, le=1000000000)
    committed_digest: str = Field(default='', max_length=64)
    segments: list[SegmentInput] = Field(min_length=1, max_length=200)
    @model_validator(mode='after')
    def check_committed_digest(self):
        if self.committed_position > 0 and not re.fullmatch(HEX64, self.committed_digest):
            raise ValueError('声明提交点需提供64位十六进制提交摘要')
        if self.committed_position == 0:
            self.committed_digest = ''
        return self
