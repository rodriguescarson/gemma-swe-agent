# The check the red-first rule asks for, written from the issue text only ("cache dependencies that don't use scopes and
# don't have sub-dependencies with scopes"; scopes still split the cache when a dependency declares them or reads
# SecurityScopes). ISSUE must fail at base; ORDINARY is behaviour the issue keeps.
from fastapi import Depends, FastAPI, Security
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient

calls = {"db": 0, "scoped": 0}


def get_db():
    calls["db"] += 1
    return "db"


def get_user(db: str = Depends(get_db)):
    return "user"


def read_scopes(security_scopes: SecurityScopes):
    calls["scoped"] += 1
    return security_scopes.scopes


app = FastAPI()


@app.get("/")
def root(db: str = Depends(get_db), user: str = Security(get_user, scopes=["read"])):
    return "ok"


@app.get("/scoped")
def scoped(a=Security(read_scopes, scopes=["a"]), b=Security(read_scopes, scopes=["b"])):
    return [a, b]


c = TestClient(app, raise_server_exceptions=False)
c.get("/")
issue = calls["db"] == 1
r = c.get("/scoped")
ordinary = calls["scoped"] == 2 and r.status_code == 200 and r.json() == [["a"], ["b"]]
print("ISSUE", "ok" if issue else "FAIL", "get_db calls", calls["db"])
print("ORDINARY", "ok" if ordinary else "FAIL", "scoped calls", calls["scoped"], r.text[:60])
raise SystemExit(0 if issue and ordinary else 1)
