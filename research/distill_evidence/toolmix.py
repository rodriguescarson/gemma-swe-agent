# Tool-call mix and predicted L4 agent time (0.99 s/call + 26.5 ms/completion token, research/own_data.md) of v10.1 runs.
# Usage: python3 toolmix.py <run_dir> ; run from /Users/carson/Projects/gemma-swe-agent/eval
import json, glob, os, re, sys, collections
d = sys.argv[1]
res = {json.loads(l)['instance_id']: json.loads(l) for l in open(os.path.join(d, 'task_results.jsonl'))}
cnt = collections.Counter(); pred_res = []; pred_all = []
for f in glob.glob(os.path.join(d, 'traces', '*.json')):
    iid = os.path.basename(f)[6:-5]; ok = res.get(iid, {}).get('resolved')
    n = c = 0
    for s in json.load(open(f))['steps']:
        if s.get('source') != 'agent': continue
        u = s.get('metrics')
        for tc in s.get('tool_calls') or []:
            u = u or (tc.get('extra') or {}).get('usage')
            if ok:
                name = tc['function_name']; a = tc.get('arguments') or {}
                if name == 'run_command':
                    m = re.search(r'/tmp/swe/(\w+)\.py', a.get('command', ''))
                    name = 'helper:' + m.group(1) if m else ('pytest' if 'pytest' in a.get('command', '') else 'raw_cmd')
                cnt[name] += 1
        if u: n += 1; c += u.get('completion_tokens', 0) or 0
    p = 0.99 * n + 0.0265 * c
    pred_all.append(p)
    if ok: pred_res.append(p)
tot = sum(cnt.values())
helpers = sum(v for k, v in cnt.items() if k.startswith('helper:'))
native = sum(cnt[k] for k in ('read_file', 'edit_file', 'write_file'))
print(f'{d}: resolved runs {len(pred_res)}, calls {tot}, helper share {helpers/tot:.1%}, native file tools {native/tot:.1%}')
for k, v in cnt.most_common(): print(f'  {k:20s} {v:4d} {v/tot:.1%}')
pred_res.sort(); pred_all.sort()
print(f'  predicted L4 s, resolved: median {pred_res[len(pred_res)//2]:.0f}, max {pred_res[-1]:.0f}, share <=290 {sum(x<=290 for x in pred_res)/len(pred_res):.2f}, <=150 {sum(x<=150 for x in pred_res)/len(pred_res):.2f}')
