@import com.potms.web.Fmt
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param List<Map<String, Object>> travels
@template.layout(ctx = ctx, title = "选择出国申请", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-vector-pen"></i> 证件领用登记 — 选择出国申请</h4>
        <a href="/issuance" class="btn btn-secondary">返回列表</a>
    </div>

    <%-- 证件是为某一次已批准的出行借出的，没有申请就没有借出的理由。
         与其给一个能不填的表单，不如先把申请选出来。 --%>
    <div class="alert alert-info py-2">
        <i class="bi bi-info-circle"></i> 证件领用须对应一条出国（境）申请。请先选择申请，再登记领用与签名。
    </div>

    <div class="table-card"><div class="table-responsive">
        <table class="table table-hover mb-0">
            <thead class="table-light"><tr>
                <th>申请</th><th>姓名</th><th>单位</th><th>地点、证照</th>
                <th>计划出行日期</th><th>批准日期</th><th>是否做证</th><th>操作</th>
            </tr></thead>
            <tbody>
            @if(travels.isEmpty())
                <tr><td colspan="8" class="text-center text-muted py-4">
                    没有可办理领用的出国申请。<br>
                    <small>已取消行程、以及已有未归还领用记录的申请不在此列。</small>
                </td></tr>
            @endif
            @for(var t : travels)
                !{long id = Fmt.n(t, "id");}
                <tr>
                    <td>#${id}</td>
                    <td><strong>${Fmt.s(t, "name")}</strong></td>
                    <td title="${Fmt.s(t, "unit")}">${Fmt.s(t, "unit")}</td>
                    <td title="${Fmt.s(t, "destination_passport")}">${Fmt.s(t, "destination_passport")}</td>
                    <td>${Fmt.s(t, "travel_dates")}</td>
                    <td>${Fmt.s(t, "approval_date", "-")}</td>
                    <td>
                        @if("是".equals(Fmt.s(t, "need_new_passport")))
                            <span class="badge bg-warning text-dark">做证</span>
                        @else
                            否
                        @endif
                    </td>
                    <td><a href="/issuance/new?travel_id=${id}" class="btn btn-sm btn-primary">登记领用</a></td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>
`)
