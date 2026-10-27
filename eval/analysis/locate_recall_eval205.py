"""File recall of v12b_locate's locate.py on the 205 EVAL tasks: query = problem statement, gold = files in the gold patch."""
import json, os, re, subprocess, sys, tarfile, tempfile, shutil
ROOT = '/Users/carson/Projects/gemma-swe-agent'
LOC = ROOT + '/submissions/v5h2-think/skills/swe-tools/scripts/locate.py'   # the v5h2 version (md5 27546e64)
tasks = {json.loads(l)['instance_id']: json.loads(l) for l in open(ROOT + '/data/heldout1k/harness_all/tasks.jsonl')}
ids = open(ROOT + '/data/distill/eval_ids.txt').read().split()
hits = {1: 0, 3: 0, 8: 0}; n = 0; rows = []
for tid in ids:
    t = tasks[tid]; gold = set(re.findall(r'^diff --git a/(\S+)', t['patch'], re.M))
    gold = {g for g in gold if not re.search(r'(^|/)tests?/|test_', g)} or gold
    d = tempfile.mkdtemp(dir=sys.argv[1])
    try:
        with tarfile.open(f"{ROOT}/data/heldout1k/harness_all/snapshots/{tid}.tgz") as tf: tf.extractall(d, filter='data')
        r = subprocess.run([sys.executable, '-I', LOC, '--query', t['problem_statement']], capture_output=True, text=True,
                           timeout=120, cwd=d, env={**os.environ, 'SWE_WS': d})
        ranked = re.findall(r'^\d+\. (\S+)', r.stdout, re.M)
        n += 1
        for k in hits: hits[k] += bool(gold & set(ranked[:k]))
        rows.append({'id': tid, 'gold': sorted(gold), 'top': ranked[:8]})
    finally:
        shutil.rmtree(d, ignore_errors=True)
print(json.dumps({'n': n, **{f'R@{k}': round(v / n, 3) for k, v in hits.items()}}))
json.dump(rows, open(sys.argv[1] + '/locate_recall_eval205.json', 'w'))
