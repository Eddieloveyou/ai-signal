#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两融持仓·趋势体检 — 对持仓逐只做趋势/贴高/量能检查 (不预测明日涨跌)
用法: TUSHARE_TOKEN=xxx python3 holdings_check.py [YYYYMMDD]
  按 daily_signal.py v2.4 同款口径逐只计算:
    多头 = 收盘>MA20>MA60;  贴高 = 收盘≥60日高×93%;  20日涨幅;  近5日均成交额
  并分档: 多头·贴高 > 多头 > 修复中(收盘>MA20但未多头) > 破20线(仅>MA60) > 破位(≤MA60)
  ⚠ 这只是趋势状态快照, 用于持有/减仓参考, 不是对明天涨跌的预测——次日个股涨跌无法预测。
  持仓快照录自 2026-08-11 同花顺截图(股数/成本/当时现价); px 仅用于核对代码映射是否正确。
"""
import os, sys, time
import pandas as pd

# (显示名, 股数, 成本, 截图现价)  显示名与交易所简称不一致的在 ALIAS 里换算
HOLDINGS = [
 ('飞科电器', 900, 31.015, 30.810), ('中科曙光', 700, 85.364, 86.350), ('道恩股份', 600, 26.008, 25.880),
 ('润泽科技', 400, 65.912, 67.850), ('大族激光', 300, 94.287, 95.380), ('联瑞新材', 286, 145.632, 143.460),
 ('四川华丰科技', 260, 148.121, 147.780), ('芯原微电子', 234, 208.932, 211.510),
 ('中微半导体设备', 200, 377.579, 363.100), ('长飞光纤', 200, 332.433, 335.920), ('北方华创', 100, 749.090, 746.100),
 ('汇成股份', 2493, 23.487, 24.290), ('苏泊尔', 2100, 41.367, 41.420), ('天和磁材科技', 2000, 32.704, 32.520),
 ('福瑞医科', 1600, 42.205, 44.880), ('北方稀土', 1400, 42.546, 41.850), ('立讯精密', 1400, 54.905, 55.630),
 ('国机精工', 1400, 46.374, 46.450), ('神马电力', 1200, 45.166, 47.380), ('侨源股份', 1200, 40.787, 41.010),
 ('航发动力', 1100, 35.975, 36.200), ('浪潮信息', 1000, 75.619, 75.110),
 ('金隅冀东', 17000, 3.610, 3.600), ('徐工机械', 16000, 8.262, 8.130), ('安道麦A', 11900, 5.431, 5.410),
 ('南钢股份', 9800, 4.711, 4.680), ('长虹美菱', 9100, 4.971, 4.930), ('东来涂料技术股份', 8921, 21.275, 21.400),
 ('安通控股', 8600, 4.241, 4.250), ('深高速', 7100, 8.321, 8.280), ('上海电气', 6400, 6.811, 6.800),
 ('七一二', 4900, 12.142, 12.080), ('正海磁材', 4800, 11.541, 11.480),
 ('中信海直', 4500, 14.282, 14.240), ('大全能源', 4176, 18.557, 18.760), ('华峰铝业', 4000, 15.602, 15.400),
 ('科达制造', 4000, 14.142, 14.730), ('通威股份', 3900, 12.559, 12.840), ('中国国航', 3600, 5.991, 5.950),
 ('梅花生物', 3600, 7.981, 7.960), ('万凯新材', 3400, 16.962, 16.690), ('杭氧股份', 3100, 23.743, 23.760),
 ('莱尔科技', 2676, 31.132, 30.590), ('神州数码', 2600, 23.880, 24.350)]
# 截图中另有1行被裁掉未收录(位于中信海直上方, 现价约11.4x)

ALIAS = {'中微半导体设备': '中微公司', '芯原微电子': '芯原股份', '四川华丰科技': '华丰科技',
         '天和磁材科技': '天和磁材', '东来涂料技术股份': '东来技术'}

if not os.environ.get('TUSHARE_TOKEN'): sys.exit('缺少 TUSHARE_TOKEN')
import tushare as ts
ts.set_token(os.environ['TUSHARE_TOKEN']); pro = ts.pro_api()

def resolve(basic):
    """显示名→ts_code: 先精确简称, 再 ALIAS, 再前缀模糊(唯一命中才用)。"""
    by_name = {n.replace(' ', ''): (c, ind) for c, n, ind in
               basic[['ts_code', 'name', 'industry']].itertuples(index=False)}
    out, miss = {}, []
    for nm, *_ in HOLDINGS:
        key = ALIAS.get(nm, nm).replace(' ', '')
        if key in by_name: out[nm] = by_name[key]; continue
        cand = [(n, v) for n, v in by_name.items() if n.startswith(key[:3]) or key.startswith(n[:3])]
        if len(cand) == 1:
            out[nm] = cand[0][1]; print(f'⚠ {nm} 模糊匹配为 {cand[0][0]}({cand[0][1][0]}), 请核对')
        else:
            miss.append(nm)
    for nm in miss: print(f'✗ {nm} 无法映射到代码, 已跳过(候选{len([1 for n in by_name if nm[:2] in n])}个)')
    return out

def bars(c, T):
    for a in range(3):
        try:
            d = pro.daily(ts_code=c, end_date=T)
            if d is not None and len(d): return d.sort_values('trade_date').tail(80).reset_index(drop=True)
        except Exception: time.sleep(0.6 * (a + 1))
    return None

def main(T):
    basic = pro.stock_basic(fields=['ts_code', 'name', 'industry'])
    code_of = resolve(basic)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=12) as ex:
        hist = dict(zip(code_of, ex.map(lambda nm: bars(code_of[nm][0], T), code_of)))

    rows = []
    for nm, sh, cost, px in HOLDINGS:
        if nm not in code_of: continue
        c, ind = code_of[nm]; d = hist.get(nm)
        if d is None or len(d) < 61:
            print(f'✗ {nm}({c}) 行情不足61根, 跳过'); continue
        cl = d['close'].values; hi = d['high'].values; am = d['amount'].values
        last = d.iloc[-1]
        if last['trade_date'] == T and abs(last['close'] / px - 1) > 0.03:
            print(f'⚠ {nm}({c}) {T}收盘{last["close"]:.2f} 与截图现价{px}差>3%, 代码映射可能有误')
        close = cl[-1]; ma20 = cl[-20:].mean(); ma60 = cl[-60:].mean(); h60 = hi[-60:].max()
        near = close >= 0.93 * h60
        if close > ma20 and ma20 > ma60: tier = '①多头·贴高' if near else '②多头'
        elif close > ma20:               tier = '③修复中'
        elif close > ma60:               tier = '④破20线'
        else:                            tier = '⑤破位'
        rows.append(dict(档=tier, 名称=nm, 代码=c, 行业=ind, 收盘=close,
                         距MA20=close / ma20 - 1, 距60日高=close / h60 - 1,
                         涨幅20日=cl[-1] / cl[-21] - 1, 日均额亿=am[-5:].mean() / 1e5,
                         市值=sh * close, 持仓盈亏=(close - cost) / cost))
    D = pd.DataFrame(rows).sort_values(['档', '距MA20'], ascending=[True, False]).reset_index(drop=True)

    print(f'\n【{T} 两融持仓·趋势体检】共{len(D)}只, 市值合计{D["市值"].sum()/1e4:.1f}万')
    for tier, g in D.groupby('档', sort=True):
        print(f'\n{tier}  {len(g)}只 / 市值{g["市值"].sum()/1e4:.1f}万')
        for _, r in g.iterrows():
            print(f"  {r['名称']:　<8}{r['代码']} [{r['行业']}] 收盘{r['收盘']:.2f} "
                  f"距MA20 {r['距MA20']*100:+.1f}% 距60日高 {r['距60日高']*100:+.1f}% "
                  f"20日{r['涨幅20日']*100:+.1f}% 日均额{r['日均额亿']:.1f}亿 盈亏{r['持仓盈亏']*100:+.1f}%")
    print('\n⚠ 以上是趋势状态, 不是明日涨跌预测; 次日个股涨跌无法预测, 请勿把任何档位当作买卖指令。')

if __name__ == '__main__':
    T = sys.argv[1] if (len(sys.argv) > 1 and sys.argv[1][:8].isdigit()) else time.strftime('%Y%m%d')
    main(T)
