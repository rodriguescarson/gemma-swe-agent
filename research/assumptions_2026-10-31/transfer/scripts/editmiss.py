import json, re, collections, tarfile, os
BASE='<repo>'
R=json.load(open('out/p10_runs.json'))
SNAP=f'{BASE}/data/heldout1k/harness_all/snapshots'
def cls(a):
    if 'old_string' not in a: return 'garbled_args(no old_string key)'
    o=a['old_string']
    if re.search(r'\\\\"|\\\\n|\\\\t|\\\\\\\\', o) or re.search(r'(?<!\\)\\n', o) and '\n' not in o: return 'escape_garble(literal backslash seqs)'
    return 'plain_mismatch'
cnt=collections.Counter(); per_repo=collections.defaultdict(collections.Counter); order=[]
plain=[]
for tid,v in R.items():
    for i,c in enumerate(v['calls']):
        if c['name']!='edit_file' or not c['result']: continue
        if 'old_string not found' not in c['result']: continue
        k=cls(c['args']); cnt[k]+=1; per_repo[tid.rsplit('_',1)[0]][k]+=1
        if k=='plain_mismatch': plain.append((tid,c))
print('failed edits by class', dict(cnt), 'total', sum(cnt.values()))
# for plain mismatches: does old_string occur in base file after normalisation?
def file_text(tid, path):
    sp=f'{SNAP}/{tid}.tgz'
    try:
        with tarfile.open(sp,'r:gz') as tf:
            for m in tf:
                n=m.name[2:] if m.name.startswith('./') else m.name
                if n==path and m.isfile(): return tf.extractfile(m).read().decode('utf-8','replace')
    except Exception: return None
sub=collections.Counter(); n=0
import random; random.seed(1); sample=random.sample(plain, min(120,len(plain)))
for tid,c in sample:
    a=c['args']; fp=a.get('filepath'); o=a.get('old_string','')
    t=file_text(tid, fp) if fp else None
    if t is None: sub['file_missing_at_base_or_new']+=1; continue
    if o in t: sub['occurs_at_base(edited_earlier_or_stale_view)']+=1
    elif re.sub(r'[ \t]+\n','\n',o) in re.sub(r'[ \t]+\n','\n',t): sub['trailing_ws']+=1
    elif re.sub(r'\s+',' ',o).strip() in re.sub(r'\s+',' ',t): sub['whitespace_or_indent_only']+=1
    elif any(l.strip() and l.strip() in t for l in o.splitlines()): sub['some_lines_match(paraphrase_or_partial)']+=1
    else: sub['no_line_matches(hallucinated)']+=1
print('plain mismatches sampled', len(sample), dict(sub))
print('per repo class shares:')
for r,c in sorted(per_repo.items(), key=lambda x:-sum(x[1].values())):
    print(f'  {r:15s}', dict(c))
