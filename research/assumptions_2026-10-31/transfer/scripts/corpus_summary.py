import json, collections
D = json.load(open('out/corpus_features.json'))
def pct(a, b): return f'{a}/{b} = {100*a/b:.1f}%' if b else 'n/a'
res = {}
for name, rows in D.items():
    n = len(rows)
    loc = collections.Counter()
    for r in rows:
        for l in (r['test_loc'] or ['no_py_test_file']): loc[l] += 1
    only_top = sum(1 for r in rows if r['test_loc'] == ['top_tests_dir'])
    anyother = sum(1 for r in rows if any(l != 'top_tests_dir' for l in r['test_loc']))
    colo = sum(1 for r in rows if 'colocated' in r['test_loc'])
    pkgt = sum(1 for r in rows if 'pkg_tests_dir' in r['test_loc'])
    style = collections.Counter(r['style_patch'] for r in rows)
    nonpy = sum(1 for r in rows if r['nonpy_src'])
    srcg = sum(1 for r in rows if r['src_layout_gold'])
    print(f'== {name} n={n}')
    print('  test files ALL under top-level tests/test/testing:', pct(only_top, n))
    print('  any test file NOT under top-level tests dir:', pct(anyother, n), '| colocated *_test.py/test_*.py beside src:', pct(colo, n), '| pkg/tests dir:', pct(pkgt, n))
    print('  test style (from test_patch lines):', dict(style))
    print('  gold patch touches a non-.py non-doc source file:', pct(nonpy, n))
    print('  gold patch under src/:', pct(srcg, n))
    if 'has_src_dir' in rows[0] or any('has_src_dir' in r for r in rows):
        rs = [r for r in rows if 'has_src_dir' in r]
        print('  [snapshot] n', len(rs), 'has top-level src/:', pct(sum(r['has_src_dir'] for r in rs), len(rs)))
        sb = collections.Counter(tuple(r['style_base']) for r in rs)
        print('  [snapshot] test style of changed test files at base:', dict(sb.most_common(8)))
        ind = collections.Counter(tuple(r['indent']) for r in rs)
        print('  [snapshot] indent unit of changed src files:', dict(ind.most_common(6)))
        print('  [snapshot] pytest config present:', pct(sum(r['cfg_pytest_opts'] for r in rs), len(rs)),
              '| pythonpath:', pct(sum(r['cfg_pythonpath'] for r in rs), len(rs)),
              '| testpaths:', pct(sum(r['cfg_testpaths'] for r in rs), len(rs)),
              '| asyncio_mode:', pct(sum(r['cfg_asyncio'] for r in rs), len(rs)),
              '| root conftest:', pct(sum(r['cfg_conftest_root'] for r in rs), len(rs)),
              '| protobuf:', pct(sum(r['uses_protobuf'] for r in rs), len(rs)))
        print('  [snapshot] py files median', sorted(r['py_files'] for r in rs)[len(rs)//2], 'max', max(r['py_files'] for r in rs))
    res[name] = rows
# per-repo for heldout: where do tests live / non-top
print('\nheldout per repo: n, any test not under top tests/, src/ layout, unittest-only share')
byrepo = collections.defaultdict(list)
for r in D['heldout1k']: byrepo[r['repo']].append(r)
for repo, rs in sorted(byrepo.items(), key=lambda x: -len(x[1])):
    nt = sum(1 for r in rs if any(l != 'top_tests_dir' for l in r['test_loc']))
    ut = sum(1 for r in rs if r['style_base'] and all(s in ('unittest','absltest') for s in r['style_base']))
    sr = sum(1 for r in rs if r['has_src_dir'])
    print(f'  {repo:35s} n={len(rs):3d} non-top-tests={nt:3d} src/={sr:3d} unittest-only={ut:3d}')
