@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import com.potms.web.LogsController.ChangeSet
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Helpers.Page<Map<String, Object>> items
@param Map<Long, ChangeSet> changes
@param Map<String, String> actionLabels
@param Map<String, String> targetLabels
@param String actionFilter
@param String targetFilter
@param String dateFrom
@param String dateTo
@param List<String> years
@template.layout(ctx = ctx, title = "操作日志", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-journal-text"></i> 操作日志</h4>
        <form method="GET" action="/logs/export" class="d-flex gap-2 align-items-center">
            <select class="form-select form-select-sm" name="year" style="width:auto">
                <option value="">选择年份</option>
                @for(var y : years)<option value="${y}">${y} 年</option>@endfor
            </select>
            <button class="btn btn-sm btn-outline-success"><i class="bi bi-file-earmark-excel"></i> 归档导出</button>
        </form>
    </div>
    <div class="alert alert-light border small text-muted py-2">
        归档导出只生成审计副本，库内日志完整保留，不会被清理。
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="GET" class="row g-2 align-items-end">
            <div class="col-md-2"><select class="form-select form-select-sm" name="action">
                <option value="">全部动作</option>
                @for(var e : actionLabels.entrySet())<option value="${e.getKey()}" selected="${Fmt.is(actionFilter, e.getKey())}">${e.getValue()}</option>@endfor
            </select></div>
            <div class="col-md-2"><select class="form-select form-select-sm" name="target_type">
                <option value="">全部对象</option>
                @for(var e : targetLabels.entrySet())<option value="${e.getKey()}" selected="${Fmt.is(targetFilter, e.getKey())}">${e.getValue()}</option>@endfor
            </select></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="date_from" placeholder="起 YYYY-MM-DD" value="${dateFrom}"></div>
            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="date_to" placeholder="止 YYYY-MM-DD" value="${dateTo}"></div>
            <div class="col-auto"><button type="submit" class="btn btn-sm btn-primary">筛选</button><a href="/logs" class="btn btn-sm btn-outline-secondary">重置</a></div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th style="width:150px">时间</th><th style="width:90px">操作人</th><th style="width:90px">动作</th>
                <th style="width:110px">对象</th><th>详情 / 变更</th><th style="width:110px">IP</th>
            </tr></thead>
            <tbody>
            @if(items.rows().isEmpty())
                <tr><td colspan="6" class="text-center text-muted py-4">暂无操作日志</td></tr>
            @endif
            @for(var r : items.rows())
                !{long id = Fmt.n(r, "id"); var ch = changes.get(id);}
                <tr>
                    <td class="small">${ctx.localTime(r.get("created_at"))}</td>
                    <td>${Fmt.s(r, "operator")}</td>
                    <td><span class="badge bg-light text-dark">${actionLabels.getOrDefault(Fmt.s(r, "action"), Fmt.s(r, "action"))}</span></td>
                    <td class="small">${targetLabels.getOrDefault(Fmt.s(r, "target_type"), Fmt.s(r, "target_type"))}
                        @if(Fmt.n(r, "target_id") > 0)<span class="text-muted">#${Fmt.n(r, "target_id")}</span>@endif
                    </td>
                    <td class="small">
                        ${Fmt.s(r, "detail", "")}
                        <%-- 变更详情默认折起来。全量摊开的话，一条改了十几个字段的记录
                           就能把整页撑满，翻日志变成翻墙纸——与 Python 版一致，点开再看。 --%>
                        @if(ch != null && !ch.isEmpty())
                            <a class="small ms-1" data-bs-toggle="collapse" href="#snap${id}" role="button">变更详情 ▾</a>
                            <div class="collapse mt-1" id="snap${id}">
                                @if(ch.isUpdate())
                                    <table class="table table-sm table-bordered mb-0" style="font-size:12px;">
                                        <thead><tr><th>字段</th><th>变更前</th><th>变更后</th></tr></thead>
                                        <tbody>
                                        @for(var c : ch.items())
                                            <tr>
                                                <td>${c.field()}</td>
                                                <td class="text-muted">${c.before().isEmpty() ? "—" : c.before()}</td>
                                                <td class="text-success">${c.after().isEmpty() ? "—" : c.after()}</td>
                                            </tr>
                                        @endfor
                                        </tbody>
                                    </table>
                                @else
                                    <table class="table table-sm table-bordered mb-0" style="font-size:12px;">
                                        <thead><tr><th colspan="2">${ch.heading()}</th></tr></thead>
                                        <tbody>
                                        @for(var c : ch.items())
                                            <tr>
                                                <td style="width:35%">${c.field()}</td>
                                                <td>${c.before().isEmpty() ? c.after() : c.before()}</td>
                                            </tr>
                                        @endfor
                                        </tbody>
                                    </table>
                                @endif
                            </div>
                        @endif
                    </td>
                    <td class="small text-muted">${Fmt.s(r, "ip_address", "-")}</td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>

    @template.components.pagination(pg = items, basePath = "/logs", query = ctx.query())
`)
