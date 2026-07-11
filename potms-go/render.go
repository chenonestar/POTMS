// 模板渲染层 — gonja(Jinja2 兼容引擎) + Flask 风格全局函数
package main

import (
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/nikolalohinski/gonja/v2"
	"github.com/nikolalohinski/gonja/v2/exec"
	"github.com/nikolalohinski/gonja/v2/loaders"
)

var (
	tmplCache = map[string]*exec.Template{}
	tmplDir   = "templates"
)

// endpointRoutes Flask endpoint → 路径模板（{param} 占位；多余 kwargs 变查询串）
var endpointRoutes = map[string]string{
	"auth.login": "/login", "auth.logout": "/logout", "auth.account": "/account",
	"dashboard.index": "/", "dashboard.backup_now": "/backup/now",
	"personnel.list": "/personnel/", "personnel.info_new": "/personnel/info/new",
	"personnel.info_list":   "/personnel/info/",
	"personnel.info_delete": "/personnel/info/{info_id}/delete",
	"personnel.info_edit":   "/personnel/info/{info_id}/edit",
	"personnel.filing_new":  "/personnel/filing/new",
	"personnel.filing_edit": "/personnel/filing/{filing_id}/edit",
	"personnel.view":        "/personnel/{filing_id}", "personnel.delete": "/personnel/{filing_id}/delete",
	"certificate.list": "/certificate/", "certificate.new": "/certificate/new",
	"certificate.edit": "/certificate/{cert_id}/edit", "certificate.delete": "/certificate/{cert_id}/delete",
	"travel.list": "/travel/", "travel.attachments": "/travel/attachments",
	"travel.new": "/travel/new", "travel.edit": "/travel/{travel_id}/edit",
	"travel.view": "/travel/{travel_id}", "travel.delete": "/travel/{travel_id}/delete",
	"travel.cancel": "/travel/{travel_id}/cancel", "travel.restore": "/travel/{travel_id}/restore",
	"travel.attachment_download": "/travel/attachment/{att_id}/download",
	"travel.attachment_preview":  "/travel/attachment/{att_id}/preview",
	"travel.attachment_delete":   "/travel/attachment/{att_id}/delete",
	"decontrol.list":             "/decontrol/", "decontrol.new": "/decontrol/new/{filing_id}",
	"decontrol.view":     "/decontrol/{dec_id}",
	"export.info_export": "/export/info", "export.filing_export": "/export/filing",
	"export.certificate_export": "/export/certificate", "export.travel_export": "/export/travel",
	"export.decontrol_export": "/export/decontrol",
	"export.print_view":       "/print/{print_type}/{id}", "export.batch_print": "/print/batch/{print_type}",
	"import_data.index": "/import/", "import_data.download_template": "/import/template",
	"logs.index": "/logs/", "logs.export": "/logs/export",
	"organization.index": "/org/", "organization.add": "/org/add",
	"organization.edit": "/org/{org_id}/edit", "organization.delete": "/org/{org_id}/delete",
	"dict_admin.index": "/dict/", "dict_admin.add": "/dict/add",
	"dict_admin.edit": "/dict/{dict_id}/edit", "dict_admin.delete": "/dict/{dict_id}/delete",
	"submit_unit.index": "/submit-unit/", "submit_unit.add": "/submit-unit/add",
	"submit_unit.edit": "/submit-unit/{uid}/edit", "submit_unit.delete": "/submit-unit/{uid}/delete",
	"search.index": "/search",
}

func urlFor(endpoint string, kwargs map[string]string) string {
	if endpoint == "static" {
		return "/static/" + kwargs["filename"]
	}
	path, ok := endpointRoutes[endpoint]
	if !ok {
		return "#"
	}
	var query []string
	for k, v := range kwargs {
		ph := "{" + k + "}"
		if strings.Contains(path, ph) {
			path = strings.ReplaceAll(path, ph, v)
		} else {
			query = append(query, url.QueryEscape(k)+"="+url.QueryEscape(v))
		}
	}
	if len(query) > 0 {
		path += "?" + strings.Join(query, "&")
	}
	return path
}

func loadTemplates() {
	loader, err := loaders.NewFileSystemLoader(tmplDir)
	if err != nil {
		log.Fatal("模板目录加载失败: ", err)
	}
	// 注册 localtime 过滤器（UTC → 本地）
	gonja.DefaultEnvironment.Filters.Register("localtime",
		func(e *exec.Evaluator, in *exec.Value, params *exec.VarArgs) *exec.Value {
			format := "%Y-%m-%d %H:%M:%S"
			if len(params.Args) > 0 {
				format = params.Args[0].String()
			}
			return exec.AsValue(toLocalTime(in.Interface(), format))
		})
	err = filepath.Walk(tmplDir, func(path string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(path, ".html") {
			return err
		}
		rel, _ := filepath.Rel(tmplDir, path)
		rel = filepath.ToSlash(rel)
		tpl, terr := exec.NewTemplate(rel, gonja.DefaultConfig, loader, gonja.DefaultEnvironment)
		if terr != nil {
			return fmt.Errorf("模板 %s 解析失败: %w", rel, terr)
		}
		tmplCache[rel] = tpl
		return nil
	})
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("已加载 %d 个模板", len(tmplCache))
}

// kwStr VarArgs 的 kwargs → map[string]string
func kwStr(params *exec.VarArgs) map[string]string {
	out := map[string]string{}
	for k, v := range params.KwArgs {
		out[k] = v.String()
	}
	return out
}

// baseContext 每请求模板全局（等价 Flask context_processor + Jinja 全局）
func baseContext(w http.ResponseWriter, r *http.Request) map[string]interface{} {
	args := map[string]interface{}{}
	for k, v := range r.URL.Query() {
		if len(v) > 0 {
			args[k] = v[0]
		}
	}
	sess := getSession(r)
	flashes := popFlashes(w, r)

	ctx := map[string]interface{}{
		"session": map[string]interface{}{
			"logged_in": isLoggedIn(r),
			"username":  sess["username"],
		},
		"request": map[string]interface{}{"args": args, "path": r.URL.Path},
		"url_for": func(params *exec.VarArgs) *exec.Value {
			if len(params.Args) == 0 {
				return exec.AsValue("#")
			}
			return exec.AsValue(urlFor(params.Args[0].String(), kwStr(params)))
		},
		"csrf_token": func() string { return csrfToken(w, r) },
		"get_flashed_messages": func(params *exec.VarArgs) *exec.Value {
			var out []interface{}
			for _, f := range flashes {
				out = append(out, []interface{}{f[0], f[1]})
			}
			return exec.AsValue(out)
		},
		// 分页链接：保留当前查询串、替换 page（替代 Jinja 的 **request.args 展开）
		"page_url": func(endpoint string, page int) string {
			q := r.URL.Query()
			q.Set("page", fmt.Sprintf("%d", page))
			return urlFor(endpoint, nil) + "?" + q.Encode()
		},
		"nav_q": func() string {
			if r.URL.Path == "/search" {
				return r.URL.Query().Get("q")
			}
			return ""
		}(),
		"dict_opts":      func(cat string) interface{} { return rowsIface(getDictOptions(cat)) },
		"dict_value":     getDictValue,
		"org_flat":       func() interface{} { return rowsIface(getOrgFlat()) },
		"org_tree_opts":  func() interface{} { return rowsIface(getOrgTreeOptions()) },
		"org_children":   func(pid int64) interface{} { return rowsIface(getOrgChildren(pid)) },
		"personnel_opts": func() interface{} { return rowsIface(getPersonnelOptions()) },
		"submit_units":   func() interface{} { return rowsIface(getSubmitUnits()) },
	}
	return ctx
}

func rowsIface(rows []Row) []interface{} {
	out := make([]interface{}, len(rows))
	for i, r := range rows {
		out[i] = r
	}
	return out
}

// render 渲染模板并写响应
func render(w http.ResponseWriter, r *http.Request, name string, data Row) {
	renderStatus(w, r, name, data, http.StatusOK)
}

func renderStatus(w http.ResponseWriter, r *http.Request, name string, data Row, status int) {
	tpl, ok := tmplCache[name]
	if !ok {
		http.Error(w, "模板不存在: "+name, 500)
		return
	}
	ctx := exec.NewContext(baseContext(w, r))
	if data != nil {
		ctx.Update(exec.NewContext(map[string]interface{}(data)))
	}
	out, err := tpl.ExecuteToString(ctx)
	if err != nil {
		log.Printf("模板渲染失败 %s: %v", name, err)
		serverError(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(status)
	w.Write([]byte(out))
}

func notFound(w http.ResponseWriter, r *http.Request) {
	if tpl, ok := tmplCache["errors/404.html"]; ok {
		ctx := exec.NewContext(baseContext(w, r))
		if out, err := tpl.ExecuteToString(ctx); err == nil {
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.WriteHeader(404)
			w.Write([]byte(out))
			return
		}
	}
	http.NotFound(w, r)
}

func serverError(w http.ResponseWriter, r *http.Request) {
	if tpl, ok := tmplCache["errors/500.html"]; ok {
		ctx := exec.NewContext(baseContext(w, r))
		if out, err := tpl.ExecuteToString(ctx); err == nil {
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			w.WriteHeader(500)
			w.Write([]byte(out))
			return
		}
	}
	http.Error(w, "Internal Server Error", 500)
}

func redirect(w http.ResponseWriter, r *http.Request, endpoint string, kwargs map[string]string) {
	http.Redirect(w, r, urlFor(endpoint, kwargs), http.StatusFound)
}
