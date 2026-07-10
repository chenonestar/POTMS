// 因私出国（境）人员审批管理系统 — Go 版主入口
package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
)

func main() {
	initConfig()
	openDB()
	defer db.Close()

	firstRun := func() bool {
		initSchema()
		fr := seedData()
		runMigrations()
		return fr
	}()

	runDailyBackup(false) // 启动即做每日备份检查（幂等）

	loadTemplates()

	mux := http.NewServeMux()
	registerRoutes(mux)

	host := envOr("POTMS_HOST", "127.0.0.1")
	port := envOr("POTMS_PORT", "5000")
	shown := host
	if host == "127.0.0.1" || host == "0.0.0.0" {
		shown = "localhost"
	}
	fmt.Println(strings.Repeat("=", 56))
	fmt.Println("  因私出国（境）人员审批管理系统 (Go)")
	fmt.Printf("  http://%s:%s\n", shown, port)
	if firstRun {
		fmt.Println("  首次运行，默认管理员: admin / admin123（请尽快改密）")
	}
	fmt.Println(strings.Repeat("=", 56))

	log.Fatal(http.ListenAndServe(host+":"+port, protect(mux)))
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// protect 全局中间件：panic 恢复 → 会话缓存释放 → 上传限流 → CSRF → 登录校验
func protect(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer releaseSession(r)
		defer func() {
			if rec := recover(); rec != nil {
				log.Printf("panic: %v (%s %s)", rec, r.Method, r.URL.Path)
				serverError(w, r)
			}
		}()
		r.Body = http.MaxBytesReader(w, r.Body, int64(MaxContentLength))

		path := r.URL.Path
		public := path == "/login" || strings.HasPrefix(path, "/static/")

		// CSRF：所有状态变更请求（含登录表单本身）
		if !csrfOK(r) {
			flashMsg(w, r, "会话已过期或页面已失效，请重新登录后再试。", "warning")
			redirect(w, r, "auth.login", nil)
			return
		}
		// 登录校验
		if !public && !isLoggedIn(r) {
			flashMsg(w, r, "请先登录。", "warning")
			redirect(w, r, "auth.login", nil)
			return
		}
		// 滑动会话过期：已登录请求每次刷新有效期
		if isLoggedIn(r) {
			saveSession(w, r, getSession(r))
		}
		next.ServeHTTP(w, r)
	})
}

func registerRoutes(mux *http.ServeMux) {
	// 静态资源
	mux.Handle("/static/", http.StripPrefix("/static/", http.FileServer(http.Dir("static"))))

	// 认证
	mux.HandleFunc("/login", handleLogin)
	mux.HandleFunc("GET /logout", handleLogout)
	mux.HandleFunc("/account", handleAccount)

	// 首页 / 备份
	mux.HandleFunc("GET /{$}", handleDashboard)
	mux.HandleFunc("POST /backup/now", handleBackupNow)

	// 人员备案
	mux.HandleFunc("GET /personnel/{$}", handlePersonnelList)
	mux.HandleFunc("/personnel/info/new", handleInfoNew)
	mux.HandleFunc("/personnel/info/{info_id}/edit", handleInfoEdit)
	mux.HandleFunc("/personnel/filing/new", handleFilingNew)
	mux.HandleFunc("/personnel/filing/{filing_id}/edit", handleFilingEdit)
	mux.HandleFunc("GET /personnel/{filing_id}", handlePersonnelView)
	mux.HandleFunc("POST /personnel/{filing_id}/delete", handlePersonnelDelete)

	// 证照
	mux.HandleFunc("GET /certificate/{$}", handleCertificateList)
	mux.HandleFunc("/certificate/new", handleCertificateNew)
	mux.HandleFunc("/certificate/{cert_id}/edit", handleCertificateEdit)
	mux.HandleFunc("POST /certificate/{cert_id}/delete", handleCertificateDelete)

	// 出国申请
	mux.HandleFunc("GET /travel/{$}", handleTravelList)
	mux.HandleFunc("GET /travel/attachments", handleTravelAttachments)
	mux.HandleFunc("GET /travel/new", handleTravelNew)
	mux.HandleFunc("POST /travel/new", handleTravelNew)
	mux.HandleFunc("/travel/{travel_id}/edit", handleTravelEdit)
	mux.HandleFunc("GET /travel/{travel_id}", handleTravelView)
	mux.HandleFunc("POST /travel/{travel_id}/delete", handleTravelDelete)
	mux.HandleFunc("POST /travel/{travel_id}/cancel", handleTravelCancel)
	mux.HandleFunc("POST /travel/{travel_id}/restore", handleTravelRestore)
	mux.HandleFunc("GET /travel/attachment/{att_id}/download", handleAttachmentDownload)
	mux.HandleFunc("GET /travel/attachment/{att_id}/preview", handleAttachmentPreview)
	mux.HandleFunc("POST /travel/attachment/{att_id}/delete", handleAttachmentDelete)

	// 撤控
	mux.HandleFunc("GET /decontrol/{$}", handleDecontrolList)
	mux.HandleFunc("/decontrol/new/{filing_id}", handleDecontrolNew)
	mux.HandleFunc("GET /decontrol/{dec_id}", handleDecontrolView)

	// 导出 / 打印
	mux.HandleFunc("GET /export/info", handleExportInfo)
	mux.HandleFunc("GET /export/filing", handleExportFiling)
	mux.HandleFunc("GET /export/certificate", handleExportCertificate)
	mux.HandleFunc("GET /export/travel", handleExportTravel)
	mux.HandleFunc("GET /export/decontrol", handleExportDecontrol)
	mux.HandleFunc("GET /print/batch/{print_type}", handleBatchPrint)
	mux.HandleFunc("GET /print/{print_type}/{id}", handlePrintView)

	// 导入
	mux.HandleFunc("/import/{$}", handleImport)
	mux.HandleFunc("GET /import/template", handleImportTemplate)

	// 日志
	mux.HandleFunc("GET /logs/{$}", handleLogs)
	mux.HandleFunc("GET /logs/export", handleLogsExport)

	// 组织架构
	mux.HandleFunc("GET /org/{$}", handleOrgIndex)
	mux.HandleFunc("POST /org/add", handleOrgAdd)
	mux.HandleFunc("POST /org/{org_id}/edit", handleOrgEdit)
	mux.HandleFunc("POST /org/{org_id}/delete", handleOrgDelete)
	mux.HandleFunc("GET /org/tree-data", handleOrgTreeData)

	// 数据字典
	mux.HandleFunc("GET /dict/{$}", handleDictIndex)
	mux.HandleFunc("POST /dict/add", handleDictAdd)
	mux.HandleFunc("POST /dict/{dict_id}/edit", handleDictEdit)
	mux.HandleFunc("POST /dict/{dict_id}/delete", handleDictDelete)

	// 报送单位
	mux.HandleFunc("GET /submit-unit/{$}", handleSubmitUnitIndex)
	mux.HandleFunc("POST /submit-unit/add", handleSubmitUnitAdd)
	mux.HandleFunc("POST /submit-unit/{uid}/edit", handleSubmitUnitEdit)
	mux.HandleFunc("POST /submit-unit/{uid}/delete", handleSubmitUnitDelete)

	// 全局搜索
	mux.HandleFunc("GET /search", handleSearch)

	// 兜底 404（中文页）
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		notFound(w, r)
	})
}
