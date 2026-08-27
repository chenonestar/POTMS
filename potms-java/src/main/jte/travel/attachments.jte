@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import com.potms.web.TravelController.MissingItem
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Helpers.Page<Map<String, Object>> items
@param String search
@param String typeFilter
@param String dateFrom
@param String dateTo
@param List<MissingItem> missing
@param Map<String, Long> typeCounts
@param long totalAtt
@param List<String> types
@param String sort
@template.layout(ctx = ctx, title = "附件总览", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-paperclip"></i> 附件总览</h4>
        <a href="/travel" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i> 返回出行列表</a>
    </div>

    <div class="row g-3 mb-3">
        <div class="col-md-3">
            <div class="card h-100"><div class="card-body py-2">
                <div class="text-muted small">附件总数</div><div class="fs-4 fw-bold">${totalAtt}</div>
            </div></div>
        </div>
        @for(var t : types)
            <div class="col-md-3">
                <div class="card h-100"><div class="card-body py-2">
                    <div class="text-muted small">${t}</div>
                    <div class="fs-4 fw-bold">${typeCounts.getOrDefault(t, 0L)}</div>
                </div></div>
            </div>
        @endfor
    </div>

    <div class="card mb-3">
        <div class="card-header ${missing.isEmpty() ? "" : "text-danger"}">
            <i class="bi bi-clipboard-x"></i> 缺件检查
            @if(missing.isEmpty())<span class="badge bg-success ms-1">全部齐备</span>@else<span class="badge bg-danger ms-1">${missing.size()} 条缺件</span>@endif
        </div>
        <div class="table-responsive">
            <table class="table table-sm mb-0">
                <thead class="table-light"><tr><th>姓名</th><th>单位</th><th>路径</th><th>缺少附件</th><th></th></tr></thead>
                <tbody>
                @if(missing.isEmpty())
                    <tr><td colspan="5" class="text-muted small">所有出行记录的必备附件均已齐备。</td></tr>
                @endif
                @for(var m : missing)
                    <tr>
                        <td>${m.name()}</td>
                        <td>${m.unit()}</td>
                        <td><span class="badge bg-secondary">路径${m.path()}</span></td>
                        <td>@for(var l : m.lack())<span class="badge bg-danger me-1">${l}</span>@endfor</td>
                        <td><a href="/travel/${m.id()}/edit" class="btn btn-sm btn-outline-warning"><i class="bi bi-upload"></i> 补传</a></td>
                    </tr>
                @endfor
                </tbody>
            </table>
        </div>
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-end">
            <div class="col-md-3"><input type="text" class="form-control form-control-sm" name="search" placeholder="姓名 / 文件名" value="${search}"></div>
            <div class="col-md-2"><select class="form-select form-select-sm" name="file_type">
                <option value="">全部类型</option>
                @for(var t : types)<option value="${t}" selected="${Fmt.is(typeFilter, t)}">${t}</option>@endfor
            </select></div>
            <div class="col-md-3"><select class="form-select form-select-sm" name="sort" onchange="this.form.submit()">
                <option value="batch" selected="${Fmt.is(sort, "batch")}">按出国批次（同一申请聚在一起）</option>
                <option value="uploaded" selected="${Fmt.is(sort, "uploaded")}">按上传时间</option>
            </select></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="date_from" placeholder="上传起 YYYY-MM-DD" value="${dateFrom}"></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="date_to" placeholder="上传止 YYYY-MM-DD" value="${dateTo}"></div>
            <div class="col-auto"><button type="submit" class="btn btn-sm btn-primary">筛选</button><a href="/travel/attachments" class="btn btn-sm btn-outline-secondary">重置</a></div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table id="mainTable" class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th data-col="姓名">姓名</th><th data-col="单位">单位</th><th data-col="类型">类型</th>
                <th data-col="文件名">文件名</th><th data-col="大小">大小</th><th data-col="上传时间">上传时间</th><th>操作</th>
            </tr></thead>
            <tbody>
            @if(items.rows().isEmpty())
                <tr><td colspan="7" class="text-center text-muted py-4">暂无附件</td></tr>
            @endif
            @for(var r : items.rows())
                !{long aid = Fmt.n(r, "id");}
                <tr>
                    <td><a href="/travel/${Fmt.n(r, "travel_id")}">${Fmt.s(r, "name")}</a></td>
                    <td title="${Fmt.s(r, "unit")}">${Fmt.s(r, "unit")}</td>
                    <td><span class="badge bg-light text-dark">${Fmt.s(r, "file_type")}</span></td>
                    <td>${Fmt.s(r, "file_name")}</td>
                    <td>${Math.round(Fmt.n(r, "file_size") / 1024.0)} KB</td>
                    <td>${ctx.localTime(r.get("uploaded_at"))}</td>
                    <td><div class="btn-group btn-group-sm">
                        <a href="/travel/attachment/${aid}/preview" target="_blank" class="btn btn-outline-info" title="预览"><i class="bi bi-eye"></i></a>
                        <a href="/travel/attachment/${aid}/download" class="btn btn-outline-secondary" title="下载"><i class="bi bi-download"></i></a>
                    </div></td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>

    @template.components.pagination(pg = items, basePath = "/travel/attachments", query = ctx.query())
`)
