@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Helpers.Page<Map<String, Object>> items
@param String search
@param String ref
@template.layout(ctx = ctx, title = "信息登记表管理", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-card-list"></i> 信息登记表管理</h4>
        <div>
            <a href="/personnel" class="btn btn-outline-secondary"><i class="bi bi-arrow-left"></i> 返回备案列表</a>
            <a href="/personnel/info/new" class="btn btn-primary ms-1"><i class="bi bi-plus-lg"></i> 新增</a>
        </div>
    </div>

    <div class="alert alert-light border small text-muted py-2">
        <b>关联备案数为 0</b> 的记录（无任何备案引用的孤儿行，通常由填错重建产生）可安全删除；有引用的记录请先处理其备案后再删。
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-end">
            <div class="col-md-3"><input type="text" class="form-control form-control-sm" name="search" placeholder="姓名 / 身份证号 / 单位 / 部门" value="${search}"></div>
            <div class="col-md-2"><select class="form-select form-select-sm" name="ref">
                <option value="">全部</option>
                <option value="orphan" selected="${Fmt.is(ref, "orphan")}">仅孤儿（0 引用）</option>
                <option value="linked" selected="${Fmt.is(ref, "linked")}">仅有备案引用</option>
            </select></div>
            <div class="col-auto">
                <button type="submit" class="btn btn-sm btn-primary">筛选</button>
                <a href="/personnel/info" class="btn btn-sm btn-outline-secondary">重置</a>
            </div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table id="mainTable" class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th data-col="编号">编号</th><th data-col="单位">单位</th><th data-col="部门">部门</th>
                <th data-col="姓名">姓名</th><th data-col="性别">性别</th><th data-col="身份证号">身份证号</th>
                <th data-col="关联备案数">关联备案数</th><th>操作</th>
            </tr></thead>
            <tbody>
            @if(items.rows().isEmpty())
                <tr><td colspan="8" class="text-center text-muted py-4">暂无信息登记表</td></tr>
            @endif
            @for(var r : items.rows())
                !{long id = Fmt.n(r, "id"); long cnt = Fmt.n(r, "filing_count");}
                <tr>
                    <td>${id}</td>
                    <td title="${Fmt.s(r, "unit")}">${Fmt.s(r, "unit")}</td>
                    <td title="${Fmt.s(r, "department")}">${Fmt.s(r, "department")}</td>
                    <td>${Fmt.s(r, "name")}</td>
                    <td>${Fmt.s(r, "gender")}</td>
                    <td>${Fmt.s(r, "id_number", "—")}</td>
                    <td>
                        @if(cnt > 0)
                            <span class="badge bg-success">${cnt}</span>
                        @else
                            <span class="badge bg-warning text-dark">0（孤儿）</span>
                        @endif
                    </td>
                    <td><div class="btn-group btn-group-sm">
                        <a href="/personnel/info/${id}/edit" class="btn btn-outline-warning" title="编辑"><i class="bi bi-pencil"></i></a>
                        @if(cnt == 0)
                            <button type="button" class="btn btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmModal"
                                    data-action="/personnel/info/${id}/delete"
                                    data-message="确定要删除 ${Fmt.s(r, "name")} 的信息登记表（编号 ${id}）吗？此操作不可恢复。"
                                    title="删除"><i class="bi bi-trash"></i></button>
                        @else
                            <button type="button" class="btn btn-outline-danger" disabled title="有备案引用，不能删除"><i class="bi bi-trash"></i></button>
                        @endif
                    </div></td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>

    @template.components.pagination(pg = items, basePath = "/personnel/info", query = ctx.query())
    @template.components.confirm_modal()
`)
