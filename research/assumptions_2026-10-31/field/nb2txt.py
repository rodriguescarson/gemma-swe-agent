import json,sys
nb=json.load(open(sys.argv[1]))
out=[]
for c in nb['cells']:
    src=''.join(c['source'])
    out.append(f"[{c['cell_type']}]\n{src}\n")
    if c['cell_type']=='code':
        for o in c.get('outputs',[]):
            if 'text' in o: out.append('OUT: '+''.join(o['text'])[:4000])
            elif 'data' in o and 'text/plain' in o['data']: out.append('OUT: '+''.join(o['data']['text/plain'])[:4000])
open(sys.argv[2],'w').write('\n'.join(out))
print(len('\n'.join(out)))
