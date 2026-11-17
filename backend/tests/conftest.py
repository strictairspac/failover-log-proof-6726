import os
import sys
import tempfile
from pathlib import Path

_DB = Path(tempfile.gettempdir()) / f'hengshi-test-{os.getpid()}.db'
os.environ['DATABASE_URL'] = f'sqlite+pysqlite:///{_DB}'
os.environ['JWT_SECRET'] = 'test-secret'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from src.config.database import Base, engine, Session


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as session:
        yield session
    Base.metadata.drop_all(engine)
