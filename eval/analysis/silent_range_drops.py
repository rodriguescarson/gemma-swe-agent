"""read_file calls whose line range is silently dropped, and how often ranges are read through `sed -n` instead.

Cause (our traces): vLLM 0.19.1's gemma4 tool parser sometimes writes a read_file argument key with a stray quote
(`start_line"`, `end_line"`, `"end_line"`). ADK passes the unknown key on, the tool ignores the range and answers
status ok with lines 1-150 of the file, so nothing tells the model it read the wrong lines. run_command takes one string
argument and is never garbled this way, which is why v12b_ctx_sed reads ranges with `sed -n 'A,Bp'`.

Per run directory (eval/kaggle/<cfg>, with results/traces/trace_<id>.json, or a directory that holds trace_<id>.json
under traces/) it counts
  garbled   read_file calls whose argument keys are not a subset of {filepath, start_line, end_line}
  silent    garbled calls the tool answered with status ok (the range was dropped without an error)
  ranged    read_file calls that asked for a range (a key that is start_line or end_line once stray quotes are stripped)
  sed       run_command calls that read lines with `sed -n '<address>p'` (line numbers or a /pattern/ range; `sed -i`
            edits and `sed s///p` are not reads; awk, head|tail and python one-liners are not counted)
and the sed share of all range reads, sed / (ranged + sed).

    python eval/analysis/silent_range_drops.py RUN_DIR [RUN_DIR ...] [--json out.json]
"""
import argparse, collections, glob, json, os, re

READ_FILE_KEYS = frozenset({'filepath', 'start_line', 'end_line'})
RANGE_KEYS = frozenset({'start_line', 'end_line'})
# sed -n [-e] '<address>p' with the script quoted or bare; the script must start with a line number, $ or a /pattern/
SED_READ = re.compile(r"""\bsed\s+(?:-[A-Za-z-]+\s+)*?-[A-Za-z]*n[A-Za-z]*\s+(?:-e\s+)?"""
                      r"""(?:'[\d$/][^']*p'|"[\d$/][^"]*p"|[\d$/][^\s'"]*p)(?=\s|$)""")


def is_sed_read(cmd):
    return bool(SED_READ.search(cmd or ''))


def status_of(observation):
    """The tool's own status word ('ok', 'error', ...) from a step's observation, None when it cannot be read."""
    try:
        return json.loads(observation['content']).get('status')
    except (TypeError, KeyError, ValueError, AttributeError):
        return None


def scan_trace(d):
    out = dict(read_file=0, ranged=0, garbled=0, silent=0, sed=0)
    keys = collections.Counter()
    for s in d.get('steps') or []:
        if s.get('source') != 'agent':
            continue
        for tc in s.get('tool_calls') or []:
            name, args = tc.get('function_name'), tc.get('arguments')
            if name == 'run_command':
                out['sed'] += is_sed_read(args.get('command') if isinstance(args, dict) else None)
            elif name == 'read_file':
                ks = set(args) if isinstance(args, dict) else set()
                out['read_file'] += 1
                out['ranged'] += any(k.strip('"\'`') in RANGE_KEYS for k in ks)
                extra = ks - READ_FILE_KEYS
                if extra:
                    out['garbled'] += 1
                    out['silent'] += status_of(s.get('observation')) == 'ok'
                    keys.update(extra)
    return {**out, 'garbled_keys': dict(keys)}


def collect(run_dir):
    """(one row per readable trace, number of unreadable trace files) for an eval/kaggle/<cfg>-style directory."""
    paths = glob.glob(os.path.join(run_dir, 'results', 'traces', 'trace_*.json'))
    paths = paths or glob.glob(os.path.join(run_dir, 'traces', 'trace_*.json'))
    rows, bad = [], 0
    for p in sorted(paths):
        try:
            d = json.load(open(p))
        except (ValueError, OSError):
            bad += 1
            continue
        rows.append(dict(run=os.path.basename(p)[len('trace_'):-len('.json')], **scan_trace(d)))
    return rows, bad


def summarise(rows):
    keys = collections.Counter()
    for r in rows:
        keys.update(r['garbled_keys'])
    tot = {k: sum(r[k] for r in rows) for k in ('read_file', 'ranged', 'garbled', 'silent', 'sed')}
    range_reads = tot['ranged'] + tot['sed']
    return dict(runs=len(rows), runs_with_garbled=sum(r['garbled'] > 0 for r in rows), read_file=tot['read_file'],
                ranged_read_file=tot['ranged'], garbled=tot['garbled'], silent=tot['silent'], sed_reads=tot['sed'],
                range_reads=range_reads, sed_share=tot['sed'] / range_reads if range_reads else None,
                garbled_keys=dict(keys))


def render(name, s, bad):
    share = 'n/a' if s['sed_share'] is None else f"{100 * s['sed_share']:.1f}%"
    keys = ', '.join(f'{k!r} x{n}' for k, n in sorted(s['garbled_keys'].items(), key=lambda kv: (-kv[1], kv[0]))) or 'none'
    return (f"{name}: runs={s['runs']} unreadable={bad}\n"
            f"  read_file={s['read_file']} ranged_read_file={s['ranged_read_file']} garbled={s['garbled']} "
            f"silent={s['silent']} runs_with_garbled={s['runs_with_garbled']}\n"
            f"  sed_reads={s['sed_reads']} range_reads={s['range_reads']} sed_share={share}\n"
            f"  garbled keys: {keys}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dirs', nargs='+')
    ap.add_argument('--json')
    a = ap.parse_args(argv)
    report = []
    for d in a.run_dirs:
        rows, bad = collect(d)
        if not rows and not bad:
            raise SystemExit(f'no traces under {d} (expected results/traces/trace_<id>.json or traces/trace_<id>.json)')
        s = summarise(rows)
        name = os.path.basename(os.path.abspath(d))
        print(render(name, s, bad))
        report.append(dict(name=name, path=os.path.abspath(d), unreadable=bad, **s, rows=rows))
    if a.json:
        json.dump(report, open(a.json, 'w'), indent=1, sort_keys=True)


if __name__ == '__main__':
    main()
