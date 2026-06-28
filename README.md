# AI双引擎·量比策略 v2.1 — 每日早盘信号

云端 routine 每交易日 9:25 克隆本仓库并运行 `daily_signal.py`，输出**当天买哪几只**并推送到你的飞书/企业微信/Telegram。

## 规则 v2.1
- 全池(60只AI主池)等权指数 T-1收盘 > MA20 → **进攻**；≤ MA20 → **今日空仓**(不做防守、不买任何ETF)。
- 进攻量比 = (今日9:25集合竞价量/100) ÷ (过去5日日均量/240)。
- **主选**：量比∈(3,20) + T-1收盘≥60日高×93% + 收盘>MA20>MA60 + 前20涨≤80% + 近5日均额≥1亿 + 开盘<9.8% + 非ST → 量比前3；**#2/#3若9:25开盘价收在竞价区间顶部20%(终值位置>80)则剔**，剩几只等额买。
- **兜底②**(主选选不出)：去掉量比>3下限和涨幅上限(留贴高+趋势) → 量比第1。
- **真空仓**(牛市深兜底,小仓位)：仅量比<20+近5日均额≥1亿+开盘<9.8% → 量比第1。
- 执行：各等额，T开盘买、T+1收盘卖，两份资金错开一天。

## 用法
```bash
export TUSHARE_TOKEN=你的tushare_token
# 推送任选其一(配了就推):
export LARK_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx   # 飞书自定义机器人
export WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx  # 企业微信群机器人
export TELEGRAM_BOT_TOKEN=xxxx; export TELEGRAM_CHAT_ID=xxxx            # Telegram
export PUSHPLUS_TOKEN=xxxx                                             # PushPlus(个人微信)
python3 daily_signal.py            # 取今天; 9:25后运行出当日买入
python3 daily_signal.py 20260626   # 指定日期(回看/测试)
```
仅输出当天买入标的，不输出收益率。详见 strategy_spec.txt。
