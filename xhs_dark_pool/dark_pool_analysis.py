# -*- coding: utf-8 -*-
"""
暗盘资金榜 次日表现验证脚本
----------------------------------
输入: dark_pool_rank.json (小红书/财富号博主每日『暗盘资金』榜单的收集结果)
用法:
  export TUSHARE_TOKEN=xxx        # 有token: 用日线核实次日 开盘/收盘/涨跌幅/是否阳线
  python3 dark_pool_analysis.py   # 无token: 直接用JSON里搜索得到的次日涨跌幅做粗统计

统计口径:
  次日涨跌幅  = 次日收盘 / 前日收盘 - 1   (持股者视角)
  次日阳线    = 次日收盘 > 次日开盘        (次日开盘买入者视角, 即开盘买当日是否赚钱)
  开盘买收益  = 次日收盘 / 次日开盘 - 1
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_records():
    with open(os.path.join(HERE, "dark_pool_rank.json"), encoding="utf-8") as f:
        data = json.load(f)
    recs = [r for r in data["records"] if r.get("dark_inflow_yi")]
    extra = data.get("additional_samples", [])
    return recs, extra


def verify_with_tushare(recs, extra, token):
    import tushare as ts
    pro = ts.pro_api(token)
    cal = pro.trade_cal(exchange="SSE", start_date="20260601", end_date="20260901",
                        is_open="1")
    open_days = sorted(cal["cal_date"].tolist())

    def next_trade_day(d):
        for x in open_days:
            if x > d:
                return x
        return None

    out = []
    for r in recs + [dict(r, top1=r["stock"], dark_inflow_yi=None) for r in extra]:
        nd = next_trade_day(r["date"])
        if nd is None:
            continue
        df = pro.daily(ts_code=r["ts_code"], start_date=nd, end_date=nd)
        if df.empty:
            print(f"⚠ {r['top1']} {nd} 无日线数据(停牌?), 跳过")
            continue
        row = df.iloc[0]
        out.append({
            "date": r["date"], "stock": r["top1"], "dark_yi": r.get("dark_inflow_yi"),
            "next_date": nd, "next_open": row["open"], "next_close": row["close"],
            "next_pct": row["pct_chg"],
            "yang": bool(row["close"] > row["open"]),
            "open_buy_ret": row["close"] / row["open"] - 1.0,
        })
    return out


def offline_rows(recs, extra):
    # 无token: 用JSON里搜索到的次日涨跌幅, 阳线用 涨跌幅>0 近似(缺开盘价, 精度有限)
    out = []
    for r in recs:
        if r.get("next_day_pct") is None:
            continue
        out.append({"date": r["date"], "stock": r["top1"], "dark_yi": r["dark_inflow_yi"],
                    "next_pct": r["next_day_pct"], "yang": r["next_day_pct"] > 0,
                    "open_buy_ret": None, "note": r.get("next_day_note", "")})
    for r in extra:
        if r.get("next_day_pct") is None:
            continue
        out.append({"date": r["date"], "stock": r["stock"], "dark_yi": None,
                    "next_pct": r["next_day_pct"], "yang": r["next_day_pct"] > 0,
                    "open_buy_ret": None, "note": r.get("next_day_note", "")})
    return out


def summarize(rows, verified):
    n = len(rows)
    if n == 0:
        print("无可统计样本")
        return
    yang = sum(1 for r in rows if r["yang"])
    avg = sum(r["next_pct"] for r in rows) / n
    print(f"\n===== 暗盘资金榜 次日表现统计 ({'Tushare核实' if verified else '搜索数据, 未核实'}) =====")
    print(f"样本数: {n}   次日阳线: {yang}  概率 {yang / n:.0%}   次日平均涨跌幅: {avg:+.2f}%")
    if verified:
        ob = [r["open_buy_ret"] for r in rows]
        print(f"次日开盘买入平均收益: {sum(ob) / len(ob):+.2%}")

    big = [r for r in rows if (r["dark_yi"] or 0) >= 10]
    small = [r for r in rows if r["dark_yi"] is not None and r["dark_yi"] < 10]
    for name, grp in (("暗盘流入≥10亿", big), ("暗盘流入<10亿", small)):
        if grp:
            y = sum(1 for r in grp if r["yang"])
            a = sum(r["next_pct"] for r in grp) / len(grp)
            print(f"{name}: {len(grp)}例  阳线 {y}/{len(grp)}  平均 {a:+.2f}%")

    print(f"\n{'日期':<10}{'个股':<8}{'暗盘(亿)':>8}{'次日%':>8}  阳线")
    for r in sorted(rows, key=lambda x: x["date"]):
        d = f"{r['dark_yi']:.2f}" if r["dark_yi"] is not None else "  -"
        print(f"{r['date']:<10}{r['stock']:<8}{d:>8}{r['next_pct']:>8.2f}  {'阳' if r['yang'] else '阴'}")


def main():
    recs, extra = load_records()
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        rows = verify_with_tushare(recs, extra, token)
        summarize(rows, verified=True)
    else:
        print("未设置 TUSHARE_TOKEN, 使用JSON内搜索数据粗统计(阳线≈次日涨跌幅>0)")
        summarize(offline_rows(recs, extra), verified=False)


if __name__ == "__main__":
    sys.exit(main())
