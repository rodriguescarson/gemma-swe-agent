import json, re, collections, tarfile
BASE='<repo>'
R=json.load(open('out/p10_runs.json')); SNAP=f'{BASE}/data/heldout1k/harness_all/snapshots'
cache={}
def file_text(tid, path):
    k=(tid,path)
    if k in cache: return cache[k]
    t=None
    try:
        with tarfile.open(f'{SNAP}/{tid}.tgz','r:gz') as tf:
            for m in tf:
                n=m.name[2:] if m.name.startswith('./') else m.name
                if n==path and m.isfile(): t=tf.extractfile(m).read().decode('utf-8','replace'); break
    except Exception: pass
    cache[k]=t; return t
def unesc(s): return s.replace('\\\\','\x00').replace('\\"','"').replace("\\'","'").replace('\\n','\n').replace('\\t','\t').replace('\x00','\\')
def norm(s): return re.sub(r'\s+',' ',s).strip()
res=collections.Counter(); recov=collections.Counter(); calls_lost=0
for tid,v in R.items():
    cl=v['calls']
    for i,c in enumerate(cl):
        if c['name']!='edit_file' or not c['result'] or 'old_string not found' not in c['result']: continue
        a=c['args']; fp=a.get('filepath'); o=a.get('old_string')
        if o is None:
            res['no_old_string_key']+=1; continue
        t=file_text(tid, fp) if fp else None
        # file may have been edited before; test against base text
        if t is None: res['file_not_in_base']+=1; continue
        if o in t: res['old_string_in_base_text(edited earlier / stale)']+=1
        elif unesc(o) in t: res['MATCHES_AFTER_UNESCAPE (pure double-escape artefact)']+=1
        elif norm(unesc(o)) in norm(t): res['matches_after_unescape+whitespace-norm']+=1
        else: res['no_match_even_unescaped']+=1
        # did the next edit_file on same file succeed?
        nxt=[x for x in cl[i+1:i+6] if x['name']=='edit_file' and x['args'].get('filepath')==fp]
        if nxt and nxt[0]['result'] and '"status": "ok"' in nxt[0]['result'][:30]: recov['next edit same file ok']+=1
        elif nxt: recov['next edit same file failed again']+=1
        else: recov['no further edit within 5 calls']+=1
print(dict(res)); print(dict(recov))
