// 批量导入 + 导入模板下载
use crate::{db, flash, helpers, page, redirect, require_login, url_escape, Req, St};
use axum::extract::{Multipart, State};
use axum::http::{header, HeaderMap, StatusCode, Uri};
use axum::response::{IntoResponse, Response};
use serde_json::json;

pub async fn index_get(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    page(&st, &mut req, "import/form.html", json!({"result": null}))
}

pub async fn index_post(State(st): State<St>, headers: HeaderMap, uri: Uri, mut mp: Multipart) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let mut csrf = String::new();
    let mut filename = String::new();
    let mut filedata: Vec<u8> = vec![];
    while let Ok(Some(field)) = mp.next_field().await {
        let name = field.name().unwrap_or("").to_string();
        let fname = field.file_name().map(|s| s.to_string());
        let data = field.bytes().await.map(|b| b.to_vec()).unwrap_or_default();
        match name.as_str() {
            "csrf_token" => csrf = String::from_utf8_lossy(&data).into_owned(),
            "file" => { if let Some(f) = fname { filename = f; filedata = data; } }
            _ => {}
        }
    }
    if !req.sess.csrf_ok(&csrf) { flash(&mut req, "表单已过期，请重试。", "danger"); return redirect(&st, &req, "import_data.index", &[]); }
    if filename.is_empty() || filedata.is_empty() {
        flash(&mut req, "请选择要上传的文件。", "warning");
        return page(&st, &mut req, "import/form.html", json!({"result": null}));
    }
    let lower = filename.to_lowercase();
    if !lower.ends_with(".xlsx") && !lower.ends_with(".xls") {
        flash(&mut req, "仅支持 .xlsx 格式的 Excel 文件。", "danger");
        return page(&st, &mut req, "import/form.html", json!({"result": null}));
    }
    let result = {
        let conn = st.db.lock().unwrap();
        match crate::excel::parse_import_file(&conn, &filedata, &req.sess.username()) {
            Ok(res) => {
                helpers::log_action(&conn, &req.sess.username(), &req.ip, "import", "batch", None, &format!("total={}, success={}, errors={}", res.total, res.success, res.errors.len()), None, None);
                Some(res)
            }
            Err(_) => None,
        }
    };
    match result {
        None => { flash(&mut req, "导入失败：无法解析文件。", "danger"); page(&st, &mut req, "import/form.html", json!({"result": null})) }
        Some(res) => {
            if res.success > 0 { flash(&mut req, &format!("成功导入 {} 条记录（共 {} 条）。", res.success, res.total), "success"); }
            if !res.errors.is_empty() { flash(&mut req, &format!("{} 条记录存在错误，详见下方报告。", res.errors.len()), "warning"); }
            let result = json!({"total": res.total, "success": res.success, "errors": res.errors});
            page(&st, &mut req, "import/form.html", json!({"result": result}))
        }
    }
}

pub async fn download_template(State(st): State<St>, headers: HeaderMap, uri: Uri) -> Response {
    let mut req = Req::new(&st, &headers, &uri);
    if let Some(r) = require_login(&st, &mut req) { return r; }
    let bytes = crate::excel::generate_import_template();
    let mut resp = (StatusCode::OK, bytes).into_response();
    resp.headers_mut().insert(header::CONTENT_TYPE, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet".parse().unwrap());
    resp.headers_mut().insert(header::CONTENT_DISPOSITION, format!("attachment; filename*=UTF-8''{}", url_escape("备案人员导入模板.xlsx")).parse().unwrap());
    resp
}
