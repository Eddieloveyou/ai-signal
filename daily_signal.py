#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI主池·集合竞价量比 日内策略 v2.4 — 每日早盘(9:25)信号 [并行加速 + 推送]
用法: python3 daily_signal.py [YYYYMMDD]
  token 读环境变量 TUSHARE_TOKEN。
  推送(任选其一, 配了就推): TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID / WECOM_WEBHOOK / LARK_WEBHOOK / PUSHPLUS_TOKEN。
输出: 只告诉当天买哪几只(主选一/二/三 或 兜底 / 深兜底, 或熄火日空仓), 不输出收益率。

═══ 规则 v2.4 (相对 v2.3 的两处实证修正) ═══
【数据·根除未来函数】量比与开盘价一律用 `stk_auction`(纯9:25撮合: vol股 / price撮合价),
   不用 `stk_auction_o`(它混入9:30开盘后成交=未来函数, 会把量比虚高、把次级票误抬进主选)。
   你 9:30 开盘买, 一切信息须在 9:25–9:30 可得; stk_auction 满足, auction_o 不满足。
   (stk_auction 历史不可回溯; 老日期取不到时回退 auction_o 并在输出打 ⚠ 仅供参考。)
【主选二/三·低开过滤替掉终值位置】终值位置需 9:15–9:25 完整路径, Tushare 取不到且 auction_o 是未来数据;
   实证回测改用"低开比例"过滤(纯 gap, 点位时间干净): #2/#3 若低开超过阈值则剔且不替补(留空)。
   阈值 LOW_OPEN_TOL=-1.5% 为跨 2024/2025-26 两段最稳健点(2024更优、牛市段几乎不输, 回撤最低)。

  择时: 60只AI主池等权指数 T-1收盘 > MA20 → 进攻; ≤ MA20(熄火) → 防守=空仓(持现金)。
        银行ETF(512800)/黄金ETF(518880) 仅作参考对比, 不实际持有。
  量比 = (今日9:25撮合量股/100) ÷ (过去5日日均量手/240)。
  候选基础筛选: 量比∈(3,20) + T-1收盘≥60日高×93%(贴高) + 多头(收盘>MA20>MA60)
              + 近5日均成交额≥1亿 + 开盘涨幅<9.8% + 非ST。  开盘价=撮合价。
  主选一: 候选中剔「20日涨幅>100%」后, 量比第1 —— 低开照买(#1龙头低开是优质买点)。
  主选二/三: 量比次高(剔「20日涨幅>80%」)的自然 #2/#3 两格, 各自仅当 gap≥LOW_OPEN_TOL 才保留;
            低开超阈值则该格留空、不向下替补(替补会买到低量比杂票, 回测更差)。
  → 有几只算几只(1~3只), 均分仓位。
  兜底(主选0只): 去掉量比∈(3,20)与20日涨幅限制; 留 贴高+多头+额≥1亿+开盘<9.8%+非ST → 量比第1, 满仓1只。
  深兜底(主选+兜底0只): 仅 额≥1亿+开盘<9.8%+非ST+量比<20 → 量比第1, 满仓1只。
  执行: T开盘买、T+1收盘卖, 两份资金错开一天。
"""
import os, sys, time, json, urllib.request, numpy as np, pandas as pd, tushare as ts
from concurrent.futures import ThreadPoolExecutor

LOW_OPEN_TOL = -0.015   # 主选二/三 允许的最大低开幅度(gap≥此值才保留); 跨周期最稳健

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
    if bt and cid: _post(f'https://api.telegram.org/bot{bt}/sendMessage', {'chat_id': cid, 'text': text})
    wecom = os.environ.get('WECOM_WEBHOOK')
    if wecom: _post(wecom, {'msgtype': 'text', 'text': {'content': text}})
    lark = os.environ.get('LARK_WEBHOOK')
    if lark: _post(lark, {'msg_type': 'text', 'content': {'text': text}})
    pp = os.environ.get('PUSHPLUS_TOKEN')
    if pp: _post('https://www.pushplus.plus/send', {'token': pp, 'title': 'AI量比信号', 'content': text})

def one(c, T):
    for a in range(3):
        try:
            d = pro.daily(ts_code=c, end_date=T)
            if d is not None: return c, d.sort_values('trade_date').tail(80).reset_index(drop=True)
        except Exception: time.sleep(0.6 * (a + 1))
    return c, None

def st_codes():
    try:
        b = pro.stock_basic(fields=['ts_code', 'name'])
        return set(b[b['name'].str.contains('ST', na=False)]['ts_code'])
    except Exception: return set()

def get_auction(T):
    """优先纯撮合 stk_auction(无未来函数); 取不到回退 stk_auction_o 并告警。
       返回 (df_indexed_by_ts_code, vol字段, price字段, 是否回退)。"""
    try:
        x = pro.stk_auction(trade_date=T)
        if x is not None and len(x): return x.set_index('ts_code'), 'vol', 'price', False
    except Exception: pass
    for a in range(2):
        try:
            x = pro.stk_auction_o(trade_date=T)
            if x is not None and len(x): return x.set_index('ts_code'), 'vol', 'open', True
        except Exception: time.sleep(0.6)
    return None, None, None, False

def main(T):
    t0 = time.time()
    hist = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        for c, d in ex.map(lambda c: one(c, T), list(POOL.values())):
            if d is not None and len(d): hist[c] = d
    st = st_codes()
    auc, VF, PF, fallback = get_auction(T)

    # 择时: 等权指数(T-1收盘) vs MA20
    closes = {}
    for c, d in hist.items():
        dd = d[d['trade_date'] < T]
        if len(dd) >= 21: closes[c] = dd.set_index('trade_date')['close']
    cdf = pd.DataFrame(closes); idx = (cdf / cdf.bfill().iloc[0]).mean(axis=1); ma = idx.rolling(20).mean()
    on = idx.iloc[-1] > ma.iloc[-1]
    head = f"【{T} AI量比·早盘信号 v2.4】等权指数{idx.iloc[-1]:.3f}{'>' if on else '≤'}MA20{ma.iloc[-1]:.3f}→{'进攻(在场)' if on else '熄火(防守)'}"

    if not on:
        return head + "\n👉 今日防守(熄火)= 空仓(持现金, 当日策略收益0)" \
                      "\n(银行ETF 512800 / 黄金ETF 518880 仅作参考对比, 不实际持有)"
    if auc is None:
        return head + "\n👉 9:25竞价数据暂未就绪, 请9:25后重跑"
    warn = "\n⚠ 量比口径回退 stk_auction_o(含未来函数), 仅供参考, 实盘请用 stk_auction" if fallback else ""

    rows = []
    for nm, c in POOL.items():
        d = hist.get(c)
        if d is None: continue
        dd = d[d['trade_date'] < T].reset_index(drop=True)
        if len(dd) < 61 or c not in auc.index: continue
        cl = dd['close'].values; hi = dd['high'].values; vo = dd['vol'].values; am = dd['amount'].values
        a = auc.loc[c]; av = a[VF]; px = a[PF]      # av=纯撮合量(股); px=撮合价=开盘价
        v5 = vo[-5:].mean()
        if not av or v5 <= 0 or not px: continue
        qb = (av / 100) / (v5 / 240)
        ctm1 = cl[-1]; h60 = hi[-60:].max(); ma20 = cl[-20:].mean(); ma60 = cl[-60:].mean()
        run20 = cl[-1] / cl[-21] - 1; amt5 = am[-5:].mean(); gap = px / ctm1 - 1
        rows.append(dict(nm=nm, c=c, qb=qb, near=ctm1 >= 0.93 * h60, trend=(ctm1 > ma20) and (ma20 > ma60),
                         run20=run20, amt5=amt5, gap=gap, isST=(c in st)))
    D = pd.DataFrame(rows)

    # 候选基础筛选: 量比∈(3,20)+贴高+多头+额≥1亿+开盘<9.8%+非ST
    base = (D['qb'] > 3) & (D['qb'] < 20) & D['near'] & D['trend'] & (D['amt5'] >= 100000) & (D['gap'] < 0.098) & (~D['isST'])
    cand = D[base].sort_values('qb', ascending=False).reset_index(drop=True)

    picks = []
    if len(cand):
        # 主选一: 剔20日涨幅>100%, 量比第1 (低开照买)
        p1 = cand[cand['run20'] <= 1.0]
        if len(p1):
            r1 = p1.iloc[0]; picks.append(('主选一', r1, '低开照买'))
            # 主选二/三: 量比次高(剔20涨>80)的自然两格, 各自 gap≥LOW_OPEN_TOL 才留, 否则留空不替补
            rest = cand[(cand['c'] != r1['c']) & (cand['run20'] <= 0.8)].reset_index(drop=True)
            for k in range(min(2, len(rest))):
                r = rest.iloc[k]
                if r['gap'] >= LOW_OPEN_TOL: picks.append((['主选二', '主选三'][k], r, ''))

    if picks:
        n = len(picks)
        items = [f"{r['nm']}(量比{r['qb']:.1f},开盘{r['gap']*100:+.1f}%)" for _, r, _ in picks]
        msg = f"👉 今日买入【主选·各1/{n}仓】: {'、'.join(items)}"
        dropped = []
        if len(cand):
            rest = cand[(cand['run20'] <= 0.8)].reset_index(drop=True)
            chosen_c = {r['c'] for _, r, _ in picks}
            for k in range(min(3, len(rest))):
                r = rest.iloc[k]
                if r['c'] not in chosen_c and r['gap'] < LOW_OPEN_TOL:
                    dropped.append(f"{r['nm']}(低开{r['gap']*100:.1f}%)")
        if dropped: msg += f"\n  (剔低开>{abs(LOW_OPEN_TOL)*100:.1f}%的次级: {'、'.join(dropped)} → 该格留空不替补)"
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
    return head + warn + "\n" + msg + f"\n(T开盘买/T+1收盘卖, 两份资金错开; 耗时{time.time()-t0:.1f}s)"

if __name__ == '__main__':
    T = sys.argv[1] if (len(sys.argv) > 1 and sys.argv[1][:8].isdigit()) else time.strftime('%Y%m%d')
    out = main(T)
    print(out)
    notify(out)
