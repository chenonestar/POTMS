@import com.potms.web.Fmt
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, Object> item
@param Map<String, Object> travel
@param String typeLabels
@param boolean canFix
@param java.util.List<com.potms.web.Helpers.DictOption> certTypeOpts
@param com.potms.service.SealStore.Status issueSeal
@param com.potms.service.SealStore.Status returnSeal
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
                <div class="col-md-4"><label class="text-muted">证件种类</label><p>
                    @if(Fmt.s(item, "cert_types").isEmpty())<span class="badge bg-warning text-dark">待核实</span>
                    @else${typeLabels}@endif
                </p></div>
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
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span>领用人签名</span>
                    @if(issueSeal.present())
                        <%-- 旧版章（签章时间未纳入签名载荷）不能给纯绿：
                           它确实验得过，但那个时间不受保护，与新章不是一回事。 --%>
                        <span class="badge ${!issueSeal.valid() ? "bg-danger"
                                : issueSeal.legacy() ? "bg-warning text-dark" : "bg-success"}">
                            <i class="bi ${issueSeal.valid() ? "bi-shield-check" : "bi-shield-exclamation"}"></i> ${issueSeal.label()}
                        </span>
                    @else
                        <span class="badge bg-secondary">未签章</span>
                    @endif
                </div>
                <div class="card-body text-center">
                    <img src="/issuance/${id}/signature.png?kind=issue" alt="领用签名" class="img-fluid border rounded bg-white">
                </div>
                @if(issueSeal.present())
                    <div class="card-footer small text-muted">
                        国密 SM3withSM2 签章 · ${issueSeal.signedAt()}<br>
                        证书：${issueSeal.certSubject()}（来源 ${issueSeal.source()}）
                    </div>
                @endif
            </div>
        </div>
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span>归还人签名</span>
                    @if(returnSeal.present())
                        <%-- 旧版章（签章时间未纳入签名载荷）不能给纯绿：
                           它确实验得过，但那个时间不受保护，与新章不是一回事。 --%>
                        <span class="badge ${!returnSeal.valid() ? "bg-danger"
                                : returnSeal.legacy() ? "bg-warning text-dark" : "bg-success"}">
                            <i class="bi ${returnSeal.valid() ? "bi-shield-check" : "bi-shield-exclamation"}"></i> ${returnSeal.label()}
                        </span>
                    @endif
                </div>
                <div class="card-body text-center">
                    @if("returned".equals(st))
                        <img src="/issuance/${id}/signature.png?kind=return" alt="归还签名" class="img-fluid border rounded bg-white">
                    @else
                        <p class="text-muted small mb-0 mt-4">尚未归还</p>
                    @endif
                </div>
                @if(returnSeal.present())
                    <div class="card-footer small text-muted">
                        国密 SM3withSM2 签章 · ${returnSeal.signedAt()}<br>
                        证书：${returnSeal.certSubject()}（来源 ${returnSeal.source()}）
                    </div>
                @endif
            </div>
        </div>
    </div>

    <div class="alert ${issueSeal.present() && !issueSeal.valid() ? "alert-danger" : "alert-light border"} small py-2">
        <i class="bi bi-shield-lock"></i>
        签章对「签名图 + 笔迹矢量 + 领用要素」整体计算，任一处被改动都会导致验章失败。
        @if("SELF_SIGNED".equals(issueSeal.source()))
            当前为<strong>自签证书</strong>：可防内部篡改，但不构成《电子签名法》意义上的可靠电子签名；
            换用有资质 CA 签发的证书只需调整配置，业务数据不受影响。
        @endif
    </div>

    <%-- 更正证件种类：只对无签名的记录开放。有签名的记录改种类会让签名名不副实，
         那种情况只能作废重录——但历史回填行本来就没有签名，也无从重录（新建强制签名）。 --%>
    @if(canFix)
        <div class="card mb-4 no-print">
            <div class="card-header"><i class="bi bi-pencil-square"></i> 更正证件种类</div>
            <div class="card-body">
                <p class="text-muted small">本记录无手写签名（历史回填或放宽模式登记），可直接更正证件种类。已签名的记录不可更改。</p>
                <form method="POST" action="/issuance/${id}/cert-types" class="row g-2 align-items-end">
                    <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                    <div class="col-md-6">
                        @for(var o : certTypeOpts)
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="cert_types"
                                       value="${o.code()}" id="fx${o.code()}"
                                       checked="${Fmt.is(Fmt.s(item, "cert_types"), o.code())}">
                                <label class="form-check-label" for="fx${o.code()}">${o.value()}</label>
                            </div>
                        @endfor
                    </div>
                    <div class="col-auto"><button type="submit" class="btn btn-outline-primary">保存更正</button></div>
                </form>
            </div>
        </div>
    @endif

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
