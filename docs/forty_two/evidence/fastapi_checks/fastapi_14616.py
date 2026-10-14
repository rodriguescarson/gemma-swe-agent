# The check the red-first rule asks for, written from the issue text only (its example: Json[list[str]] sent through Form()).
# ISSUE = the result the issue asks for (must fail at base); ORDINARY = one ordinary call the fix must not alter.
from typing import Annotated, List

from fastapi import FastAPI, Form
from fastapi.testclient import TestClient
from pydantic import Json

app = FastAPI()


@app.post("/upload")
def upload(tags: Annotated[Json[List[str]], Form()]):
    return {"tags": tags}


@app.post("/plain")
def plain(items: Annotated[List[str], Form()]):
    return {"items": items}


c = TestClient(app, raise_server_exceptions=False)
r = c.post("/upload", data={"tags": '["abc", "def"]'})
issue = r.status_code == 200 and r.json() == {"tags": ["abc", "def"]}
r2 = c.post("/plain", data={"items": ["a", "b"]})
ordinary = r2.status_code == 200 and r2.json() == {"items": ["a", "b"]}
print("ISSUE", "ok" if issue else "FAIL", r.status_code, r.text[:120])
print("ORDINARY", "ok" if ordinary else "FAIL", r2.status_code, r2.text[:120])
raise SystemExit(0 if issue and ordinary else 1)
