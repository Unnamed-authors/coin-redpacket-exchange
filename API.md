# 金币兑换系统接口文档

## 基础约定

主服务 `http://localhost:8080`，下游模拟服务 `http://127.0.0.1:8081`。

主服务 POST 请求使用 `Content-Type: application/json`，请求体上限 4096 字节，必须为 JSON 对象。除登录和健康检查外，主服务接口均需要登录 Cookie。浏览器自动携带同源 Cookie；命令行使用 `curl -c cookies.txt` 保存、`-b cookies.txt` 携带。会话有效期 24 小时，Cookie 为 HttpOnly、SameSite=Strict；退出使会话失效。

金额单位均为**整数分**，金币为整数；时间戳为 Unix 秒；每日额度按 Asia/Shanghai 日期计算。主服务业务错误格式为 `{"error":"错误原因"}`，Debug 下游代理错误有附加字段。

## 主服务接口

### GET /api/health

不需登录。HTTP 200：`{"ok":true}`。

### POST /api/login

```json
{"username":"demo","password":"demo12345"}
```

HTTP 200：`{"ok":true}`，并设置 session Cookie。错误密码或用户不存在返回 HTTP 401。

```bash
curl -c cookies.txt http://localhost:8080/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo12345"}'
```

### POST /api/logout

请求体 `{}`。HTTP 200：`{"ok":true}`，删除服务端会话并清除 Cookie。未登录返回 401。

### GET /api/me

读取登录用户账户与历史订单；不接受外部 userId。HTTP 200 示例：

```json
{
  "username":"demo",
  "available":1999900,
  "frozen":0,
  "redpacketBalance":1,
  "todayCount":1,
  "orders":[{
    "id":"3f4d36cfed554bf092e16c2048544a54",
    "user_id":"demo",
    "idem":"client-unique-request-0001",
    "coins":100,
    "amount":1,
    "status":"SUCCESS",
    "mode":"success",
    "day":"2026-10-16",
    "created":1792123200,
    "updated":1792123201,
    "packet_id":"mock-packet-id",
    "expires":1792728001,
    "recovered":0,
    "attempts":1,
    "next_attempt":0,
    "error":null
  }]
}
```

| 字段 | 含义 |
|---|---|
| available / frozen | 可用 / 冻结金币 |
| redpacketBalance | 尚未过期的成功红包金额合计，单位分 |
| todayCount | 当日受理数，含 PENDING、SUCCESS、FAILED |
| orders | 全部本人订单，创建时间倒序 |
| id / idem | 服务端订单号 / 客户端幂等号 |
| status | PENDING 结果待确认、SUCCESS 成功、FAILED 明确失败 |
| mode / recovered | 原故障场景 / 是否已恢复模拟服务（0 或 1） |
| attempts | 后台已结束的处理轮数；一轮通常先查询，必要时发送 |
| next_attempt | PENDING 的下一次可调度时间，0 表示可立即处理；终态忽略 |
| packet_id / expires | 成功红包编号 / 到期时间，未成功时为 null |
| error | 最近处理说明；PENDING 的错误不是最终失败判定 |

### POST /api/exchanges

```json
{"coins":10000,"requestId":"client-unique-request-0001","mode":"timeout_success"}
```

| 参数 | 必填 | 约束 |
|---|---|---|
| coins | 是 | JSON 整数，100～1,000,000，100 的整数倍；布尔值、小数、数字字符串均拒绝 |
| requestId | 是 | 8～100 字符，用户范围内唯一；网络异常后须保留原值重试 |
| mode | 否 | 默认 success，取值见故障场景表 |

首次受理 HTTP **202**：

```json
{"id":"3f4d36cfed554bf092e16c2048544a54","status":"PENDING"}
```

**202 只表示订单和冻结已提交，不表示红包发放成功。** 后续轮询 `/api/me`。同一用户、同一 requestId、相同金额和 mode 重试返回 HTTP 200 和完整原订单；参数不同返回 409。重复请求不会新增订单或重复占额度。

HTTP 400：输入不合法、可用金币不足、当日已受理 10 次。校验拒绝不扣金币、不计次数。主服务 500 或网络断开可能无法确定是否已经受理，使用原 requestId 重试，不生成新号。

```bash
curl -b cookies.txt http://localhost:8080/api/exchanges \
  -H 'Content-Type: application/json' \
  -d '{"coins":100,"requestId":"example-exchange-0001","mode":"timeout_success"}'
curl -b cookies.txt http://localhost:8080/api/me
```

### POST /api/recover

本地演示的下游故障恢复，非人工资金结算接口。

```json
{"id":"服务端订单号"}
```

仅对本人 PENDING 且 mode 为 unavailable / http_error / malformed 的订单设置 recovered=1、立即调度。后台先查原订单，查不到再以原编号正常发送，不改金额和原始 mode，不直接解冻或标记成功。

HTTP 200：`{"ok":true}`。对不匹配、他人或终态订单不执行变更，仍返回相同结果，避免暴露其他用户订单是否存在。

## Debug 接口与页面

登录后，页面右上角点击 **Debug 接口测试**。可选择接口、编辑 JSON、生成新幂等号、重复发送相同请求、切换下游场景，查看 HTTP 状态码、耗时、原始响应及最近请求记录。下方实时展示本人订单、后台重试信息与资金流水。

### GET /api/debug/ledger

HTTP 200：

```json
{"ledger":[{"id":2,"exchange_id":"订单号","kind":"DEBIT","coins":100,"created":1792123201}]}
```

只返回本人最近 100 条流水，倒序。kind：FREEZE 冻结、DEBIT 最终扣减、RELEASE 失败解冻。三者的 coins 均为正数，业务含义由 kind 区分。

### POST /api/debug/downstream

登录后的安全代理，允许测试 send/query，不接受任意下游 URL。请求：

```json
{
  "operation":"send",
  "amount":1,
  "requestId":"debug-test-request-0001",
  "mode":"timeout_success"
}
```

operation 为 send 或 query；amount 为 1～10000 的整数分，默认 1；requestId 长度 8～100；mode 默认 success。query 也需要合法 requestId，amount 仅参与参数校验。mode=unavailable 时代理使用连接拒绝地址；其余查询场景不改变原发放记录。

代理将请求号转换为 `debug-用户ID-SHA256(客户端requestId)`，避免与业务订单及其他用户的直连调用碰撞。**直连不创建兑换订单、不冻结金币、不计入主服务红包余额，也没有后台替你查询；需要手动 query。** 真正资金闭环测试应调用 `/api/exchanges`。

正常代理 HTTP 200：

```json
{
  "requestId":"debug-demo-...",
  "elapsedMs":5,
  "result":{"code":0,"message":"success","data":{"redpacketId":"...","issuedAt":1792123201}},
  "isolated":true
}
```

超时 HTTP 504；下游 HTTP 错误、连接拒绝等 HTTP 502，例如：

```json
{
  "requestId":"debug-demo-...",
  "elapsedMs":2003,
  "error":"TimeoutError",
  "outcome":"UNKNOWN",
  "isolated":true
}
```

HTTP 502/504 不说明是否发放。约 30 秒后用**相同客户端 requestId**、operation=query 再查询。下游 code=1001 的明确失败会被成功代理为 HTTP 200，业务判定看 result.code。malformed 场景也可能 HTTP 200，不能仅凭传输状态认为发放成功。

## 下游红包模拟服务

本地独立服务，不要求登录，仅绑定回环地址；生产对接应增加服务认证和授权。

### POST /api/v1/redpacket/send

```json
{"userId":"demo","amount":1,"requestId":"downstream-unique-id","mode":"success"}
```

userId、requestId 为字符串；amount 为 1～10000 的 JSON 整数分。mode 为扩展故障参数，省略时读取 MOCK_MODE 环境变量或默认 success。

HTTP 200 正常成功：

```json
{"code":0,"message":"success","data":{"redpacketId":"持久化红包ID","issuedAt":1792123201}}
```

`issuedAt` 是为了计算真实发放后七天有效期而增加的协议字段；主服务结算要求它为整数秒。

同一 requestId 同一 userId 和 amount 只发放一次，返回原持久化结果。更换 userId 或 amount 返回 HTTP 409。已受理请求的最终结果不会因为修改 mode 反转。故障开关 http_error/malformed 在发送入口优先模拟异常，业务后台会先查询，避免重复结算。

### GET /api/v1/redpacket/query?requestId=...

HTTP 200，通过 code 表达查询结果：

| code | 含义 | 资金动作 |
|---|---|---|
| 0 | 已成功，含 redpacketId 和 issuedAt | 扣减冻结金币 |
| 1001 | 明确拒绝，终态不可反转 | 解冻 |
| 102 | 已受理，处理中 | 保持冻结，继续查 |
| 404 | 尚无持久化记录 | 保持冻结，以原 requestId 幂等发送 |
| 其他码、异常报文 | 无法确认 | 保持冻结，继续查 |

注意业务 code=404 不同于 HTTP 404。HTTP 404/500/503 等错误都不作为明确拒绝处理。

## 故障场景及处理策略

| mode | 模拟行为 | 主服务处理 |
|---|---|---|
| success | 立即成功 | 原子扣减冻结金币并记录成功 |
| failure | HTTP 200，code=1001 | 原子解冻并记录失败 |
| timeout_success | 先持久化受理，延迟 30 秒返回成功 | 2 秒读取超时后保留冻结；约 30～35 秒后查询成功并扣减 |
| timeout_failure | 先持久化受理，延迟 30 秒返回拒绝 | 先冻结；查询到 1001 后才解冻 |
| unavailable | 主服务访问本地拒绝连接端口 | 结果未知，持续查询；点击恢复后继续原单 |
| http_error | HTTP 503 | 结果未知，保持冻结，恢复后继续原单 |
| malformed | HTTP 200，code=0 但缺少有效成功凭证 | 校验失败，保持冻结，恢复后继续原单 |

后台处理结束后约 3 秒安排下一轮（调度精度约 0.5 秒，繁忙时会延后）。urllib 的 2 秒为网络 I/O 超时，不是整个多次调用流程的全局截止时间。订单持久化，进程重启继续查询。没有“超时超过 N 次自动退金币”的逻辑。

状态转换只有 `PENDING → SUCCESS` 或 `PENDING → FAILED`。冻结和建单同一事务，终态更新、账户变更和流水也同一事务，重复消费只能结算一次。幂等发放与查询要求下游长期保留不可反转的记录；如果真实下游不能满足这一协议，仅凭发送超时无法安全退款。

## 通用 HTTP 错误

| 状态 | 含义 |
|---|---|
| 400 | 请求格式、金额、次数、余额或参数不合法 |
| 401 | 未登录、会话过期或凭证错误 |
| 403 | 不允许的 Origin |
| 404 | 接口不存在 |
| 409 | 幂等编号对应的参数不一致 |
| 413 | 主服务 POST 请求体超过 4096 字节 |
| 415 | 主服务 POST 不是 application/json |
| 500 | 主服务内部异常；原 requestId 重试 |
| 502 / 504 | Debug 代理下游错误 / 超时，结果 UNKNOWN |

Debug 和故障恢复接口为本地验收功能；上线前应移除或限制为有权限的运维入口。

## 多用户维护与管理员接口

迁移会为现有 demo 账号设置 ADMIN，其他历史用户默认 USER，保留已有余额和订单。`GET /api/me` 新增 `role` 字段（ADMIN / USER）。管理员登录后右上角有「用户管理」，可搜索、创建、停用/启用和重置密码。普通用户只能操作本人账户，不能调用以下接口，越权返回 HTTP 403。

### GET /api/admin/users

需管理员会话。HTTP 200：

```json
{"users":[{"id":"demo","username":"demo","available":2000000,"frozen":0,"role":"ADMIN","enabled":1,"created":1792123200,"orderCount":0}]}
```

列表不含密码哈希或会话令牌。enabled 为 1/0。历史账号若无创建时间则 created=0。

### POST /api/admin/users

```json
{"username":"alice","password":"alice12345","initialCoins":2000000}
```

username：3～32 位 ASCII 字母、数字或下划线，区分大小写；password：8～128 字符；initialCoins：0～100000000 的整数，可省略（默认 0）。新账号固定为 USER，独立 ID；客户端不可授予管理员角色。初始金币仅创建时设置，不提供覆盖已有账户余额的接口。

HTTP 201：

```json
{"id":"服务端用户ID","username":"alice","role":"USER","enabled":1,"available":2000000,"frozen":0}
```

重复用户名返回 409，参数不合法返回 400。账户、属性和 CREATE 审计记录同一事务写入，初始金币计入审计记录。

### POST /api/admin/users/update

需要用户 ID，至少提供 enabled 或 password，可一起提供：

```json
{"id":"用户ID","enabled":false}
```

```json
{"id":"用户ID","password":"new-password-123"}
```

enabled 必须是 JSON 布尔值；password 为 8～128 字符。HTTP 200：`{"ok":true}`；用户不存在 404，不能停用当前管理员（409）。停用和重置密码在同一事务内撤销目标用户全部登录会话，旧 Cookie 后续返回 401；停用账号正确密码登录也返回 403。启用后需重新登录。操作记录进入 `user_events`，不记录明文密码。

停用不删除账户和资金流水，不取消已受理订单：后台仍可查询和结算，避免因停用造成已发红包退款。余额、订单、流水、每日额度、客户端幂等号和 Debug 下游请求号均按用户隔离。

## 为什么正常兑换也先返回 PENDING？

本实现选择异步受理接口：事务提交订单与冻结后立即返回 HTTP 202，后台独立调用下游；后续通过 `GET /api/me` 查询业务结果。普通成功也使用相同流程，所以第一次响应可能只有订单 ID 和 PENDING。

这不是一次 HTTP 调用返回两次，也不是资金安全要求所有正常请求必须先 PENDING，而是当前接口契约。也可以设计为同步等待有限时间、已知结果直接返回、未知再返回 PENDING；本实现保留统一异步契约。

Debug 分开显示「接口原始响应」与「业务处理结果」：前者保留首次 202 / PENDING，后者每 2 秒读取该订单并展示 SUCCESS / FAILED / PENDING 及红包、金额、到期时间。后台核实期间不能把 PENDING 展示成兑换成功。

## 我的红包列表

`GET /api/me` 新增 `serverTime`（服务器 Unix 秒）。前端「我的红包」从该接口本人订单中筛选 `status=SUCCESS` 且有红包编号、到期时间的记录，展示金额（amount / 100 元）、发放时间（expires - 604800）、到期时间和红包/订单编号。

有效红包判定 `expires > serverTime`；提供有效、已过期和全部三个筛选。有效红包金额之和对应 redpacketBalance，失败、待确认订单和 Debug 独立测试不进入红包列表。当前仅支持查看与发放，未实现消费核销，界面不提供消费操作。
