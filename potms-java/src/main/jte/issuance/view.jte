@import com.potms.web.Fmt
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, Object> item
@param Map<String, Object> travel
@param String typeLabels
!{long id = Fmt.n(item, "id"); String st = Fmt.s(item, "status");}
@template.layout(ctx = ctx, title = "证件领用详情", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-vector-pen"></i> 证件领用详情</h4>
        <div class="no-print">
            <a href="/issuance" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i> 返回列表</a>
            <a href="/print/issuance/${id}" class="btn btn-outline-primary btn-sm" target="_blank"><i class="bi bi-printer"></i> 打印</a>
            @if("issued".equals(st))
                <a href="/issuance/${id}/return" class="btn btn-success btn-sm"><i class="bi bi-box-arrow-in-left"></i> 办理归还</a>
            @endif
        </div>
    </div>

    @if("voided".equals(st))
        <div class="alert alert-secondary">
            <i class="bi bi-x-octagon"></i> 本记录已作废。原因：<strong>${Fmt.s(item, "void_reason")}</strong>
        </div>
    @endif

    <div class="alert alert-light border small text-muted py-2">
        <i class="bi bi-info-circle"></i> 签名一经保存不可修改。如登记有误，请<strong>作废后重新登记</strong>，以保证凭证的证据效力。
    </div>

    <div class="card mb-3">
        <div class="card-header"><strong>因私出国（境）证件领用登记表</strong></div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-3"><label class="text-muted">领用人</label><p>${Fmt.s(item, "holder_name")}</p></div>
                <div class="col-md-3"><label class="text-muted">身份证号</label><p><code>${Fmt.s(item, "id_number", "-")}</code></p></div>
                <div class="col-md-3"><label class="text-muted">工作单位</label><p>${Fmt.s(item, "work_unit")}</p></div>
                <div class="col-md-3"><label class="text-muted">状态</label><p>
                    @if("issued".equals(st))<span class="badge bg-primary">已领用（待归还）</span>
                    @elseif("returned".equals(st))<span class="badge bg-success">已归还</span>
                    @else<span class="badge bg-secondary">已作废</span>@endif
                </p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-4"><label class="text-muted">证件种类</label><p>${typeLabels}</p></div>
                <div class="col-md-4"><label class="text-muted">证件号码</label><p>${Fmt.s(item, "cert_nos", "-")}</p></div>
                <div class="col-md-2"><label class="text-muted">领用日期</label><p>${Fmt.s(item, "issue_date")}</p></div>
                <div class="col-md-2"><label class="text-muted">发放人</label><p>${Fmt.s(item, "issuer")}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-2"><label class="text-muted">归还日期</label><p>${Fmt.s(item, "return_date", "未归还")}</p></div>
                <div class="col-md-2"><label class="text-muted">接收人</label><p>${Fmt.s(item, "return_operator", "-")}</p></div>
                <div class="col-md-4"><label class="text-muted">备注</label><p>${Fmt.s(item, "remarks", "-")}</p></div>
                <div class="col-md-4"><label class="text-muted">登记时间</label><p>${ctx.localTime(item.get("created_at"))}</p></div>
            </div>
            @if(travel != null)
                <div class="row mt-2">
                    <div class="col-md-12"><label class="text-muted">关联出行</label><p>
                        <a href="/travel/${Fmt.n(travel, "id")}">#${Fmt.n(travel, "id")} ${Fmt.s(travel, "destination_passport")} · ${Fmt.s(travel, "travel_dates")}</a>
                    </p></div>
                </div>
            @endif
        </div>
    </div>

    <div class="row g-3 mb-3">
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header">领用人签名</div>
                <div class="card-body text-center">
                    <img src="/issuance/${id}/signature.png?kind=issue" alt="领用签名" class="img-fluid border rounded bg-white">
                </div>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header">归还人签名</div>
                <div class="card-body text-center">
                    @if("returned".equals(st))
                        <img src="/issuance/${id}/signature.png?kind=return" alt="归还签名" class="img-fluid border rounded bg-white">
                    @else
                        <p class="text-muted small mb-0 mt-4">尚未归还</p>
                    @endif
                </div>
            </div>
        </div>
    </div>

    @if(!"voided".equals(st))
        <div class="card mb-4 no-print">
            <div class="card-header text-danger"><i class="bi bi-x-octagon"></i> 作废本记录</div>
            <div class="card-body">
                <p class="text-muted small">签名不可编辑。登记有误时作废本记录，然后重新登记一条。</p>
                <form method="POST" action="/issuance/${id}/void" class="row g-2 align-items-end">
                    <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                    <div class="col-md-6">
                        <label class="form-label required">作废原因</label>
                        <input type="text" class="form-control" name="void_reason" placeholder="如：证件种类登记有误" required>
                    </div>
                    <div class="col-auto"><button type="submit" class="btn btn-outline-danger">确认作废</button></div>
                </form>
            </div>
        </div>
    @endif
`)
