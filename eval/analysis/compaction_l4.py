"""Where a task's time and context go on the scorer's own hardware (Kaggle 4xL4 eval kernels, scorer recipe: in-flow
compaction at 14,336 prompt tokens, 5 events kept), read from the traces alone.

Reports: wall time split (setup / model calls / tools); a per-call latency fit (completion tokens, uncached new prompt
tokens, context length: a near-zero context term means vLLM's prefix cache is working); compaction, seen as the prompt
shrinking between two calls (the trace has no compaction event), its extra seconds over the fit and the reads of
already-read files after it; what filled the context before the first compaction, and how many runs would stay under the
threshold if every tool output were capped; identical repeated reads/commands; time-cap expiries and their outcome.

    python eval/analysis/compaction_l4.py eval/kaggle/g4-l4-v12-p312 [--ids data/kaggle_valid_ids.txt]
"""
import argparse, collections, json, os

import numpy as np

TH = 14336


def calls(trace):
    """per agent step: model seconds, prompt/completion tokens, tool calls, tool seconds"""
    out, prev = [], None
    for s in trace['steps']:
        ex = s.get('extra') or {}
        t = ex.get('elapsed_s')
        if s.get('source') != 'agent':
            prev = t if t is not None else prev
            continue
        m, obs, end = s.get('metrics') or {}, s.get('observation'), t
        if isinstance(obs, dict) and isinstance(obs.get('extra'), dict) and obs['extra'].get('elapsed_s') is not None:
            end = obs['extra']['elapsed_s']
        out.append(dict(llm=(t - prev) if None not in (t, prev) else None, prompt=m.get('prompt_tokens'),
                        completion=m.get('completion_tokens') or 0, tool_s=(end - t) if None not in (end, t) else 0.0,
                        tools=[(tc.get('function_name'), tc.get('arguments') or {}) for tc in s.get('tool_calls') or []]))
        prev = end
    return out


def runs(root, ids):
    for line in open(os.path.join(root, 'results.jsonl')):
        r = json.loads(line)
        p = os.path.join(root, 'results', 'traces', f"trace_{r['id']}.json")
        if (ids is None or r['id'] in ids) and os.path.exists(p):
            tr = json.load(open(p))
            setup = next((s['extra']['elapsed_s'] for s in tr['steps'] if (s.get('extra') or {}).get('event_type') == 'task_prompt'), 0.0)
            yield r, setup, calls(tr)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--ids')
    a = ap.parse_args(argv)
    ids = set(open(a.ids).read().split()) if a.ids else None
    data = list(runs(a.root, ids))
    # latency fit over normal calls (no drop): completion, new uncached prompt tokens, context length
    X, Y = [], []
    for _, _, cs in data:
        for p, c in zip(cs, cs[1:]):
            if c['llm'] is None or not (p['prompt'] and c['prompt']):
                continue
            new = c['prompt'] - p['prompt'] - p['completion']
            if new >= -200:
                X.append([1.0, c['completion'], max(new, 0), c['prompt']]); Y.append(c['llm'])
    X, Y = np.array(X), np.array(Y)
    k, *_ = np.linalg.lstsq(X, Y, rcond=None)
    r2 = 1 - ((Y - X @ k) ** 2).sum() / ((Y - Y.mean()) ** 2).sum()
    wall = sum(r.get('secs') or 0 for r, _, _ in data)
    llm = sum(c['llm'] or 0 for _, _, cs in data for c in cs)
    tool = sum(c['tool_s'] for _, _, cs in data for c in cs)
    setup = sum(s for _, s, _ in data)
    compl = sum(c['completion'] for _, _, cs in data for c in cs)
    print(f"{a.root}: {len(data)} runs, {sum(bool(r['resolved']) for r, _, _ in data)} solved, {len(Y) + len(data)} model calls")
    print(f'wall {wall:,.0f} s: setup {setup / wall:.1%}, model calls {llm / wall:.1%}, tools {tool / wall:.1%}, '
          f'decode (completion x fit) {k[1] * compl / wall:.1%}')
    print(f'latency fit (R2 {r2:.3f}): {k[0]:.2f} s + {k[1] * 1e3:.1f} ms/completion tok + {k[2] * 1e3:.2f} ms/new prompt tok '
          f'+ {k[3] * 1e3:.3f} ms/context tok; mean completion {compl / max(1, len(Y) + len(data)):.0f} tok/call')
    # compaction
    extra, first_at, rereads, hit = [], [], 0, []
    fill, n_fill = collections.Counter(), collections.Counter()
    for r, _, cs in data:
        seen, dropped, before = set(), False, []
        for i, (p, c) in enumerate(zip(cs, cs[1:])):
            if not (p['prompt'] and c['prompt']):
                continue
            new = c['prompt'] - p['prompt'] - p['completion']
            if new < -200:
                if c['llm'] is not None:
                    extra.append(c['llm'] - k[1] * c['completion'] - k[2] * c['prompt'])
                if not dropped:
                    first_at.append(i + 2)
                dropped = True
            elif not dropped:
                t = p['tools'][0][0] if p['tools'] else '(text)'
                fill[t] += new; n_fill[t] += 1; fill['model completions'] += p['completion']; before.append((new, p['completion']))
            for name, args in c['tools']:
                if name == 'read_file':
                    path = args.get('path') or args.get('file_path')
                    rereads += dropped and path in seen
                    if not dropped:
                        seen.add(path)
        hit.append((dropped, bool(r['resolved']), cs[0]['prompt'] or 0 if cs else 0, before))
    med = lambda v: sorted(v)[len(v) // 2] if v else float('nan')
    nh = sum(d for d, _, _, _ in hit)
    print(f'compaction: {nh}/{len(hit)} runs ({sum(s for d, s, _, _ in hit if d)} of them solved), {len(extra)} drops, first at '
          f'call {med(first_at)} (median); extra s per drop over the fit {med(extra):.1f} median, {sum(extra):,.0f} total; '
          f'reads of an already-read file after a drop {rereads}')
    tot = sum(fill.values())
    print('context added before the first compaction: ' + ', '.join(f'{t} {v / tot:.0%}' + (f' (mean {v / n_fill[t]:.0f}/call)' if t in n_fill else '')
                                                          for t, v in fill.most_common() if v / tot >= 0.01))
    for cap in (1500, 1000, 600):
        over = 0
        for _, _, base, before in hit:
            s = base
            for new, c in before:
                s += c + min(new, cap)
                if s >= TH:
                    over += 1
                    break
        print(f'  tool outputs capped at {cap} tokens: {over}/{len(hit)} runs still cross {TH} (same calls; ignores extra reads)')
    # repeats and expiries
    rep = rep_s = 0
    for _, _, cs in data:
        seen = set()
        for c in cs:
            for name, args in c['tools']:
                key = (name, json.dumps(args, sort_keys=True)) if name in ('read_file', 'run_command') else None
                if key and key in seen:
                    rep += 1; rep_s += (c['llm'] or 0) + c['tool_s']
                if key:
                    seen.add(key)
    print(f'identical repeated read_file/run_command calls: {rep}, {rep_s:,.0f} s ({rep_s / wall:.1%} of wall)')
    to = [r for r, _, _ in data if 'timeout' in str(r.get('err') or '').lower()]
    print(f"time-cap expiries: {len(to)}, with a captured patch {sum(bool((r.get('patch') or '').strip()) for r in to)}, "
          f"solved {sum(bool(r['resolved']) for r in to)}; other runs solved "
          f"{sum(bool(r['resolved']) for r, _, _ in data) - sum(bool(r['resolved']) for r in to)}/{len(data) - len(to)}")


if __name__ == '__main__':
    main()
