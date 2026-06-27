# AI双引擎·量比策略 — 每日信号脚本

云端 routine 克隆本仓库后运行,输出当日选股。

## 用法
```bash
export TUSHARE_TOKEN=你的token
python3 daily_signal.py open    # 9:25 集合竞价后, 出进攻排序
python3 daily_signal.py close   # 14:55 尾盘, 出防守反弹
```
- `open`:判断AI主池(60只)等权指数 vs MA20。在场→量比前3名(+兜底/深兜底);熄火→提示走防守。
- `close`:AI熄火日 + 中证1000开关(站上MA20或收阳)→ 超跌反弹Top1(收阳+白名单板块);否则停泊512800。

规则详见 strategy_spec.txt。固定60只池含幸存者偏差,绝对收益预期请打折。
