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
│   ├── validators.py         # 身份证 / 日期校验
│   ├── helpers.py            # 分页 / 复姓 / 日志
│   └── excel_export.py       # openpyxl 表格生成
├── templates/                # Jinja2 模板 (Bootstrap 5)
├── static/                   # CSS / JS
├── uploads/                  # PDF 附件存储 (运行时创建)
├── exports/                  # 临时 Excel 文件 (运行时创建)
├── backup/                   # 数据库备份 (运行时创建)
└── venv/                     # Python 虚拟环境
```

---

## 打包部署

### 方式一：源码直接运行（开发/测试）

适用于已有 Python 环境的机器，直接 `python app.py` 启动。

### 方式二：PyInstaller 打包为单个 .exe（推荐）

无需安装 Python，拷贝即用。

```bash
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 打包为单文件
pyinstaller --onefile --add-data "templates;templates" --add-data "static;static" --name "POTMS" app.py

# 3. 输出文件位于 dist/POTMS.exe
```

首次运行时程序会自动创建 `data.db` 以及 `uploads/`、`exports/`、`backup/` 目录。

> **注意**：打包后 `admin123` 为默认密码，首次登录后建议在数据库中修改。

### 方式三：Windows 自启动（开机运行）

将 `POTMS.exe` 快捷方式放入 Windows 启动文件夹：

```
C:\Users\<用户名>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
```

或使用 `nssm`（Non-Sucking Service Manager）注册为 Windows 服务：

```bash
nssm install POTMS "C:\POTMS\dist\POTMS.exe"
nssm set POTMS AppDirectory "C:\POTMS\dist"
nssm start POTMS
```

---

## 数据库备份

SQLite 数据库为单文件 `data.db`，备份即复制该文件。

### 手动备份

```bash
copy data.db backup\data_20260703.db
```

### 自动备份（Windows 任务计划程序）

创建批处理文件 `backup.bat`：

```bat
@echo off
set BACKUP_DIR=E:\POTMS\backup
set DATE=%date:~0,4%%date:~5,2%%date:~8,2%
copy E:\POTMS\data.db %BACKUP_DIR%\data_%DATE%.db
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

## 修改管理员密码

```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('新密码'))"
```

将输出的哈希值更新到 `data.db` 中 `users` 表的 `password_hash` 字段：

```sql
UPDATE users SET password_hash = '新哈希值' WHERE username = 'admin';
```

---

## 技术栈

| 层级 | 选型 |
|---|---|
| Web 框架 | Flask 3 |
| 数据库 | SQLite3（Python 标准库，免安装） |
| 前端 | Bootstrap 5 + Jinja2 |
| Excel | openpyxl |
| 打包 | PyInstaller |

> 为什么选 Python 而非 Go？详见 `开发需求文档.html` 第 9.5 节对比分析。
