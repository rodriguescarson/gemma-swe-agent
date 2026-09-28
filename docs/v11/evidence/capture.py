"""Capture the exact OpenAI request bodies the v10 bundle sends (scenarios a and d of tests/test_v10_flow.py),
offline, with the scripted mock model. Output: bodies_<scenario>.json in this directory."""
import json, sys, tempfile
from pathlib import Path
ROOT = Path("/Users/carson/Projects/gemma-swe-agent")
sys.path.insert(0, str(ROOT / "tests"))
import test_v10_flow as F
from v10_support import sandbox as S
from v10_support.mock_llm import MockLLM
OUT = Path(__file__).resolve().parent
root = Path(tempfile.mkdtemp(prefix="v11cap_", dir=str(OUT)))
bundle = S.copy_bundle(root)
tasks, snaps = F.make_task(root / "task")
with MockLLM() as mock:
    for k in sys.argv[1:] or ["a", "d"]:
        url = mock.add_route(f"s{k}", F.SCENARIOS[k])
        run = S.run_eval_cli(bundle=bundle, tasks=tasks, snapshots=snaps, results=root / f"res_{k}",
                             api_base=url, task_ids=[F.TID], timeout=420)
        log = mock.log(f"s{k}")
        (OUT / f"bodies_{k}.json").write_text(json.dumps(log, indent=1, ensure_ascii=False))
        tr = run.trace(F.TID)
        (OUT / f"trace_{k}.json").write_text(json.dumps(tr, indent=1, ensure_ascii=False))
        print(k, "rc", run.rc, "rows", run.rows[:1] and {x: run.rows[0].get(x) for x in ("resolved", "error")},
              "requests", len(log), "summarizer", mock.summarizer_calls(f"s{k}"), "secs", round(run.secs, 1))
