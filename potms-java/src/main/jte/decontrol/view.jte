@import com.potms.web.Fmt
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, Object> dec
!{long id = Fmt.n(dec, "id");}
@template.layout(ctx = ctx, title = "撤控详情", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-arrow-repeat"></i> 撤控备案详情</h4>
        <div class="no-print">
            <a href="/decontrol" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i> 返回列表</a>
            <a href="/print/decontrol/${id}" class="btn btn-outline-primary btn-sm" target="_blank"><i class="bi bi-printer"></i> 打印</a>
            <a href="/personnel/${Fmt.n(dec, "personnel_filing_id")}" class="btn btn-outline-info btn-sm"><i class="bi bi-person"></i> 查看原备案</a>
        </div>
    </div>

    <div class="card mb-4">
        <div class="card-header"><strong>因私事出国（境）人员撤控备案表</strong></div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-2"><label class="text-muted">中文姓</label><p>${Fmt.s(dec, "surname")}</p></div>
                <div class="col-md-2"><label class="text-muted">中文名</label><p>${Fmt.s(dec, "given_name")}</p></div>
                <div class="col-md-2"><label class="text-muted">性别</label><p>${Fmt.s(dec, "gender")}</p></div>
                <div class="col-md-3"><label class="text-muted">出生日期</label><p>${Fmt.s(dec, "birth_date")}</p></div>
                <div class="col-md-3"><label class="text-muted">身份证号</label><p><code>${Fmt.s(dec, "id_number")}</code></p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-4"><label class="text-muted">户口所在地</label><p>${Fmt.s(dec, "residence")}</p></div>
                <div class="col-md-2"><label class="text-muted">政治面貌</label><p>${Fmt.s(dec, "political_status")}</p></div>
                <div class="col-md-3"><label class="text-muted">工作单位</label><p>${Fmt.s(dec, "work_unit")}</p></div>
                <div class="col-md-3"><label class="text-muted">人事主管单位</label><p>${Fmt.s(dec, "supervisor_unit")}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-3"><label class="text-muted">报送单位名称</label><p>${Fmt.s(dec, "submit_unit_name")}</p></div>
                <div class="col-md-2"><label class="text-muted">报送单位类别</label><p>${Fmt.s(dec, "submit_unit_type")}</p></div>
                <div class="col-md-2"><label class="text-muted">联系人</label><p>${Fmt.s(dec, "submit_contact")}</p></div>
                <div class="col-md-2"><label class="text-muted">联系电话</label><p>${Fmt.s(dec, "submit_phone")}</p></div>
                <div class="col-md-3"><label class="text-muted">入库批号</label><p>${Fmt.s(dec, "batch_no")}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-3"><label class="text-muted">撤控日期</label><p>${Fmt.s(dec, "decontrol_date", "-")}</p></div>
                <div class="col-md-3"><label class="text-muted">证件移交日期</label><p>${Fmt.s(dec, "cert_handover_date", "-")}</p></div>
                <div class="col-md-6"><label class="text-muted">撤控原因</label><p>${Fmt.s(dec, "reason")}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-12"><label class="text-muted">录入时间</label><p>${ctx.localTime(dec.get("created_at"))}</p></div>
            </div>
        </div>
    </div>
`)
