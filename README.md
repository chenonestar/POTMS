# 因私出国（境）人员审批管理系统

## 项目简介

对纳入备案管理范围的人员进行因私出国（境）事项的全流程审批与管理，涵盖人员备案、证照登记、出国申请、信息变更、Excel 导出及在线打印。

- **规模**：约 500 人，单用户统管，无多级审批
- **架构**：前后端一体，Flask + SQLite3 + Bootstrap 5
- **语言**：Python 3.12+

---

## 快速开始

### 1. 环境要求

- Python 3.12 或更高版本
- Windows 10/11（64 位）

### 2. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境 (Windows)
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 3. 初始化数据库

```bash
python init_reset.py
```

> 执行后生成 `data.db`，包含管理员账户 `admin` / `admin123`。

### 4. 启动应用

```bash
python app.py
```

浏览器打开 **http://localhost:5000**，使用上述账户登录。

---

## 目录结构

```
POTMS/
├── app.py                    # Flask 主入口
├── config.py                 # 配置文件
├── database.py               # 数据库初始化 + 种子数据
├── auth.py                   # 登录认证
├── init_reset.py             # 重置数据库脚本
├── requirements.txt          # Python 依赖
├── blueprints/               # 业务蓝图
│   ├── dashboard.py          # 仪表盘
│   ├── personnel.py          # 人员备案
│   ├── certificate.py        # 证照管理
│   ├── travel.py             # 出国申请（含附件）
│   ├── decontrol.py          # 撤控备案
│   └── export.py             # Excel 导出 / 打印
├── utils/                    # 工具函数
│   ├── validators.py         # 身份证 / 日期 / 出行区间校验
│   ├── helpers.py            # 分页 / 复姓 / 日志（含变更快照）
│   ├── security.py           # bcrypt 密码哈希与校验
│   ├── backup.py             # 每日自动备份 + 保留30天
│   ├── excel_import.py       # Excel 批量导入
│   └── excel_export.py       # openpyxl 表格生成
├── static/js/regions.js      # 省市区三级联动数据
├── templates/                # Jinja2 模板 (Bootstrap 5)
├── static/                   # CSS / JS
├── uploads/                  # PDF 附件存储 (运行时创建)
├── exports/                  # 临时 Excel 文件 (运行时创建)
├── backup/                   # 数据库备份 (运行时创建)
└── venv/                     # Python 虚拟环境
```

---

## 打包部署

### 方式一：源码直接运行

适用于已有 Python 环境的机器：

```bash
pip install -r requirements.txt
python app.py            # 浏览器打开 http://localhost:5000
```

**运行模式说明**

- **默认即生产模式**：使用 **waitress**（纯 Python WSGI 服务器）提供服务，**不是** Flask 自带的开发服务器，也**不开启** debug。
- 需要开发调试（热重载 + 调试器）时，设置环境变量 `POTMS_DEBUG=1` 再启动。
- 首次运行才会在控制台提示默认账户 `admin / admin123`；改密后或非首次启动不再显示。

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `POTMS_DEBUG` | 关闭 | 设为 `1` 启用 Flask 开发服务器（仅调试用，勿用于生产） |
| `POTMS_HOST` | `127.0.0.1` | 监听地址；如需局域网访问设为 `0.0.0.0` |
| `POTMS_PORT` | `5000` | 监听端口 |
| `SECRET_KEY` | 自动持久化 | 会话密钥，优先级高于 `.secret_key` 文件 |

### 方式二：PyInstaller 打包为单个 .exe（推荐生产）

无需安装 Python，拷贝即用。

**一键打包（推荐）**：在 Windows 上直接双击运行仓库根目录的 **`build.bat`**，它会自动安装依赖、执行打包并输出 `dist\POTMS.exe`。

手动打包命令如下：

```bash
# 1. 安装打包工具（在已装好项目依赖的同一环境中）
pip install -r requirements.txt
pip install pyinstaller

# 2. 打包为单文件（Windows 用分号 ; 分隔；Linux/macOS 用冒号 :）
pyinstaller --onefile ^
  --name "POTMS" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --hidden-import bcrypt ^
  --hidden-import waitress ^
  --exclude-module cryptography ^
  app.py

# 3. 输出文件位于 dist/POTMS.exe（单文件，约 12–15 MB）
```

> **说明**
> - 打包后的 exe **同样以 waitress 生产服务器运行**（debug 关闭）。
> - `--add-data "static;static"` 会把前端静态资源一并打包，包括 `static/vendor/`（**本地内置的 Bootstrap 与 Bootstrap Icons**，无需外网 CDN，断网/内网也能正常显示）与 `static/js/regions.js`（省市区三级联动数据）。
> - `--hidden-import bcrypt --hidden-import waitress` 确保二者被正确收集（waitress 为惰性导入，需显式声明）；若打包后启动报缺少模块，可再追加 `--collect-all bcrypt`。
> - `--exclude-module cryptography`：本项目不依赖 cryptography，排除后可减小体积；部分环境该包存在损坏的二进制绑定，会导致打包分析报错，排除即可规避。
> - 已在 Linux 环境实测：单文件构建成功、启动后经 waitress 提供服务，`data.db`/`uploads`/`exports`/`backup` 正确生成于可执行文件同目录。Windows 下用同样命令（`--add-data` 分隔符改 `;`）即可产出 `.exe`。
> - 程序已适配打包环境：**模板/静态资源**从解压目录读取，而 **`data.db`、`uploads/`、`exports/`、`backup/`、`.secret_key`** 会持久化到 **`POTMS.exe` 所在目录**（不会随临时目录清除而丢失）。

### 目录与数据持久化

首次运行时，程序在 **exe 同目录** 自动创建：

| 文件/目录 | 用途 | 是否需备份 |
|---|---|---|
| `data.db` | SQLite 数据库（全部业务数据） | ✅ 必须 |
| `uploads/` | PDF 附件 | ✅ 必须 |
| `backup/` | 每日自动备份（保留最近 30 天） | 可选 |
| `exports/` | 临时 Excel 导出文件 | 否 |
| `.secret_key` | 会话密钥（持久化，避免重启后登录失效） | 建议随库一起备份 |

> 建议将 `POTMS.exe` 与数据放在一个**具有写权限**的目录（如 `D:\POTMS\`），不要放在 `C:\Program Files\` 等受 UAC 保护的位置。

### 首次运行与安全

- 默认管理员：`admin` / `admin123`，**首次登录后请立即改密**（见"修改管理员密码"）。
- 会话默认 **1 小时** 无操作自动超时（`config.py` 的 `PERMANENT_SESSION_LIFETIME`）。
- 如需在多台机器间固定会话密钥，可设置环境变量 `SECRET_KEY`（优先级高于 `.secret_key` 文件）。

### 方式三：Windows 自启动（开机运行）

将 `POTMS.exe` 快捷方式放入 Windows 启动文件夹：

```
C:\Users\<用户名>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
```

或使用 `nssm`（Non-Sucking Service Manager）注册为 Windows 服务，实现无人值守常驻：

```bash
nssm install POTMS "D:\POTMS\POTMS.exe"
nssm set POTMS AppDirectory "D:\POTMS"
nssm start POTMS
```

> 注册为服务时，`AppDirectory` 必须设为 exe 所在目录，确保 `data.db` 等数据写入正确位置。

---

## 数据库备份

SQLite 数据库为单文件 `data.db`，备份即复制该文件。

### 内置自动备份（默认已启用）

系统已内置每日自动备份，**无需额外配置**：

- 应用启动及每次进入首页时触发检查，当天未备份则自动复制一份到 `backup/data_YYYYMMDD.db`（幂等，当天只备份一次）。
- 自动清理 **30 天前** 的旧备份。
- 首页仪表盘显示"最近备份"日期，并提供 **「立即备份」** 手动按钮。

### 手动备份（离线冷备）

直接复制数据文件即可：

```bash
copy data.db backup\data_20260703.db
```

> 完整冷备建议同时复制 `data.db`、`uploads/`（附件）、`.secret_key`。

### 外部定时备份（可选，Windows 任务计划程序）

若需异地/额外备份，可创建批处理文件 `backup.bat`：

```bat
@echo off
set BACKUP_DIR=E:\POTMS_backup
set DATE=%date:~0,4%%date:~5,2%%date:~8,2%
copy D:\POTMS\data.db %BACKUP_DIR%\data_%DATE%.db
xcopy /E /I /Y D:\POTMS\uploads %BACKUP_DIR%\uploads_%DATE%
```

在 Windows 任务计划程序中创建每日定时任务执行该脚本。

---

## 配置说明

编辑 `config.py` 可调整以下参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `SECRET_KEY` | 随机生成 | Flask 会话密钥 |
| `DATABASE` | `data.db` | 数据库文件路径 |
| `UPLOAD_FOLDER` | `uploads/` | PDF 附件存储目录 |
| `MAX_CONTENT_LENGTH` | 10 MB | 上传文件大小上限 |
| `PERMANENT_SESSION_LIFETIME` | 3600 秒 | 登录超时时间 |
| `CERT_EXPIRY_WARN_DAYS` | 30 天 | 证照到期提前预警天数 |

---

## 修改用户名 / 密码

**推荐：界面内修改。** 登录后点击右上角用户名 →「账户设置」（或侧边栏「系统设置 → 账户设置」），可修改**用户名**与**密码**：任何修改都需先验证当前密码；改密码后会要求用新密码重新登录。

---

**备用：命令行改密码。** 密码采用 **bcrypt** 加盐哈希存储。生成新密码哈希：

```bash
python -c "from utils.security import hash_password; print(hash_password('新密码'))"
```

将输出的哈希值（以 `$2b$` 开头）更新到 `data.db` 中 `users` 表的 `password_hash` 字段：

```sql
UPDATE users SET password_hash = '$2b$...新哈希值...' WHERE username = 'admin';
```

> **兼容说明**：系统兼容旧版 `werkzeug`（pbkdf2）哈希——若数据库中仍是旧哈希，管理员**首次登录成功后会自动升级为 bcrypt**，无需手动迁移。

---

## 技术栈

| 层级 | 选型 |
|---|---|
| Web 框架 | Flask 3 |
| 数据库 | SQLite3（Python 标准库，免安装） |
| 前端 | Bootstrap 5 + Jinja2 |
| Excel | openpyxl |
| 密码哈希 | bcrypt |
| 打包 | PyInstaller |

> 为什么选 Python 而非 Go？详见 `开发需求文档.html` 第 9.5 节对比分析。
