import sys,re,glob,json
N='<scratch>/assume/nearmiss'
def elines(task,cfg=None,k=10):
    ents=json.load(open(N+'/patches_main.json'))
    for i,e in enumerate(ents):
        if e['task']==task and (cfg is None or cfg in e['cfg'].split('+')):
            f=glob.glob(f'{N}/gr/runs/nm_main/replay_logs/{i}_{task}.log')[0]
            txt=open(f,errors='replace').read()
            fail=txt.split('=== FAILURES ===')[1].split('=== PASSES ===')[0] if '=== FAILURES ===' in txt else txt[:3000]
            # first failure block
            blocks=re.split(r'\n_{3,} .* _{3,}\n',fail)
            heads=re.findall(r'\n_{3,} (.*?) _{3,}\n',fail)
            out=[]
            for h,b in list(zip(heads,blocks[1:]))[:2]:
                el=[l for l in b.split('\n') if l.startswith('E ')][:k]
                out.append((h,el))
            return e['cfg'],out
if __name__=='__main__':
    c,o=elines(sys.argv[1],sys.argv[2] if len(sys.argv)>2 and sys.argv[2]!='-' else None, int(sys.argv[3]) if len(sys.argv)>3 else 8)
    print(sys.argv[1],c)
    for h,el in o:
        print(' ',h); [print('    ',l[:170]) for l in el]
