#!/usr/bin/env python3
# Stage 2: backtest engine. Configurable filters. Replays day by day 2021-01-04 .. latest.
import sys, os, pickle
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = pickle.load(open(os.path.join(HERE,'rawdata.pkl'),'rb'))
POOL = RAW['pool']; C2N = RAW['code2name']
CODES = list(POOL.values())
BT_START = '20210104'

# ---------- build per-stock feature frames ----------
FEAT = {}
for code in CODES:
    q = RAW['qfq'][code].copy()        # qfq: open/high/low/close/vol  (price qfq)
    d = RAW['daily'][code].copy()      # raw: open/high/low/close/vol(手)/amount(千元)
    a = RAW['auction'][code].copy()    # auction: open/high/low/close/vol(shares)/amount(yuan)
    q = q.sort_values('trade_date'); d = d.sort_values('trade_date'); a = a.sort_values('trade_date')
    q = q.set_index('trade_date'); d = d.set_index('trade_date'); a = a.set_index('trade_date')
    f = pd.DataFrame(index=q.index)
    f['cq'] = q['close']; f['oq'] = q['open']; f['hq'] = q['high']
    f['ma20'] = f['cq'].rolling(20, min_periods=20).mean()
    f['ma60'] = f['cq'].rolling(60, min_periods=60).mean()
    f['high60'] = f['hq'].rolling(60, min_periods=20).max()
    f['chg20'] = f['cq'] / f['cq'].shift(20) - 1
    f['draw_amount'] = d['amount'].reindex(q.index)     # raw daily amount 千元
    f['draw_vol'] = d['vol'].reindex(q.index)           # raw daily vol 手
    f['draw_close'] = d['close'].reindex(q.index)       # raw daily close
    f['avg5vol'] = f['draw_vol'].rolling(5, min_periods=5).mean()  # 手, will shift when used
    # 60-day-high bar character (window ENDING at this row): is it 阴线? how many bars since?
    hq=f['hq'].values; oq=f['oq'].values; cqv=f['cq'].values
    n=len(f); hi_yin=np.zeros(n,dtype=bool); hi_ds=np.full(n,np.nan)
    for i in range(n):
        lo=max(0,i-59); j=lo+int(np.nanargmax(hq[lo:i+1]))
        hi_yin[i]=cqv[j]<oq[j]; hi_ds[i]=i-j
    f['hi_yin']=hi_yin; f['hi_ds']=hi_ds
    f['a_close'] = a['close'].reindex(q.index)
    f['a_open']  = a['open'].reindex(q.index)
    f['a_high']  = a['high'].reindex(q.index)
    f['a_low']   = a['low'].reindex(q.index)
    f['a_vol']   = a['vol'].reindex(q.index)            # shares
    f['a_amount']= a['amount'].reindex(q.index)         # yuan
    FEAT[code] = f

# ---------- ST intervals ----------
ST = {}
for code in CODES:
    nc = RAW['namechg'].get(code)
    ivs = []
    if nc is not None and len(nc):
        for _,r in nc.iterrows():
            nm = str(r.get('name',''))
            if 'ST' in nm:
                sd = str(r.get('start_date') or '00000000')
                ed = str(r.get('end_date') or '99999999')
                ivs.append((sd, ed))
    ST[code] = ivs
def is_st(code, day):
    for sd,ed in ST[code]:
        if sd <= day <= ed: return True
    return False

DAYS_ALL = sorted(set().union(*[set(FEAT[c].index) for c in CODES]))
DAYS = [d for d in DAYS_ALL if d >= BT_START]

# ---------- equal-weight regime index (qfq close-to-close mean) ----------
cqmat = pd.DataFrame({c: FEAT[c]['cq'] for c in CODES}).sort_index()
rets = cqmat.pct_change()
idx_ret = rets.mean(axis=1, skipna=True)          # equal-weight daily return
idx_level = (1+idx_ret.fillna(0)).cumprod()
idx_ma20 = idx_level.rolling(20, min_periods=20).mean()

def price_limit(code):
    p=code.split('.')[0]
    return 0.198 if (p.startswith('300') or p.startswith('301') or p.startswith('688')) else 0.098

def limit_down_T(code, T):
    # T-day close limit-down? (qfq close vs T-1 close, board-aware, 1.5% buffer)
    f=FEAT[code]
    if T not in f.index: return False
    il=f.index.get_loc(T)
    if il<1: return False
    tm1c=f.iloc[il-1]['cq']; Tc=f.iloc[il]['cq']
    if pd.isna(tm1c) or tm1c<=0 or pd.isna(Tc): return False
    return (Tc/tm1c-1) <= -(price_limit(code)-0.015)

def feat_at(code, day):
    f = FEAT[code]
    if day not in f.index: return None
    return f.loc[day]

def run(require_bull=True, label='with_bull', hard_gates=False, tg_hi=None, yin_max_days=None,
        exclude=None, bo_ratio=None, bo_chg=0.40, deep_mode='on', deep_min_lb=None,
        sell_open_on_ld=True, open_rules=None):
    # open_rules: dict ts_code -> 'no_high'(开盘>=0不买) / 'no_low'(开盘<0不买). 个股盘口过滤。
    # sell_open_on_ld: if a pick hit 跌停 on T, settle the sell at T+1 OPEN (not T+1 close).
    # exclude: set of ts_codes to drop from candidate universe.
    # bo_ratio/bo_chg: tail filter — drop picks with 贴高比>=bo_ratio AND 20日涨幅>bo_chg.
    # tg_hi: optional upper bound on 贴高比 (tm1_close/high60). e.g. 0.96 -> only 93%~96% band.
    # yin_max_days: if set (e.g. 7), drop picks whose 60日高点 bar is 阴线 AND 距高点 > yin_max_days
    #               trading days. 阳线高点 unrestricted. Applied globally (all tiers + Top5).
    # hard_gates: globally drop 高开>9.8% / 20日涨幅>100% / 量比>20 from the whole candidate
    #             universe BEFORE any tier (affects 兜底/深兜底 and Top5 display too).
    days = DAYS
    decisions = []   # per backtest day
    for k, T in enumerate(days):
        # previous trade day index in the full per-stock series handled via shift; use global prev day
        prev = DAYS_ALL[DAYS_ALL.index(T)-1] if DAYS_ALL.index(T)>0 else None
        # regime switch uses T-1 index level vs its MA20
        regime_attack = False
        if prev in idx_level.index and prev in idx_ma20.index:
            if pd.notna(idx_ma20.loc[prev]) and idx_level.loc[prev] > idx_ma20.loc[prev]:
                regime_attack = True
        rows = []
        for code in CODES:
            f = FEAT[code]
            if T not in f.index: continue
            iloc = f.index.get_loc(T)
            if iloc < 1: continue
            r = f.iloc[iloc]
            rp = f.iloc[iloc-1]              # T-1 row
            tm1_close = rp['cq']
            ma20 = rp['ma20']; ma60 = rp['ma60']; high60 = rp['high60']
            if pd.isna(tm1_close): continue
            chg20 = rp['chg20']
            # 量比: auction vol(shares)/100 / (avg5 daily vol(手, up to T-1)/240)
            avg5 = rp['avg5vol']            # mean of 5 days ending T-1
            avol = r['a_vol']
            if pd.isna(avg5) or avg5<=0 or pd.isna(avol):
                liangbi = np.nan
            else:
                liangbi = (avol/100.0) / (avg5/240.0)
            a_close=r['a_close']; a_high=r['a_high']; a_low=r['a_low']; a_open=r['a_open']
            raw_prev_close = rp['draw_close']
            kpzf = (a_close/raw_prev_close - 1) if (pd.notna(a_close) and pd.notna(raw_prev_close) and raw_prev_close>0) else np.nan
            if pd.notna(a_high) and pd.notna(a_low) and a_high>a_low:
                zwpos = (a_close-a_low)/(a_high-a_low)
            else:
                zwpos = 0.5
            amount_yi = rp['draw_amount']/1e5 if pd.notna(rp['draw_amount']) else np.nan  # 千元 -> 亿元
            tiegao = pd.notna(high60) and tm1_close >= high60*0.93 \
                     and (tg_hi is None or tm1_close <= high60*tg_hi)
            bull = pd.notna(ma20) and pd.notna(ma60) and (tm1_close>ma20>ma60)
            st = is_st(code, T)
            rows.append(dict(code=code, name=C2N[code], liangbi=liangbi, tiegao=tiegao, bull=bull,
                chg20=chg20, a_close=a_close, a_high=a_high, a_low=a_low, a_open=a_open,
                zwpos=zwpos, kpzf=kpzf, amount_yi=amount_yi, st=st,
                tm1_close=tm1_close, high60=high60,
                hi_yin=bool(rp['hi_yin']), hi_ds=rp['hi_ds'],
                oq=r['oq'], cq=r['cq']))
        df = pd.DataFrame(rows)
        if hard_gates and len(df):
            df = df[(df.kpzf.notna()) & (df.kpzf<0.098) &
                    (df.liangbi.notna()) & (df.liangbi<=20) &
                    (~(df.chg20>1.0))].copy()
        if yin_max_days is not None and len(df):
            # drop 阴线高点 that are stale (距高点 > yin_max_days); 阳线高点 kept
            df = df[~(df.hi_yin & (df.hi_ds>yin_max_days))].copy()
        if exclude and len(df):
            df = df[~df.code.isin(exclude)].copy()
        if open_rules and len(df):
            def _keep_open(x):
                rule=open_rules.get(x.code)
                if rule=='no_high' and pd.notna(x.kpzf) and x.kpzf>=0: return False
                if rule=='no_low'  and pd.notna(x.kpzf) and x.kpzf<0:  return False
                return True
            df=df[df.apply(_keep_open,axis=1)].copy()
        if bo_ratio is not None and len(df):
            # tail filter: drop 破高(贴高比>=bo_ratio) 且 已涨多(20日涨幅>bo_chg) 的追高接力
            tgr = df.tm1_close/df.high60
            df = df[~((tgr>=bo_ratio) & (df.chg20>bo_chg))].copy()
        dec = dict(date=T, k=k, regime='进攻' if regime_attack else '防守',
                   engine='空仓', picks=[], df=df)
        if regime_attack and len(df):
            def base_ok(x):
                ok = pd.notna(x.liangbi) and (3 < x.liangbi < 20) and x.tiegao \
                     and pd.notna(x.amount_yi) and x.amount_yi>=1.0 \
                     and pd.notna(x.kpzf) and x.kpzf<0.098 and (not x.st)
                if require_bull: ok = ok and x.bull
                return ok
            cand = df[df.apply(base_ok, axis=1)].copy()
            cand = cand.sort_values('liangbi', ascending=False)
            picks=[]
            if len(cand):
                rws = [cand.iloc[i] for i in range(min(3, len(cand)))]
                # 选1 = 量比第1名 (chg20<=1.0 已由硬过滤保证;选1不设开盘下限)
                picks.append(rws[0]['code'])
                # 选2/选3 = 量比第2、3名;须 20日涨幅<=80% 且 开盘涨跌幅>-1.5%。
                # 不满足则该名次空缺,不顺延、不向下递补(有几个算几个)。
                for i in (1, 2):
                    if i < len(rws):
                        rx = rws[i]
                        if (not (rx.chg20 > 0.8)) and (rx.kpzf > -0.015):
                            picks.append(rx['code'])
            if picks:
                dec['engine']='主选'; dec['picks']=picks
            else:
                # 兜底: drop 量比(3,20)&chg20; keep tiegao,bull?,amount,kpzf,st
                def fb_ok(x):
                    ok = x.tiegao and pd.notna(x.amount_yi) and x.amount_yi>=1.0 \
                         and pd.notna(x.kpzf) and x.kpzf<0.098 and (not x.st) and pd.notna(x.liangbi)
                    if require_bull: ok = ok and x.bull
                    return ok
                fb = df[df.apply(fb_ok, axis=1)].sort_values('liangbi', ascending=False)
                if len(fb):
                    dec['engine']='兜底'; dec['picks']=[fb.iloc[0]['code']]
                elif deep_mode!='off':
                    # 深兜底: amount>=1, kpzf<9.8, non-st, 量比<20
                    # deep_mode: 'on'(原版) / 'off'(关闭→空仓) / 'tight'(加量比>3下限+贴高)
                    def db_ok(x):
                        ok = pd.notna(x.amount_yi) and x.amount_yi>=1.0 and pd.notna(x.kpzf) \
                               and x.kpzf<0.098 and (not x.st) and pd.notna(x.liangbi) and x.liangbi<20
                        if deep_mode=='tight':
                            ok = ok and x.liangbi>3 and x.tiegao
                        if deep_min_lb is not None:
                            ok = ok and x.liangbi>deep_min_lb
                        return ok
                    db = df[df.apply(db_ok, axis=1)].sort_values('liangbi', ascending=False)
                    if len(db):
                        dec['engine']='深兜底'; dec['picks']=[db.iloc[0]['code']]
        decisions.append(dec)

    # ---------- net value: two batches staggered by 1 day ----------
    n=len(days)
    fac = {'A':np.ones(n), 'B':np.ones(n)}
    for k,dec in enumerate(decisions):
        if dec['picks'] and k+1<n:
            batch = 'A' if k%2==0 else 'B'
            picks=dec['picks']
            # entry factor: close_q(k)/open_q(k) averaged; sell factor close_q(k+1)/close_q(k)
            fent=[]; fsel=[]
            for code in picks:
                f=FEAT[code]; T=days[k]; T1=days[k+1]
                if T in f.index and T1 in f.index:
                    oq=f.loc[T,'oq']; ckq=f.loc[T,'cq']; ck1=f.loc[T1,'cq']; ok1=f.loc[T1,'oq']
                    if pd.notna(oq) and oq>0 and pd.notna(ckq) and pd.notna(ck1):
                        # T日跌停 → 次日开盘卖(sell at T+1 open); else T+1 close
                        sellp = ok1 if (sell_open_on_ld and limit_down_T(code,T) and pd.notna(ok1) and ok1>0) else ck1
                        fent.append(ckq/oq); fsel.append(sellp/ckq)
            if fent:
                fac[batch][k]   *= np.mean(fent)
                fac[batch][k+1] *= np.mean(fsel)
    nvA = 0.5*np.cumprod(fac['A']); nvB = 0.5*np.cumprod(fac['B'])
    nv = nvA+nvB
    nv_series = pd.Series(nv, index=days)
    # daily returns & yearly
    daily_ret = nv_series.pct_change().fillna(nv_series.iloc[0]/1.0 - 1)
    yrs={}
    for y in ['2021','2022','2023','2024','2025','2026']:
        mask=[d.startswith(y) for d in days]
        if not any(mask): continue
        sub=nv_series[[d for d in days if d.startswith(y)]]
        # year return = end/ start_of_year_prev
        sidx=[i for i,d in enumerate(days) if d.startswith(y)]
        start_nv = nv[sidx[0]-1] if sidx[0]>0 else 1.0
        yrs[y]= nv[sidx[-1]]/start_nv - 1
    # max drawdown
    run_max=np.maximum.accumulate(nv); dd=nv/run_max-1; maxdd=dd.min()
    total = nv[-1]/1.0 -1
    return dict(label=label, require_bull=require_bull, days=days, decisions=decisions,
                nv=nv_series, nvA=nvA, nvB=nvB, daily_ret=daily_ret, yearly=yrs,
                maxdd=maxdd, total=total, idx_level=idx_level, idx_ma20=idx_ma20)

if __name__=='__main__':
    # canonical v2.1 strategy: hard gates + 多头排列 + 阴线高点距≤7天过滤 + 深兜底量比>5
    #   + 个股盘口过滤(高开不买/低开不买) + T日跌停次日开盘卖
    _n2c={v:k for k,v in C2N.items()}
    NO_HIGH=['英维克','兆易创新','联瑞新材','高澜股份','绿的谐波']      # 开盘>=0 不买
    NO_LOW =['生益电子','风华高科','景旺电子','亨通光电']               # 开盘<0  不买
    OPEN_RULES={}
    for nm in NO_HIGH:
        if nm in _n2c: OPEN_RULES[_n2c[nm]]='no_high'
    for nm in NO_LOW:
        if nm in _n2c: OPEN_RULES[_n2c[nm]]='no_low'
    g=run(require_bull=True, label='gated', hard_gates=True, yin_max_days=7, deep_min_lb=5,
          open_rules=OPEN_RULES)
    pickle.dump(g, open(os.path.join(HERE,'res_gated.pkl'),'wb'))
    print(f"[v2.1 canonical] final_nv={g['nv'].iloc[-1]:.2f} total={g['total']*100:.1f}% maxDD={g['maxdd']*100:.1f}%")
    for y,v in g['yearly'].items(): print(f"   {y}: {v*100:7.2f}%")
    print()
    for rb in (True, False):
        res=run(require_bull=rb, label='with_bull' if rb else 'no_bull')
        pickle.dump(res, open(os.path.join(HERE, f"res_{'with' if rb else 'no'}_bull.pkl"),'wb'))
        ntrade=sum(1 for d in res['decisions'] if d['picks'])
        nattack=sum(1 for d in res['decisions'] if d['regime']=='进攻')
        print(f"=== {'WITH 多头排列' if rb else 'WITHOUT 多头排列'} ===")
        print(f" days={len(res['days'])} attack_days={nattack} trade_days={ntrade}")
        print(f" final_nv={res['nv'].iloc[-1]:.4f}  total_return={res['total']*100:.2f}%  maxDD={res['maxdd']*100:.2f}%")
        for y,v in res['yearly'].items():
            print(f"   {y}: {v*100:7.2f}%")
        print()
