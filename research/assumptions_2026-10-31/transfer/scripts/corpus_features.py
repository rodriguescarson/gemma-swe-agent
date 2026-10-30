"""Per-task repo-convention features for public 129, heldout1k 1046 (snapshots), pallets 476 (patch paths; 40 snapshots).
Writes out/corpus_features.json (one row per task). Read-only on data/."""
import json, re, tarfile, os, sys, collections
R = '<repo>/data'
def load(p): return [json.loads(l) for l in open(p)]
pub = load(f'{R}/tasks.jsonl'); held = load(f'{R}/heldout1k/tasks.jsonl'); pal = load(f'{R}/pallets/tasks.jsonl')
HELD_SNAP = f'{R}/heldout1k/harness_all/snapshots'; PAL_SNAP = f'{R}/pallets/harness/snapshots'

def diff_paths(p):
    out = []
    for m in re.finditer(r'^diff --git "?a/(.*?)"? "?b/(.*?)"?$', p or '', re.M): out.append(m.group(2))
    if out: return out
    for m in re.finditer(r'^\+\+\+ (?:b/)?(\S+)', p or '', re.M):
        if m.group(1) != '/dev/null': out.append(m.group(1))
    return out
DOC = re.compile(r'(^|/)(docs?|doc|changelog|changes|news|release|README|LICENSE|CONTRIBUTING|HISTORY)\b|\.(md|rst|txt|cff)$', re.I)
def is_test_path(p):
    b = os.path.basename(p)
    return (b.startswith('test_') or b.endswith('_test.py') or b == 'conftest.py'
            or re.search(r'(^|/)(tests?|testing)(/|$)', p) is not None)
def test_loc(p):
    parts = p.split('/')
    if parts[0] in ('tests', 'test', 'testing'): return 'top_tests_dir'
    d = os.path.dirname(p)
    if re.search(r'(^|/)(tests?|testing)$', d): return 'pkg_tests_dir'      # pkg/tests/x.py, src/pkg/tests
    b = os.path.basename(p)
    if b.endswith('_test.py') or b.startswith('test_'): return 'colocated'  # test file beside source, no tests dir
    return 'other'
def style_of(text):
    if text is None: return None
    tc = bool(re.search(r'class\s+\w+\(\s*[\w\.]*TestCase\s*\)', text))
    absl = 'absltest' in text or 'from absl' in text or 'import absl' in text
    fn = bool(re.search(r'^def test_\w+', text, re.M))
    cls = bool(re.search(r'^class\s+Test\w*(\(\s*(object)?\s*\))?\s*:', text, re.M))
    if absl: return 'absltest'
    if tc and not fn and not cls: return 'unittest'
    if tc: return 'mixed'
    if fn or cls: return 'pytest'
    return 'none'
def indent_unit(text):
    c = collections.Counter()
    for l in (text or '').splitlines():
        m = re.match(r'^( +|\t+)\S', l)
        if m and not l.lstrip().startswith(('#', '"', "'", '*')):
            s = m.group(1)
            c['tab' if s[0] == '\t' else len(s)] += 1
    if not c: return None
    ks = [k for k in c if k != 'tab']
    if 'tab' in c and c['tab'] > sum(c[k] for k in ks): return 'tab'
    # smallest indent that is >=10% of indented lines
    tot = sum(c.values())
    for k in sorted(ks):
        if c[k] >= 0.1 * tot: return k
    return None

def tar_scan(path, want):
    names = []; data = {}
    try:
        with tarfile.open(path, 'r:gz') as tf:
            for m in tf:
                n = m.name[2:] if m.name.startswith('./') else m.name
                if n.startswith('.git/') or n == '.git': continue
                names.append(n)
                if n in want and m.isfile():
                    try: data[n] = tf.extractfile(m).read().decode('utf-8', 'replace')
                    except Exception: pass
    except Exception as e:
        return None, None
    return names, data

def row(t, snap_dir):
    gp = diff_paths(t['patch']); tp = diff_paths(t['test_patch'])
    src = [p for p in gp if not is_test_path(p) and not DOC.search(p)]
    r = {'id': t['instance_id'], 'repo': t['repo'], 'gold_files': gp, 'test_files': tp,
         'nonpy_src': [p for p in src if not p.endswith('.py')],
         'src_layout_gold': any(p.startswith('src/') for p in src),
         'test_loc': sorted({test_loc(p) for p in tp if p.endswith('.py')}),
         'new_test_file': bool(re.search(r'^(new file mode|@@ -0,0 )', t['test_patch'] or '', re.M))}
    # style from test_patch hunks (all sets)
    added = '\n'.join(l[1:] for l in (t['test_patch'] or '').splitlines() if l.startswith(('+', ' ')))
    r['style_patch'] = style_of(added)
    if snap_dir:
        sp = f"{snap_dir}/{t['instance_id']}.tgz"
        if os.path.exists(sp):
            want = set(tp) | set(src) | {'pytest.ini', 'tox.ini', 'setup.cfg', 'pyproject.toml', 'conftest.py'}
            names, data = tar_scan(sp, want)
            if names is not None:
                top = collections.Counter(n.split('/')[0] for n in names if '/' in n)
                r['has_src_dir'] = 'src' in top
                r['top_dirs'] = sorted(top)[:25]
                r['n_files'] = len(names)
                r['py_files'] = sum(1 for n in names if n.endswith('.py'))
                r['tree_lines'] = None
                st = {p: style_of(data.get(p)) for p in tp if p.endswith('.py') and p in data}
                r['style_base'] = sorted(set(v for v in st.values() if v))
                r['indent'] = sorted({str(indent_unit(data[p])) for p in src if p.endswith('.py') and p in data})
                cfg = ''.join(data.get(k, '') for k in ('pytest.ini', 'tox.ini', 'setup.cfg', 'pyproject.toml'))
                r['cfg_pytest_opts'] = bool(re.search(r'\[tool\.pytest|\[pytest\]|\[tool:pytest\]', cfg))
                r['cfg_pythonpath'] = bool(re.search(r'^\s*pythonpath\s*=', cfg, re.M))
                r['cfg_testpaths'] = bool(re.search(r'^\s*testpaths\s*=', cfg, re.M))
                r['cfg_asyncio'] = 'asyncio_mode' in cfg
                r['cfg_conftest_root'] = 'conftest.py' in data
                r['uses_protobuf'] = any(n.endswith('.proto') or n.endswith('_pb2.py') for n in names)
    return r
out = {'public': [row(t, None) for t in pub]}
out['heldout1k'] = []
for i, t in enumerate(held):
    out['heldout1k'].append(row(t, HELD_SNAP))
    if i % 200 == 0: print('held', i, file=sys.stderr)
out['pallets'] = [row(t, PAL_SNAP) for t in pal]
json.dump(out, open('out/corpus_features.json', 'w'))
for k, v in out.items(): print(k, len(v), 'with snapshot feats', sum(1 for r in v if 'has_src_dir' in r))
