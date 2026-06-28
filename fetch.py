#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 1: 拉取并缓存 60 只票的回测原始数据(2021-2026)→ rawdata.pkl。
依赖 tushare,token 从环境变量 TUSHARE_TOKEN 读取(或命令行第 1 个参数)。
   python3 fetch.py [TUSHARE_TOKEN]
"""
import sys, os, time, pickle
import tushare as ts

TOKEN = (sys.argv[1] if len(sys.argv) > 1 else '') or os.environ.get('TUSHARE_TOKEN', '')
ts.set_token(TOKEN)
PRO = ts.pro_api()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'rawdata.pkl')

POOL = {
 '风华高科':'000636.SZ','华工科技':'000988.SZ','德明利':'001309.SZ','大族激光':'002008.SZ',
 '科大讯飞':'002230.SZ','东山精密':'002384.SZ','双环传动':'002472.SZ','科士达':'002518.SZ',
 '英维克':'002837.SZ','洁美科技':'002859.SZ','深南电路':'002916.SZ','创世纪':'300083.SZ',
 '拓尔思':'300229.SZ','中际旭创':'300308.SZ','润泽科技':'300442.SZ','胜宏科技':'300476.SZ',
 '高澜股份':'300499.SZ','新易盛':'300502.SZ','昊志机电':'300503.SZ','长芯博创':'300548.SZ',
 '精测电子':'300567.SZ','太辰光':'300570.SZ','长川科技':'300604.SZ','光库科技':'300620.SZ',
 '江苏雷利':'300660.SZ','江丰电子':'300666.SZ','金力永磁':'300748.SZ','龙磁科技':'300835.SZ',
 '兆龙互连':'300913.SZ','申菱环境':'301018.SZ','铜冠铜箔':'301217.SZ','永鼎股份':'600105.SH',
 '中国巨石':'600176.SH','生益科技':'600183.SH','有研新材':'600206.SH','亨通光电':'600487.SH',
 '中天科技':'600522.SH','柏诚股份':'601133.SH','长飞光纤':'601869.SH','中科曙光':'603019.SH',
 '华正新材':'603186.SH','景旺电子':'603228.SH','宏和科技':'603256.SH','鸣志电器':'603728.SH',
 '兆易创新':'603986.SH','中微公司':'688012.SH','绿的谐波':'688017.SH','拓荆科技':'688072.SH',
 '步科股份':'688160.SH','生益电子':'688183.SH','寒武纪':'688256.SH','联瑞新材':'688300.SH',
 '汇成股份':'688403.SH','源杰科技':'688498.SH','佰维存储':'688525.SH','华丰科技':'688629.SH',
 '鼎通科技':'688668.SH','伟创电气':'688698.SH','普冉股份':'688766.SH','中控技术':'688777.SH',
}
CODE2NAME = {v: k for k, v in POOL.items()}
START = '20200901'; END = '20260626'   # 多取前置窗口以算 MA60/60日高


def safe(fn, **kw):
    for i in range(5):
        try:
            return fn(**kw)
        except Exception as e:
            print('  retry', i, str(e)[:80]); time.sleep(1.5)
    raise RuntimeError('failed ' + str(kw))


def main():
    data = {'pool': POOL, 'code2name': CODE2NAME, 'start': START, 'end': END,
            'daily': {}, 'qfq': {}, 'auction': {}, 'namechg': {}}
    codes = list(POOL.values())
    for i, code in enumerate(codes):
        print(f'[{i+1}/{len(codes)}] {code} {CODE2NAME[code]}')
        # 原始日线(vol 手, amount 千元)
        d = safe(PRO.daily, ts_code=code, start_date=START, end_date=END)
        data['daily'][code] = d.sort_values('trade_date').reset_index(drop=True)
        # 前复权 K 线(算 MA / 60日高 / 涨幅);ts.pro_bar 自带前复权
        q = safe(ts.pro_bar, ts_code=code, adj='qfq', start_date=START, end_date=END)
        data['qfq'][code] = q.sort_values('trade_date').reset_index(drop=True)
        # 开盘集合竞价(vol 股, amount 元)
        a = safe(PRO.stk_auction_o, ts_code=code, start_date=START, end_date=END)
        data['auction'][code] = a.sort_values('trade_date').reset_index(drop=True)
        # 名称变更(用于 ST 标记)
        try:
            data['namechg'][code] = PRO.namechange(ts_code=code)
        except Exception:
            data['namechg'][code] = None
        time.sleep(0.35)
    cal = safe(PRO.trade_cal, exchange='SSE', start_date=START, end_date=END, is_open='1')
    data['trade_days'] = sorted(cal['cal_date'].tolist())
    with open(OUT, 'wb') as f:
        pickle.dump(data, f)
    print('saved', OUT, 'stocks=', len(codes), 'trade_days=', len(data['trade_days']))


if __name__ == '__main__':
    main()
