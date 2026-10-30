"""Per (cfg, task) features from the ATIF traces: last own check before submit, whether tests were run."""
import json, glob, os, re, sys
N='<scratch>/assume/nearmiss'
R='<repo>'
valid=[l.strip() for l in open(R+'/data/kaggle_valid_ids.txt') if l.strip()]

def parse_obs(content):
    """-> (status, exit_code, stdout, stderr)"""
    try:
        o=json.loads(content)
    except Exception:
        return None,None,content or '',''
    if not isinstance(o,dict): return None,None,str(o),''
    st=o.get('status')
    if 'exit_code' in o: return st,o['exit_code'],o.get('stdout',''),o.get('stderr','')
    det=o.get('details') or {}
    if isinstance(det,dict) and 'exit_code' in det:
        return st,det['exit_code'],det.get('stdout',''),det.get('stderr','') or o.get('error_message','')
    return st,None,o.get('stdout',''),o.get('error_message','')

def strip_heredocs(cmd):
    """keep the invoking lines, drop heredoc bodies (their text is data, not commands)"""
    out=[];term=None
    for line in cmd.split('\n'):
        if term is not None:
            if line.strip()==term: term=None
            continue
        out.append(line)
        m=re.search(r"<<-?\s*(['\"]?)(\w+)\1",line)
        if m: term=m.group(2)
    return '\n'.join(out)

CMDPOS=r'(?:^|[;&|(]\s*|&&\s*|\|\|\s*|\n\s*|\bcd [^;&|]+(?:&&|;)\s*|\bexport [^;&|]+(?:&&|;)\s*)'
def kind(cmd):
    c=strip_heredocs(cmd)
    if re.search(r'(?:-m\s+(?:pytest|unittest)\b)|(?:'+CMDPOS+r'(?:python3?\s+-m\s+)?(?:pytest|py\.test)\b)',c): return 'pytest'
    if re.search(r'py_compile|compileall',c): return 'py_compile'
    if re.search(CMDPOS+r'(?:env\s+\w+=\S+\s+)?(?:\w+=\S+\s+)*python3?(?:\.\d+)?\b',c): return 'python'
    return 'other'

def pytest_targets(cmd):
    """test paths mentioned in a pytest command (tokens ending .py / containing tests/ or ::)"""
    toks=re.findall(r'[\w./\-\[\]:]+',cmd)
    out=[]
    for t in toks:
        if t.endswith('.py') or '::' in t or re.match(r'^(tests?|testing)(/|$)',t) or '/tests/' in t or t.startswith('./tests'):
            out.append(t)
    return out

def load_trace(cfgdir,task):
    f=f'{N}/{cfgdir}/traces/trace_{task}.json'
    if not os.path.exists(f): return None
    return json.load(open(f))

def calls(d):
    """ordered list of dict(step, name, args, status, exit, stdout, stderr, elapsed)"""
    out=[]
    for s in d['steps']:
        tcs=s.get('tool_calls') or []
        obs=s.get('observation')
        # one observation per step in this ATIF; if several tool calls in a step, observation content may be list
        for i,tc in enumerate(tcs):
            c=obs.get('content') if isinstance(obs,dict) else None
            st,ec,so,se=parse_obs(c) if c is not None else (None,None,'','')
            out.append(dict(step=s['step_id'],name=tc['function_name'],args=tc.get('arguments') or {},status=st,exit=ec,stdout=so,stderr=se,
                            t=(tc.get('extra') or {}).get('elapsed_s')))
    return out

def feats(cfgdir,task):
    d=load_trace(cfgdir,task)
    if d is None: return None
    cs=calls(d)
    sub=[i for i,c in enumerate(cs) if c['name']=='submit_patch']
    upto=sub[0] if sub else len(cs)           # up to first submit (or whole trace when the agent timed out)
    pre=cs[:upto]
    runs=[c for c in pre if c['name']=='run_command']
    chk=[c for c in runs if kind(c['args'].get('command',''))in('pytest','python','py_compile') and c['exit'] is not None]
    last=chk[-1] if chk else None
    # edits
    edit_idx=[i for i,c in enumerate(pre) if c['name'] in('edit_file','write_file') and c['status']=='ok']
    last_edit=edit_idx[-1] if edit_idx else -1
    after_edit=[c for c in pre[last_edit+1:] if c['name']=='run_command' and c['exit'] is not None and kind(c['args'].get('command',''))in('pytest','python','py_compile')]
    pyt=[c for c in runs if kind(c['args'].get('command',''))=='pytest']
    return dict(n_calls=len(cs),submitted=bool(sub),
                last_check_kind=kind(last['args'].get('command','')) if last else None,
                last_check_exit=last['exit'] if last else None,
                last_check_cmd=(last['args'].get('command','')[:300] if last else None),
                check_after_last_edit=bool(after_edit),
                last_after_edit_kind=kind(after_edit[-1]['args'].get('command','')) if after_edit else None,
                last_after_edit_exit=after_edit[-1]['exit'] if after_edit else None,
                last_after_edit_cmd=(after_edit[-1]['args'].get('command','')[:300] if after_edit else None),
                n_pytest=len(pyt),
                pytest_cmds=[c['args'].get('command','')[:300] for c in pyt],
                pytest_exits=[c['exit'] for c in pyt],
                pytest_after_edit=[(c['args'].get('command','')[:300],c['exit']) for c in pyt if c in after_edit],
                n_edits=len(edit_idx),
                )
if __name__=='__main__':
    out={}
    for cfgdir,short in [('traces_v12','v12'),('traces_v12bg','v12bg')]:
        for t in valid:
            f=feats(cfgdir,t)
            if f: out[f'{short}:{t}']=f
    json.dump(out,open(N+'/trace_feats.json','w'),indent=1)
    print(len(out))
