# AI主池·量比策略 v2.3 — 每日早盘信号

云端 routine 每交易日 9:25 克隆本仓库并运行 `daily_signal.py`，输出**当天买哪几只**并推送到你的飞书/企业微信/Telegram。

## 规则 v2.3
- **择时**：全池(60只AI主池)等权指数 T-1收盘 > MA20 → **进攻(在场)**；≤ MA20(熄火) → **防守=空仓**(持现金, 当日收益0)。银行ETF(512800)/黄金ETF(518880) 仅作参考对比, 不实际持有。
- **量比** = (今日9:25集合竞价量/100) ÷ (过去5日日均量/240)。
- **候选基础筛选**：量比∈(3,20) + T-1收盘≥60日高×93%(贴高) + 多头排列(收盘>MA20>MA60) + 近5日均额≥1亿 + 开盘涨幅<9.8% + 非ST。
- **主选(最多3只, 均分仓位)**：
  - 主选一：候选中**剔20日涨幅>100%**后, 量比第1。
  - 主选二：主选一之外, **剔20日涨幅>80% 且 剔终值位置>80%**后, 量比第1。
  - 主选三：主选一二之外, **剔20日涨幅>80% 且 剔终值位置>80%**后, 量比第1。
  - 终值位置 = (竞价最终价−区间低)/(区间高−区间低)×100；单一价无区间者不剔。
- **兜底**(主选0只)：去掉量比∈(3,20)与20日涨幅限制(留贴高+多头+额≥1亿+开盘<9.8%+非ST) → 量比第1, 满仓1只。
- **深兜底**(主选+兜底0只)：仅量比<20 + 近5日均额≥1亿 + 开盘<9.8% + 非ST → 量比第1, 满仓1只。
- **执行**：T开盘买、T+1收盘卖，本金两份错开一天滚动。

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
