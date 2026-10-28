"""Tool calls the harness rejects as "mandatory input parameters are not present", over every local run with traces.

Cause (forum 747168, our traces): the model closes a string argument with a backtick instead of Gemma's string delimiter,
so vLLM's gemma4 parser runs that argument into the next one and splits the rest into junk keys; ADK then rejects the call.
The model usually resends the identical call. Reports how often that happens, the seconds it costs, and solves against the
same task's runs that edited without any rejection (task-matched expectation).

    python eval/analysis/parser_rejections.py [results_root ...] [--json out.json]
"""
import argparse, collections, glob, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MARK = 'mandatory input parameters are not present'
EDIT_TOOLS = ('edit_file', 'write_file')


def scan_trace(d):
    """(rejected calls, seconds between the previous agent step and each rejected one, edit attempts, rejections by tool)"""
    n = edits = 0; lost = 0.0; prev = 0.0; by_tool = collections.Counter()
    for s in d.get('steps') or []:
        if s.get('source') != 'agent':
            continue
        ex = s.get('extra') if isinstance(s.get('extra'), dict) else {}
        t = ex.get('elapsed_s') or prev
        calls = s.get('tool_calls') or []
        edits += sum(tc.get('function_name') in EDIT_TOOLS for tc in calls)
        if MARK in str(s.get('observation')):
            n += 1; lost += t - prev
            by_tool.update(tc.get('function_name') for tc in calls)
        prev = t
    return n, lost, edits, by_tool


def collect(roots):
    runs, by_tool = [], collections.Counter()
    for root in roots:
        for rdir in sorted(glob.glob(os.path.join(root, '*/'))):
            rj, td = os.path.join(rdir, 'results.jsonl'), os.path.join(rdir, 'results', 'traces')
            if not (os.path.exists(rj) and os.path.isdir(td)):
                continue
            for line in open(rj):
                try:
                    r = json.loads(line)
                    d = json.load(open(os.path.join(td, f"trace_{r['id']}.json")))
                except (ValueError, KeyError, OSError):
                    continue
                n, lost, edits, bt = scan_trace(d)
                by_tool.update(bt)
                runs.append(dict(cfg=os.path.basename(rdir.rstrip('/')), id=r['id'], resolved=bool(r.get('resolved')),
                                 rejected=n, secs_lost=round(lost, 1), edits=edits))
    return runs, by_tool


def summarise(runs, by_tool):
    ctrl = collections.defaultdict(list)          # same task, edited, never rejected
    for r in runs:
        if r['rejected'] == 0 and r['edits'] > 0:
            ctrl[r['id']].append(r['resolved'])
    out = {'runs': len(runs), 'configs': len({r['cfg'] for r in runs}), 'rejections_by_tool': dict(by_tool)}
    for k in (1, 3):
        rs = [r for r in runs if r['rejected'] >= k]
        m = [(r, sum(ctrl[r['id']]) / len(ctrl[r['id']])) for r in rs if ctrl[r['id']]]
        out[f'ge{k}'] = {'runs': len(rs), 'matched': len(m), 'solved': sum(r['resolved'] for r, _ in m),
                         'expected_matched': round(sum(e for _, e in m), 1),
                         'mean_secs_lost': round(sum(r['secs_lost'] for r in rs) / max(1, len(rs)), 1)}
    per_cfg = collections.defaultdict(lambda: {'runs': 0, 'ge1': 0, 'ge3': 0})
    for r in runs:
        c = per_cfg[r['cfg']]; c['runs'] += 1; c['ge1'] += r['rejected'] >= 1; c['ge3'] += r['rejected'] >= 3
    out['per_config'] = dict(sorted(per_cfg.items()))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('roots', nargs='*', default=[os.path.join(ROOT, 'eval/a6000/results')])
    ap.add_argument('--json')
    a = ap.parse_args(argv)
    runs, by_tool = collect(a.roots)
    rep = summarise(runs, by_tool)
    print(json.dumps({k: v for k, v in rep.items() if k != 'per_config'}, sort_keys=True))
    for cfg in ('p4_v12', 'p4_v12a', 'p4_v12b', 'p4_v12b6', 'p4_v12c', 'p4_v12r'):
        if cfg in rep['per_config']:
            print(cfg, rep['per_config'][cfg])
    if a.json:
        json.dump({**rep, 'rows': runs}, open(a.json, 'w'), indent=1, sort_keys=True)


if __name__ == '__main__':
    main()
