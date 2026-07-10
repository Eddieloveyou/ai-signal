#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
泰格医药(300347.SZ)历史「单日涨约 9% 后, 第二天涨跌幅」统计。

口径:
  - 涨幅 = Tushare `pro.daily` 的 pct_chg(真实日涨跌幅, 前复权无关, 未来函数无涉)。
  - 命中日: 当日 pct_chg >= THR(默认 9.0%)。
  - 次日: 下一个交易日的 pct_chg。
  - 输出: 样本数 / 次日均值 / 中位数 / 上涨占比 / 极值 / 明细。

注意:
  - 创业板涨停幅度 2020-08-24 起由 10% 提到 20%。此前 +9% 已近涨停,
    此后 +9% 只是强势但未封板 —— 两段样本性质不同, 报告里按时间分段。

用法:
  export TUSHARE_TOKEN=你的token
  python3 tiger_after_9pct.py            # 默认阈值 9.0%
  python3 tiger_after_9pct.py 9.5        # 自定义阈值
"""
import os, sys
import tushare as ts

CODE = '300347.SZ'
THR = float(sys.argv[1]) if len(sys.argv) > 1 else 9.0
SPLIT = '20200824'  # 创业板涨跌幅由 10%->20% 的分界日

if not os.environ.get('TUSHARE_TOKEN'):
    sys.exit('缺少 TUSHARE_TOKEN')
ts.set_token(os.environ['TUSHARE_TOKEN'])
pro = ts.pro_api()

# 拉全历史日线(pro.daily 单次上限约 6000 行, 300347 自 2012 上市足够一次取完)
df = pro.daily(ts_code=CODE, start_date='20120101', end_date='20260710')
df = df.sort_values('trade_date').reset_index(drop=True)
print(f'{CODE}  日线 {len(df)} 根  {df.trade_date.iloc[0]} → {df.trade_date.iloc[-1]}')

hits = []
for i in range(len(df) - 1):
    if df.pct_chg.iloc[i] >= THR:
        hits.append((df.trade_date.iloc[i], df.pct_chg.iloc[i],
                     df.trade_date.iloc[i + 1], df.pct_chg.iloc[i + 1]))

def report(rows, title):
    if not rows:
        print(f'\n[{title}] 无样本')
        return
    nxt = [r[3] for r in rows]
    up = sum(1 for x in nxt if x > 0)
    n = len(nxt)
    print(f'\n[{title}]  样本 {n}')
    print(f'  次日均值 {sum(nxt)/n:+.2f}%   中位数 {sorted(nxt)[n//2]:+.2f}%')
    print(f'  次日上涨 {up}/{n} = {up/n*100:.0f}%   最好 {max(nxt):+.2f}%   最差 {min(nxt):+.2f}%')

print(f'\n=== 单日涨幅 >= {THR}% 后, 次日涨跌幅 ===')
report(hits, f'全样本 (>= {THR}%)')
report([r for r in hits if r[0] < SPLIT], f'2020-08-24 前(涨停10%制)')
report([r for r in hits if r[0] >= SPLIT], f'2020-08-24 后(涨停20%制)')

print('\n明细 (命中日 +涨幅  ->  次日 涨跌幅):')
for d, pc, nd, npc in hits:
    print(f'  {d}  {pc:+6.2f}%   ->  {nd}  {npc:+7.2f}%')
