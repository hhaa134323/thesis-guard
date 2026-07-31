"""Thesis Watch — 个人持仓条件核对 Agent（v0.1）。

包内只含「数据 + 逻辑」层，刻意不依赖 agent 框架与网络：
- models：thesis 卡结构化 schema（对应 docs/thesis-card-schema.md）
- conditions：破局条件两层逻辑（对应 docs/broken-condition-schema.md）
- redline：R3/R5 文案黑名单校验（对应 README 红线表）
- config：用户可配阈值（Layer 2 红线包）
- evidence：证据引用自检契约（对应 docs/harness-design.md §5）
- store：SQLite 持久化（单库，预置账号，无注册）

Agent loop（A: Claude Agent SDK / B: 手搓 SDK loop）与 fetchers 待选型确认 +
源码 clone 后接入（见 docs/BLOCKERS.md B1）。
"""

__version__ = "0.0.1"
