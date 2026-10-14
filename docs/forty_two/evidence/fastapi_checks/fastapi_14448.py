# The check the red-first rule asks for, written from the issue text only (wrapper sync or async x original sync or async,
# "if either is async, then it has to be awaited", partials and callable instances "in all those levels"), in the style of
# the existing tests/test_dependency_wrapped.py (which only has a sync wrapper). ISSUE must fail at base; ORDINARY = the
# existing sync-wrapper cases, which pass at base.
from functools import partial, wraps

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def sync_wrap(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def async_wrap(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


def plain() -> bool:
    return True


async def coro() -> bool:
    return True


class Instance:
    @sync_wrap
    async def __call__(self) -> bool:
        return True


app = FastAPI()
deps = {
    "sync-wrapper-async": sync_wrap(coro),          # ordinary per the existing test file
    "sync-wrapper-sync": sync_wrap(plain),          # ordinary
    "async-wrapper-sync": async_wrap(plain),        # issue: the wrapper is async
    "partial-async-wrapper-sync": partial(async_wrap(plain)),
    "instance-wrapped-async-call": Instance(),      # issue: callable instance, wrapped __call__
}
for name, dep in deps.items():
    def ep(value: bool = Depends(dep)):
        return value
    app.get("/" + name)(ep)
app.get("/endpoint-async-wrapper")(async_wrap(plain))   # issue: path operation function wrapped by an async wrapper

c = TestClient(app, raise_server_exceptions=False)
res = {p: c.get("/" + p) for p in list(deps) + ["endpoint-async-wrapper"]}
ok = {p: r.status_code == 200 and r.json() is True for p, r in res.items()}
ordinary_keys = ["sync-wrapper-async", "sync-wrapper-sync"]
issue = all(v for k, v in ok.items() if k not in ordinary_keys)
ordinary = all(ok[k] for k in ordinary_keys)
print("ISSUE", "ok" if issue else "FAIL", {k: (res[k].status_code, res[k].text[:30]) for k in ok if k not in ordinary_keys})
print("ORDINARY", "ok" if ordinary else "FAIL", {k: res[k].status_code for k in ordinary_keys})
raise SystemExit(0 if issue and ordinary else 1)
