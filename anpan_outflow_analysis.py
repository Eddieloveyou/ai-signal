#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暗盘资金流出 × 次日阳线 概率分析
用法: python3 anpan_outflow_analysis.py [YYYYMMDD] [--days 22] [--top 10] [--push]
  token 读环境变量 TUSHARE_TOKEN; 默认统计截至最近已完结交易日的前 22 个交易日(约1个月)。

═══ 口径说明 ═══
小红书博主每天发的"暗盘资金流出榜"来自行情软件的私有指标(号称识别主力把大单拆成小单的
隐蔽出货), 其拆单识别算法不公开、无法用公开数据精确复现。公开数据里最接近的代理口径是
【主力净流出 = (大单+超大单)卖出额 − (大单+超大单)买入额】, 即 Tushare `moneyflow` 接口
(同花顺/东财App"主力净流出"同源口径)。本脚本用它作为"暗盘流出"的代理。

═══ 做什么 ═══
1. 最近 N 个交易日, 每天取全市场主力净流出最大的前 K 只(默认10只) → 当日流出排名榜。
2. 对每只上榜股票匹配【次日】开盘/收盘 → 次日涨跌幅、次日是否阳线(收盘>开盘)。
3. 统计: 总体阳线率; 按流出排名(第1名~第K名)、按流出金额分档、按流出强度(流出/成交额)
   分档、按当日涨跌方向 分组的阳线率与平均次日涨跌幅; 并给出流出规模与次日表现的
   Spearman 相关, 自动总结"哪一组买到阳线概率最大"。
输出: 控制台摘要 + reports/anpan_YYYYMMDD.md 完整报告(含每天Top K明细表)。
"""
import os, sys, time, json, argparse, urllib.request
import numpy as np, pandas as pd

WAN = 1e4          # moneyflow 金额单位: 万元
QIAN = 1e3         # daily.amount 单位: 千元


# ──────────────────────────── 数据获取 ────────────────────────────
def fetch_all(fn, limit=6000, **kw):
    """带 offset 翻页, 防止单次行数截断。"""
    out, offset = [], 0
    while True:
        for a in range(3):
            try:
                d = fn(limit=limit, offset=offset, **kw)
                break
            except Exception:
                time.sleep(0.8 * (a + 1)); d = None
        if d is None or len(d) == 0:
            break
        out.append(d)
        if len(d) < limit:
            break
        offset += limit
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def trade_days(pro, end_date, need):
    cal = pro.trade_cal(end_date=end_date, is_open='1',
                        start_date=str(int(end_date[:4]) - 1) + end_date[4:])
    days = sorted(cal['cal_date'].tolist())
    return days[-need:]


def build_dataset(pro, end_date, n_days=22, top_k=10):
    """返回 (明细DataFrame, 使用的排名日列表)。
    明细每行 = 某个排名日 T 的流出榜第 rank 名股票 + 其 T+1 表现。"""
    # 需要 n_days 个排名日 + 每个排名日的次日 → 共 n_days+1 个交易日
    days = trade_days(pro, end_date, n_days + 1)
    if len(days) < 2:
        sys.exit('交易日历不足')
    rank_days, next_of = days[:-1], {days[i]: days[i + 1] for i in range(len(days) - 1)}

    try:
        basic = pro.stock_basic(fields=['ts_code', 'name'])
        names = dict(zip(basic['ts_code'], basic['name']))
    except Exception:
        names = {}

    daily = {}          # trade_date -> 全市场 daily (索引 ts_code)
    for d in days:
        dd = fetch_all(pro.daily, trade_date=d)
        if len(dd) == 0:
            sys.exit(f'{d} 无日线数据(是否为未完结交易日?)')
        daily[d] = dd.set_index('ts_code')

    rows = []
    for T in rank_days:
        mf = fetch_all(pro.moneyflow, trade_date=T)
        if len(mf) == 0:
            print(f'⚠ {T} 无 moneyflow 数据, 跳过'); continue
        # 主力净流出(万元) = (大单+超大单)卖出 − 买入; 正数=净流出
        mf['main_out'] = (mf['sell_lg_amount'] + mf['sell_elg_amount']
                          - mf['buy_lg_amount'] - mf['buy_elg_amount'])
        top = mf.sort_values('main_out', ascending=False).head(top_k).reset_index(drop=True)
        d0, d1 = daily[T], daily[next_of[T]]
        for i, r in top.iterrows():
            c = r['ts_code']
            nm = names.get(c, c)
            row = dict(date=T, rank=i + 1, ts_code=c, name=nm,
                       out_yi=r['main_out'] / WAN,                    # 亿元
                       net_mf_yi=-r['net_mf_amount'] / WAN if 'net_mf_amount' in r else np.nan)
            if c in d0.index:
                a0 = d0.loc[c]
                row['day0_pct'] = a0['pct_chg']
                amt = a0['amount'] * QIAN                              # 元
                row['intensity'] = (r['main_out'] * WAN) / amt if amt > 0 else np.nan
            else:
                row['day0_pct'] = np.nan; row['intensity'] = np.nan
            if c in d1.index:
                a1 = d1.loc[c]
                row['next_open_gap'] = (a1['open'] / a1['pre_close'] - 1) * 100
                row['next_pct'] = a1['pct_chg']
                row['next_yang'] = bool(a1['close'] > a1['open'])
                row['next_up'] = bool(a1['pct_chg'] > 0)
            else:
                row['next_open_gap'] = np.nan; row['next_pct'] = np.nan
                row['next_yang'] = None; row['next_up'] = None       # 次日停牌等
            rows.append(row)
        time.sleep(0.15)                                               # 限速保护
    return pd.DataFrame(rows), rank_days


# ──────────────────────────── 统计 ────────────────────────────
def _grp_stats(df, key):
    g = df.groupby(key, observed=True)
    s = pd.DataFrame({
        'n': g.size(),
        '阳线率%': g['next_yang'].mean() * 100,
        '收涨率%': g['next_up'].mean() * 100,
        '次日均涨跌%': g['next_pct'].mean(),
        '次日中位%': g['next_pct'].median(),
    })
    return s.round(2)


def analyze(df):
    """df: build_dataset 明细。返回 (结果dict, 有效样本df)。"""
    v = df.dropna(subset=['next_pct']).copy()
    v['next_yang'] = v['next_yang'].astype(bool)
    v['next_up'] = v['next_up'].astype(bool)
    res = {'n_total': len(df), 'n_valid': len(v), 'n_suspend': len(df) - len(v)}
    if len(v) == 0:
        return res, v

    res['overall'] = dict(yang=v['next_yang'].mean() * 100, up=v['next_up'].mean() * 100,
                          mean=v['next_pct'].mean(), med=v['next_pct'].median())
    res['by_rank'] = _grp_stats(v, 'rank')

    v['金额档'] = pd.qcut(v['out_yi'], min(4, v['out_yi'].nunique()), duplicates='drop', precision=2)
    res['by_amount'] = _grp_stats(v, '金额档')

    vi = v.dropna(subset=['intensity']).copy()
    if len(vi) >= 8:
        vi['强度档'] = pd.qcut(vi['intensity'], min(4, vi['intensity'].nunique()), duplicates='drop', precision=3)
        res['by_intensity'] = _grp_stats(vi, '强度档')

    vd = v.dropna(subset=['day0_pct']).copy()
    if len(vd):
        vd['当日方向'] = np.where(vd['day0_pct'] > 3, '当日大涨>3%',
                        np.where(vd['day0_pct'] > 0, '当日小涨0~3%',
                        np.where(vd['day0_pct'] > -3, '当日小跌0~-3%', '当日大跌<-3%')))
        res['by_day0'] = _grp_stats(vd, '当日方向')

    # Spearman: 流出越大 → 次日表现? (手工实现, 免 scipy 依赖)
    def spearman(a, b):
        ra, rb = pd.Series(a).rank(), pd.Series(b).rank()
        return float(np.corrcoef(ra, rb)[0, 1])
    res['rho_out_next'] = spearman(v['out_yi'], v['next_pct'])
    res['rho_out_yang'] = spearman(v['out_yi'], v['next_yang'].astype(int))

    # 自动结论: 各分组里样本≥15 的最高阳线率
    cands = []
    for key, label in [('by_rank', '流出排名'), ('by_amount', '流出金额'),
                       ('by_intensity', '流出强度'), ('by_day0', '当日涨跌')]:
        if key in res:
            t = res[key][res[key]['n'] >= 15]
            for idx, r in t.iterrows():
                cands.append((f'{label}={idx}', r['阳线率%'], int(r['n']), r['次日均涨跌%']))
    if cands:
        res['best'] = max(cands, key=lambda x: x[1])
        res['worst'] = min(cands, key=lambda x: x[1])
    return res, v


# ──────────────────────────── 报告 ────────────────────────────
def md_table(df, index_name=None):
    """极简 markdown 表格(免 tabulate 依赖)。index_name 非空时把索引作为首列。"""
    d = df.reset_index() if index_name is not None else df.copy()
    if index_name is not None:
        d = d.rename(columns={d.columns[0]: index_name})
    d = d.astype(str)
    head = '| ' + ' | '.join(d.columns) + ' |'
    sep = '|' + '|'.join(['---'] * len(d.columns)) + '|'
    body = ['| ' + ' | '.join(r) + ' |' for r in d.values]
    return '\n'.join([head, sep] + body)


def make_report(df, res, rank_days, top_k):
    L = [f'# 暗盘(主力)资金流出榜 × 次日表现 — {rank_days[0]}~{rank_days[-1]} '
         f'({len(rank_days)}个交易日, 每日Top{top_k})', '',
         '> 口径: 主力净流出 = (大单+超大单)卖出额 − 买入额, Tushare `moneyflow`。',
         '> 小红书"暗盘资金"为软件私有拆单指标, 无公开数据, 此为最接近的代理口径。',
         '> 阳线 = 次日收盘 > 次日开盘; 收涨 = 次日涨跌幅 > 0。', '']
    if 'overall' in res:
        o = res['overall']
        L += [f"## 总体 (有效样本 {res['n_valid']}, 次日停牌剔除 {res['n_suspend']})",
              f"- 次日**阳线率 {o['yang']:.1f}%**, 收涨率 {o['up']:.1f}%, "
              f"次日平均涨跌 {o['mean']:+.2f}%, 中位 {o['med']:+.2f}%",
              f"- Spearman(流出金额, 次日涨跌幅) = {res['rho_out_next']:+.3f}; "
              f"(流出金额, 次日阳线) = {res['rho_out_yang']:+.3f} "
              f"(|ρ|<0.1 基本无单调关系)", '']
    for key, title, idx in [('by_rank', '按流出排名(第几名)', '排名'),
                            ('by_amount', '按流出金额(亿元)分档', '金额档'),
                            ('by_intensity', '按流出强度(流出/当日成交额)分档', '强度档'),
                            ('by_day0', '按当日涨跌方向', '当日方向')]:
        if key in res:
            L += [f'## {title}', md_table(res[key], idx), '']
    if 'best' in res:
        b, w = res['best'], res['worst']
        L += ['## 自动结论',
              f"- **阳线概率最大**的组: {b[0]} → 阳线率 {b[1]:.1f}% (n={b[2]}, 次日均涨跌 {b[3]:+.2f}%)",
              f"- 阳线概率最小的组: {w[0]} → 阳线率 {w[1]:.1f}% (n={w[2]}, 次日均涨跌 {w[3]:+.2f}%)", '']
    L += ['## 每日流出榜明细 (含次日表现)', '']
    show = df.copy()
    show['next_yang'] = show['next_yang'].apply(
        lambda x: '阳' if x is True else ('阴' if x is False else '停牌'))
    cols = dict(date='日期', rank='名次', name='股票', out_yi='主力净流出(亿)',
                day0_pct='当日%', next_open_gap='次日开盘%', next_pct='次日涨跌%', next_yang='次日K线')
    show = show[list(cols)].rename(columns=cols)
    for c in ['主力净流出(亿)', '当日%', '次日开盘%', '次日涨跌%']:
        show[c] = show[c].astype(float).round(2)
    L.append(md_table(show))
    return '\n'.join(L)


def notify(text):
    def _post(url, data):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                         headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=15).read()
        except Exception as e:
            print('推送失败:', e)
    bt, cid = os.environ.get('TELEGRAM_BOT_TOKEN'), os.environ.get('TELEGRAM_CHAT_ID')
    if bt and cid: _post(f'https://api.telegram.org/bot{bt}/sendMessage', {'chat_id': cid, 'text': text})
    if os.environ.get('WECOM_WEBHOOK'): _post(os.environ['WECOM_WEBHOOK'], {'msgtype': 'text', 'text': {'content': text}})
    if os.environ.get('LARK_WEBHOOK'): _post(os.environ['LARK_WEBHOOK'], {'msg_type': 'text', 'content': {'text': text}})
    if os.environ.get('PUSHPLUS_TOKEN'): _post('https://www.pushplus.plus/send',
        {'token': os.environ['PUSHPLUS_TOKEN'], 'title': '暗盘流出×次日阳线', 'content': text})


def summary_text(res, rank_days, top_k):
    if 'overall' not in res:
        return '无有效样本'
    o = res['overall']
    s = [f"【暗盘(主力)流出榜×次日 {rank_days[0]}~{rank_days[-1]} 每日Top{top_k}】",
         f"次日阳线率 {o['yang']:.1f}% / 收涨率 {o['up']:.1f}% / 均值 {o['mean']:+.2f}%",
         f"流出规模与次日涨跌 Spearman {res['rho_out_next']:+.3f}"]
    if 'best' in res:
        b = res['best']
        s.append(f"阳线概率最大组: {b[0]} → {b[1]:.1f}% (n={b[2]})")
    return '\n'.join(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('end_date', nargs='?', default=time.strftime('%Y%m%d'))
    ap.add_argument('--days', type=int, default=22, help='统计的排名日数量(交易日), 默认22≈1个月')
    ap.add_argument('--top', type=int, default=10, help='每日取流出最大的前几名')
    ap.add_argument('--push', action='store_true', help='推送摘要(飞书/企微/TG/PushPlus)')
    a = ap.parse_args()

    if not os.environ.get('TUSHARE_TOKEN'):
        sys.exit('缺少 TUSHARE_TOKEN')
    import tushare as ts
    ts.set_token(os.environ['TUSHARE_TOKEN'])
    pro = ts.pro_api()

    df, rank_days = build_dataset(pro, a.end_date, a.days, a.top)
    if len(df) == 0:
        sys.exit('未取到流出榜数据(检查 moneyflow 权限: 需2000积分)')
    res, _ = analyze(df)
    rpt = make_report(df, res, rank_days, a.top)
    os.makedirs('reports', exist_ok=True)
    path = f'reports/anpan_{rank_days[-1]}.md'
    with open(path, 'w') as f:
        f.write(rpt)
    txt = summary_text(res, rank_days, a.top)
    print(txt)
    print(f'\n完整报告: {path}')
    if a.push:
        notify(txt)


if __name__ == '__main__':
    main()
