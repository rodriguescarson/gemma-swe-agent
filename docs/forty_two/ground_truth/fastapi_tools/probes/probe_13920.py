# Which PEP 695 alias uses fail at base (fastapi_13920)? Run with the task venv from the task workspace.
from typing import Annotated

from fastapi import Depends, FastAPI, Query
from fastapi.testclient import TestClient


def some_value() -> int:
    return 123


type PlainInt = int
type QueryInt = Annotated[int, Query(gt=0)]
type DepInt = Annotated[int, Depends(some_value)]

app = FastAPI()


@app.get("/plain")
def plain(q: PlainInt) -> int:
    return q


@app.get("/query")
def query(q: QueryInt) -> int:
    return q


@app.get("/dep")
def dep(v: DepInt) -> int:
    return v


c = TestClient(app)
for path in ("/plain?q=5", "/query?q=5", "/query?q=-1", "/dep"):
    r = c.get(path)
    print(path, r.status_code, r.text[:160])
