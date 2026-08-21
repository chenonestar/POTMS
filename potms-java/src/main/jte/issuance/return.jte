@import com.potms.web.Fmt
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, Object> item
@param String returnDate
@param String typeLabels
!{long id = Fmt.n(item, "id");}
@template.layout(ctx = ctx, title = "证件归还登记", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-box-arrow-in-left"></i> 证件归还登记</h4>

    <div class="alert alert-info py-2">
        领用记录 #${id}：<strong>${Fmt.s(item, "holder_name")}</strong> ·
        ${typeLabels} · 领用日期 ${Fmt.s(item, "issue_date")}
        @if(!Fmt.s(item, "cert_nos").isEmpty()) · 证件号 ${Fmt.s(item, "cert_nos")}@endif
    </div>

    <form method="POST" action="/issuance/${id}/return" id="signForm" class="needs-validation" novalidate>
        <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
        <div class="form-section">
            <h5>归还信息</h5>
            <div class="row g-3">
                <div class="col-md-3">
                    <label class="form-label required">归还日期</label>
                    <input type="text" class="form-control" name="return_date" value="${returnDate}" placeholder="YYYYMMDD" maxlength="8" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label">经办人（接收人）</label>
                    <input type="text" class="form-control" value="${ctx.operatorName()}" readonly>
                </div>
            </div>
        </div>
        <div class="form-section">
            <h5>归还人签名</h5>
            @template.components.signature_pad(label = "归还人手写签名")
        </div>
        <div class="mt-3 mb-4">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> 保存归还登记</button>
            <a href="/issuance/${id}" class="btn btn-secondary">取消</a>
        </div>
    </form>
`)
