@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Helpers.Page<Map<String, Object>> items
@param String search
@param String statusFilter
@param String politicalFilter
@param String rankFilter
@param String genderFilter
@param String tagFilter
@param String residenceFilter
@param String sortBy
@param List<Helpers.DictOption> politicalOpts
@param List<Helpers.DictOption> rankOpts
@template.layout(ctx = ctx, title = "人员备案列表", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-people"></i> 人员备案列表</h4>
        <div>
            <a href="/personnel/info/new" class="btn btn-primary"><i class="bi bi-plus-lg"></i> 新增</a>
            <a href="/personnel/info" class="btn btn-outline-secondary ms-1" title="管理信息登记表、清理无备案引用的孤儿记录"><i class="bi bi-card-list"></i> 信息表管理</a>
            <button type="button" class="btn btn-outline-success ms-1" onclick="batchPrint('filing')"><i class="bi bi-printer"></i> 批量打印</button>
            <div class="dropdown d-inline-block ms-1">
                <button class="btn btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown" type="button"><i class="bi bi-layout-three-columns"></i> 列显示</button>
                <ul class="dropdown-menu p-2" id="colMenu" style="min-width:160px;"></ul>
            </div>
            <div class="dropdown d-inline-block ms-1">
                <button class="btn btn-outline-success dropdown-toggle" data-bs-toggle="dropdown" type="button"><i class="bi bi-file-earmark-excel"></i> 导出备案表</button>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="#" onclick="exportFiltered('/export/filing');return false;">按当前筛选导出</a></li>
                    <li><a class="dropdown-item" href="#" onclick="exportSelected('/export/filing');return false;">导出选中行</a></li>
                    <li><a class="dropdown-item" href="/export/filing">全量导出</a></li>
                </ul>
            </div>
            <div class="dropdown d-inline-block ms-1">
                <button class="btn btn-outline-success dropdown-toggle" data-bs-toggle="dropdown" type="button"><i class="bi bi-file-earmark-excel"></i> 导出信息表</button>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="#" onclick="exportFiltered('/export/info');return false;">按当前筛选导出</a></li>
                    <li><a class="dropdown-item" href="#" onclick="exportSelected('/export/info');return false;">导出选中行</a></li>
                    <li><a class="dropdown-item" href="/export/info">全量导出</a></li>
                </ul>
            </div>
        </div>
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-end">
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="search" placeholder="姓名 / 身份证号 / 单位" value="${search}"></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="residence" placeholder="户口所在地" value="${residenceFilter}"></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="status">
                <option value="">全部状态</option>
                <option value="active" selected="${Fmt.is(statusFilter, "active")}">有效</option>
                <option value="decontrolled" selected="${Fmt.is(statusFilter, "decontrolled")}">已撤控</option>
            </select></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="political_status">
                <option value="">政治面貌</option>
                @for(var o : politicalOpts)<option value="${o.value()}" selected="${Fmt.is(politicalFilter, o.value())}">${o.value()}</option>@endfor
            </select></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="rank">
                <option value="">职级</option>
                @for(var o : rankOpts)<option value="${o.code()}" selected="${Fmt.is(rankFilter, o.code())}">${o.value()}</option>@endfor
            </select></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="gender">
                <option value="">性别</option>
                <option value="男" selected="${Fmt.is(genderFilter, "男")}">男</option>
                <option value="女" selected="${Fmt.is(genderFilter, "女")}">女</option>
            </select></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="tag">
                <option value="">标记</option>
                <option value="新增" selected="${Fmt.is(tagFilter, "新增")}">新增</option>
                <option value="更新" selected="${Fmt.is(tagFilter, "更新")}">更新</option>
            </select></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="sort">
                <option value="created_at_desc" selected="${Fmt.is(sortBy, "created_at_desc")}">录入时间（新→旧）</option>
                <option value="created_at_asc" selected="${Fmt.is(sortBy, "created_at_asc")}">录入时间（旧→新）</option>
                <option value="name_asc" selected="${Fmt.is(sortBy, "name_asc")}">姓名排序</option>
                <option value="birth_date_asc" selected="${Fmt.is(sortBy, "birth_date_asc")}">出生日期</option>
            </select></div>
            <div class="col-auto">
                <button type="submit" class="btn btn-sm btn-primary">筛选</button>
                <a href="/personnel" class="btn btn-sm btn-outline-secondary">重置</a>
            </div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table id="mainTable" class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th style="width:30px"><input type="checkbox" id="selectAll" onchange="toggleAll(this)" title="全选"></th>
                <th data-col="姓名">姓名</th><th data-col="性别">性别</th><th data-col="出生日期">出生日期</th>
                <th data-col="身份证号">身份证号</th><th data-col="工作单位">工作单位</th>
                <th data-col="职务/职称">职务/职称</th><th data-col="标记">标记</th>
                <th data-col="状态">状态</th><th>操作</th>
            </tr></thead>
            <tbody>
            @if(items.rows().isEmpty())
                <tr><td colspan="10" class="text-center text-muted py-4">暂无备案记录</td></tr>
            @endif
            @for(var row : items.rows())
                !{String name = Fmt.s(row, "surname") + Fmt.s(row, "given_name");
                  boolean active = Fmt.eq(row, "status", "active");
                  long id = Fmt.n(row, "id");}
                <tr class="${active ? "" : "row-danger"}">
                    <td><input type="checkbox" class="row-check" value="${id}"></td>
                    <td>${name}</td>
                    <td>${Fmt.s(row, "gender")}</td>
                    <td>${Fmt.s(row, "birth_date")}</td>
                    <td><code>${Fmt.maskId(row, "id_number")}</code></td>
                    <td title="${Fmt.s(row, "work_unit")}">${Fmt.s(row, "work_unit")}</td>
                    <td title="${Fmt.s(row, "position_or_title")}">${Fmt.s(row, "position_or_title")}</td>
                    <td><span class="${Fmt.eq(row, "tag", "新增") ? "tag-new" : "tag-update"}">${Fmt.s(row, "tag")}</span></td>
                    <td><span class="${active ? "status-active" : "status-decontrolled"}">${Fmt.statusLabel(Fmt.s(row, "status"))}</span></td>
                    <td><div class="btn-group btn-group-sm">
                        <a href="/personnel/${id}" class="btn btn-outline-info" title="查看"><i class="bi bi-eye"></i></a>
                        <a href="/print/filing/${id}" class="btn btn-outline-secondary" title="打印" target="_blank"><i class="bi bi-printer"></i></a>
                        @if(Fmt.n(row, "info_id") > 0)
                            <a href="/personnel/info/${Fmt.n(row, "info_id")}/edit" class="btn btn-outline-warning" title="编辑信息表"><i class="bi bi-pencil-square"></i></a>
                        @endif
                        @if(active)
                            <a href="/personnel/filing/${id}/edit" class="btn btn-outline-warning" title="编辑备案表"><i class="bi bi-pencil"></i></a>
                            <a href="/decontrol/new?filing_id=${id}" class="btn btn-outline-secondary" title="撤控"><i class="bi bi-arrow-repeat"></i></a>
                            <button type="button" class="btn btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmModal"
                                    data-action="/personnel/${id}/delete"
                                    data-message="确定要删除 ${name} 的备案记录吗？"><i class="bi bi-trash"></i></button>
                        @endif
                    </div></td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>

    @template.components.pagination(pg = items, basePath = "/personnel", query = ctx.query())
    @template.components.confirm_modal()
`, scripts = @`
    <script>
    document.addEventListener('DOMContentLoaded', function () { initColumnToggle('mainTable', 'colMenu', 'cols_personnel'); });
    </script>
`)
