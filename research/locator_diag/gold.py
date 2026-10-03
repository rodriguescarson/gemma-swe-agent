import json, sys
ids = set(sys.argv[1:])
for l in open("/Users/carson/Projects/gemma-swe-agent/data/tasks.jsonl"):
    r = json.loads(l)
    if r["instance_id"] in ids:
        print("=====", r["instance_id"]); print(r["patch"][:4000])
