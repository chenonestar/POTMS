@param com.potms.web.Ctx ctx
@param String username
@template.layout(ctx = ctx, title = "账户设置", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-person-gear"></i> 账户设置</h4>
    <div class="card" style="max-width:560px;">
        <div class="card-body">
            <form method="POST" action="/account" class="needs-validation" novalidate>
                <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                <div class="mb-3">
                    <label class="form-label required">当前密码</label>
                    <input type="password" class="form-control" name="current_password" required autocomplete="current-password">
                    <div class="form-text">修改用户名或密码都需要先验证当前密码。</div>
                </div>
                <hr>
                <div class="mb-3">
                    <label class="form-label">用户名</label>
                    <input type="text" class="form-control" name="new_username" value="${username}" minlength="3">
                </div>
                <div class="mb-3">
                    <label class="form-label">新密码</label>
                    <input type="password" class="form-control" name="new_password" minlength="6" autocomplete="new-password">
                    <div class="form-text">留空表示不修改密码；至少 6 个字符。修改密码后需重新登录。</div>
                </div>
                <div class="mb-3">
                    <label class="form-label">确认新密码</label>
                    <input type="password" class="form-control" name="confirm_password" autocomplete="new-password">
                </div>
                <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> 保存</button>
                <a href="/" class="btn btn-secondary">返回</a>
            </form>
        </div>
    </div>
`)
