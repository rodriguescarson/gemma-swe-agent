import json, glob, os, collections
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
MARK='mandatory input parameters are not present'
for name,td in (('v12 (old build)','tr_v12'),('garble (12 Oct build)','tr_garble')):
    runs=0; rej=0; nr=0; edits=0; err_kinds=collections.Counter(); steps=0
    for p in sorted(glob.glob(td+'/traces/trace_*.json')):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        t=json.load(open(p)); n=0
        for s in t['steps']:
            if s.get('source')!='agent': continue
            steps+=1
            o=str(s.get('observation'))
            if MARK in o: n+=1
            for tc in (s.get('tool_calls') or []):
                if tc.get('function_name') in ('edit_file','write_file'): edits+=1
            if "'status': 'error'" in o or '"status": "error"' in o or 'error_type' in o:
                m=None
                import re
                m=re.search(r'error_type["\']?: ?["\'](\w+)',o)
                err_kinds[m.group(1) if m else 'other_error']+=1
        nr+=1
        if n: runs+=1; rej+=n
    print(name,'runs',nr,'agent steps',steps,'runs with >=1 parser rejection',runs,'rejections',rej,'edit/write calls',edits,'tool error kinds',dict(err_kinds.most_common(6)))
