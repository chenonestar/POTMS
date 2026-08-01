# POTMS — .NET 版

因私出国（境）人员审批管理系统的 **ASP.NET Core 实现**，与 Python / Go / Rust 三版功能与界面一致。

## 技术栈

| 层次 | 选型 | 许可证 |
|---|---|---|
| 运行时 | .NET 8 (LTS) | MIT |
| Web 框架 | ASP.NET Core **Razor Pages** | MIT |
| 数据库 | **Microsoft.Data.Sqlite** | MIT |
| 数据访问 | **Dapper** | Apache-2.0 |
| Excel | **DocumentFormat.OpenXml** | MIT |
| 密码 | **BCrypt.Net-Next** + 内置 PBKDF2 | MIT |
| 前端 | Bootstrap 5.3.3 + Bootstrap Icons（本地 vendored） | MIT |
| 测试 | xUnit | Apache-2.0 |

**全部依赖均为宽松许可证**，无商业授权义务、无营收门槛、无部署方身份判定。

> 选型过程中排除了两个常见候选：
> - **NPOI 2.8** 已改为 OSMF（开源维护费）模式，年营收 ≥ 1 万美元的创收用户需付费；
>   且其 SkiaSharp 依赖在运行时加载失败。
> - **ClosedXML** 依赖的 SixLabors.ImageSharp 3.x 有营收门槛。
>
> 改用 OpenXML SDK 后不再需要任何图像库：签名 PNG 的尺寸直接从 IHDR 块解析
> （与 Python 版 `utils/excel_export.py` 的 `_png_size` 同一做法）。

## 与其它三版共用数据库

四个版本共用同一个 `data.db`：

- `Data/Schema.cs` 由 **`tools/gen-schema.py` 从 Python 版 `database.py` 自动生成**，
  避免手抄造成 schema 漂移。改动 `database.py` 后须重新生成，CI 会校验同步。
- **不使用 EF Core Migrations**——它会引入 `__EFMigrationsHistory` 表并接管 schema，
  破坏共用前提。改用与其它三版一致的「常量 DDL + 幂等 `Migrate()`」。
- 密码哈希互通：本版可验证 Python 版 bcrypt 生成的哈希，也兼容旧的
  werkzeug `pbkdf2:sha256`（登录时透明升级为 bcrypt）。

```bash
# 改动 Python 版 schema 后同步到 .NET 版
python3 potms-dotnet/tools/gen-schema.py
```

## 运行

```bash
cd potms-dotnet/src/POTMS
dotnet run
# 默认 http://127.0.0.1:5000，首次运行创建 admin / admin123
```

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `POTMS_BASE` | 可执行文件所在目录 | 数据目录（data.db / uploads / exports / backup） |
| `POTMS_HOST` | `127.0.0.1` | 监听地址 |
| `POTMS_PORT` | `5000` | 监听端口 |
| `POTMS_TZ_OFFSET` | `8` | 展示时区偏移（数据库统一存 UTC） |
| `SECRET_KEY` | 自动生成并持久化 | 数据保护密钥 |

## 测试

```bash
dotnet test potms-dotnet/POTMS.sln
```

除校验器 / 安全 / 签名 / schema 一致性的单元测试外，还有一组**全站页面冒烟**
（`PageSmokeTests.cs`）：把应用跑在临时数据目录上，登录后逐个 GET 全部页面，
断言不出现 5xx。**空库与有数据各跑一遍**——两者触发的失败路径不同：

- 空库：`(SELECT COUNT(*) …)` 这类计算列没有声明类型，结果集为空时
  Microsoft.Data.Sqlite 的 `GetFieldType()` 无值可推断而退化为 `byte[]`，
  Dapper 便无法匹配**位置式 record** 的构造函数签名（`/Travel/Attachments`
  曾因此在首次部署时 500，而人工冒烟总是带着数据做，测不出来）。
- 有数据：dynamic 拆箱、字典键为 null、空集合上的 `First()` 等只有真取到行才会炸。

## 发布

自包含发布为**目录**，目标机无需安装 .NET 运行时：

```bash
dotnet publish src/POTMS/POTMS.csproj -c Release -r win-x64 --self-contained true \
  -p:PublishTrimmed=false -p:PublishSingleFile=false -o dist/POTMS-dotnet
```

两个 `false` 是刻意的：

- **不裁剪** —— Razor 与模型绑定大量依赖反射，裁剪后会在运行时才炸，且微软对
  MVC/Razor Pages 不声明裁剪支持。
- **不打单文件** —— 单文件需把原生库（SQLite）释放到 `%TEMP%`，在受管控的政务终端上
  可能因权限受限或杀软误报而起不来。目录发布则 dll 就在目录里，零释放。

产物约 100–130 MB / 约 390 个文件。压包拷贝到目标机解压后双击 `POTMS.exe` 即可。
换平台需重新指定 RID（`linux-x64`、`linux-arm64` 等），与 Go / Rust 版一样按平台各出一份。

## 功能范围

与 Python 版一致，含 **REQ-012 证件领用管理（手写签名）**：

- 登录（会话滑动超时、CSRF、每 IP 登录锁定）、账户设置
- 仪表盘（统计、逾期未还、证照到期预警、每日自动备份）
- 人员备案：信息登记表 / 备案表 CRUD、信息表管理页、撤控重报自动关联
- 证照登记（30 天到期预警）
- 出国明细：附件分类上传（PDF 魔数校验）、在线预览、取消 / 恢复行程、附件总览缺件检查
- **证件领用**：领用 / 归还登记（均须手写签名）、作废重登、签名图服务
- 撤控备案、组织架构、数据字典、报送单位、操作日志（变更前后快照）、全局搜索
- Excel 导出六表 + 日志年度归档（签名嵌图）、批量导入、打印与批量打印

### 数据完整性约束（与其它三版一致）

- **单一数据源**：出行表的证件领用 / 归还日期为**派生只读字段**，
  由证件领用模块唯一写入，杜绝双写造成口径不一致。
- **删除守卫**：备案 / 信息表 / 出行 / 组织 / 字典 / 报送单位在被引用时禁止删除。
- **签名不可编辑**：一经保存只能作废重登，保证凭证证据效力。

## 已知差异

- 手写签名采集与其它三版**共用同一份 `static/js/signature.js`**（一行未改），
  故鼠标签名的观感与 Python / Go / Rust 版完全一致——换用 .NET 不会改善签名质量，
  真正的提升需要原生 Windows Ink（另见仓库中的技术方案讨论）。
- 本版不提供单文件 exe（原因见上）。若必须单文件，Rust 版是四者中最合适的选择。
