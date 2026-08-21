# POTMS · 纯 Rust 版

因私出国（境）人员审批管理系统 —— **axum + minijinja + rusqlite** 单文件实现。

## 技术栈

| 层面 | 选型 |
|------|------|
| Web 框架 | axum（异步 / Tokio） |
| 模板引擎 | minijinja（Jinja2 兼容，与 Python/Go 版复用同一套模板） |
| 数据库 | rusqlite（`bundled`，静态链接 SQLite，无 DLL 依赖） |
| 资源打包 | rust-embed（模板 + 静态资源嵌入二进制，**真单文件 exe**） |
| 密码 | bcrypt + werkzeug pbkdf2 兼容（登录透明升级） |
| Excel | rust_xlsxwriter（导出）/ calamine（导入） |
| 时间 | time（固定时区偏移，store UTC / display local，无 tzdata 依赖） |

数据库结构与 Python 版、Go 版**逐字一致**，三版可共用同一个 `data.db`。

## 运行

双击 `POTMS.exe`，浏览器打开 http://127.0.0.1:5000 ，默认账户 `admin / admin123`（首次登录后请及时修改）。

数据文件（`data.db`、`uploads/`、`exports/`、`backup/`、`.secret_key`）在 exe 同级目录自动创建。
可用环境变量覆盖：`POTMS_BASE`（数据目录）、`POTMS_TZ_OFFSET`（时区偏移小时，默认 8，
与另外四版同名；旧名 `POTMS_TZ` 仍然认）、`SECRET_KEY`。

## 构建

```bash
cargo build --release            # 本机
cargo build --release --target x86_64-pc-windows-msvc   # Windows exe
```

产物为单个 `potms.exe`（模板与静态资源已嵌入，无需附带任何目录）。

### 账户设置：姓名与登录账号的分工

「账户设置」里除用户名 / 密码外还可维护**姓名**。两个字段口径不同：

- **姓名**（`users.full_name`）→ 业务单据、打印件、导出表上的「经办人」。打印出来的
  领用凭证上写「经办人：admin」没法拿去归档，必须是真人名字。
- **登录账号**（`users.username`）→ 操作日志的「操作人」。账号是身份标识，姓名可以
  随时改；日志只记「张三」的话，改名之后历史记录就对不上人了。日志页展示时按账号
  查出姓名，渲染成「张三（admin）」。

姓名不强制：留空时单据回退显示登录账号，仪表盘提示一次，不挡流程。

老库升级后，账户设置页底部会出现**历史经办人回填**按钮，把业务表里等于登录账号的
经办人批量改成姓名（操作日志不动；执行前自动备份一次 `data.db`；不可撤销）。
`users.full_name` 由启动时的幂等迁移自动补齐——五版共用同一个 `data.db`，
哪一版先启动都能补上。
