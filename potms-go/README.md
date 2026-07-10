# POTMS — Go 版（因私出国（境）人员审批管理系统）

Python/Flask 版的**纯 Go 重写**：功能一致、界面一致（复用同一套模板与静态资源）。

## 技术栈（全部纯 Go，无 cgo）

| 层 | 选型 |
|---|---|
| Web 框架 | `net/http` 标准库（Go 1.22+ 模式路由） |
| 模板引擎 | `gonja/v2`（Jinja2 兼容，原模板近乎原样运行） |
| 数据库 | `modernc.org/sqlite`（纯 Go SQLite，WAL + 外键） |
| Excel | `excelize/v2`（导出 5 类表单 + 日志归档 + 批量导入） |
| 密码哈希 | `x/crypto/bcrypt`（兼容旧 werkzeug pbkdf2 哈希透明升级） |

## 功能对齐清单（与 Python 版逐项一致）

- 登录/登出/账户设置；**登录防爆破**（5 次失败锁 10 分钟，锁定写日志）
- 会话 1 小时滑动超时；**CSRF** 全覆盖（会话令牌 + 常量时间比对）
- 首页仪表盘（统计/证照预警/**逾期未还**（10/5 个工作日口径）/近期出行/备份状态）
- 人员备案（信息登记表 + 登记备案表、树状部门级联、撤控重报自动关联）
- 证照登记（三证 + 30 天到期预警）
- 出国申请（路径 A/B、PDF 附件**魔数校验**、附件预览/下载、**行程取消/恢复**、附件总览+缺件检查）
- 撤控备案（报送单位配置联动、撤控日期/证件移交日期）
- Excel 导出（全量/按筛选/选中行，标题行+冻结表头，编码转中文）、批量导入（模板下载+逐行校验）
- 在线打印/批量打印（签名栏排版一致）
- 操作日志（字段级变更快照、筛选、**年度归档导出**）
- 数据字典/组织架构/报送单位维护（引用保护删除）
- **全局搜索**（一次搜遍四模块）
- 每日自动备份保留 30 天 + 手动备份；导出文件 7 天自动清理
- 时间 **store UTC / display local**（默认 +8，`POTMS_TZ_OFFSET` 可配）
- 身份证校验位/出生/性别一致性、日期真实性、出行区间校验（前端 JS 与 Python 版同一份）
- 前端窗口化自适应分页、表头排序、列显示、草稿等（同一份 main.js/style.css，行为完全一致）

## 构建与运行

```bash
cd potms-go
go build -ldflags="-s -w" -o potms-go .        # Linux/macOS
GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o POTMS.exe .   # Windows 单文件 exe（约 18MB）
```

运行（`templates/`、`static/` 目录需与可执行文件同目录）：

```bash
./potms-go
# 默认 http://localhost:5000 ，首次运行 admin / admin123
```

环境变量：`POTMS_HOST` / `POTMS_PORT` / `POTMS_BASE`（数据目录）/ `POTMS_TZ_OFFSET` / `SECRET_KEY`。

数据文件与 Python 版布局一致（`data.db`、`uploads/`、`exports/`、`backup/`、`.secret_key`），
**数据库 schema 完全相同**——两版可指向同一个 `data.db` 互换使用。

## 测试

```bash
go test ./...
```

- `TestFullSystem`：端到端（登录→29 个页面→建档/证照/出国/撤控/重报关联/取消恢复/导出/导入模板/归档/备份/404）
- `TestLoginLockout`：防爆破锁定 + 日志
- `TestValidators`：身份证/性别/日期/工作日/逾期/时区/复姓/户口规范化

## 与 Python 版的差异说明

- 模板引擎为 gonja（Jinja2 兼容），个别 Jinja 语法做了等价改写（链式内联 if → `{% if %}`、
  `**kwargs` 展开 → `page_url()`、dict `.get()` → 属性访问），渲染结果一致。
- 部署为单个二进制 + `templates/` + `static/` 两个目录（Python 版为 PyInstaller 单文件内嵌）。
