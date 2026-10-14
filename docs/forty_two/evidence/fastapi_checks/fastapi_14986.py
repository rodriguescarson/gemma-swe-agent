# The check the red-first rule asks for, written from the issue text only ("do not store root_path in servers"; "escape
# Swagger UI configs"). ISSUE must fail at base; ORDINARY = what one request with a root_path returns today.
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.testclient import TestClient

app = FastAPI()


@app.get("/x")
def x():
    return 1


s1 = TestClient(app, root_path="/a").get("/openapi.json").json().get("servers")
s2 = TestClient(app, root_path="/b").get("/openapi.json").json().get("servers")
bad = "</script><script>alert(1)</script>"
html = get_swagger_ui_html(openapi_url="/o.json", title="t", swagger_ui_parameters={"x": bad},
                           init_oauth={"y": bad}).body.decode()
issue_store = s2 == [{"url": "/b"}]
issue_escape = bad not in html
ordinary = s1 == [{"url": "/a"}]
print("ISSUE", "ok" if issue_store and issue_escape else "FAIL", "second request servers", s2, "raw payload in html", bad in html)
print("ORDINARY", "ok" if ordinary else "FAIL", "first request servers", s1)
raise SystemExit(0 if issue_store and issue_escape and ordinary else 1)
