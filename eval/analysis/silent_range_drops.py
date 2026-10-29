"""read_file calls whose line range is silently dropped, and how often ranges are read through `sed -n` instead.

Cause (our traces): vLLM 0.19.1's gemma4 tool parser sometimes writes a read_file argument key with a stray quote
(`start_line"`, `end_line"`, `"end_line"`). ADK passes the unknown key on, the tool ignores the range and answers
status ok with lines 1-150 of the file, so nothing tells the model it read the wrong lines. run_command takes one string
argument and is never garbled this way, which is why v12b_ctx_sed reads ranges with `sed -n 'A,Bp'`.

Per run directory (eval/kaggle/<cfg>, with results/traces/trace_<id>.json, or a directory that holds trace_<id>.json
under traces/) it counts
  garbled   read_file calls whose argument keys are not a subset of {filepath, start_line, end_line}
  silent    garbled calls the tool answered with status ok (the range was dropped without an error)
  ranged    read_file calls that asked for a range: an argument key that is start_line or end_line once everything but
            letters and underscores is stripped from it (`start_line"`, `"end_line"` and the backslash-escaped
            `start_line\\"` all count)
  sed       run_command calls that read lines with `sed -n`, by the rule in is_sed_read(): a print over line numbers, `$`
            or a range, not an in-place edit, not a search by one pattern, not a filter on a program's output (a pipe
            from `cat file` is a file read); awk, head|tail and python one-liners are not counted
and the sed share of all range reads, sed / (ranged + sed). A trace file that is not JSON, not a JSON object or not
made of step objects is counted as unreadable, never a crash.

    python eval/analysis/silent_range_drops.py RUN_DIR [RUN_DIR ...] [--json out.json]
"""
import argparse, collections, glob, json, os, re

READ_FILE_KEYS = frozenset({'filepath', 'start_line', 'end_line'})
RANGE_KEYS = frozenset({'start_line', 'end_line'})
# `sed` + its option words + the script (quoted, or one bare word), up to the next blank or the end of the command
SED_CALL = re.compile(r"""\bsed((?:\s+-[A-Za-z-]\S*)*)\s+('[^']*'|"[^"]*"|[^\s'"-]\S*)(?=\s|$)""")
# one line or pattern address; a range ends in another address or in +N
_ADDR = r"(?:\d+|\$|/(?:\\.|[^/\\])*/)"
_END = rf"(?:{_ADDR}|\+\d+)"
# a print that reads by position (line number or $, alone or ending a range) or by a range between two addresses
_READ_CMD = rf"(?:(?:\d+|\$)(?:,{_END})?|{_ADDR},{_END})p"
# the command just before a pipe into sed, when it only hands over a file's lines (cat or nl, options, then a file)
PIPE_BREAK = re.compile(r'\|\|?|&&|;|\n')
FILE_PIPE = re.compile(r'\s*(?:cat|nl)(?:\s+-\S+)*\s+[^\s<>|&;()-]')
_READ_IN_SCRIPT = re.compile(rf"(?:^|[;\n])\s*{_READ_CMD}\s*(?=[;\n]|$)")


def normal_key(k):
    """An argument key with everything but letters and underscores removed: `start_line"`, `"end_line"` and the
    backslash-escaped `start_line\\"` all become the key the model meant."""
    return re.sub(r'[^A-Za-z_]', '', str(k))


def is_sed_read(cmd):
    """True when a run_command string reads lines of a file with sed. The rule, pinned by the table in
    tests/test_silent_range_drops.py:
      - the command is `sed` with -n (or --quiet / --silent) among its options, in any spelling (-n, -ne, -n -e, -En)
        and without -i / --in-place in any spelling (-i, -ni, -in, -i.bak): an in-place edit is not a read;
      - the script prints by position or by range: `A,Bp`, `Np`, `$p`, `/pat1/,/pat2/p`, `A,+Np`, also with a quit
        after it (`A,Bp;Bq`, `A,B{p;q}`). One pattern address alone (`/pat/p`) is a search, and `s/a/b/p` is a
        substitution; neither is a read;
      - sed reads a file, not program output: `git log | sed -n '1p'` and `pytest | sed -n '5,9p'` filter what a
        program printed and are not reads. A pipe from `cat` or `nl` of a file is a read (`cat -n f.py | sed -n
        '5,9p'` picks lines of f.py); so are `sed -n '5,9p' f | head`, `a && sed ...` and `a || sed ...`."""
    if not isinstance(cmd, str):
        return False
    for m in SED_CALL.finditer(cmd):
        before = cmd[:m.start()].rstrip()
        if before.endswith('|') and not before.endswith('||') and not FILE_PIPE.match(re.split(PIPE_BREAK, before[:-1])[-1]):
            continue
        opts = m.group(1).split()
        if any(o.startswith('--in-place') or (not o.startswith('--') and 'i' in o) for o in opts):
            continue
        if not any(o in ('--quiet', '--silent') or (not o.startswith('--') and 'n' in o) for o in opts):
            continue
        script = m.group(2)
        script = script[1:-1] if script[0] in '\'"' else script
        if _READ_IN_SCRIPT.search(re.sub(r'\{\s*p\s*;\s*q\s*;?\s*\}', 'p', script)):
            return True
    return False


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
                out['ranged'] += any(normal_key(k) in RANGE_KEYS for k in ks)
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
            with open(p) as f:
                d = json.load(f)
            row = scan_trace(d)
        except (ValueError, OSError, AttributeError, TypeError):
            # not JSON, not readable, valid JSON that is not an object (null, [], a string: no .get), or steps that are
            # not objects: an unreadable trace, counted and reported, never a crash
            bad += 1
            continue
        rows.append(dict(run=os.path.basename(p)[len('trace_'):-len('.json')], **row))
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
