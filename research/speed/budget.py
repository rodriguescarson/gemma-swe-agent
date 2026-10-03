"""12 h budget for v10.x at caps 5.0-6.5 min (speed.md sect. 6)."""
import statistics as st
from sim import agent_times, in_clock, solve_k, V_of, S_START, OVERSHOOT, H12
tv4, tv9 = agent_times('k_v4'), agent_times('k_v9_eog')
tv10 = agent_times('p1_v10') + agent_times('r2_v10_1')
print('public mean agent s/task: v4 %.1f  v9_eog %.1f  v10.x %.1f (pooled p1_v10+r2_v10_1, L4-scaled)' % (
    st.mean(a for a,_ in tv4), st.mean(a for a,_ in tv9), st.mean(a for a,_ in tv10)))
scen=[]
for name,times,T_h,ne in (('sub3',tv4,10.50,61/74),('sub3',tv4,10.42,61/74),('sub4',tv9,10.07,63/74)):
    for vf in (1.5,2.0,2.5):
        A=T_h-V_of(ne,vf)
        scen.append((name,T_h,vf,A))
print('\nscenario            A(h)  N   ovh  k     | v10.x in-clock hours at cap 5.0 / 5.5 / 6.0 / 6.5 min  (capped share at 6.0)')
worst={}
for name,T_h,vf,A in scen:
    for n in (120,130):
        for ovh in (5.0,12.0):
            k=solve_k(times:=(tv4 if name=='sub3' else tv9), A, n)
            hs=[]
            for cap in (300,330,360,390):
                per=[ovh+(cap+OVERSHOOT if c else min(k*a,cap+OVERSHOOT)) for a,c in tv10]
                hs.append((S_START+n*st.mean(per))/3600)
                worst[cap]=max(worst.get(cap,0),hs[-1])
            capsh=sum(1 for a,c in tv10 if c or k*a>=360)/len(tv10)
            if ovh==5.0 or n==130:
                print(f'{name} T={T_h:5.2f} Vf={vf} {A:5.2f} {n} {ovh:4.0f} {k:5.2f} | ' + ' / '.join(f'{h:5.2f}' for h in hs) + f'   ({capsh:.0%})')
print('\nworst projected in-clock hours over all scenarios:', {c/60: round(h,2) for c,h in worst.items()})
# Distribution-free bound (gap_5 sect. 4): T(c1) <= S + N*ovh + max(m, c1/c0) * (A - S - N*ovh),
# m = v10.x per-task slowdown vs the calibrating bundle on public tasks (uncapped mean ratio).
m3 = st.mean(a for a,_ in tv10)/st.mean(a for a,_ in tv4); m4 = st.mean(a for a,_ in tv10)/st.mean(a for a,_ in tv9)
print(f'\nm(v10.x / v4) = {m3:.2f}, m(v10.x / v9_eog) = {m4:.2f}')
for name,T_h,vf,A in scen:
    m = m3 if name=='sub3' else m4
    for n,ovh in ((120,5.0),(130,12.0)):
        row=[]
        for c1 in (300,330,360,390):
            f=max(m, c1/300)
            row.append((S_START+n*ovh+f*(A*3600-S_START-n*ovh))/3600)
        print(f'bound {name} T={T_h} Vf={vf} A={A:.2f} N={n} ovh={ovh:.0f}: ' + ' / '.join(f'{h:5.2f}' for h in row))

print('\nDistribution-free bound by absolute validation time V (h), Q=0: cap 5.0 / 5.5 / 6.0 / 6.5 min')
for name,T_h,m in (('sub3',10.50,m3),('sub4',10.07,m4)):
    for V in (0.0,0.4,0.5,1.0,1.3,1.7):
        A=T_h-V
        for n,ovh in ((120,5.0),(130,12.0)):
            row=[(S_START+n*ovh+max(m,c/300)*(A*3600-S_START-n*ovh))/3600 for c in (300,330,360,390)]
            print(f'  {name} T={T_h:5.2f} V={V:3.1f} A={A:5.2f} N={n} ovh={ovh:2.0f}: '+' / '.join(f'{h:5.2f}' for h in row))
print('\nsub6 rule: with S+N*ovh = %.2f h, bound(c) = S+N*ovh + (c/300)*(T6 - S - N*ovh) <= 11.3 h (0.7 h margin) needs' % ((S_START+120*5)/3600))
for c in (330,360):
    b=(S_START+120*5)/3600
    print(f'  cap {c/60:.1f} min: T6 <= {b+(11.3-b)*300/c:.2f} h (11.5 h line: {b+(11.5-b)*300/c:.2f} h)')
