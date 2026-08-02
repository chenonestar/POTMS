@import com.potms.web.Fmt
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param String q
@param int total
@param List<Map<String, Object>> personnel
@param List<Map<String, Object>> certificates
@param List<Map<String, Object>> travels
@param List<Map<String, Object>> decontrols
@param List<Map<String, Object>> issuances
@template.layout(ctx = ctx, title = "全局搜索", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-search"></i> 全局搜索</h4>

    <form method="GET" class="card mb-3"><div class="card-body py-2">
        <div class="input-group">
            <input type="text" class="form-control" name="q" value="${q}" placeholder="姓名 / 身份证号 / 证件号 / 目的地 / 撤控原因" autofocus>
            <button class="btn btn-primary"><i class="bi bi-search"></i> 搜索</button>
        </div>
    </div></form>

    @if(q.isEmpty())
        <p class="text-muted">请输入关键词。每个模块最多展示 50 条。</p>
    @else
        <p class="text-muted">关键词「<strong>${q}</strong>」共命中 <strong>${total}</strong> 条。</p>

        <div class="card mb-3">
            <div class="card-header">人员备案 <span class="badge bg-light text-dark">${personnel.size()}</span></div>
            <div class="table-responsive"><table class="table table-sm mb-0">
                <tbody>
                @if(personnel.isEmpty())<tr><td class="text-muted small">无</td></tr>@endif
                @for(var r : personnel)
                    <tr>
                        <td><a href="/personnel/${Fmt.n(r, "id")}">${Fmt.s(r, "surname")}${Fmt.s(r, "given_name")}</a></td>
                        <td><code>${Fmt.maskId(r, "id_number")}</code></td>
                        <td>${Fmt.s(r, "work_unit")}</td>
                        <td>${Fmt.statusLabel(Fmt.s(r, "status"))}</td>
                    </tr>
                @endfor
                </tbody>
            </table></div>
        </div>

        <div class="card mb-3">
            <div class="card-header">证照登记 <span class="badge bg-light text-dark">${certificates.size()}</span></div>
            <div class="table-responsive"><table class="table table-sm mb-0">
                <tbody>
                @if(certificates.isEmpty())<tr><td class="text-muted small">无</td></tr>@endif
                @for(var r : certificates)
                    <tr>
                        <td><a href="/certificate/${Fmt.n(r, "id")}/edit">${Fmt.s(r, "name")}</a></td>
                        <td>${Fmt.s(r, "unit")}</td>
                        <td class="small">${Fmt.s(r, "passport_no", "-")} / ${Fmt.s(r, "hm_pass_no", "-")} / ${Fmt.s(r, "tw_pass_no", "-")}</td>
                    </tr>
                @endfor
                </tbody>
            </table></div>
        </div>

        <div class="card mb-3">
            <div class="card-header">出国明细 <span class="badge bg-light text-dark">${travels.size()}</span></div>
            <div class="table-responsive"><table class="table table-sm mb-0">
                <tbody>
                @if(travels.isEmpty())<tr><td class="text-muted small">无</td></tr>@endif
                @for(var r : travels)
                    <tr>
                        <td><a href="/travel/${Fmt.n(r, "id")}">${Fmt.s(r, "name")}</a></td>
                        <td>${Fmt.s(r, "destination_passport")}</td>
                        <td>${Fmt.s(r, "travel_dates")}</td>
                        <td>${Fmt.eq(r, "trip_status", "cancelled") ? "已取消" : "正常"}</td>
                    </tr>
                @endfor
                </tbody>
            </table></div>
        </div>

        <div class="card mb-3">
            <div class="card-header">证件领用 <span class="badge bg-light text-dark">${issuances.size()}</span></div>
            <div class="table-responsive"><table class="table table-sm mb-0">
                <tbody>
                @if(issuances.isEmpty())<tr><td class="text-muted small">无</td></tr>@endif
                @for(var r : issuances)
                    <tr>
                        <td><a href="/issuance/${Fmt.n(r, "id")}">${Fmt.s(r, "holder_name")}</a></td>
                        <td>${Fmt.s(r, "cert_nos", "-")}</td>
                        <td>${Fmt.s(r, "issue_date")}</td>
                        <td>${Fmt.s(r, "status")}</td>
                    </tr>
                @endfor
                </tbody>
            </table></div>
        </div>

        <div class="card mb-4">
            <div class="card-header">撤控备案 <span class="badge bg-light text-dark">${decontrols.size()}</span></div>
            <div class="table-responsive"><table class="table table-sm mb-0">
                <tbody>
                @if(decontrols.isEmpty())<tr><td class="text-muted small">无</td></tr>@endif
                @for(var r : decontrols)
                    <tr>
                        <td><a href="/decontrol/${Fmt.n(r, "id")}">${Fmt.s(r, "surname")}${Fmt.s(r, "given_name")}</a></td>
                        <td>${Fmt.s(r, "work_unit")}</td>
                        <td>${Fmt.s(r, "reason")}</td>
                        <td>${Fmt.s(r, "decontrol_date", "-")}</td>
                    </tr>
                @endfor
                </tbody>
            </table></div>
        </div>
    @endif
`)
