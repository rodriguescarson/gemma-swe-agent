# The check the red-first rule asks for, written from the issue text only ("partial() ... async functions and callable
# classes"). ISSUE = the result the issue asks for (must fail at base); ORDINARY = a call that already works.
from functools import partial

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


async def async_dep(value: str) -> str:
    return value


class AsyncCallable:
    async def __call__(self, value: str) -> str:
        return value


def sync_dep(value: str) -> str:
    return value


app = FastAPI()


@app.get("/async")
def a(v: str = Depends(partial(async_dep, "async-ok"))):
    return v


@app.get("/class")
def b(v: str = Depends(partial(AsyncCallable(), "class-ok"))):
    return v


@app.get("/sync")
def s(v: str = Depends(partial(sync_dep, "sync-ok"))):
    return v


c = TestClient(app, raise_server_exceptions=False)
got = {p: c.get(p) for p in ("/async", "/class", "/sync")}
issue = all(got[p].status_code == 200 and got[p].json() == p[1:] + "-ok" for p in ("/async", "/class"))
ordinary = got["/sync"].status_code == 200 and got["/sync"].json() == "sync-ok"
print("ISSUE", "ok" if issue else "FAIL", {p: (r.status_code, r.text[:40]) for p, r in got.items() if p != "/sync"})
print("ORDINARY", "ok" if ordinary else "FAIL", got["/sync"].status_code, got["/sync"].text[:40])
raise SystemExit(0 if issue and ordinary else 1)
