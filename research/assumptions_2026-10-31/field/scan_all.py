import re, glob, json, csv, collections, statistics as st
draws=list(csv.DictReader(open('draws_ds/x/public_config_draws.csv',encoding='utf-8')))
byref=collections.defaultdict(list)
for r in draws:
    if r['source']=='public_notebook': byref[r['notebook_ref']].append(int(r['tasks_of_58']))
def vals(txt,key):
    return sorted(set(re.findall(key+r'\\*["\']?\s*[:=]\s*\\*["\']?(\d+(?:\.\d+)?)',txt)),key=float)
rows=[]
refs=[l.strip() for l in open('nball/refs.txt')]
for ref in refs:
    d='nball/'+ref.replace('/','_')
    fs=glob.glob(d+'/*.ipynb')
    if not fs: continue
    txt=open(fs[0],encoding='utf-8').read()
    cap=vals(txt,'max_time_minutes'); calls=vals(txt,'max_tool_calls'); to=vals(txt,'timeout_seconds'); turns=vals(txt,'max_turns')
    temp=vals(txt,'temperature'); thk=vals(txt,'thinking_budget'); topk=vals(txt,'top_k')
    sc=byref.get(ref,[])
    rows.append((ref,cap,calls,to,turns,temp,thk,topk,sc))
print(len(rows),'notebooks parsed')
print('ref | max_time_min | max_calls | timeout_s | turns | temp | think | top_k | third-party scored draws (tasks/58)')
for r in rows:
    if r[8] or r[1]:
        print(r[0][:62].ljust(62),'|',','.join(r[1]),'|',','.join(r[2]),'|',','.join(r[3]),'|',','.join(r[4]),'|',','.join(r[5]),'|',','.join(r[6]),'|',','.join(r[7]),'|',r[8])
json.dump(rows,open('scan_all.json','w'))
