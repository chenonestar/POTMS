using POTMS;
using POTMS.Data;

var cfg = new Config();

// 初始化数据库（首次运行建表 + 种子），随后执行幂等迁移
var db = new Db(cfg);
var firstRun = db.IsFirstRun;
if (firstRun)
{
    db.Initialize();
    db.SeedData();
}
db.Migrate();

// --init-db：仅初始化数据库后退出（供 CI 与 schema 一致性校验使用）
if (args.Contains("--init-db"))
{
    Console.WriteLine($"数据库已初始化：{cfg.Database}");
    return;
}

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton(cfg);
builder.Services.AddSingleton(db);

var app = builder.Build();
app.MapGet("/", () => "POTMS (.NET) 骨架就绪");
app.Run();

/// <summary>供集成测试引用的入口标记类型。</summary>
public partial class Program;
