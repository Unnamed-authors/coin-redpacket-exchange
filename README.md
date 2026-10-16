# 余额宝金币兑换消费红包

本地可运行的 React + Python 3.11 + SQLite 示例。所有金额使用整数分，金币使用整数。仅模拟资金，无真实支付。

## 启动

需要 Python 3.11+、Node.js 20.19+（推荐 22）及 npm；首次安装依赖需联网。

```bash
./start.sh
```

打开 **http://localhost:8080**，账号 **demo**，密码 **demo12345**。初始 2,000,000 金币。前端构建后由后端同源托管，模拟红包服务监听 127.0.0.1:8081。Ctrl+C 停止，数据库保留在 `data/`，重启自动继续处理中订单。

## 体验异常场景

登录后打开 Debug，选择发起兑换接口，再选择正常、明确失败、30 秒延迟成功/失败、连接拒绝、HTTP 503 或异常报文。前端每 2 秒刷新状态。延迟场景客户端 2 秒即超时，金币仍冻结，约 30～35 秒后后台查询得出最终结果。连接拒绝、503、异常报文会保持处理中；点击对应订单的「恢复模拟服务」后以**原订单号**重试，不直接修改资金状态。

每天按 Asia/Shanghai 日期最多提交 10 笔受理订单，含失败和处理中；校验失败及相同幂等号重试不计数。金币必须为 100 的整数倍，单笔 100～1,000,000；不接受截断与小数。红包余额为未过期成功红包的金额总和，不含消费核销（题目未要求消费能力）。

## 实现

- `server.py`：登录、会话、金币账户、兑换、持久化任务与对账工作线程。
- `mock_redpacket.py`：独立 HTTP 下游，独立 SQLite 文件，幂等发放、延迟与查询。
- `schema.sql`：账户、订单、会话和不可重复记账约束。
- `frontend/`：React PC 页面，源码及 npm 锁文件。
- `tests/`：资金事务测试、HTTP 验收、浏览器验收、双进程重启验收。
- `DELIVERY.md`：设计、安全边界和实测结果。

状态只从 `PENDING` 转为 `SUCCESS` 或 `FAILED`。冻结与持久化订单在同一 SQLite `BEGIN IMMEDIATE` 事务完成（订单本身充当 durable outbox）。后台先查询结果，查询不存在时才使用原编号发送。重复发送由下游唯一索引保障。同一订单状态检查、资金更新和流水写入在同一事务中，重复工作线程不会重复扣减。

未知结果保持冻结；**HTTP 错误、连接错误、超时、未知业务码、查询不存在、畸形报文都不是解冻依据**。只有约定的终态拒绝码 `1001` 解冻。下游必须保证幂等编号的结果不可反转、幂等记录长期保留；否则仅调用发送接口无法解决跨服务的资金一致性问题。

## API

主服务：`POST /api/login`、`POST /api/logout`、`GET /api/me`、`POST /api/exchanges`（`coins, requestId, mode`）、`POST /api/recover`（`id`，仅本地演示故障恢复）。订单接口使用登录会话，用户 ID 从会话读取，不接受客户端冒用身份。

模拟下游：

```bash
curl http://127.0.0.1:8081/api/v1/redpacket/send \
  -H 'Content-Type: application/json' \
  -d '{"userId":"demo","amount":1,"requestId":"example-unique-id","mode":"success"}'
curl 'http://127.0.0.1:8081/api/v1/redpacket/query?requestId=example-unique-id'
```

`mode` 支持 `success / failure / timeout_success / timeout_failure / http_error / malformed`，默认可用 `MOCK_MODE` 配置。连接拒绝由主服务 `unavailable` 模式调用 127.0.0.1:1 模拟，或实际停止下游进程。

成功格式为 `code:0, message:success, data:{redpacketId, issuedAt}`。`issuedAt` 是附加协议字段，保证从下游实际发放时间算 7 天；对接真实服务需提供可信发放时间。查询 `102` 表示处理中，`404` 表示尚无记录，`1001` 表示不可反转的失败。HTTP 4xx/5xx 不等于业务终态失败。

主服务环境变量：`DB_PATH`、`REDPACKET_URL`、`PORT`；模拟服务：`MOCK_DB_PATH`、`MOCK_PORT`、`MOCK_MODE`。默认启动脚本使用 8080/8081。

## 复现测试

```bash
python3 -m unittest discover -s tests -v
# 以下 HTTP 验收需要先运行 ./start.sh；创建独立 qa_* 用户，不修改 demo
python3 tests/acceptance.py
python3 tests/concurrency_acceptance.py
# 双进程故障恢复使用临时数据库和 28080/28081，自动清理
python3 tests/restart_acceptance.py
# 浏览器验收需本机 Chrome 和 Playwright；会在 demo 账号生成两笔订单
python3 -m pip install -r requirements-test.txt
python3 tests/browser_acceptance.py
cd frontend && npm run build && npm audit
```

浏览器截图在 `artifacts/`。若 demo 今日额度用完，可使用新建本地数据库运行独立演示，不要在运行中删除数据库。

## 接口文档与 Debug

完整字段、响应、curl 和异常策略见 [API.md](API.md)。登录后点击右上角「Debug 接口测试」，可编辑 JSON、检查响应及耗时、验证幂等、模拟下游异常，并实时查看订单重试和资金流水。独立下游直连使用隔离请求号；业务兑换测试会占用本人当日次数。

浏览器接口文档：[http://localhost:8080/docs/api](http://localhost:8080/docs/api)。Debug 专项验收：

```bash
python3 tests/debug_acceptance.py
```

该测试创建独立账号，实际等待 30 秒验证超时后的查询，不消耗 demo 的兑换额度。证据见 `artifacts/debug-acceptance.txt`。

## 多用户维护

使用 demo 管理员登录，点击右上角「用户管理」，创建任意多个普通用户并设置各自的初始金币；随后退出，用新用户名和密码登录体验。支持搜索、停用/启用、重置密码，余额和订单均独立。停用或改密会撤销该用户会话，已受理订单继续结算。普通用户看不到管理入口且管理员 API 拒绝越权。

Debug 的「接口原始响应」保留首次受理结果，「业务处理结果」每 2 秒自动查询最终状态；正常请求也先返回 PENDING 是本项目的异步接口契约。

```bash
python3 tests/multiuser_acceptance.py
python3 tests/users_browser_acceptance.py
```

## 查看已有红包

登录后可在「我的红包」查看有效与过期消费红包，支持按状态筛选，展示面额、发放/到期时间及关联编号。点击红包余额卡片的「查看我的红包」可定位列表。兑换成功自动刷新，未接入消费核销。

```bash
python3 tests/redpackets_acceptance.py
```

普通兑换表单默认正常兑换，下游故障选项只在 Debug 中。今日额度来自当前用户的实际受理记录，测试账号可能已满；可通过管理员创建新用户体验。不会通过清空历史绕过每日限额。
