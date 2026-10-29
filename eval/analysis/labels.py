"""Clean labels and comparable reach bands for the 74 public tasks. The 'resolved' label of the 2,442 agent runs in
eval/analysis/out/run_audit.json (33 configs) is what task_reach.json, the 32-task screen and the paired comparisons rest on,
but a run is only comparable with the scorer when it ran its budget (5 min, 40 tool calls), had no internet, was graded in the
scorer's environment and is not a replay of another config's draw. This script keeps the raw label next to a corrected one,
flags every row, and recomputes the reach bands on the comparable rows only.

Per (cfg, id) row in labels_clean.json:
  raw_resolved     the 'resolved' of results.jsonl (Kaggle 4x L4 kernels and the A6000 box)
  resolved         the corrected label. Only a box row whose patch was replayed under the scorer's Pygments 2.20.0 (the box
                   grades with 2.21.0, which changes rich_3782 and rich_4079 even for the gold patch) and whose test verdict
                   differs gets a new value; every other row keeps its raw label
  flags.env_regraded  the patch was replayed under Pygments 2.20.0 (rows replayed with an agent error ran no test, so
                   their label stands)
  flags.base_passes   the task's hidden tests already pass on the unpatched base in the scorer's environment (the label does
                   not measure the patch): fastapi_14851, fastapi_14077, requests_6644
  flags.network    the run reached the internet (a pip install, a curl, a live HTTP request); the scorer has none. Failed
                   attempts that returned nothing are not flagged: the scorer behaves the same
  flags.duplicate_of  the config re-ran another config's bundle with the same seed (a replay of one draw); the original name
  flags.budget     null at the scorer's 5 min / 40 calls, else the config's own budget ("8min/28calls")
  notes            other hygiene codes of the row (harness-killed, zero-call text leak, Pygments-exposed, ...)
  excluded         why the row is not comparable: network, harness_killed, duplicate_config, budget (empty = comparable)

Reach bands (as eval/analysis/out/task_reach.json was built, over the solve rate of a task's runs): never 0; rare under 10%;
contested 10 to 90%; always above 90% ('every_run' counts the tasks every run solved). The comparable bands use the
corrected label over the comparable rows, and the tasks whose base passes are reported apart from the bands. The 32-task
screen is contested plus rare, written to data/screen32_clean_ids.txt; task_reach.json and screen32_ids.txt are not touched.

Inputs, frozen snapshots in eval/analysis/out/label_inputs/ (so this runs from tracked files plus the raw results.jsonl):
  grader_tasks.json        the label-grader stage: per task the gold and empty-patch verdicts in the scorer's environment
                           (python 3.12, Pygments 2.20.0; the keys the script needs out of its tasks.json)
  hygiene_flags.json       the hygiene stage: budgets per config, the 8 network rows, duplicate pairs, stack drift
  hygiene_row_flags.json   its per-row codes ("cfg|id" -> codes)
  regraded.json            the regrade stage: the 41 box rows on rich_3782 and rich_4079 under Pygments 2.20.0
  regraded_p4.json         the two rows of the plain 'p4' run dir, which that stage's p4_* glob missed (same method)

    python eval/analysis/labels.py [--labels F] [--reach F] [--screen F]
"""
import argparse, collections, hashlib, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDS = set(open(os.path.join(ROOT, 'data/kaggle_valid_ids.txt')).read().split())
SPEC = (5.0, 40)                   # the scorer's budget: minutes and tool calls per task
BANDS = ('never', 'rare_lt10', 'contested_10_90', 'always_gt90')
REASONS = ('network', 'harness_killed', 'duplicate_config', 'budget')
STEPS = (('raw labels, every run', 'raw_resolved', ()),
         ('corrected labels', 'resolved', ()),
         ('and no network or harness-killed rows', 'resolved', ('network', 'harness_killed')),
         ('and a duplicate config counted once', 'resolved', ('network', 'harness_killed', 'duplicate_config')),
         ('and only configs at 5 min / 40 calls', 'resolved', REASONS))
LOOSE_SHARE = 0.5                  # sensitivity: configs whose first model call repeats on this share of tasks are one draw
OTHER_CODES = ('BUDGET_NOT_5MIN_40CALLS', 'NETWORK_SUCCESS')          # these two are the budget and network flags themselves


def read_json(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return json.load(f)


def label_input(name):
    return read_json('eval/analysis/out/label_inputs', name)


def band(solved, n):
    """The reach band of a task solved by `solved` of `n` runs (integer arithmetic, so 10% and 90% are exact)."""
    if not n:
        return 'nodata'
    if solved == 0:
        return 'never'
    if solved * 10 < n:
        return 'rare_lt10'
    return 'contested_10_90' if solved * 10 <= 9 * n else 'always_gt90'


def agent_configs():
    """(side, run dir name) of every audited agent config, in run_audit.json order ('L4 <dir>' is a Kaggle kernel,
    'box <dir>' an A6000 run)."""
    table = read_json('eval/analysis/out/run_audit.json')['table']
    return [tuple(t['cfg'].split(' ', 1)) for t in table]


def read_rows(configs):
    """One row per (config, id) of the 74 public tasks, straight from results.jsonl."""
    rows = []
    for side, name in configs:
        base = 'eval/kaggle' if side == 'L4' else 'eval/a6000/results'
        seen = {}
        with open(os.path.join(ROOT, base, name, 'results.jsonl')) as f:
            for line in f:
                r = json.loads(line) if line.strip() else {}
                if r.get('id') in IDS:
                    if r['id'] in seen:
                        raise ValueError(f"{base}/{name}/results.jsonl has two rows for {r['id']}")
                    seen[r['id']] = r
        for tid in sorted(seen):
            r = seen[tid]
            rows.append(dict(cfg=name, side=side, id=tid, raw_resolved=bool(r.get('resolved')),
                             resolved=bool(r.get('resolved')),
                             patch_sha1=hashlib.sha1((r.get('patch') or '').encode()).hexdigest()))
    return rows


def apply_regrades(rows, regraded):
    """Mark the replayed rows and take the replay's test verdict where it differs from the box's label. A replay whose label
    or patch hash disagrees with results.jsonl would be a different row, so it raises; a row outside the audited configs
    (p4_adapter, p4_v16a) is skipped. Returns the changed labels."""
    by = {(r['cfg'], r['id']): r for r in rows}
    changed = []
    for g in regraded:
        r = by.get((g['cfg'], g['id']))
        if r is None:
            continue
        if g['old_resolved'] != r['raw_resolved'] or g['patch_sha1'] != r['patch_sha1']:
            raise ValueError(f"the regrade of {g['cfg']} {g['id']} was made on a different row than results.jsonl holds")
        r['env_regraded'] = True
        if g['phase'] == 'tests' and g['new_resolved'] != r['raw_resolved']:
            r['resolved'] = bool(g['new_resolved'])
            changed.append(dict(cfg=r['cfg'], id=r['id'], raw=r['raw_resolved'], resolved=r['resolved'], exit=g['exit'],
                                old_exit=g['old_exit'], why='replayed under Pygments 2.20.0; the box graded with 2.21.0'))
    return changed


def budget_of(b):
    return f"{b['max_time_minutes']:g}min/{b['max_tool_calls']}calls"


def flag_rows(rows, tasks, hyg, row_flags):
    """Set flags, notes and excluded on every row; returns {cfg: budget dict} for the audited configs."""
    budgets = {}
    for cfg in dict.fromkeys(r['cfg'] for r in rows):
        if cfg not in hyg['budget']:
            raise KeyError(f"{cfg} has no budget in hygiene_flags.json: re-run the hygiene stage before relabelling")
        budgets[cfg] = hyg['budget'][cfg]
    dup_of = {p['b']: p['a'] for p in hyg['duplicate_detail']['pairs'] if p['same_bundle']}
    net = {(c, i) for c, i, _ in hyg['network']}
    for r in rows:
        b = budgets[r['cfg']]
        in_spec = (float(b['max_time_minutes']), b['max_tool_calls']) == SPEC
        codes = row_flags.get(f"{r['cfg']}|{r['id']}", [])
        r['flags'] = dict(env_regraded=r.pop('env_regraded', False), base_passes=bool(tasks[r['id']]['base_resolved']),
                          network=(r['cfg'], r['id']) in net, duplicate_of=dup_of.get(r['cfg']),
                          budget=None if in_spec else budget_of(b))
        r['notes'] = sorted(c for c in codes if c not in OTHER_CODES)
        why = dict(network=r['flags']['network'], harness_killed='HARNESS_KILLED_ROW' in codes,
                   duplicate_config=r['flags']['duplicate_of'] is not None, budget=not in_spec)
        r['excluded'] = [k for k in REASONS if why[k]]
        del r['patch_sha1']
    return budgets


def reach(rows, label, drop=()):
    """{id: {n, solved, band}} over the rows that have none of the `drop` reasons."""
    n, s = collections.Counter(), collections.Counter()
    for r in rows:
        if not set(r['excluded']) & set(drop):
            n[r['id']] += 1
            s[r['id']] += r[label]
    return {tid: dict(n=n[tid], solved=s[tid], band=band(s[tid], n[tid])) for tid in sorted(IDS)}


def counts(table, apart=()):
    """Band counts over the tasks not in `apart`, plus the tasks every run solved."""
    t = {k: v for k, v in table.items() if k not in apart}
    c = collections.Counter(v['band'] for v in t.values())
    return dict({b: c[b] for b in BANDS}, nodata=c['nodata'], tasks=len(t), runs=sum(v['n'] for v in t.values()),
                every_run=sum(1 for v in t.values() if v['n'] and v['solved'] == v['n']))


def clusters(pairs, share):
    """Union of the config pairs whose first model call repeats on at least `share` of the tasks (a sensitivity check:
    these configs share a seed and prompt without being reruns of one bundle)."""
    parent = {}
    find = lambda x: x if parent.setdefault(x, x) == x else find(parent[x])
    for p in pairs:
        k, m = p['first_msg_and_call_identical'].split('/')
        if int(k) / int(m) >= share:
            parent[find(p['b'])] = find(p['a'])
    out = collections.defaultdict(list)
    for x in parent:
        out[find(x)].append(x)
    return list(out.values())


def sensitivity(rows, hyg, budgets):
    """Bands under other readings of 'comparable' (the main bands are in `final`)."""
    date = {c: v['run_date'] for c, v in hyg['stack'].items()}
    loose = set()
    for cl in clusters(hyg['duplicate_detail']['pairs'], LOOSE_SHARE):
        loose |= set(sorted(cl, key=lambda c: (date.get(c, ''), c))[1:])          # keep the earliest config of each cluster
    time_ok = {c for c, b in budgets.items() if float(b['max_time_minutes']) == SPEC[0]}
    row_ok = lambda r: not set(r['excluded']) & {'network', 'harness_killed'}
    variants = {
        'time_only_budget': ('configs at 5 min whatever their call cap, duplicates once',
                             lambda r: row_ok(r) and r['cfg'] in time_ok and 'duplicate_config' not in r['excluded']),
        'loose_duplicates': (f'at 5 min / 40 calls, configs sharing the first call on {LOOSE_SHARE:.0%} of tasks counted once',
                             lambda r: row_ok(r) and 'budget' not in r['excluded'] and r['cfg'] not in loose),
        'kaggle_only': ('the Kaggle kernels at 5 min / 40 calls (the scorer\'s own environment)',
                        lambda r: row_ok(r) and 'budget' not in r['excluded'] and r['side'] == 'L4')}
    base = {r['id'] for r in rows if r['flags']['base_passes']}
    out = {}
    for name, (what, keep) in variants.items():
        kept = [r for r in rows if keep(r)]
        t = reach(kept, 'resolved')
        out[name] = dict(what=what, configs=len({r['cfg'] for r in kept}), **counts(t, base),
                         screen=sorted(k for k, v in t.items() if k not in base and v['band'] in BANDS[1:3]))
    return out


def build():
    configs = agent_configs()
    rows = read_rows(configs)
    tasks = label_input('grader_tasks.json')
    hyg = label_input('hygiene_flags.json')
    row_flags = label_input('hygiene_row_flags.json')
    changed = apply_regrades(rows, label_input('regraded.json') + label_input('regraded_p4.json'))
    budgets = flag_rows(rows, tasks, hyg, row_flags)
    base = sorted(t for t in IDS if tasks[t]['base_resolved'])

    tables = [reach(rows, label, drop) for _, label, drop in STEPS]
    steps = []
    for (name, label, drop), t in zip(STEPS, tables):
        kept = [r for r in rows if not set(r['excluded']) & set(drop)]
        steps.append(dict(step=name, configs=len({r['cfg'] for r in kept}), **counts(t)))
    final = tables[-1]
    steps.append(dict(step='and the tasks whose base passes reported apart', configs=steps[-1]['configs'], **counts(final, base)))
    raw = tables[0]
    lists = {b: sorted(k for k, v in final.items() if v['band'] == b and k not in base) for b in BANDS}
    screen = sorted(lists['rare_lt10'] + lists['contested_10_90'])

    cfgs = []
    for side, name in configs:
        mine = [r for r in rows if r['cfg'] == name]
        dup = next((r['flags']['duplicate_of'] for r in mine), None)
        cfgs.append(dict(cfg=name, side=side, budget=budget_of(budgets[name]),
                         at_spec=all(r['flags']['budget'] is None for r in mine), duplicate_of=dup, rows=len(mine),
                         raw_solved=sum(r['raw_resolved'] for r in mine), solved=sum(r['resolved'] for r in mine),
                         comparable_rows=sum(1 for r in mine if not r['excluded'])))
    labels = dict(
        meta=dict(configs=len(configs), rows=len(rows), raw_solved=sum(r['raw_resolved'] for r in rows),
                  solved=sum(r['resolved'] for r in rows), labels_changed=changed,
                  env_regraded_rows=sum(r['flags']['env_regraded'] for r in rows),
                  excluded={k: sum(1 for r in rows if k in r['excluded']) for k in REASONS},
                  comparable_rows=sum(1 for r in rows if not r['excluded']),
                  comparable_configs=[c['cfg'] for c in cfgs if c['comparable_rows'] and c['at_spec'] and not c['duplicate_of']],
                  base_passes=base,
                  rule="comparable = no network row, not harness-killed, not a duplicate config, config at 5 min / 40 calls"),
        configs=cfgs, rows=rows)
    per_task = {}
    for tid in sorted(IDS):
        per_task[tid] = dict(raw=dict(raw[tid]), clean=dict(final[tid]), base_passes=tid in base)
    reach_doc = dict(
        definition=dict(bands="over the solve rate of a task's comparable runs: never 0; rare under 10%; contested 10 to 90%; "
                              "always above 90%; every_run counts tasks every run solved",
                        comparable=labels['meta']['rule'], base_passing="tasks whose hidden tests pass on the unpatched base are "
                        "reported apart from the bands", raw="the 33 configs, raw labels, no exclusion (reproduces task_reach.json)"),
        comparable_configs=labels['meta']['comparable_configs'],
        dropped_configs=dict(duplicate={c['cfg']: c['duplicate_of'] for c in cfgs if c['duplicate_of']},
                             budget={c['cfg']: c['budget'] for c in cfgs if not c['at_spec']}),
        steps=steps, **lists, base_passing=[dict(id=t, **final[t], raw=raw[t]) for t in base],
        nodata=sorted(k for k, v in final.items() if v['band'] == 'nodata'),
        moved={k: [raw[k]['band'], final[k]['band']] for k in sorted(IDS) if k not in base and raw[k]['band'] != final[k]['band']},
        sensitivity=sensitivity(rows, hyg, budgets), screen=screen, tasks=per_task)
    return labels, reach_doc


def write_json(path, doc, per_line=()):
    """JSON with each item of the keys in `per_line` on its own line (a 2,442-row file stays diffable)."""
    with open(path, 'w') as f:
        f.write('{\n')
        keys = list(doc)
        for i, k in enumerate(keys):
            end = ',\n' if i < len(keys) - 1 else '\n'
            if k in per_line:
                f.write(f' {json.dumps(k)}: [\n' + ',\n'.join('  ' + json.dumps(x) for x in doc[k]) + '\n ]' + end)
            else:
                f.write(f' {json.dumps(k)}: {json.dumps(doc[k], indent=1)}' + end)
        f.write('}\n')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--labels', default=os.path.join(ROOT, 'eval/analysis/out/labels_clean.json'))
    ap.add_argument('--reach', default=os.path.join(ROOT, 'eval/analysis/out/task_reach_clean.json'))
    ap.add_argument('--screen', default=os.path.join(ROOT, 'data/screen32_clean_ids.txt'))
    ap.add_argument('--old-screen', default=os.path.join(ROOT, 'data/screen32_ids.txt'))
    a = ap.parse_args(argv)
    labels, reach_doc = build()
    write_json(a.labels, labels, per_line=('configs', 'rows'))
    write_json(a.reach, reach_doc)
    with open(a.screen, 'w') as f:
        f.write(''.join(t + '\n' for t in reach_doc['screen']))
    m = labels['meta']
    print(f"{m['configs']} configs, {m['rows']} rows: {m['raw_solved']} raw solves, {m['solved']} corrected "
          f"({len(m['labels_changed'])} labels changed, {m['env_regraded_rows']} rows replayed under Pygments 2.20.0); "
          f"excluded rows by reason {m['excluded']}; {m['comparable_rows']} comparable rows in {len(m['comparable_configs'])} configs")
    print('\n| step | configs | runs | tasks | never | rare<10% | contested | always>90% | every run |\n|---|---|---|---|---|---|---|---|---|')
    for s in reach_doc['steps']:
        print(f"| {s['step']} | {s['configs']} | {s['runs']} | {s['tasks']} | {s['never']} | {s['rare_lt10']} | "
              f"{s['contested_10_90']} | {s['always_gt90']} | {s['every_run']} |")
    print('\nbase-passing, apart: ' + ', '.join(f"{b['id']} {b['solved']}/{b['n']}" for b in reach_doc['base_passing']))
    if os.path.exists(a.old_screen):
        old = set(open(a.old_screen).read().split())
        new = set(reach_doc['screen'])
        print(f"screen: {len(old)} before, {len(new)} now; added {sorted(new - old)}; removed {sorted(old - new)}")


if __name__ == '__main__':
    main()
