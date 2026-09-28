"""Per-stage adapter routing, offline: v10 copy + two dummy PEFT dirs (adapters/v11_loc, adapters/v11_fix),
`adapter:` on locator and fixer only; scenario d (forced compaction inside the fixer). Records the request `model`
field per agent, including the compaction summariser."""
import json, shutil, sys, tempfile
from pathlib import Path
ROOT = Path("/Users/carson/Projects/gemma-swe-agent")
sys.path.insert(0, str(ROOT / "tests"))
import test_v10_flow as F
from v10_support import sandbox as S
from v10_support.mock_llm import MockLLM
OUT = Path(__file__).resolve().parent
root = Path(tempfile.mkdtemp(prefix="v11ad_", dir=str(OUT)))
bundle = S.copy_bundle(root)
peft = json.loads(open(ROOT / "submissions/v4_lora_test/adapters/main_lora/adapter_config.json").read())
for name in ("v11_loc", "v11_fix"):
    d = bundle / "adapters" / name
    d.mkdir(parents=True)
    (d / "adapter_config.json").write_text(json.dumps(peft))
    shutil.copy(ROOT / "submissions/v4_lora_test/adapters/main_lora/adapter_model.safetensors", d / "adapter_model.safetensors")
for stage, name in (("locator", "v11_loc"), ("fixer", "v11_fix")):
    p = bundle / "sub_agents" / f"{stage}.yaml"
    txt = p.read_text()
    p.write_text(txt.replace("model: gemma-4-31b-it-qat-w4a16-ct\n", f"model: gemma-4-31b-it-qat-w4a16-ct\nadapter: {name}\n"))
tasks, snaps = F.make_task(root / "task")
with MockLLM() as mock:
    url = mock.add_route("ad", F.SCENARIOS["d"])
    run = S.run_eval_cli(bundle=bundle, tasks=tasks, snapshots=snaps, results=root / "res", api_base=url, task_ids=[F.TID], timeout=420)
    log = mock.log("ad")
    print("rc", run.rc, "row", run.rows[:1] and {k: run.rows[0].get(k) for k in ("resolved", "error")})
    for e in log:
        roles = [m["role"] for m in e["body"]["messages"]]
        print(e["agent"], "model=", e["body"].get("model"), "roles=", roles[-2:])
    (OUT / "bodies_adapter.json").write_text(json.dumps(log, indent=1, ensure_ascii=False))
    if run.rc:
        print(run.stderr[-2000:])
