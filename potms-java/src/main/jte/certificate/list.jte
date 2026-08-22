@import com.potms.web.CertificateController.Expiring
@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Helpers.Page<Map<String, Object>> items
@param String search
@param String hasPassport
@param String hasHm
@param String hasTw
@param Map<Long, List<Expiring>> expiring
@template.layout(ctx = ctx, title = "证照管理", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-card-checklist"></i> 证照登记列表</h4>
        <div>
            <a href="/certificate/new" class="btn btn-primary"><i class="bi bi-plus-lg"></i> 新增</a>
            <button type="button" class="btn btn-outline-success ms-1" onclick="batchPrint('certificate')"><i class="bi bi-printer"></i> 批量打印</button>
            <div class="dropdown d-inline-block ms-1">
                <button class="btn btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown" type="button"><i class="bi bi-layout-three-columns"></i> 列显示</button>
                <ul class="dropdown-menu p-2" id="colMenu" style="min-width:160px;"></ul>
            </div>
            <div class="dropdown d-inline-block ms-1">
                <button class="btn btn-outline-success dropdown-toggle" data-bs-toggle="dropdown" type="button"><i class="bi bi-file-earmark-excel"></i> 导出</button>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="#" onclick="exportFiltered('/export/certificate');return false;">按当前筛选导出</a></li>
                    <li><a class="dropdown-item" href="#" onclick="exportSelected('/export/certificate');return false;">导出选中行</a></li>
                    <li><a class="dropdown-item" href="/export/certificate">全量导出</a></li>
                </ul>
            </div>
        </div>
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-end">
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="search" placeholder="姓名 / 单位" value="${search}"></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="has_passport"><option value="">护照</option><option value="1" selected="${Fmt.is(hasPassport, "1")}">有护照</option><option value="0" selected="${Fmt.is(hasPassport, "0")}">无护照</option></select></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="has_hm"><option value="">港澳通行证</option><option value="1" selected="${Fmt.is(hasHm, "1")}">有港澳</option><option value="0" selected="${Fmt.is(hasHm, "0")}">无港澳</option></select></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="has_tw"><option value="">台湾通行证</option><option value="1" selected="${Fmt.is(hasTw, "1")}">有台湾</option><option value="0" selected="${Fmt.is(hasTw, "0")}">无台湾</option></select></div>
            <div class="col-auto"><button type="submit" class="btn btn-sm btn-primary">筛选</button><a href="/certificate" class="btn btn-sm btn-outline-secondary">重置</a></div>
        </form>
    </div></div>

    @if(!expiring.isEmpty())
        <div class="alert alert-warning d-flex align-items-center">
            <i class="bi bi-exclamation-triangle-fill me-2"></i>
            <div>以下证照即将到期（30天内）：
                @for(var row : items.rows())
                    @if(expiring.containsKey(Fmt.n(row, "id")))
                        @for(var e : expiring.get(Fmt.n(row, "id")))
                            <strong>${Fmt.s(row, "name")}</strong> — ${e.label()} (${e.expiry()}) &nbsp;
                        @endfor
                    @endif
                @endfor
            </div>
        </div>
    @endif

    <div class="table-card"><div class="table-responsive">
        <table id="mainTable" class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th style="width:30px"><input type="checkbox" id="selectAll" onchange="toggleAll(this)" title="全选"></th>
                <th data-col="单位">单位</th><th data-col="部门">部门</th><th data-col="姓名">姓名</th>
                <th data-col="普通护照">普通护照</th><th data-col="护照有效期">护照有效期</th>
                <th data-col="港澳通行证">港澳通行证</th><th data-col="港澳通有效期">港澳通有效期</th>
                <th data-col="台湾通行证">台湾通行证</th><th data-col="台湾通有效期">台湾通有效期</th><th>操作</th>
            </tr></thead>
            <tbody>
            @if(items.rows().isEmpty())
                <tr><td colspan="11" class="text-center text-muted py-4">暂无证照记录</td></tr>
            @endif
            @for(var row : items.rows())
                !{long id = Fmt.n(row, "id"); boolean warn = expiring.containsKey(id);}
                <tr class="${warn ? "row-warning" : ""}">
                    <td><input type="checkbox" class="row-check" value="${id}"></td>
                    <td title="${Fmt.s(row, "unit")}">${Fmt.s(row, "unit")}</td>
                    <td title="${Fmt.s(row, "department")}">${Fmt.s(row, "department")}</td>
                    <td>${Fmt.s(row, "name")}</td>
                    <td>${Fmt.s(row, "passport_no", "-")}</td>
                    <td>${Fmt.s(row, "passport_expiry", "-")}</td>
                    <td>${Fmt.s(row, "hm_pass_no", "-")}</td>
                    <td>${Fmt.s(row, "hm_pass_expiry", "-")}</td>
                    <td>${Fmt.s(row, "tw_pass_no", "-")}</td>
                    <td>${Fmt.s(row, "tw_pass_expiry", "-")}</td>
                    <td><div class="btn-group btn-group-sm">
                        <a href="/print/certificate/${id}" class="btn btn-outline-secondary" title="打印" target="_blank"><i class="bi bi-printer"></i></a>
                        <a href="/certificate/${id}/edit" class="btn btn-outline-warning" title="编辑"><i class="bi bi-pencil"></i></a>
                        <button type="button" class="btn btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmModal"
                                data-action="/certificate/${id}/delete"
                                data-message="确定要删除 ${Fmt.s(row, "name")} 的证照记录吗？"><i class="bi bi-trash"></i></button>
                    </div></td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>

    @template.components.pagination(pg = items, basePath = "/certificate", query = ctx.query())
    @template.components.confirm_modal()
`, scripts = @`
    <script>
    document.addEventListener('DOMContentLoaded', function () { initColumnToggle('mainTable', 'colMenu', 'cols_certificate'); });
    </script>
`)
