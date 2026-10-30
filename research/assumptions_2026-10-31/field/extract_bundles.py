import ast, json, sys, glob, os, re
out={}
def consts(node):
    try: return ast.literal_eval(node)
    except Exception: return None
def find_bundles(src):
    found=[]
    try: tree=ast.parse(src)
    except Exception:
        return found
    for n in ast.walk(tree):
        v=None
        if isinstance(n,ast.Dict):
            v=consts(n)
        elif isinstance(n,ast.Call) and getattr(n.func,'attr','')=='loads' and n.args and isinstance(n.args[0],ast.Constant) and isinstance(n.args[0].value,str):
            try: v=json.loads(n.args[0].value)
            except Exception: v=None
        if isinstance(v,dict) and any(isinstance(k,str) and k.endswith('agent.yaml') for k in v):
            found.append(v)
    return found
for p in sorted(glob.glob('nb/*/*.ipynb')):
    nb=json.load(open(p))
    name=p.split('/')[1]
    bs=[]
    for c in nb['cells']:
        if c['cell_type']!='code': continue
        src=''.join(c['source'])
        # drop magics
        src='\n'.join(l for l in src.split('\n') if not l.strip().startswith(('%','!')))
        bs+=find_bundles(src)
    out[name]=bs
    print(name,len(bs),'bundle dict(s)', [sorted(b.keys()) for b in bs][:1])
json.dump(out,open('bundles.json','w'))
