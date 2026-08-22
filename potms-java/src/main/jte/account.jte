@param com.potms.web.Ctx ctx
@param String username
@param String fullName
@param long legacyTotal
<%-- 分段与文案对齐 Python 版 templates/account.html：三段（登录账户 / 修改密码 /
   安全验证），字段名与提交契约完全一致。这里不是自由发挥的地方——五版界面要一致。 --%>
@template.layout(ctx = ctx, title = "账户设置", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-person-gear"></i> 账户设置</h4>

    <div class="row">
        <div class="col-lg-6">
            <form method="POST" action="/account" class="needs-validation" novalidate>
                <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">

                <div class="form-section">
                    <h5>登录账户</h5>
                    <label class="form-label required">用户名</label>
                    <input type="text" class="form-control" name="new_username" value="${username}" minlength="3" required autocomplete="username">
                    <div class="form-text">修改后需使用新用户名登录。</div>

                    <label class="form-label mt-3">姓名</label>
                    <input type="text" class="form-control" name="new_full_name" value="${fullName}" maxlength="30" placeholder="例如：张建国" autocomplete="name">
                    <div class="form-text">
                        <strong>单据与打印件上的「经办人」显示这个名字</strong>，不是登录账号。
                        留空则退回显示登录账号。<br>
                        操作日志仍按登录账号记录——账号是身份标识，姓名可以改，日志只记姓名的话改名后就对不上人了。
                    </div>
                </div>

                <div class="form-section">
                    <h5>修改密码 <small class="text-muted fw-normal">（不修改请留空）</small></h5>
                    <div class="mb-2">
                        <label class="form-label">新密码</label>
                        <input type="password" class="form-control" name="new_password" minlength="6" placeholder="至少 6 位；留空表示不修改" autocomplete="new-password">
                    </div>
                    <div class="mb-1">
                        <label class="form-label">确认新密码</label>
                        <input type="password" class="form-control" name="confirm_password" autocomplete="new-password">
                    </div>
                    <div class="form-text">修改密码后需使用新密码重新登录。</div>
                </div>

                <div class="form-section">
                    <h5>安全验证</h5>
                    <label class="form-label required">当前密码</label>
                    <input type="password" class="form-control" name="current_password" required placeholder="请输入当前密码以确认身份" autocomplete="current-password">
                    <div class="form-text">任何修改都需要先验证当前密码。</div>
                </div>

                <div class="mt-3 mb-4">
                    <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> 保存</button>
                    <a href="/" class="btn btn-secondary">取消</a>
                </div>
            </form>

            @if(legacyTotal > 0)
            <div class="form-section border-warning mt-4">
                <h5><i class="bi bi-clock-history"></i> 历史经办人回填</h5>
                <p class="mb-2">
                    业务记录里还有 <strong class="text-danger">${legacyTotal}</strong> 条
                    把登录账号「${username}」当作经办人。
                    @if(!fullName.isEmpty() && !fullName.equals(username))
                    可一次性改成「<strong>${fullName}</strong>」。
                    @else
                    <span class="text-muted">请先填写并保存姓名，再执行回填。</span>
                    @endif
                </p>
                <ul class="small text-muted">
                    <li>只改业务表（信息表 / 备案表 / 证照 / 出行 / 撤控 / 证件领用）的经办人字段。</li>
                    <li><strong>操作日志不动</strong>——审计需要登录账号。</li>
                    <li>执行前会自动备份一次 data.db 到 backup 目录，整件事也会记进操作日志。</li>
                    <li><strong>此操作不可撤销</strong>，请确认姓名填写正确后再点。</li>
                </ul>
                <form method="POST" action="/account/backfill-operator"
                      onsubmit="return confirm('确定把 ${legacyTotal} 条历史记录的经办人改为「${fullName}」吗？此操作不可撤销。');">
                    <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                    <button type="submit" class="btn btn-warning"
                            disabled="${fullName.isEmpty() || fullName.equals(username)}">
                        <i class="bi bi-arrow-repeat"></i> 回填这 ${legacyTotal} 条记录
                    </button>
                </form>
            </div>
            @endif
        </div>
    </div>
`)
