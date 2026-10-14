# The check the red-first rule asks for, written from the issue text only ("Add support for PEP695 TypeAliasType"). The
# rule says the check must fail on the current code; the obvious aliases (a plain type, a Query-annotated type) pass at
# base, so this script reports each role separately: which of them is red is what the rule makes the agent find.
from typing import Annotated

from fastapi import Depends, FastAPI, Query
from fastapi.testclient import TestClient
from typing_extensions import TypeAliasType


def some_value() -> int:
    return 123


PlainInt = TypeAliasType("PlainInt", int)
QueryInt = TypeAliasType("QueryInt", Annotated[int, Query(gt=0)])
DepInt = TypeAliasType("DepInt", Annotated[int, Depends(some_value)])

app = FastAPI()


@app.get("/plain")
def plain(q: PlainInt):
    return q


@app.get("/query")
def query(q: QueryInt):
    return q


@app.get("/dep")
def dep(v: DepInt):
    return v


c = TestClient(app, raise_server_exceptions=False)
roles = {"plain": c.get("/plain?q=5"), "query": c.get("/query?q=5"), "dep": c.get("/dep")}
want = {"plain": 5, "query": 5, "dep": 123}
ok = {k: r.status_code == 200 and r.json() == want[k] for k, r in roles.items()}
print("ISSUE", "ok" if ok["dep"] else "FAIL", "alias carrying Depends:", roles["dep"].status_code, roles["dep"].text[:80])
print("ORDINARY", "ok" if ok["plain"] and ok["query"] else "FAIL", {k: roles[k].status_code for k in ("plain", "query")})
raise SystemExit(0 if all(ok.values()) else 1)
