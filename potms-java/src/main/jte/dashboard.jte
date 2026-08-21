@import com.potms.web.DashboardController.*
@import java.util.List
@param com.potms.web.Ctx ctx
@param long totalActive
@param long totalDecontrolled
@param long totalCertificates
@param long totalTravel
@param long certInStorage
@param long certInUse
@param long certOverdue
@param List<OverdueItem> overdue
@param List<ExpiringItem> expiring
@param List<RecentTrip> recentTravel
@param long issPending
@param long issThisMonth
@param String backupDate
@template.layout(ctx = ctx, title = "首页仪表盘 - 因私出国（境）审批管理", content = @`
    <div class="d-flex justify-content-between align-items-center mt-3 mb-3">
        <h4 class="mb-0">首页仪表盘</h4>
        <form method="POST" action="/backup/now" class="d-flex align-items-center gap-2">
            <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
            <span class="text-muted small">
                @if(backupDate.isEmpty())尚无备份@else最近备份：${backupDate}@endif
            </span>
            <button type="submit" class="btn btn-sm btn-outline-secondary">
                <i class="bi bi-hdd"></i> 立即备份
            </button>
        </form>
    </div>

    <%-- 姓名没填时提示一次。不强制、不挡流程——只是提醒单据上会显示登录账号。 --%>
    @if(ctx.operatorName() == null || ctx.operatorName().equals(ctx.user()))
    <div class="alert alert-warning alert-dismissible fade show py-2 small" role="alert">
        <i class="bi bi-person-exclamation"></i>
        尚未填写<strong>姓名</strong>，证件领用等单据与打印件上的「经办人」会显示登录账号
        「${ctx.user()}」。
        <a href="/account" class="alert-link">去账户设置补全</a>。
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>
    @endif

    <div class="row g-3">
        <div class="col-6 col-md-3">
            <a class="card text-decoration-none h-100" href="/personnel">
                <div class="card-body">
                    <div class="text-muted small">在控备案人员</div>
                    <div class="fs-3 fw-bold">${totalActive}</div>
                </div>
            </a>
        </div>
        <div class="col-6 col-md-3">
            <a class="card text-decoration-none h-100" href="/decontrol">
                <div class="card-body">
                    <div class="text-muted small">已撤控人员</div>
                    <div class="fs-3 fw-bold">${totalDecontrolled}</div>
                </div>
            </a>
        </div>
        <div class="col-6 col-md-3">
            <a class="card text-decoration-none h-100" href="/certificate">
                <div class="card-body">
                    <div class="text-muted small">证照登记</div>
                    <div class="fs-3 fw-bold">${totalCertificates}</div>
                </div>
            </a>
        </div>
        <div class="col-6 col-md-3">
            <a class="card text-decoration-none h-100" href="/travel">
                <div class="card-body">
                    <div class="text-muted small">出国（境）明细</div>
                    <div class="fs-3 fw-bold">${totalTravel}</div>
                </div>
            </a>
        </div>
    </div>

    <div class="row g-3 mt-1">
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header">证件状态</div>
                <ul class="list-group list-group-flush">
                    <li class="list-group-item d-flex justify-content-between">
                        <span>在库（未领用）</span><span class="badge bg-secondary">${certInStorage}</span>
                    </li>
                    <li class="list-group-item d-flex justify-content-between">
                        <span>使用中（已领未还）</span><span class="badge bg-primary">${certInUse}</span>
                    </li>
                    <li class="list-group-item d-flex justify-content-between">
                        <span>逾期未还</span>
                        <span class="badge ${certOverdue > 0 ? "bg-danger" : "bg-success"}">${certOverdue}</span>
                    </li>
                </ul>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header">证件领用</div>
                <ul class="list-group list-group-flush">
                    <li class="list-group-item d-flex justify-content-between">
                        <span>待归还</span><span class="badge bg-primary">${issPending}</span>
                    </li>
                    <li class="list-group-item d-flex justify-content-between">
                        <span>本月领用</span><span class="badge bg-secondary">${issThisMonth}</span>
                    </li>
                </ul>
                <div class="card-footer bg-white">
                    <a href="/issuance" class="small text-decoration-none">查看领用登记 →</a>
                </div>
            </div>
        </div>

    <div class="row g-3 mt-1">
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header text-danger">
                    <i class="bi bi-exclamation-triangle"></i> 证件逾期未还
                </div>
                <div class="table-responsive">
                    <table class="table table-sm mb-0">
                        <thead><tr><th>姓名</th><th>应还日期</th><th>行程</th></tr></thead>
                        <tbody>
                        @if(overdue.isEmpty())
                            <tr><td colspan="3" class="text-muted small">无逾期记录</td></tr>
                        @endif
                        @for(var o : overdue)
                            <tr>
                                <td>${o.name()}</td>
                                <td class="text-danger">${o.deadline()}</td>
                                <td>${o.tripStatus().equals("cancelled") ? "已取消" : "正常"}</td>
                            </tr>
                        @endfor
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        <div class="col-md-6">
            <div class="card h-100">
                <div class="card-header text-warning-emphasis">
                    <i class="bi bi-hourglass-split"></i> 证照 30 天内到期
                </div>
                <div class="table-responsive">
                    <table class="table table-sm mb-0">
                        <thead><tr><th>姓名</th><th>证件</th><th>有效期至</th></tr></thead>
                        <tbody>
                        @if(expiring.isEmpty())
                            <tr><td colspan="3" class="text-muted small">无临期证照</td></tr>
                        @endif
                        @for(var e : expiring)
                            <tr><td>${e.name()}</td><td>${e.type()}</td><td>${e.expiry()}</td></tr>
                        @endfor
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <div class="row g-3 mt-1 mb-4">
        <div class="col-12">
            <div class="card h-100">
                <div class="card-header">近期出行</div>
                <ul class="list-group list-group-flush">
                    @if(recentTravel.isEmpty())<li class="list-group-item text-muted small">暂无数据</li>@endif
                    @for(var t : recentTravel)
                        <li class="list-group-item">
                            <div class="d-flex justify-content-between">
                                <span>${t.name()}</span>
                                <span class="text-muted small">${t.destination()}</span>
                            </div>
                            <div class="text-muted small">${t.travelDates()}</div>
                        </li>
                    @endfor
                </ul>
            </div>
        </div>
    </div>
`)
