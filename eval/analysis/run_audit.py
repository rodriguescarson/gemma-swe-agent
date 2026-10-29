"""Audit of every 74-task agent run with traces (Kaggle 4xL4 kernels and the A6000 box, paced to L4): where time goes, which
failure classes happen without any check catching them, and how often, per config. Oracle and rescore runs (gold or saved
patches graded with no agent, so no tool calls) are skipped in the table and in the reach line.

first_edit is the median elapsed seconds of a run's first successful change to a non-test source file inside the repository
(edit_file, write_file, or the swe-tools edit.py helper); repro scripts, /tmp files and tests do not count. Edits made through
other shell commands (python heredocs, sed -i) are not seen, so a config that edits that way has first_edit blank. src_diff
counts the runs whose final patch touches such a file.

    python eval/analysis/run_audit.py [--json eval/analysis/out/run_audit.json] > eval/analysis/out/run_audit.md
"""
import argparse, collections, glob, json, os, posixpath, re, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compaction_l4 import calls  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDS = set(open(os.path.join(ROOT, 'data/kaggle_valid_ids.txt')).read().split())
MIN_ROWS = 70                      # a run needs this many of the 74 ids (and as many traces) to be audited
MARK = 'mandatory input parameters are not present'
TEST_PATH = re.compile(r'(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$|conftest\.py$)')
SAFE_PATH = re.compile(r'[\w.+@/-]+')
DIFF_FILE = re.compile(r'^diff --git a/\S+ b/(\S+)$', re.M)
PLUS_FILE = re.compile(r'^\+\+\+ b/(\S+)', re.M)      # a patch without 'diff --git' headers names its files only here
SANDBOX_ROOT = re.compile(r'^/workspace/+')               # the repository root inside the sandbox
HELPER_EDIT = re.compile(r'(?:^|[\s;&|(])python3?\s+(?:\S*/)?edit\.py\s+(\S+)')   # the swe-tools edit helper: edit.py <path> <<EOF
WHOLE_SUITE = re.compile(r'pytest(\s+-{1,2}[\w=-]+)*\s*(\||;|&|$)')
SWALLOWED = re.compile(r'<\|tool_call>|\bcall:(run_command|read_file|edit_file|write_file|submit_patch|get_status)\{')
ERRS = [('old_string not found', 'edit_miss'), ('occurs', 'edit_ambiguous'), ('timed out after', 'cmd_timeout'),
        ('budget exhausted', 'budget_out'), ('cannot be greater than end_line', 'bad_range'),
        ('Source path', 'bad_path'), ('No such file', 'bad_path'), (MARK, 'parser_reject')]


def is_src_path(p):
    """A non-test source file inside the repository: a relative path (or one under the sandbox root /workspace/; any other
    absolute path such as /tmp/repro.py is outside the repository) with a directory part, so root-level scripts (repro.py,
    reproduce_issue.py, module_a.py: scratch files in the benchmark's package repos, which keep their code under fastapi/
    and rich/) and config files do not count, and not under tests."""
    p = SANDBOX_ROOT.sub('', str(p or '').strip())
    if not SAFE_PATH.fullmatch(p) or p.startswith('/'):       # empty, absolute, or a parser-garbled path (backticks, spaces)
        return False
    p = posixpath.normpath(p)
    return '/' in p and not p.startswith('../') and not TEST_PATH.search(p)


def patch_files(patch):
    """The files a unified diff names: the 'diff --git' headers, or, for a patch that has none, its '+++ b/<path>' lines
    ('+++ /dev/null', a deleted file, is not one of them)."""
    patch = patch or ''
    return DIFF_FILE.findall(patch) or PLUS_FILE.findall(patch)


def patch_touches_src(patch):
    return any(is_src_path(f) for f in patch_files(patch))


def runs():
    for base in ('eval/kaggle', 'eval/a6000/results'):
        for d in sorted(glob.glob(os.path.join(ROOT, base, '*/'))):
            rj, td = os.path.join(d, 'results.jsonl'), os.path.join(d, 'results', 'traces')
            if not (os.path.exists(rj) and os.path.isdir(td)):
                continue
            rows = [json.loads(l) for l in open(rj) if l.strip()]
            rows = [r for r in rows if r.get('id') in IDS]
            if len(rows) < MIN_ROWS:
                continue
            yield ('L4 ' if 'kaggle' in base else 'box ') + os.path.basename(d.rstrip('/')), d, rows


def audit(r, tr):
    st = tr['steps']
    cs = calls(tr)
    out = collections.Counter()
    seen, sub_t, first_edit, submitted, prev_p = set(), None, None, False, None
    t = 0.0
    for s in st:
        ex = s.get('extra') or {}
        if s.get('source') == 'system' and ex.get('event_type') == 'continuation_nudge':
            out['nudges'] += 1
        if s.get('source') != 'agent':
            continue
        t = ex.get('elapsed_s') or t
        tcs = s.get('tool_calls') or []
        obs = s.get('observation')
        o = str(obs.get('content') if isinstance(obs, dict) else obs or '')
        ok = '"status": "ok"' in o.replace("'", '"')
        msg = str(s.get('message') or '')
        if not tcs:
            out['text_steps'] += 1
            if SWALLOWED.search(msg):
                out['swallowed_call'] += 1
        for tc in tcs:
            name, a = tc.get('function_name'), tc.get('arguments') or {}
            out['calls'] += 1
            if submitted:
                out['after_submit'] += 1
            key = (name, json.dumps(a, sort_keys=True))
            if name in ('read_file', 'run_command') and key in seen:
                out['repeat'] += 1
            seen.add(key)
            if name == 'read_file':
                out['reads'] += 1
                if not isinstance(a.get('start_line'), int) or not isinstance(a.get('end_line'), int):
                    out['read_unranged'] += 1
                elif a['end_line'] - a['start_line'] + 1 > 80:
                    out['read_over80'] += 1
            if name == 'run_command':
                c = str(a.get('command') or '')
                he = HELPER_EDIT.search(c)
                if he and first_edit is None and ok and is_src_path(he.group(1)):
                    first_edit = t               # the helper exits non-zero on NO CHANGE, a syntax revert or a refusal
                if 'pytest' in c and WHOLE_SUITE.search(c):
                    out['whole_suite'] += 1
                if len(o) >= 4900:
                    out['cmd_truncated'] += 1
            if name in ('edit_file', 'write_file'):
                out['edits'] += 1
                path = a.get('filepath') or a.get('path') or ''
                if TEST_PATH.search(str(path)):
                    out['test_edit'] += 1
                # the first change to the repository's own code, not a repro script, a /tmp file or a test
                if first_edit is None and ok and is_src_path(path):
                    first_edit = t
            if name == 'submit_patch':
                submitted, sub_t = True, t
            if name == 'get_status':
                out['get_status'] += 1
        for needle, cls in ERRS:
            if needle in o:
                out[cls] += 1
                break
    for p, c in zip(cs, cs[1:]):
        if p['prompt'] and c['prompt'] and c['prompt'] - p['prompt'] - p['completion'] < -200:
            out['compactions'] += 1
    comp = sum(c['completion'] for c in cs)
    return dict(id=r['id'], solved=bool(r.get('resolved')), secs=r.get('secs') or 0,
                timeout='timeout' in str(r.get('err') or '').lower(), empty=not (r.get('patch') or '').strip(),
                src_diff=patch_touches_src(r.get('patch')), submitted=submitted, submit_s=sub_t, first_edit_s=first_edit,
                completion=comp, llm_calls=len(cs), **out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    a = ap.parse_args(argv)
    table, allrows, skipped = [], [], []
    for cfg, d, rows in runs():
        per = []
        for r in rows:
            p = os.path.join(d, 'results', 'traces', f"trace_{r['id']}.json")
            if os.path.exists(p):
                per.append(audit(r, json.load(open(p))))
        if len(per) < MIN_ROWS:
            continue
        if not any(x.get('calls') for x in per) and not any((r.get('calls') or 0) > 0 for r in rows):
            skipped.append(cfg)          # oracle / rescore: patches graded with no agent, so "solved" says nothing about reach
            continue
        for x in per:
            x['cfg'] = cfg
        allrows += per
        n = len(per)
        S = lambda k: sum(x.get(k, 0) for x in per)
        R = lambda k: sum(1 for x in per if x.get(k, 0))
        fe = [x['first_edit_s'] for x in per if x['first_edit_s'] is not None]
        table.append(dict(cfg=cfg, n=n, solved=S('solved'), timeout=S('timeout'), empty=S('empty'),
                          no_submit=n - S('submitted'), secs=round(S('secs') / n), calls=round(S('calls') / n, 1),
                          tok_per_call=round(S('completion') / max(1, S('llm_calls'))),
                          first_edit=round(statistics.median(fe)) if fe else None, src_diff=R('src_diff'),
                          compact_runs=R('compactions'), rej_runs=R('parser_reject'), edit_miss=S('edit_miss'),
                          repeat=S('repeat'), unranged=S('read_unranged'), over80=S('read_over80'),
                          trunc=S('cmd_truncated'), whole=S('whole_suite'), test_edit=R('test_edit'),
                          swallowed=S('swallowed_call'), nudge_runs=R('nudges'), cmd_timeout=S('cmd_timeout'),
                          budget_out=R('budget_out'), after_submit=S('after_submit')))
    cols = list(table[0].keys())
    print('| ' + ' | '.join(cols) + ' |')
    print('|' + '---|' * len(cols))
    for t in table:
        print('| ' + ' | '.join('' if t[c] is None else str(t[c]) for c in cols) + ' |')
    # tasks by reach over every agent run
    by = collections.defaultdict(list)
    for x in allrows:
        by[x['id']].append(x['solved'])
    never = sorted(k for k, v in by.items() if not any(v))
    always = sorted(k for k, v in by.items() if all(v))
    print(f"\n{len(table)} agent configs, {len(allrows)} runs ({len(skipped)} oracle/rescore configs without tool calls skipped); "
          f"tasks never solved by any run: {len(never)}; solved by every run: {len(always)}; "
          f"contested: {len(by) - len(never) - len(always)}")
    if a.json:
        json.dump({'table': table, 'never': never, 'always': always, 'skipped': skipped, 'rows': allrows}, open(a.json, 'w'),
                  indent=1)


if __name__ == '__main__':
    main()
