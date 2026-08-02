@import com.potms.web.Fmt
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, Object> filing
@param Map<String, Object> info
@param Map<String, Object> successor
@param Map<String, Object> predecessor
@param Map<String, String> infoLabels
!{long fid = Fmt.n(filing, "id");
  String fullName = Fmt.s(filing, "surname") + Fmt.s(filing, "given_name");
  boolean active = Fmt.eq(filing, "status", "active");}
@template.layout(ctx = ctx, title = fullName + " - 备案详情", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-person-vcard"></i> 备案人员详情</h4>
        <div class="no-print">
            <a href="/personnel" class="btn btn-outline-secondary btn-sm"><i class="bi bi-arrow-left"></i> 返回列表</a>
            <a href="/print/filing/${fid}" class="btn btn-outline-primary btn-sm" target="_blank"><i class="bi bi-printer"></i> 打印备案表</a>
            @if(info != null)
                <a href="/print/info/${Fmt.n(info, "id")}" class="btn btn-outline-primary btn-sm" target="_blank"><i class="bi bi-printer"></i> 打印信息表</a>
            @endif
            @if(active)
                <a href="/personnel/filing/${fid}/edit" class="btn btn-warning btn-sm"><i class="bi bi-pencil"></i> 编辑备案表</a>
            @endif
            @if(info != null)
                <a href="/personnel/info/${Fmt.n(info, "id")}/edit" class="btn btn-warning btn-sm"><i class="bi bi-pencil-square"></i> 编辑信息表</a>
            @endif
        </div>
    </div>

    @if(predecessor != null || successor != null)
        <div class="alert alert-info d-flex align-items-center">
            <i class="bi bi-arrow-repeat me-2"></i>
            <div>
                @if(predecessor != null)
                    本记录为<strong>撤控后重报</strong>，原备案记录：<a href="/personnel/${Fmt.n(predecessor, "id")}">${Fmt.s(predecessor, "surname")}${Fmt.s(predecessor, "given_name")} #${Fmt.n(predecessor, "id")}</a>（${ctx.localDate(predecessor.get("created_at"))}）。
                @endif
                @if(successor != null)
                    本记录已被<strong>重报替代</strong>，新备案记录：<a href="/personnel/${Fmt.n(successor, "id")}">${Fmt.s(successor, "surname")}${Fmt.s(successor, "given_name")} #${Fmt.n(successor, "id")}</a>（${ctx.localDate(successor.get("created_at"))}）。
                @endif
            </div>
        </div>
    @endif

    <div class="card mb-3">
        <div class="card-header"><strong>因私事出国（境）人员登记备案表</strong></div>
        <div class="card-body">
            <div class="row">
                <div class="col-md-3"><label class="text-muted">中文姓</label><p>${Fmt.s(filing, "surname")}</p></div>
                <div class="col-md-3"><label class="text-muted">中文名</label><p>${Fmt.s(filing, "given_name")}</p></div>
                <div class="col-md-2"><label class="text-muted">性别</label><p>${Fmt.s(filing, "gender")}</p></div>
                <div class="col-md-2"><label class="text-muted">出生日期</label><p>${Fmt.s(filing, "birth_date")}</p></div>
                <div class="col-md-2"><label class="text-muted">身份证号</label><p><code>${Fmt.s(filing, "id_number")}</code></p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-4"><label class="text-muted">户口所在地</label><p>${Fmt.s(filing, "residence")}</p></div>
                <div class="col-md-2"><label class="text-muted">政治面貌</label><p>${Fmt.s(filing, "political_status")}</p></div>
                <div class="col-md-4"><label class="text-muted">工作单位</label><p>${Fmt.s(filing, "work_unit")}</p></div>
                <div class="col-md-2"><label class="text-muted">职务（级）或职称</label><p>${Fmt.s(filing, "position_or_title")}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-4"><label class="text-muted">人事主管单位</label><p>${Fmt.s(filing, "supervisor_unit")}</p></div>
                <div class="col-md-2"><label class="text-muted">标记</label><p><span class="badge ${Fmt.eq(filing, "tag", "新增") ? "bg-primary" : "bg-warning"}">${Fmt.s(filing, "tag")}</span></p></div>
                <div class="col-md-2"><label class="text-muted">已告知本人</label><p>${Fmt.s(filing, "informed")}</p></div>
                <div class="col-md-4"><label class="text-muted">备注</label><p>${Fmt.s(filing, "remarks", "-")}</p></div>
            </div>
            <div class="row mt-2">
                <div class="col-md-12"><label class="text-muted">录入时间</label><p>${ctx.localTime(filing.get("created_at"))}</p></div>
            </div>
        </div>
    </div>

    @if(info != null)
        <div class="card mb-4">
            <div class="card-header"><strong>备案人员信息登记表</strong></div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-4"><label class="text-muted">单位</label><p>${Fmt.s(info, "unit")}</p></div>
                    <div class="col-md-4"><label class="text-muted">部门</label><p>${Fmt.s(info, "department")}</p></div>
                    <div class="col-md-4"><label class="text-muted">姓名</label><p>${Fmt.s(info, "name")}</p></div>
                </div>
                <div class="row mt-2">
                    <div class="col-md-2"><label class="text-muted">性别</label><p>${Fmt.s(info, "gender")}</p></div>
                    <div class="col-md-2"><label class="text-muted">出生日期</label><p>${Fmt.s(info, "birth_date")}</p></div>
                    <div class="col-md-3"><label class="text-muted">身份证号</label><p><code>${Fmt.s(info, "id_number", "-")}</code></p></div>
                    <div class="col-md-2"><label class="text-muted">参加工作日期</label><p>${Fmt.s(info, "work_start_date", "-")}</p></div>
                    <div class="col-md-3"><label class="text-muted">学历 / 学位</label><p>${infoLabels.getOrDefault("education", "-")} / ${infoLabels.getOrDefault("degree", "-")}</p></div>
                </div>
                <div class="row mt-2">
                    <div class="col-md-2"><label class="text-muted">职称</label><p>${infoLabels.getOrDefault("title", "-")}</p></div>
                    <div class="col-md-2"><label class="text-muted">职级</label><p>${infoLabels.getOrDefault("rank", "-")}</p></div>
                    <div class="col-md-2"><label class="text-muted">政治面貌</label><p>${Fmt.s(info, "political_status")}</p></div>
                    <div class="col-md-2"><label class="text-muted">入党日期</label><p>${Fmt.s(info, "party_join_date", "-")}</p></div>
                    <div class="col-md-4"><label class="text-muted">职务（岗位名称）</label><p>${Fmt.s(info, "position")}</p></div>
                </div>
            </div>
        </div>
    @endif
`)
