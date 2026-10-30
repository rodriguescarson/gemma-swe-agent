import json, glob, os, statistics as st
valid=set(l.strip() for l in open('<repo>/data/kaggle_valid_ids.txt') if l.strip())
for name,td in (('v12','tr_v12'),('garble','tr_garble')):
    rate=[];dt_all=[];tool_s=[]
    for p in sorted(glob.glob(td+'/traces/trace_*.json')):
        i=os.path.basename(p)[6:-5]
        if i not in valid: continue
        t=json.load(open(p)); prev=None
        for s in t['steps']:
            e=s.get('extra') if isinstance(s.get('extra'),dict) else {}
            el=e.get('elapsed_s')
            if s.get('source')!='agent' or el is None: continue
            m=s.get('metrics') or {}
            if prev is not None and m.get('completion_tokens'):
                dt=el-prev
                dt_all.append(dt)
                if m['completion_tokens']>=400 and dt>0: rate.append(m['completion_tokens']/dt)
            prev=el
    print(name,'steps',len(dt_all),'median s/step',round(st.median(dt_all),2),'mean',round(st.mean(dt_all),2),'tok/s (steps>=400 tok) median',round(st.median(rate),1),'p10',round(sorted(rate)[len(rate)//10],1))
