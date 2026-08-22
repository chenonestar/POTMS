@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@import java.util.Set
@param com.potms.web.Ctx ctx
@param Helpers.Page<Map<String, Object>> items
@param String search
@param String categoryFilter
@param String needPassportFilter
@param String passportStatus
@param String dateFrom
@param String dateTo
@param Set<Long> overdueIds
@param Map<Long, String> deadlines
@param List<Helpers.DictOption> categoryOpts
@template.layout(ctx = ctx, title = "出国（境）明细", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-airplane"></i> 出国（境）人员明细</h4>
        <div>
            <a href="/travel/new" class="btn btn-primary"><i class="bi bi-plus-lg"></i> 新增</a>
            <a href="/travel/attachments" class="btn btn-outline-secondary ms-1"><i class="bi bi-paperclip"></i> 附件总览</a>
            <button type="button" class="btn btn-outline-success ms-1" onclick="batchPrint('travel')"><i class="bi bi-printer"></i> 批量打印</button>
            <div class="dropdown d-inline-block ms-1">
                <button class="btn btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown" type="button"><i class="bi bi-layout-three-columns"></i> 列显示</button>
                <ul class="dropdown-menu p-2" id="colMenu" style="min-width:160px;"></ul>
            </div>
            <div class="dropdown d-inline-block ms-1">
                <button class="btn btn-outline-success dropdown-toggle" data-bs-toggle="dropdown" type="button"><i class="bi bi-file-earmark-excel"></i> 导出</button>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="#" onclick="exportFiltered('/export/travel');return false;">按当前筛选导出</a></li>
                    <li><a class="dropdown-item" href="#" onclick="exportSelected('/export/travel');return false;">导出选中行</a></li>
                    <li><a class="dropdown-item" href="/export/travel">全量导出</a></li>
                </ul>
            </div>
        </div>
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-end">
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="search" placeholder="姓名 / 地点证照" value="${search}"></div>
            <div class="col-md-2"><select class="form-select form-select-sm" name="category">
                <option value="">全部类别</option>
                @for(var o : categoryOpts)<option value="${o.value()}" selected="${Fmt.is(categoryFilter, o.value())}">${o.value()}</option>@endfor
            </select></div>
            <div class="col-md-1"><select class="form-select form-select-sm" name="need_new_passport">
                <option value="">是否做证</option>
                <option value="是" selected="${Fmt.is(needPassportFilter, "是")}">需做证</option>
                <option value="否" selected="${Fmt.is(needPassportFilter, "否")}">不做证</option>
            </select></div>
            <div class="col-md-2"><select class="form-select form-select-sm" name="passport_status">
                <option value="">证件状态</option>
                <option value="storage" selected="${Fmt.is(passportStatus, "storage")}">在库（未领用）</option>
                <option value="inuse" selected="${Fmt.is(passportStatus, "inuse")}">使用中（已领未还）</option>
                <option value="overdue" selected="${Fmt.is(passportStatus, "overdue")}">逾期未还</option>
            </select></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="date_from" placeholder="出行起 YYYYMMDD" value="${dateFrom}"></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="date_to" placeholder="出行止 YYYYMMDD" value="${dateTo}"></div>
            <div class="col-auto"><button type="submit" class="btn btn-sm btn-primary">筛选</button><a href="/travel" class="btn btn-sm btn-outline-secondary">重置</a></div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table id="mainTable" class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th style="width:30px"><input type="checkbox" id="selectAll" onchange="toggleAll(this)" title="全选"></th>
                <th data-col="姓名">姓名</th><th data-col="单位">单位</th><th data-col="地点、证照">地点、证照</th>
                <th data-col="类别">类别</th><th data-col="计划出行日期">计划出行日期</th>
                <th data-col="是否做证">是否做证</th><th data-col="证件状态">证件状态</th><th>操作</th>
            </tr></thead>
            <tbody>
            @if(items.rows().isEmpty())
                <tr><td colspan="9" class="text-center text-muted py-4">暂无出行记录</td></tr>
            @endif
            @for(var row : items.rows())
                !{long id = Fmt.n(row, "id");
                  boolean od = overdueIds.contains(id);
                  boolean cancelled = Fmt.eq(row, "trip_status", "cancelled");
                  boolean collected = !Fmt.s(row, "passport_collect_date").isEmpty();
                  boolean returned = !Fmt.s(row, "passport_return_date").isEmpty();}
                <tr class="${od ? "row-danger" : (cancelled ? "row-muted" : "")}">
                    <td><input type="checkbox" class="row-check" value="${id}"></td>
                    <td>${Fmt.s(row, "name")}@if(cancelled)<span class="badge bg-secondary ms-1">已取消</span>@endif</td>
                    <td title="${Fmt.s(row, "unit")}">${Fmt.s(row, "unit")}</td>
                    <td>${Fmt.s(row, "destination_passport")}</td>
                    <td>${Fmt.s(row, "category")}</td>
                    <td>${Fmt.s(row, "travel_dates")}</td>
                    <td>${Fmt.s(row, "need_new_passport")}</td>
                    <td>
                        @if(od)
                            <span class="badge bg-danger">逾期未还</span>
                            <div class="small text-danger">应还 ${deadlines.getOrDefault(id, "")}</div>
                        @elseif(returned)
                            <span class="badge bg-success">已归还</span>
                        @elseif(collected)
                            <span class="badge bg-primary">使用中</span>
                        @else
                            <span class="badge bg-secondary">在库</span>
                        @endif
                    </td>
                    <td><div class="btn-group btn-group-sm">
                        <a href="/travel/${id}" class="btn btn-outline-info" title="查看"><i class="bi bi-eye"></i></a>
                        <a href="/print/travel/${id}" class="btn btn-outline-secondary" title="打印" target="_blank"><i class="bi bi-printer"></i></a>
                        <a href="/travel/${id}/edit" class="btn btn-outline-warning" title="编辑"><i class="bi bi-pencil"></i></a>
                        <button type="button" class="btn btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmModal"
                                data-action="/travel/${id}/delete"
                                data-message="确定要删除 ${Fmt.s(row, "name")} 的出行记录吗？相关附件一并删除。"><i class="bi bi-trash"></i></button>
                    </div></td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>

    @template.components.pagination(pg = items, basePath = "/travel", query = ctx.query())
    @template.components.confirm_modal()
`, scripts = @`
    <script>
    document.addEventListener('DOMContentLoaded', function () { initColumnToggle('mainTable', 'colMenu', 'cols_travel'); });
    </script>
`)
