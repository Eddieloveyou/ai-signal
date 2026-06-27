#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI双引擎·量比策略 每日信号. 用法: python3 daily_signal.py [open|close] [YYYYMMDD]
依赖 tushare, token 从环境变量 TUSHARE_TOKEN 读取(或第3个参数)。"""
import os, sys, numpy as np, pandas as pd, tushare as ts

POOL = {  # 60只AI主池
 '风华高科':'000636.SZ','华工科技':'000988.SZ','德明利':'001309.SZ','大族激光':'002008.SZ','科大讯飞':'002230.SZ',
 '东山精密':'002384.SZ','双环传动':'002472.SZ','科士达':'002518.SZ','英维克':'002837.SZ','洁美科技':'002859.SZ',
 '深南电路':'002916.SZ','创世纪':'300083.SZ','拓尔思':'300229.SZ','中际旭创':'300308.SZ','润泽科技':'300442.SZ',
 '胜宏科技':'300476.SZ','高澜股份':'300499.SZ','新易盛':'300502.SZ','昊志机电':'300503.SZ','长芯博创':'300548.SZ',
 '精测电子':'300567.SZ','太辰光':'300570.SZ','长川科技':'300604.SZ','光库科技':'300620.SZ','江苏雷利':'300660.SZ',
 '江丰电子':'300666.SZ','金力永磁':'300748.SZ','龙磁科技':'300835.SZ','兆龙互连':'300913.SZ','申菱环境':'301018.SZ',
 '铜冠铜箔':'301217.SZ','永鼎股份':'600105.SH','中国巨石':'600176.SH','生益科技':'600183.SH','有研新材':'600206.SH',
 '亨通光电':'600487.SH','中天科技':'600522.SH','柏诚股份':'601133.SH','长飞光纤':'601869.SH','中科曙光':'603019.SH',
 '华正新材':'603186.SH','景旺电子':'603228.SH','宏和科技':'603256.SH','鸣志电器':'603728.SH','兆易创新':'603986.SH',
 '中微公司':'688012.SH','绿的谐波':'688017.SH','拓荆科技':'688072.SH','步科股份':'688160.SH','生益电子':'688183.SH',
 '寒武纪':'688256.SH','联瑞新材':'688300.SH','汇成股份':'688403.SH','源杰科技':'688498.SH','佰维存储':'688525.SH',
 '华丰科技':'688629.SH','鼎通科技':'688668.SH','伟创电气':'688698.SH','普冉股份':'688766.SH','中控技术':'688777.SH'}
N2T={v:k for k,v in POOL.items()}
WHITE5={'商贸零售','社会服务','医药生物','电子','公用事业'}

def api():
    tok=os.environ.get('TUSHARE_TOKEN') or (sys.argv[3] if len(sys.argv)>3 else '')
    ts.set_token(tok); return ts.pro_api()
pro=api()

def last_trade_day(d):
    cal=pro.trade_cal(exchange='SSE', end_date=d, start_date=str(int(d[:4])-1)+d[4:], is_open=1)
    days=sorted(cal['cal_date']); return days[-1], days

def daily_hist(code, end, n=130):
    df=pro.daily(ts_code=code, end_date=end).sort_values('trade_date')
    return df.tail(n).reset_index(drop=True)

def pool_index_ma20(end):
    closes={}
    for c in POOL.values():
        d=daily_hist(c,end,80)
        if len(d)>=21: closes[c]=d.set_index('trade_date')['close']
    df=pd.DataFrame(closes); reb=df/df.bfill().iloc[0]; idx=reb.mean(axis=1)
    ma=idx.rolling(20).mean()
    return idx, ma

def run_open(T):
    print(f"【今日进攻仓 9:25】{T}")
    # 1. AI主池指数 vs MA20 (T-1判断)
    idx,ma=pool_index_ma20(T)
    dts=list(idx.index); tm1=dts[-2] if dts[-1]==T else dts[-1]
    if idx.get(tm1) <= ma.get(tm1):
        print(f"AI主池等权指数({idx.get(tm1):.4f}) ≤ MA20({ma.get(tm1):.4f}) → AI熄火,今日走防守(反弹见14:55)"); return
    print(f"AI主池指数 > MA20 → 进攻")
    # 2. 9:25集合竞价量比 + 筛选
    auc=pro.stk_auction_o(trade_date=T)
    avmap=dict(zip(auc['ts_code'],auc['vol']))
    rows=[]
    for nm,c in POOL.items():
        d=daily_hist(c,T,130)
        if T not in set(d['trade_date']) or len(d)<61: continue
        i=d.index[d['trade_date']==T][0]
        if i<60: continue
        vol5=d['vol'].iloc[i-5:i].mean(); av=avmap.get(c)
        if not av or vol5<=0: continue
        qb=(av/100)/(vol5/240)
        h60=d['high'].iloc[i-60:i].max(); ctm1=d['close'].iloc[i-1]
        ma20=d['close'].iloc[i-20:i].mean(); ma60=d['close'].iloc[i-60:i].mean()
        run20=d['close'].iloc[i-1]/d['close'].iloc[i-21]-1
        amt5=d['amount'].iloc[i-5:i].mean()/10  # 千元→万元? amount单位千元; /10万=亿. 用>=100000(千元)=1亿
        amt5b=d['amount'].iloc[i-5:i].mean()
        gap=d['open'].iloc[i]/d['close'].iloc[i-1]-1
        rows.append(dict(nm=nm,c=c,qb=qb,near=ctm1>=0.95*h60,trend=(ctm1>ma20)&(ma20>ma60),
            run20=run20,amt=amt5b,gap=gap,nearpct=ctm1/h60*100))
    D=pd.DataFrame(rows)
    def show(sel,tag):
        s=sel.sort_values('qb',ascending=False)
        for k,(_,r) in enumerate(s.head(3).iterrows(),1):
            print(f"  No.{k} {r['nm']}({r['c']}) 量比{r['qb']:.2f} 开盘{r['gap']*100:+.1f}% 现价/60日高{r['nearpct']:.0f}% [{tag}]")
        return len(s)>0
    main=D[(D['qb']>3)&(D['qb']<20)&D['near']&D['trend']&(D['run20']<=0.6)&(D['amt']>=100000)&(D['gap']<0.098)]
    if len(main)>0: show(main,'主选·前3名各1/3'); print("  → 开盘买入、明日收盘卖出,两份资金错开滚动"); return
    fb1=D[(D['qb']<20)&D['near']&D['trend']&(D['run20']<=0.6)&(D['amt']>=100000)&(D['gap']<0.098)]
    fb2=D[(D['qb']<20)&D['near']&D['trend']&(D['amt']>=100000)&(D['gap']<0.098)]
    deep=D[(D['qb']<20)&(D['amt']>=100000)&(D['gap']<0.098)]
    for sel,tag in [(fb1,'兜底①放宽量比'),(fb2,'兜底②放宽前20涨幅'),(deep,'深兜底·真空仓·牛市专用·慎用·小仓位')]:
        if len(sel)>0:
            r=sel.sort_values('qb',ascending=False).iloc[0]
            print(f"  兜底1只: {r['nm']}({r['c']}) 量比{r['qb']:.2f} 开盘{r['gap']*100:+.1f}% [{tag}]")
            print("  → 开盘买入、明日收盘卖出"); return
    print("  今日无任何可买标的,空仓")

def run_close(T):
    print(f"【今日防守·超跌反弹 14:55】{T}")
    idx,ma=pool_index_ma20(T)
    dts=list(idx.index); tm1=dts[-2] if dts[-1]==T else dts[-1]
    if idx.get(tm1) > ma.get(tm1):
        print("AI主池指数 > MA20 → AI在场,今日是进攻日,防守不启用(进攻见9:25)"); return
    print("AI主池跌破MA20 → AI熄火,进入防守")
    # 中证1000开关
    zz=pro.index_daily(ts_code='000852.SH', end_date=T).sort_values('trade_date').tail(25)
    zc=zz['close'].iloc[-1]; zma=zz['close'].tail(20).mean(); zo=zz['open'].iloc[-1]
    if not (zc>zma or zc>zo):
        print(f"中证1000({zc:.0f}) 跌破MA20({zma:.0f}) 且收阴 → 今日不做反弹,资金停泊银行ETF 512800"); return
    print(f"中证1000 站上MA20或收阳 → 做超跌反弹")
    print("  [提示] 全市场超跌反弹选股需当日近收盘实时行情;tushare日线为EOD,建议用 ts.realtime_quote 对预筛候选取实时价后套用规则(本脚本预留接口)。")
    print("  规则: 10cm主板 + 板块∈{商贸/社服/医药/电子/公用} + 当天收阳 + T当日跌≤3% + 强/中/兜底信号 + 买20日跌最深Top1; 尾盘买,明日开盘>0.3%卖否则明日尾盘卖。")

if __name__=='__main__':
    mode=sys.argv[1] if len(sys.argv)>1 else 'open'
    T=sys.argv[2] if len(sys.argv)>2 else None
    if not T:
        import datetime; T,_=last_trade_day(pro.trade_cal(exchange='SSE',is_open=1,end_date='29991231').iloc[-1]['cal_date'] if False else __import__('time').strftime('%Y%m%d'))
    (run_open if mode=='open' else run_close)(T)
