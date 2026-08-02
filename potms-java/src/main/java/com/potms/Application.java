package com.potms;

import com.potms.data.Db;
import com.potms.service.Security;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration;
import org.springframework.context.annotation.Bean;

/** 应用入口 — 对应 Python 版 app.py / .NET 版 Program.cs。 */
@SpringBootApplication(exclude = DataSourceAutoConfiguration.class)
public class Application {

    public static void main(String[] args) {
        Config cfg = new Config();

        // 建库与迁移必须在 Web 容器起来之前完成
        Db db = new Db(cfg);
        boolean firstRun = db.isFirstRun();
        if (firstRun) {
            db.initialize();
            db.seedData(Security::hashPassword);
        }
        db.migrate();

        // --init-db：仅初始化数据库后退出（供 CI 与 schema 一致性校验使用）
        for (String a : args) {
            if ("--init-db".equals(a)) {
                System.out.println("数据库已初始化：" + cfg.database);
                return;
            }
        }

        var app = new SpringApplication(Application.class);
        app.setDefaultProperties(java.util.Map.of(
                "server.address", envOr("POTMS_HOST", "127.0.0.1"),
                "server.port", envOr("POTMS_PORT", "5000")));
        var ctx = app.run(args);

        String port = ctx.getEnvironment().getProperty("local.server.port",
                envOr("POTMS_PORT", "5000"));
        System.out.println("=".repeat(56));
        System.out.println("  因私出国（境）人员审批管理系统 (Java)");
        System.out.println("  http://localhost:" + port);
        if (firstRun) {
            System.out.println("  首次运行，默认管理员: admin / admin123（请尽快改密）");
        }
        System.out.println("=".repeat(56));
    }

    /** Config 与 Db 在 main 里已构造，此处交给容器复用同一实例。 */
    @Bean
    Config config() {
        return new Config();
    }

    @Bean
    Db db(Config cfg) {
        return new Db(cfg);
    }

    private static String envOr(String key, String dflt) {
        String v = System.getenv(key);
        return (v == null || v.isBlank()) ? dflt : v;
    }
}
