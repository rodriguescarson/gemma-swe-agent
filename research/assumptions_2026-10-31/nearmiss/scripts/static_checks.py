"""(b) cheap static checks on each failing patch, applied to a clone of the base workspace:
   py_compile of changed .py files, and `python -c import <module>` for each changed package module."""
import json, os, subprocess, shutil, sys, re, tempfile
N='<scratch>/assume/nearmiss'
S=N.rsplit('/assume',1)[0]
PY=S+'/labels/venv/bin/python'
WS=os.path.expanduser('~/.cache/g4/ws')
TMP=N+'/tmp_ws'; os.makedirs(TMP,exist_ok=True)

def changed_files(patch):
    fs=[]
    for l in patch.split('\n'):
        m=re.match(r'^diff --git a/(.*?) b/(.*)$',l)
        if m: fs.append(m.group(2))
    return fs

def run(entry):
    task=entry['task']; patch=entry['patch']
    dst=f'{TMP}/{task}_{abs(hash(patch))%10**8}'
    if os.path.exists(dst): shutil.rmtree(dst)
    subprocess.run(['cp','-cR',f'{WS}/{task}/base',dst],check=True)
    pf=dst+'.patch'; open(pf,'w').write(patch if patch.endswith('\n') else patch+'\n')
    ap=subprocess.run(['git','apply','--whitespace=nowarn',pf],cwd=dst,capture_output=True,text=True)
    res=dict(task=task,apply_rc=ap.returncode,apply_err=ap.stderr[:300],files=changed_files(patch))
    env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':dst,'HOME':TMP}
    comp=[];imp=[]
    for f in res['files']:
        if not f.endswith('.py') or not os.path.exists(f'{dst}/{f}'): continue
        r=subprocess.run([PY,'-c','import sys;compile(open(sys.argv[1],"rb").read(),sys.argv[1],"exec")',f],cwd=dst,env=env,capture_output=True,text=True)
        comp.append((f,r.returncode,r.stderr.strip().split('\n')[-1][:200]))
        # import smoke for modules inside a package (skip tests, scripts, docs_src, setup files)
        parts=f[:-3].split('/')
        if parts[0] in('tests','scripts','docs_src','docs','benchmarks','examples','tools'): continue
        mod='.'.join(parts[:-1] if parts[-1]=='__init__' else parts)
        r=subprocess.run([PY,'-c','import '+mod],cwd=dst,env=env,capture_output=True,text=True,timeout=120)
        imp.append((mod,r.returncode,r.stderr.strip().split('\n')[-1][:200]))
    res['py_compile']=comp; res['import']=imp
    shutil.rmtree(dst,ignore_errors=True); os.remove(pf)
    return res
if __name__=='__main__':
    ents=json.load(open(N+'/patches_main.json'))
    out=[run(e) for e in ents]
    json.dump(out,open(N+'/static_checks.json','w'),indent=1)
    print(len(out),'entries; apply failures',sum(1 for o in out if o['apply_rc']),
          'py_compile fails',sum(1 for o in out if any(c[1] for c in o['py_compile'])),
          'import fails',sum(1 for o in out if any(c[1] for c in o['import'])))
