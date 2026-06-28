#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI主池·集合竞价量比 日内策略 v2.3 — 每日早盘(9:25)信号 [并行加速 + 推送]
用法: python3 daily_signal.py [YYYYMMDD]
  token 读环境变量 TUSHARE_TOKEN。
  推送(任选其一, 配了就推): TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID / WECOM_WEBHOOK / LARK_WEBHOOK / PUSHPLUS_TOKEN。
输出: 只告诉当天买哪几只(主选一/二/三 或 兜底 / 深兜底, 或熄火日空仓), 不输出收益率。

规则 v2.3:
  择时: 60只AI主池等权指数 T-1收盘 > MA20 → 进攻; ≤ MA20(熄火) → 防守=空仓(持现金)。
        银行ETF(512800)/黄金ETF(518880) 仅作参考对比, 不实际持有。
  量比 = (今日9:25竞价量/100) ÷ (过去5日日均量/240)。
  候选基础筛选: 量比∈(3,20) + T-1收盘≥60日高×93%(贴高) + 多头排列(收盘>MA20>MA60)
              + 近5日均成交额≥1亿 + 开盘涨幅<9.8% + 非ST。
  主选一: 在候选中剔除「20日涨幅>100%」后, 取量比第1。
  主选二: 在主选一之外, 剔除「20日涨幅>80%」且剔除「终值位置>80%」后, 取量比第1。
  主选三: 在主选一二之外, 剔除「20日涨幅>80%」且剔除「终值位置>80%」后, 取量比第1。
  → 有几只算几只(1~3只), 均分仓位。
  兜底(主选0只): 去掉量比∈(3,20)与20日涨幅限制; 留 贴高+多头+额≥1亿+开盘<9.8%+非ST → 量比第1, 满仓1只。
  深兜底(主选+兜底0只): 仅 额≥1亿+开盘<9.8%+非ST+量比<20 → 量比第1, 满仓1只。
  执行: T开盘买、T+1收盘卖, 两份资金错开一天。
  终值位置 = (竞价最终价 − 竞价区间低) ÷ (竞价区间高 − 竞价区间低) × 100; 无区间(单一价)者不剔。
"""
import os, sys, time, json, urllib.request, numpy as np, pandas as pd, tushare as ts
from concurrent.futures import ThreadPoolExecutor

POOL = {
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

if not os.environ.get('TUSHARE_TOKEN'): sys.exit('缺少 TUSHARE_TOKEN')
ts.set_token(os.environ['TUSHARE_TOKEN']); pro = ts.pro_api()

def _post(url, data, headers=None):
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers or {'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print('推送失败:', e)

def notify(text):
    bt, cid = os.environ.get('TELEGRAM_BOT_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    if bt and cid:
        _post(f'https://api.telegram.org/bot{bt}/sendMessage', {'chat_id': cid, 'text': text})
    wecom = os.environ.get('WECOM_WEBHOOK')
    if wecom:
        _post(wecom, {'msgtype': 'text', 'text': {'content': text}})
    lark = os.environ.get('LARK_WEBHOOK')   # 飞书自定义机器人
    if lark:
        _post(lark, {'msg_type': 'text', 'content': {'text': text}})
    pp = os.environ.get('PUSHPLUS_TOKEN')
    if pp:
        _post('https://www.pushplus.plus/send', {'token': pp, 'title': 'AI量比信号', 'content': text})

def one(c, T):
    for a in range(3):
        try:
            d = pro.daily(ts_code=c, end_date=T)
            if d is not None: return c, d.sort_values('trade_date').tail(80).reset_index(drop=True)
        except Exception:
            time.sleep(0.6 * (a + 1))
    return c, None

def st_codes():
    try:
        b = pro.stock_basic(fields=['ts_code', 'name'])
        return set(b[b['name'].str.contains('ST', na=False)]['ts_code'])
    except Exception:
        return set()

def main(T):
    t0 = time.time()
    hist = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for c, d in ex.map(lambda c: one(c, T), list(POOL.values())):
            if d is not None and len(d): hist[c] = d
    st = st_codes()
    auc = None
    for a in range(3):
        try:
            x = pro.stk_auction_o(trade_date=T)
            if x is not None and len(x): auc = x.set_index('ts_code'); break
        except Exception: time.sleep(0.8)

    # 择时: 等权指数(T-1收盘) vs MA20
    closes = {}
    for c, d in hist.items():
        dd = d[d['trade_date'] < T]
        if len(dd) >= 21: closes[c] = dd.set_index('trade_date')['close']
    cdf = pd.DataFrame(closes); idx = (cdf / cdf.bfill().iloc[0]).mean(axis=1); ma = idx.rolling(20).mean()
    on = idx.iloc[-1] > ma.iloc[-1]
    head = f"【{T} AI量比·早盘信号】等权指数{idx.iloc[-1]:.3f}{'>' if on else '≤'}MA20{ma.iloc[-1]:.3f}→{'进攻(在场)' if on else '熄火(防守)'}"

    if not on:
        return head + "\n👉 今日防守(熄火)= 空仓(持现金, 当日策略收益0)" \
                      "\n(银行ETF 512800 / 黄金ETF 518880 仅作参考对比, 不实际持有)"
    if auc is None:
        return head + "\n👉 9:25竞价数据暂未就绪, 请9:25后重跑"

    rows = []
    for nm, c in POOL.items():
        d = hist.get(c)
        if d is None: continue
        dd = d[d['trade_date'] < T].reset_index(drop=True)
        if len(dd) < 61 or c not in auc.index: continue
        cl = dd['close'].values; hi = dd['high'].values; vo = dd['vol'].values; am = dd['amount'].values
        a = auc.loc[c]; av, aop, ahi, alo = a['vol'], a['open'], a['high'], a['low']
        v5 = vo[-5:].mean()
        if not av or v5 <= 0 or not aop: continue
        qb = (av / 100) / (v5 / 240)
        ctm1 = cl[-1]; h60 = hi[-60:].max(); ma20 = cl[-20:].mean(); ma60 = cl[-60:].mean()
        run20 = cl[-1] / cl[-21] - 1; amt5 = am[-5:].mean(); gap = aop / ctm1 - 1
        rng = ahi - alo; spos = ((aop - alo) / rng * 100) if rng > 0 else np.nan
        rows.append(dict(nm=nm, c=c, qb=qb, near=ctm1 >= 0.93 * h60, trend=(ctm1 > ma20) and (ma20 > ma60),
                         run20=run20, amt5=amt5, gap=gap, spos=spos, isST=(c in st)))
    D = pd.DataFrame(rows)

    # 候选基础筛选: 量比∈(3,20)+贴高+多头+额≥1亿+开盘<9.8%+非ST
    base = (D['qb'] > 3) & (D['qb'] < 20) & D['near'] & D['trend'] & (D['amt5'] >= 100000) & (D['gap'] < 0.098) & (~D['isST'])
    cand = D[base].sort_values('qb', ascending=False).reset_index(drop=True)

    picks, chosen = [], set()
    if len(cand):
        # 主选一: 剔20日涨幅>100%, 量比第1
        p1 = cand[(~cand['c'].isin(chosen)) & (cand['run20'] <= 1.0)]
        if len(p1):
            r = p1.iloc[0]; picks.append(('主选一', r)); chosen.add(r['c'])
        # 主选二、三: 剔20日涨幅>80% 且 终值位置>80%, 量比第1 (依次)
        for lab in ['主选二', '主选三']:
            p = cand[(~cand['c'].isin(chosen)) & (cand['run20'] <= 0.8) & ~(cand['spos'] > 80)]
            if len(p):
                r = p.iloc[0]; picks.append((lab, r)); chosen.add(r['c'])

    if picks:
        n = len(picks)
        items = [f"{r['nm']}(量比{r['qb']:.1f})" for _, r in picks]
        msg = f"👉 今日买入【主选·各1/{n}仓】: {'、'.join(items)}"
    else:
        fb = D[(D['qb'] < 20) & D['near'] & D['trend'] & (D['amt5'] >= 100000) & (D['gap'] < 0.098) & (~D['isST'])]
        if len(fb):
            r = fb.sort_values('qb', ascending=False).iloc[0]
            msg = f"👉 今日买入【兜底·满仓1只】: {r['nm']}(量比{r['qb']:.1f})"
        else:
            deep = D[(D['amt5'] >= 100000) & (D['gap'] < 0.098) & (~D['isST']) & (D['qb'] < 20)]
            if len(deep):
                r = deep.sort_values('qb', ascending=False).iloc[0]
                msg = f"👉 今日买入【深兜底·满仓1只】: {r['nm']}(量比{r['qb']:.1f})"
            else:
                msg = "👉 今日无合格标的 → 空仓"
    return head + "\n" + msg + f"\n(T开盘买/T+1收盘卖, 两份资金错开; 耗时{time.time()-t0:.1f}s)"

if __name__ == '__main__':
    T = sys.argv[1] if (len(sys.argv) > 1 and sys.argv[1][:8].isdigit()) else time.strftime('%Y%m%d')
    out = main(T)
    print(out)
    notify(out)
