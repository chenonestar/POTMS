@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Helpers.Page<Map<String, Object>> items
@param Map<Long, String> typeLabels
@param String search
@param String statusFilter
@param String certTypeFilter
@param String dateFrom
@param String dateTo
@param List<Helpers.DictOption> certTypeOpts
@template.layout(ctx = ctx, title = "证件领用", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-vector-pen"></i> 证件领用登记</h4>
        <div>
            <a href="/issuance/new" class="btn btn-primary"><i class="bi bi-plus-lg"></i> 新增领用</a>
            <a href="/export/issuance" class="btn btn-outline-success ms-1"><i class="bi bi-file-earmark-excel"></i> 导出</a>
        </div>
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-end">
            <div class="col-md-3"><input type="text" class="form-control form-control-sm" name="search" placeholder="姓名 / 身份证号 / 证件号" value="${search}"></div>
            <div class="col-md-2"><select class="form-select form-select-sm" name="status">
                <option value="">全部状态</option>
                <option value="issued" selected="${Fmt.is(statusFilter, "issued")}">已领用（待归还）</option>
                <option value="returned" selected="${Fmt.is(statusFilter, "returned")}">已归还</option>
                <option value="voided" selected="${Fmt.is(statusFilter, "voided")}">已作废</option>
            </select></div>
            <div class="col-md-2"><select class="form-select form-select-sm" name="cert_type">
                <option value="">证件种类</option>
                @for(var o : certTypeOpts)<option value="${o.code()}" selected="${Fmt.is(certTypeFilter, o.code())}">${o.value()}</option>@endfor
                <option value="pending" selected="${Fmt.is(certTypeFilter, "pending")}">待核实（历史回填未判定）</option>
            </select></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="date_from" placeholder="领用起 YYYYMMDD" value="${dateFrom}"></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="date_to" placeholder="领用止 YYYYMMDD" value="${dateTo}"></div>
            <div class="col-auto"><button type="submit" class="btn btn-sm btn-primary">筛选</button><a href="/issuance" class="btn btn-sm btn-outline-secondary">重置</a></div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th>领用日期</th><th>持证人</th><th>工作单位</th><th>证件种类</th><th>证件号码</th>
                <th>状态</th><th>归还日期</th><th>签名</th><th>操作</th>
            </tr></thead>
            <tbody>
            @if(items.rows().isEmpty())
                <tr><td colspan="9" class="text-center text-muted py-4">暂无领用记录</td></tr>
            @endif
            @for(var r : items.rows())
                !{long id = Fmt.n(r, "id"); String st = Fmt.s(r, "status");}
                <tr class="${"voided".equals(st) ? "row-muted" : ""}">
                    <td>${Fmt.s(r, "issue_date")}</td>
                    <td>${Fmt.s(r, "holder_name")}</td>
                    <td title="${Fmt.s(r, "work_unit")}">${Fmt.s(r, "work_unit")}</td>
                    <%-- 历史回填里判不出种类的：空白单元格会被当成漏渲染，明确标出来才好收口 --%>
                    <td>@if(Fmt.s(r, "cert_types").isEmpty())<span class="badge bg-warning text-dark">待核实</span>
                        @else${typeLabels.getOrDefault(id, "")}@endif</td>
                    <td>${Fmt.s(r, "cert_nos", "-")}</td>
                    <td>
                        @if("issued".equals(st))<span class="badge bg-primary">已领用</span>
                        @elseif("returned".equals(st))<span class="badge bg-success">已归还</span>
                        @else<span class="badge bg-secondary">已作废</span>@endif
                    </td>
                    <td>${Fmt.s(r, "return_date", "-")}</td>
                    <td><img src="/issuance/${id}/signature.png" alt="签名" style="height:28px;" onerror="this.style.display='none'"></td>
                    <td><div class="btn-group btn-group-sm">
                        <a href="/issuance/${id}" class="btn btn-outline-info" title="查看"><i class="bi bi-eye"></i></a>
                        <a href="/print/issuance/${id}" class="btn btn-outline-secondary" title="打印" target="_blank"><i class="bi bi-printer"></i></a>
                        @if("issued".equals(st))
                            <a href="/issuance/${id}/return" class="btn btn-outline-success" title="办理归还"><i class="bi bi-box-arrow-in-left"></i></a>
                        @endif
                    </div></td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>

    @template.components.pagination(pg = items, basePath = "/issuance", query = ctx.query())
`)
