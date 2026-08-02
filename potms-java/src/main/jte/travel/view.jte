@import com.potms.web.Fmt
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, Object> travel
@param List<Map<String, Object>> attachments
@param List<Map<String, Object>> issuances
@param String deadline
@param boolean overdue
!{long id = Fmt.n(travel, "id");
  boolean cancelled = Fmt.eq(travel, "trip_status", "cancelled");}
@template.layout(ctx = ctx, title = Fmt.s(travel, "name") + " - 出行详情", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-airplane"></i> 出国（境）明细详情</h4>
        <div class="no-print">
            <a href="/travel" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i> 返回列表</a>
            <a href="/print/travel/${id}" class="btn btn-outline-primary btn-sm" target="_blank"><i class="bi bi-printer"></i> 打印</a>
            <a href="/travel/${id}/edit" class="btn btn-warning btn-sm"><i class="bi bi-pencil"></i> 编辑</a>
            <a href="/issuance/new?travel_id=${id}" class="btn btn-outline-success btn-sm"><i class="bi bi-vector-pen"></i> 证件领用</a>
        </div>
    </div>

    @if(cancelled)
        <div class="alert alert-secondary d-flex justify-content-between align-items-center">
            <div><i class="bi bi-x-circle"></i> 本行程已于 <strong>${Fmt.s(travel, "cancel_date")}</strong> 取消。已申领证件须于取消日起 5 个工作日内送回保管。</div>
            <form method="POST" action="/travel/${id}/restore" class="m-0">
                <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                <button class="btn btn-sm btn-outline-secondary">恢复为正常</button>
            </form>
        </div>
    @else
        <div class="card mb-3 no-print"><div class="card-body py-2">
            <form method="POST" action="/travel/${id}/cancel" class="row g-2 align-items-end m-0">
                <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                <div class="col-auto"><label class="form-label mb-0 small text-muted">取消行程（留空取今天）</label>
                    <input type="text" class="form-control form-control-sm" name="cancel_date" placeholder="YYYYMMDD" maxlength="8"></div>
                <div class="col-auto"><button class="btn btn-sm btn-outline-danger">取消行程</button></div>
            </form>
        </div></div>
    @endif

    @if(overdue)
        <div class="alert alert-danger"><i class="bi bi-exclamation-triangle-fill"></i> 证件逾期未还，应还日期 <strong>${deadline}</strong>。</div>
    @endif

    <div class="card mb-3">
        <div class="card-header"><strong>因私出国（境）人员明细表</strong></div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-3"><label class="text-muted">单位</label><p>${Fmt.s(travel, "unit")}</p></div>
                <div class="col-md-3"><label class="text-muted">部门</label><p>${Fmt.s(travel, "department")}</p></div>
                <div class="col-md-2"><label class="text-muted">姓名</label><p>${Fmt.s(travel, "name")}</p></div>
                <div class="col-md-2"><label class="text-muted">职务</label><p>${Fmt.s(travel, "position")}</p></div>
                <div class="col-md-2"><label class="text-muted">职称</label><p>${Fmt.s(travel, "title", "-")}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-3"><label class="text-muted">身份证号</label><p><code>${Fmt.s(travel, "id_number")}</code></p></div>
                <div class="col-md-5"><label class="text-muted">地点、证照</label><p>${Fmt.s(travel, "destination_passport")}</p></div>
                <div class="col-md-2"><label class="text-muted">类别</label><p>${Fmt.s(travel, "category")}</p></div>
                <div class="col-md-2"><label class="text-muted">是否做证</label><p>${Fmt.s(travel, "need_new_passport")}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-3"><label class="text-muted">计划出行日期</label><p>${Fmt.s(travel, "travel_dates")}</p></div>
                <div class="col-md-2"><label class="text-muted">批准日期</label><p>${Fmt.s(travel, "approval_date", "-")}</p></div>
                <div class="col-md-2"><label class="text-muted">证件号码</label><p>${Fmt.s(travel, "passport_no", "-")}</p></div>
                <div class="col-md-2"><label class="text-muted">实际回国日期</label><p>${Fmt.s(travel, "actual_return_date", "-")}</p></div>
                <div class="col-md-3"><label class="text-muted">应还日期</label><p>${deadline.isEmpty() ? "-" : deadline}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-3"><label class="text-muted">证件领用日期 <small>(派生)</small></label><p>${Fmt.s(travel, "passport_collect_date", "未领用")}</p></div>
                <div class="col-md-3"><label class="text-muted">证件归还日期 <small>(派生)</small></label><p>${Fmt.s(travel, "passport_return_date", "未归还")}</p></div>
                <div class="col-md-6"><label class="text-muted">录入时间</label><p>${ctx.localTime(travel.get("created_at"))}</p></div>
            </div>
        </div>
    </div>

    <div class="card mb-3">
        <div class="card-header"><strong>附件</strong></div>
        <ul class="list-group list-group-flush">
            @if(attachments.isEmpty())
                <li class="list-group-item text-muted small">暂无附件</li>
            @endif
            @for(var att : attachments)
                <li class="list-group-item d-flex justify-content-between align-items-center py-1">
                    <span><i class="bi bi-file-pdf text-danger"></i> [${Fmt.s(att, "file_type")}] ${Fmt.s(att, "file_name")} (${Math.round(Fmt.n(att, "file_size") / 1024.0)} KB)</span>
                    <span>
                        <a href="/travel/attachment/${Fmt.n(att, "id")}/preview" target="_blank" class="btn btn-sm btn-outline-info"><i class="bi bi-eye"></i></a>
                        <a href="/travel/attachment/${Fmt.n(att, "id")}/download" class="btn btn-sm btn-outline-secondary"><i class="bi bi-download"></i></a>
                    </span>
                </li>
            @endfor
        </ul>
    </div>

    <div class="card mb-4">
        <div class="card-header"><strong>证件领用记录</strong></div>
        <div class="table-responsive">
            <table class="table table-sm mb-0">
                <thead><tr><th>领用日期</th><th>持证人</th><th>状态</th><th>归还日期</th><th></th></tr></thead>
                <tbody>
                @if(issuances.isEmpty())
                    <tr><td colspan="5" class="text-muted small">暂无领用记录</td></tr>
                @endif
                @for(var i : issuances)
                    <tr>
                        <td>${Fmt.s(i, "issue_date")}</td>
                        <td>${Fmt.s(i, "holder_name")}</td>
                        <td>${Fmt.s(i, "status")}</td>
                        <td>${Fmt.s(i, "return_date", "-")}</td>
                        <td><a href="/issuance/${Fmt.n(i, "id")}" class="btn btn-sm btn-outline-info"><i class="bi bi-eye"></i></a></td>
                    </tr>
                @endfor
                </tbody>
            </table>
        </div>
    </div>
`)
