#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创业板指(399006.SZ) 形态统计: 连跌数日后 收绿+长下影线 → 次日走势
用法: python3 chinext_shadow_stats.py [YYYYMMDD]   (默认今天; 统计截止日往前推两年)
数据: 优先 Tushare index_daily(需 TUSHARE_TOKEN); 无 token 回退新浪免费接口(无需注册)。

形态定义(可在下方 PARAMS 调整):
  收绿      : 当日收盘 < 昨收 (下跌)
  长下影线  : 下影线 = min(开,收) - 低;
              需同时满足 下影线 ≥ SHADOW_BODY_X × 实体 且 下影线/昨收 ≥ SHADOW_PCT_MIN
  连跌 N 天 : 信号日之前已有 ≥ PRIOR_DOWN_DAYS 个连续下跌日(不含信号日本身)
统计输出: 样本明细 + 次日高开概率/平均高开、次日收涨概率、次日平均/中位涨跌、
          次日盘中最大冲高/最大回撤、T+3/T+5 累计, 以及参数敏感性对照。
"""
import os, sys, json, time, urllib.request
import numpy as np, pandas as pd

PARAMS = dict(
    SHADOW_BODY_X=1.5,     # 下影线至少是实体的多少倍
    SHADOW_PCT_MIN=0.008,  # 下影线相对昨收的最小幅度(0.8%)
    PRIOR_DOWN_DAYS=2,     # 信号日前至少连跌几天
)
YEARS = 2

def fetch_tushare(end):
    token = os.environ.get('TUSHARE_TOKEN')
    if not token: return None
    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
        start = (pd.Timestamp(end) - pd.DateOffset(years=YEARS, days=40)).strftime('%Y%m%d')
        d = pro.index_daily(ts_code='399006.SZ', start_date=start, end_date=end)
        if d is None or not len(d): return None
        d = d.sort_values('trade_date').reset_index(drop=True)
        return pd.DataFrame(dict(date=pd.to_datetime(d['trade_date']),
                                 open=d['open'], high=d['high'], low=d['low'], close=d['close']))
    except Exception as e:
        print('Tushare 获取失败, 回退新浪:', e)
        return None

def fetch_sina(end):
    n = int(YEARS * 250 + 40)
    url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'CN_MarketData.getKLineData?symbol=sz399006&scale=240&ma=no&datalen={n}')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0',
                                               'Referer': 'https://finance.sina.com.cn'})
    raw = urllib.request.urlopen(req, timeout=20).read().decode('utf-8')
    arr = json.loads(raw)
    d = pd.DataFrame(arr)
    d['date'] = pd.to_datetime(d['day'])
    for c in ('open', 'high', 'low', 'close'): d[c] = d[c].astype(float)
    d = d[d['date'] <= pd.Timestamp(end)].sort_values('date').reset_index(drop=True)
    return d[['date', 'open', 'high', 'low', 'close']]

def find_signals(df, SHADOW_BODY_X, SHADOW_PCT_MIN, PRIOR_DOWN_DAYS):
    df = df.copy()
    df['pre_close'] = df['close'].shift(1)
    df['down'] = df['close'] < df['pre_close']
    df['body'] = (df['close'] - df['open']).abs()
    df['lower_shadow'] = df[['open', 'close']].min(axis=1) - df['low']
    df['shadow_pct'] = df['lower_shadow'] / df['pre_close']
    # 之前连续下跌天数(不含当日)
    run = 0; runs = []
    for dn in df['down'].fillna(False):
        runs.append(run)
        run = run + 1 if dn else 0
    df['prior_down'] = runs
    sig = (df['down']
           & (df['lower_shadow'] >= SHADOW_BODY_X * df['body'])
           & (df['shadow_pct'] >= SHADOW_PCT_MIN)
           & (df['prior_down'] >= PRIOR_DOWN_DAYS))
    return df, df.index[sig.fillna(False)]

def report(df, idx, label):
    rows = []
    for i in idx:
        if i + 1 >= len(df): continue  # 信号日就是最后一天(即今天) → 次日未知
        t, n = df.loc[i], df.loc[i + 1]
        rows.append(dict(
            信号日=t['date'].strftime('%Y-%m-%d'),
            当日=round((t['close'] / t['pre_close'] - 1) * 100, 2),
            下影=round(t['shadow_pct'] * 100, 2),
            连跌=int(t['prior_down']),
            次日高开=round((n['open'] / t['close'] - 1) * 100, 2),
            次日涨跌=round((n['close'] / t['close'] - 1) * 100, 2),
            次日最高=round((n['high'] / t['close'] - 1) * 100, 2),
            次日最低=round((n['low'] / t['close'] - 1) * 100, 2),
            T3=round((df.loc[min(i + 3, len(df) - 1), 'close'] / t['close'] - 1) * 100, 2),
            T5=round((df.loc[min(i + 5, len(df) - 1), 'close'] / t['close'] - 1) * 100, 2),
        ))
    print(f"\n═══ {label} ═══")
    if not rows:
        print('  近两年无符合样本'); return
    r = pd.DataFrame(rows)
    with pd.option_context('display.width', 200):
        print(r.to_string(index=False))
    nd = r['次日涨跌']
    print(f"  样本 {len(r)} 个 | 次日收涨 {int((nd > 0).sum())}/{len(r)} = {(nd > 0).mean() * 100:.0f}%"
          f" | 次日均值 {nd.mean():+.2f}% 中位 {nd.median():+.2f}%"
          f" | 高开概率 {(r['次日高开'] > 0).mean() * 100:.0f}% 平均开盘 {r['次日高开'].mean():+.2f}%")
    print(f"  次日盘中: 平均冲高 {r['次日最高'].mean():+.2f}% / 平均杀跌 {r['次日最低'].mean():+.2f}%"
          f" | T+3 均值 {r['T3'].mean():+.2f}% 胜率 {(r['T3'] > 0).mean() * 100:.0f}%"
          f" | T+5 均值 {r['T5'].mean():+.2f}% 胜率 {(r['T5'] > 0).mean() * 100:.0f}%")

def main():
    end = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1][:8].isdigit() else time.strftime('%Y%m%d')
    df = fetch_tushare(end)
    if df is None: df = fetch_sina(end)
    df = df[df['date'] >= pd.Timestamp(end) - pd.DateOffset(years=YEARS)].reset_index(drop=True)
    print(f"数据: 创业板指 {df['date'].iloc[0]:%Y-%m-%d} ~ {df['date'].iloc[-1]:%Y-%m-%d} 共{len(df)}个交易日")

    df2, idx = find_signals(df, **PARAMS)
    report(df2, idx, f"基准: 收绿+下影≥{PARAMS['SHADOW_BODY_X']}×实体且≥{PARAMS['SHADOW_PCT_MIN']*100:.1f}%+此前连跌≥{PARAMS['PRIOR_DOWN_DAYS']}天")

    # 敏感性对照
    for pd_days in (1, 3):
        p = dict(PARAMS, PRIOR_DOWN_DAYS=pd_days)
        d2, ix = find_signals(df, **p)
        report(d2, ix, f"对照: 连跌≥{pd_days}天(其余同基准)")
    p = dict(PARAMS, SHADOW_PCT_MIN=0.015)
    d2, ix = find_signals(df, **p)
    report(d2, ix, "对照: 下影线≥1.5%(极端恐慌后的深V)")

    # 若最后一个交易日本身就是信号日, 单独提示
    if len(idx) and idx[-1] == len(df2) - 1:
        t = df2.iloc[-1]
        print(f"\n★ 最新交易日 {t['date']:%Y-%m-%d} 本身即符合形态"
              f"(当日{(t['close']/t['pre_close']-1)*100:+.2f}%, 下影{t['shadow_pct']*100:.2f}%, 此前连跌{int(t['prior_down'])}天)"
              " → 上表统计即是对『明天』的历史参照。")

if __name__ == '__main__':
    main()
