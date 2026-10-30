"""Group the P10 (v12, non-public repos) capture by task and rebuild tool-call -> result pairs.
Read-only on the capture file. Writes out/p10_runs.json. Post-compaction fragments (first user message starts
'For context:') are attached to their task via shared tool_call ids, else a unique time-window + repo match."""
import json, hashlib, collections
CAP = 'p3/capture.jsonl'
TASKS = '<repo>/data/heldout1k/tasks.jsonl'
tasks = {}
for l in open(TASKS):
    r = json.loads(l); tasks[r['instance_id']] = r
items = [json.loads(l) for l in open('p3/items.jsonl')]
win = {i['task']: (i['t0'], i['t1']) for i in items}
def text(u):
    return u if isinstance(u, str) else ''.join(x.get('text', '') if isinstance(x, dict) else str(x) for x in u)
recs_all = []
n_sum = 0
for l in open(CAP):
    d = json.loads(l)
    msgs = d['body']['messages']
    if len(msgs) < 2 or msgs[0]['role'] != 'system':
        n_sum += 1; continue
    recs_all.append(d)
print('regular calls', len(recs_all), 'summariser calls', n_sum)
by_key = collections.defaultdict(list); frags = []
for d in recs_all:
    u = text(d['body']['messages'][1]['content'])
    if u.startswith('You are evaluating'):
        by_key[hashlib.md5(u.encode()).hexdigest()].append(d)
    else:
        frags.append(d)
print('first-message groups', len(by_key), 'continuation calls', len(frags))
runs = {}
for k, recs in by_key.items():
    recs.sort(key=lambda d: d['t'])
    u = text(recs[0]['body']['messages'][1]['content'])
    c = [tid for tid in win if tasks[tid]['problem_statement'][:300] in u and tasks[tid]['repo'] in u.split('\n')[0]]
    if len(c) > 1:
        c = [t for t in c if win[t][0] - 30 <= recs[0]['t'] <= win[t][1] + 30] or c
    if len(c) != 1:
        print('unmatched group', len(c)); continue
    runs.setdefault(c[0], []).extend(recs)
# attach continuation calls
def ids_of(d):
    s = set()
    for m in d['body']['messages']:
        if m['role'] == 'tool' and m.get('tool_call_id'): s.add(m['tool_call_id'])
        for tc in (m.get('tool_calls') or []): s.add(tc['id'])
    return s
idx = collections.defaultdict(set)
for tid, rs in runs.items():
    for d in rs:
        for tc in (d['response']['choices'][0]['message'].get('tool_calls') or []): idx[tc['id']].add(tid)
by_id = by_time = lost = 0
for d in sorted(frags, key=lambda d: d['t']):
    cand = collections.Counter()
    for i in ids_of(d):
        for t in idx.get(i, ()): cand[t] += 1
    tid = None
    if cand:
        tid = cand.most_common(1)[0][0]; by_id += 1
    else:
        u = text(d['body']['messages'][1]['content'])
        c = [t for t in win if win[t][0] - 5 <= d['t'] <= win[t][1] + 30 and tasks[t]['repo'] in u]
        if len(c) == 1: tid = c[0]; by_time += 1
    if tid is None: lost += 1; continue
    runs[tid].append(d)
    for tc in (d['response']['choices'][0]['message'].get('tool_calls') or []): idx[tc['id']].add(tid)
print('continuations attached by id', by_id, 'by time', by_time, 'lost', lost)
out = {}
for tid, recs in runs.items():
    recs.sort(key=lambda d: d['t'])
    calls = []; results = {}
    for d in recs:
        m = d['response']['choices'][0]['message']
        for tc in (m.get('tool_calls') or []):
            try: a = json.loads(tc['function']['arguments'])
            except Exception: a = {'_raw': tc['function']['arguments']}
            calls.append({'id': tc['id'], 'name': tc['function']['name'], 'args': a, 't': d['t']})
        for mm in d['body']['messages']:
            if mm['role'] == 'tool':
                results[mm.get('tool_call_id')] = mm['content'] if isinstance(mm['content'], str) else json.dumps(mm['content'])
    seen = set(); cl = []
    for c in calls:
        if c['id'] in seen: continue
        seen.add(c['id']); c['result'] = results.get(c['id']); cl.append(c)
    first_user = text(recs[0]['body']['messages'][1]['content'])
    out[tid] = {'n_model_calls': len(recs), 'calls': cl, 't_first': recs[0]['t'], 't_last': recs[-1]['t'],
                'first_user': first_user if first_user.startswith('You are evaluating') else None}
json.dump(out, open('out/p10_runs.json', 'w'))
print('written', len(out), 'runs; total tool calls', sum(len(v['calls']) for v in out.values()),
      'results found', sum(1 for v in out.values() for c in v['calls'] if c['result'] is not None))
