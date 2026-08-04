# POTMS — Java 版

因私出国（境）人员审批管理系统的 **Spring Boot 实现**，与 Python / Go / Rust / .NET 四版功能与界面一致。

## 技术栈

| 层次 | 选型 | 许可证 |
|---|---|---|
| 运行时 | **Java 21 LTS**（Temurin / 毕昇 / Dragonwell 任一） | GPLv2 + Classpath Exception |
| Web 框架 | **Spring Boot 4.1** | Apache-2.0 |
| 模板 | **JTE 3.2**（编译期生成 Java 代码，零反射） | Apache-2.0 |
| 数据库 | **sqlite-jdbc**（裸 JDBC + JdbcTemplate，无 ORM） | Apache-2.0 |
| 连接池 | HikariCP | Apache-2.0 |
| Excel | **Apache POI 5.5** | Apache-2.0 |
| 国密 | **BouncyCastle 1.85**（SM2/SM3） | MIT 式 |
| 密码 | spring-security-crypto（BCrypt） | Apache-2.0 |
| 前端 | Bootstrap 5.3.3 + Bootstrap Icons（本地 vendored） | MIT |
| 测试 | JUnit 5 | EPL-2.0 |

**全部依赖均为宽松许可证**，无商业授权义务、无营收门槛。依赖树中只有
`log4j-api`（日志门面），**没有 `log4j-core`**，不存在 Log4Shell 攻击面——
政务安全扫描通常会问这一条。

### ⚠️ 禁止替换为 Oracle JDK

这是本技术栈唯一的许可证雷区，请写进运维交接单：

> Oracle JDK 的 **NFTC 免费窗口过期后**，生产使用需购买 Java SE Universal
> Subscription，且**按企业总员工数计费**，不是按开发者数。
>
> 使用 Temurin / Corretto / Zulu / 毕昇 / Dragonwell 等任一 OpenJDK 发行版，
> **Oracle 许可义务归零**。CI 已固定使用 Temurin。

## 与其它四版共用数据库

五个版本共用同一个 `data.db`：

- `src/main/resources/schema.sql` 与 `Data/Schema.java` 由
  **`tools/gen-schema-java.py` 从 Python 版 `database.py` 自动生成**，
  避免手抄造成 schema 漂移。改动 `database.py` 后须重新生成，CI 会校验同步。
- **不使用 JPA/Hibernate**——它会引入自己的元数据表并接管 schema，
  破坏共用前提。改用与其它四版一致的「常量 DDL + 幂等 `migrate()`」。
- 密码哈希双向互通：本版可验证 Python 版 bcrypt 生成的哈希，反之亦然；
  也兼容更早的 werkzeug `pbkdf2:sha256`（登录时透明升级为 bcrypt）。

```bash
# 改动 Python 版 schema 后同步到 Java 版
python3 potms-java/tools/gen-schema-java.py
```

DDL 走 classpath 资源而非 Java 文本块，是刻意的：文本块会按最小缩进剥离
前导空白、并裁掉每行行尾空白，无法保证与来源逐字节相同。

## 运行

```bash
cd potms-java
mvn package
java -jar target/potms.jar
# 默认 http://127.0.0.1:5000，首次运行创建 admin / admin123
```

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `POTMS_BASE` | 当前工作目录 | 数据目录（data.db / uploads / exports / backup） |
| `POTMS_HOST` | `127.0.0.1` | 监听地址 |
| `POTMS_PORT` | `5000` | 监听端口 |
| `POTMS_TZ_OFFSET` | `8` | 展示时区偏移（数据库统一存 UTC） |
| `SECRET_KEY` | 自动生成并持久化 | 会话密钥 |

## 国密签章（本版独有）

手写签名位图本身在《电子签名法》下**不构成可靠电子签名**：谁有数据库写权限，
谁就能换掉那张图，事后无法自证。本版用 SM3withSM2 对
「签名图摘要 + 笔迹矢量 + 领用要素」整体签章，锁死凭证。领用详情页会当场验章，
任一处被改动都会显示「签章校验失败」。

证书来源可配置，三种模式业务代码完全一致：

| `POTMS_SM2_SOURCE` | 说明 | 效力 |
|---|---|---|
| `selfsigned`（默认） | 首次运行自动生成，存于数据目录 `.sm2.p12` | 只防内部篡改，**不能对外举证** |
| `pkcs12` | 加载有资质 CA 签发的 `.p12` | ✅ 构成可靠电子签名 |
| `pkcs11` | USB Key / 智能密码钥匙，私钥不出介质 | ✅ 同上 |

| 变量 | 用途 |
|---|---|
| `POTMS_SM2_KEYSTORE` | `pkcs12` 模式的证书文件路径 |
| `POTMS_SM2_PKCS11_LIB` | `pkcs11` 模式的厂商驱动库路径 |
| `POTMS_SM2_PASSWORD` | 证书库口令 |
| `POTMS_SM2_ALIAS` | 密钥条目别名（默认取第一个） |
| `POTMS_SM2_SUBJECT` | 自签证书的主体名 |

将来单位拿到正式证书，**只改环境变量，不动业务数据与代码**。

签章存在独立的 `cert_issuance_seal` 表，刻意不往 `cert_issuance` 加列：
那张表由 `database.py` 统一定义、五版共用，加列会牵动全部版本；独立成表是
纯增量，其它四版对它无感知。

## 测试

```bash
mvn -f potms-java/pom.xml package -DskipTests   # 冒烟要用 target/potms.jar
mvn -f potms-java/pom.xml test
```

- **校验器差分测试**：同一组用例分别喂给 Python 与 Java，输出逐行 diff 必须一致，
  包括错误提示文案——这些文案直接显示给用户，五版须一字不差。
- **全站页面冒烟**：起真进程走真 HTTP，遍历全部 GET 页面断言无 5xx，
  **空库与有数据各跑一遍**。两种库态触发的失败路径不同：空库暴露「结果集为空时的
  取值假设」，有数据暴露拆箱、空集合、字典键为 null 之类。.NET 版正是在空库这条
  路径上出过 500——人工冒烟总带着数据做，测不出来。
- **国密签章**：签验往返、三类篡改检测、拼接歧义、密钥复用、PEM 导出。
- **浏览器级交互验证**：真开一个 Chrome，用 CDP 派发鼠标事件在签名板上画一道
  波浪线，断言画布上确实多出墨色像素、提示文案变成「已签名」、提交时
  `sign_png` / `sign_meta` 被填上；组织架构页则断言点「加部门」能弹出模态框、
  上级与提示语都填对。用 CDP 直接驱动而不引 Selenium / Playwright：
  `java.net.http` 自带 WebSocket，够用，政务项目少一个依赖是一个。
  找不到浏览器时整类跳过，CI 上则显式检查 Chrome 在位，避免静默跳过。

  这一层是补出来的。签名板坏过一次——模板引了 `signature.js` 却没调
  `POTMSSignature.attach()`，画布一片空白、鼠标点了没反应，而页面 HTTP 200、
  HTML 元素一个不少，纯 HTTP 冒烟全绿。同一类窟窿此前还漏过 CSS 全 404。
  凡是「渲染出来才算数」的东西，只有真跑浏览器才测得到。

## 发布

CI 产出 **jpackage 目录版**，目标机无需安装 JRE：

```
dist/POTMS/
  POTMS.exe            ← 双击启动（带控制台窗口，与 Go / Rust / .NET 三版一致）
  runtime/             ← jlink 裁剪后的运行时（约 50 MB）
  app/potms.jar
  potms-fatjar.jar     ← 备用：任何装了 JRE 的机器都能 java -jar 跑
```

同时保留胖 jar 是有意为之：**它是五版里唯一「一份产物跑遍所有平台」的形态**
（sqlite-jdbc 把 20 个平台的原生库都打在 jar 内）。jpackage 目录版则与
Go / Rust / .NET 一样按平台各出一份。

### 导出文件名的编码兜底

导出文件名含中文，能否落盘取决于 `sun.jnu.encoding`——它由 JVM 启动时按系统
语系确定。中文 Windows 是 GBK，没问题；C/POSIX 语系的容器与 CI 是
`ANSI_X3.4-1968`（ASCII），`Path.of("中文.xlsx")` 直接抛
`InvalidPathException: Malformed input`。

**`-Dsun.jnu.encoding=UTF-8` 不解决问题**——实测该属性会被 JVM 覆盖回系统值，
命令行传入无效：

```
$ java -Dsun.jnu.encoding=UTF-8 EncProbe
  System.getProperty(sun.jnu.encoding) = ANSI_X3.4-1968   ← 没被改掉
```

故只能在代码层兜底：落盘前检查文件系统编码能否表示该名字，不能就退回
`export_<时间戳>.xlsx`；下载名（HTTP `Content-Disposition`，按 RFC 5987 编码）
始终保持中文，用户看到的仍是「因私出国境证件领用登记表_20260802.xlsx」。

### 任务管理器里的程序名

`--description` 会写进 exe 版本资源的 `FileDescription`，也就是任务管理器
显示的那个程序名。它**不能直接写在命令行上**——JDK 启动器按系统 ANSI 代码页
解码 argv，而打包机（GitHub windows runner）是 en-US、ACP=1252，中文到不了
jpackage 手里。实测对照：

```
直接传参   --name 名称探针  →  jpackage 收到 ������������
@参数文件  --name 名称探针  →  jpackage 收到 名称探针
```

参数文件是 jpackage 自己用默认字符集读的（JDK 18+ 恒为 UTF-8），绕开了 argv
那道解码。故中文元数据一律走 `@jpackage-args.txt`，并在打包后从成品 exe 把
`FileDescription` 读回来核对，读不到中文就让流水线红——参数文件只保证中文安全
抵达 jpackage，写进 Windows 版本资源时会不会再掉一次，只有在 Windows 上读回来
才算数。

## 组织架构为什么没有「排序」

界面是**树形**的，与 Python / Go / Rust 三版一致，没有排序字段。

Java 版最初照 .NET 版做成了扁平表格 + 行内「排序」编辑框，实际用起来没人说得清
那个数字是什么：Python 建节点时把 `sort_order` 写死成 0、页面上从不暴露，
四版里三版都没有这个概念。留着只会让人猜，索性去掉。

**只是不再从界面上改它**——查询仍是 `ORDER BY parent_id, sort_order, id`，
老库里已有的非零排序值照样生效，与 Python 版对同一个库的表现完全一致。
重命名时表单不提交 `sort_order`，后端据此原样保留库里的值，
不会把老库的排序悄悄抹平（有回归用例盯着）。

## 静态资源挂载路径

```properties
spring.mvc.static-path-pattern=/static/**
```

这一行不能省。Spring Boot 默认把 `classpath:/static/` 映射到 `/**`，
即 `/css/style.css`；而五版共用同一套模板，模板里写的是 Flask 约定的
`/static/css/style.css`。少了这行，CSS/JS 全部 404，页面 HTTP 状态照样 200，
只是退化成没有样式的裸 HTML。

冒烟测试因此增加了一条：从真实渲染出的页面里扒出所有 `/static/...` 引用逐个请求，
断言 200 且 Content-Type 不是 `text/html`。查 Content-Type 是为了另一种坏法——
静态路径没进鉴权白名单时会被 302 到登录页，浏览器把一篇 HTML 当样式表用，
状态码同样是 200。引用清单从页面里扒而不是手写，手写的清单会跟着模板一起过时。

## 功能范围

与 Python 版一致，含 **REQ-012 证件领用管理（手写签名）**，另加国密签章：

- 登录（会话滑动超时、CSRF、每 IP 登录锁定）、账户设置
- 仪表盘（统计、逾期未还、证照到期预警、每日自动备份）
- 人员备案：信息登记表 / 备案表 CRUD、信息表管理页、撤控重报自动关联
- 证照登记（30 天到期预警、条件必填）
- 出国明细：附件分类上传（PDF 魔数校验）、在线预览、取消 / 恢复行程、附件总览缺件检查
- **证件领用**：领用 / 归还登记（均须手写签名）、作废重登、签名图服务、**国密签章**
- 撤控备案、组织架构、数据字典、报送单位、操作日志（变更前后快照）、全局搜索
- Excel 导出六表 + 日志年度归档（签名嵌图）、批量导入、打印与批量打印

### 数据完整性约束（与其它四版一致）

- **单一数据源**：出行表的证件领用 / 归还日期为**派生只读字段**，
  由证件领用模块唯一写入。表单提取函数根本不读这两个字段，伪造 POST 也进不来。
- **删除守卫**：备案 / 信息表 / 出行 / 组织 / 字典 / 报送单位在被引用时禁止删除。
- **签名不可编辑**：一经保存只能作废重登，保证凭证证据效力。

## 已知差异

- 手写签名采集与其它四版**共用同一份 `static/js/signature.js`**（md5 一致，一行未改），
  故鼠标签名的观感完全相同——换用 Java 不会改善签名质量。
- 数据库多一张 `cert_issuance_seal` 表（国密签章存证），其它四版不读不写，
  不影响共用。
- 启动约 3 秒、常驻内存约 300 MB，是五版里最重的一版。功能无差别，
  但「双击就开」的体感不如 Rust / Go 版。
- Excel 签名嵌图不需要任何第三方图像库（POI 借 JDK 自带 ImageIO 算尺寸）；
  Python 版与 .NET 版为避开 Pillow / ImageSharp 都手写了 IHDR 解析器。

### 信创适配

毕昇 JDK 支持麒麟 V10 / UOS 20 / openEuler；龙芯 JDK 过 JCK 认证。

⚠️ **龙芯 LoongArch 需自行编译 sqlite-jdbc 原生库**：该 jar 内置 20 个平台的
原生库，覆盖 aarch64（鲲鹏 / 飞腾）、riscv64、ppc64，但**不含 LoongArch64**。
当前交付目标为 Windows x64，此项暂不适用。
