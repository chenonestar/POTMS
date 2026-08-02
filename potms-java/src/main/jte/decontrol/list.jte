@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Helpers.Page<Map<String, Object>> items
@param String search
@param String unitTypeFilter
@param List<Helpers.DictOption> unitTypeOpts
@template.layout(ctx = ctx, title = "撤控备案", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-arrow-repeat"></i> 撤控备案</h4>
        <div>
            <button type="button" class="btn btn-outline-success" onclick="batchPrint('decontrol')"><i class="bi bi-printer"></i> 批量打印</button>
            <div class="dropdown d-inline-block ms-1">
                <button class="btn btn-outline-success dropdown-toggle" data-bs-toggle="dropdown" type="button"><i class="bi bi-file-earmark-excel"></i> 导出</button>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" href="#" onclick="exportFiltered('/export/decontrol');return false;">按当前筛选导出</a></li>
                    <li><a class="dropdown-item" href="#" onclick="exportSelected('/export/decontrol');return false;">导出选中行</a></li>
                    <li><a class="dropdown-item" href="/export/decontrol">全量导出</a></li>
                </ul>
            </div>
        </div>
    </div>

    <div class="alert alert-light border small text-muted py-2">
        撤控从「人员备案列表」的撤控按钮发起：选定人员后本页仅作查看与导出。
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-end">
            <div class="col-md-3"><input type="text" class="form-control form-control-sm" name="search" placeholder="姓名 / 身份证号 / 撤控原因" value="${search}"></div>
            <div class="col-md-2"><select class="form-select form-select-sm" name="submit_unit_type">
                <option value="">报送单位类别</option>
                @for(var o : unitTypeOpts)<option value="${o.code()}" selected="${Fmt.is(unitTypeFilter, o.code())}">${o.value()}</option>@endfor
            </select></div>
            <div class="col-auto"><button type="submit" class="btn btn-sm btn-primary">筛选</button><a href="/decontrol" class="btn btn-sm btn-outline-secondary">重置</a></div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table id="mainTable" class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th style="width:30px"><input type="checkbox" id="selectAll" onchange="toggleAll(this)" title="全选"></th>
                <th data-col="姓名">姓名</th><th data-col="身份证号">身份证号</th><th data-col="工作单位">工作单位</th>
                <th data-col="报送单位">报送单位</th><th data-col="入库批号">入库批号</th>
                <th data-col="撤控日期">撤控日期</th><th data-col="撤控原因">撤控原因</th><th>操作</th>
            </tr></thead>
            <tbody>
            @if(items.rows().isEmpty())
                <tr><td colspan="9" class="text-center text-muted py-4">暂无撤控记录</td></tr>
            @endif
            @for(var r : items.rows())
                !{long id = Fmt.n(r, "id");}
                <tr>
                    <td><input type="checkbox" class="row-check" value="${id}"></td>
                    <td>${Fmt.s(r, "surname")}${Fmt.s(r, "given_name")}</td>
                    <td><code>${Fmt.maskId(r, "id_number")}</code></td>
                    <td title="${Fmt.s(r, "work_unit")}">${Fmt.s(r, "work_unit")}</td>
                    <td title="${Fmt.s(r, "submit_unit_name")}">${Fmt.s(r, "submit_unit_name")}</td>
                    <td>${Fmt.s(r, "batch_no")}</td>
                    <td>${Fmt.s(r, "decontrol_date", "-")}</td>
                    <td title="${Fmt.s(r, "reason")}">${Fmt.s(r, "reason")}</td>
                    <td><div class="btn-group btn-group-sm">
                        <a href="/decontrol/${id}" class="btn btn-outline-info" title="查看"><i class="bi bi-eye"></i></a>
                        <a href="/print/decontrol/${id}" class="btn btn-outline-secondary" title="打印" target="_blank"><i class="bi bi-printer"></i></a>
                    </div></td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>

    @template.components.pagination(pg = items, basePath = "/decontrol", query = ctx.query())
`, scripts = @`
    <script>
    document.addEventListener('DOMContentLoaded', function () { initColumnToggle('mainTable', 'colMenu', 'cols_decontrol'); });
    </script>
`)
