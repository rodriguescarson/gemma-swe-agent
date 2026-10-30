import sys, re, json, statistics as st
sys.path.insert(0,'<scratch>/assume/runtime/scripts')
from load import *

def patch_files(patch):
    return re.findall(r'^diff --git a/(\S+) b/', patch or '', flags=re.M)
def is_test_path(p):
    b=p.split('/')[-1]
    return ('/tests/' in '/'+p) or ('/test/' in '/'+p) or b.startswith('test_') or b.endswith('_test.py') or b=='conftest.py'
def is_scratch(p):
    b=p.split('/')[-1].lower()
    return p.startswith('/tmp') or bool(re.match(r'(repro|reproduc|scratch|tmp|temp|debug|demo|try|check|verify|test_)',b))
CMD_WRITE=re.compile(r"(sed\s+-i|\bpatch\b\s+-p|git\s+apply|tee\s|>>?\s*[\w./-]+\.py|write_text|\.write\(|open\([^)]*['\"]w)")

def timeline(t):
    """return list of dict per agent step: call_t, obs_t, start_t, ctoks, ptoks, tools[(name,args,ok)], msg"""
    out=[]; prev_end=0.0
    for s in t['steps']:
        ex=s.get('extra') or {}
        if s['source']=='system' and ex.get('event_type')=='system_instruction':
            prev_end=ex['elapsed_s']; continue
        if s['source']=='user': continue
        if s['source']=='system':   # continuation nudge
            out.append(dict(kind='nudge',call_t=ex.get('elapsed_s'),obs_t=None,start_t=prev_end,ctoks=0,ptoks=0,tools=[],msg=''))
            continue
        if s['source']!='agent': continue
        call_t=ex.get('elapsed_s')
        tcs=s.get('tool_calls') or []
        obs=s.get('observation')
        obs_t=None; ok=None; content=''
        if obs:
            obs_t=(obs.get('extra') or {}).get('elapsed_s')
            content=str(obs.get('content',''))
            ok='"status": "ok"' in content[:60] or '"status":"ok"' in content[:60]
        m=s.get('metrics') or {}
        out.append(dict(kind=ex.get('event_type'),call_t=call_t,obs_t=obs_t,start_t=prev_end,ctoks=m.get('completion_tokens',0),ptoks=m.get('prompt_tokens',0),
                        tools=[(tc['function_name'],tc.get('arguments') or {}) for tc in tcs],ok=ok,obs=content[:300],msg=str(s.get('message') or '')[:200],
                        llmcalls=s.get('llm_call_count')))
        prev_end=obs_t if obs_t is not None else call_t
    return out

def analyse(run,i,rr):
    t=trace(run,i); r=rr[i]
    tl=timeline(t)
    pf=[p for p in patch_files(r.get('patch')) if not is_test_path(p) and not is_scratch(p)]
    edits=[]  # (time, kind, path)
    for e in tl:
        for (n,a) in e['tools']:
            if n in ('edit_file','write_file') and e.get('ok'):
                p=a.get('filepath') or ''
                edits.append((e['obs_t'] or e['call_t'], n, p))
            elif n=='run_command':
                c=str(a.get('command',''))
                if CMD_WRITE.search(c) and e.get('ok'):
                    edits.append((e['obs_t'] or e['call_t'],'cmd',c[:80]))
    src_edits=[x for x in edits if (x[1] in ('edit_file','write_file') and x[2] in pf) or (x[1]=='cmd' and any(f.split('/')[-1] in x[2] for f in pf))]
    submit=[e['call_t'] for e in tl if any(n=='submit_patch' for n,_ in e['tools'])]
    last_el=max([x for e in tl for x in (e['call_t'],e['obs_t']) if x is not None]+[0])
    capped=('session timeout' in (r.get('err') or ''))
    return dict(id=i,resolved=bool(r['resolved']),capped=capped,secs=r['secs'],calls=r['calls'],last_el=last_el,
                n_steps=len([e for e in tl if e['kind']!='nudge']),src_edit_times=[round(x[0],1) for x in src_edits],
                first_src_edit=min([x[0] for x in src_edits],default=None),last_src_edit=max([x[0] for x in src_edits],default=None),
                submit_t=submit[0] if submit else None,patch_src_files=pf,tl=tl,err=r.get('err'),ctoks=sum(e['ctoks'] for e in tl),
                patch_len=len(r.get('patch') or ''))

BASEPASS={'fastapi_14077','fastapi_14851','requests_6644'}
def end_kind(a):
    if a['submit_t'] is not None: return 'submit'
    if a['capped'] or a['secs']>=299 or a['last_el']>=295: return 'cap'
    return 'other'
def load_all(run):
    rr=rows(run); A=[analyse(run,i,rr) for i in VALID]
    for a in A: a['end']=end_kind(a); a['base']=a['id'] in BASEPASS
    return A
