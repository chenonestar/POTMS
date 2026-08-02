@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@param com.potms.web.Ctx ctx
@param java.util.Map<String, String> data
@param long filingId
@param List<Helpers.DictOption> politicalOpts
@param List<Helpers.DictOption> supervisorOpts
@param List<Helpers.DictOption> unitTypeOpts
@param List<Helpers.SubmitUnit> submitUnits
@template.layout(ctx = ctx, title = "撤控备案", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-arrow-repeat"></i> 因私事出国（境）人员撤控备案表</h4>
    <div class="alert alert-warning small py-2">
        提交后，该人员的备案状态将标记为「已撤控」。若日后重新备案，系统会自动关联新旧记录。
    </div>

    <form method="POST" action="/decontrol/new?filing_id=${filingId}" class="needs-validation" novalidate>
        <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">

        <div class="form-section">
            <h5>身份信息 <small class="text-muted">(自备案表带入)</small></h5>
            <div class="row g-3">
                <div class="col-md-2"><label class="form-label required">中文姓</label><input type="text" class="form-control" name="surname" value="${Fmt.v(data, "surname")}" required></div>
                <div class="col-md-3"><label class="form-label required">中文名</label><input type="text" class="form-control" name="given_name" value="${Fmt.v(data, "given_name")}" required></div>
                <div class="col-md-2"><label class="form-label required">性别</label>
                    <select class="form-select" name="gender" required>
                        <option value="男" selected="${Fmt.is(Fmt.v(data, "gender"), "男")}">男</option>
                        <option value="女" selected="${Fmt.is(Fmt.v(data, "gender"), "女")}">女</option>
                    </select>
                </div>
                <div class="col-md-2"><label class="form-label required">出生日期</label><input type="text" class="form-control" name="birth_date" value="${Fmt.v(data, "birth_date")}" maxlength="8" required></div>
                <div class="col-md-3"><label class="form-label required">身份证号</label><input type="text" class="form-control" name="id_number" value="${Fmt.v(data, "id_number")}" maxlength="18" required></div>
            </div>
            <div class="row g-3 mt-1">
                <div class="col-md-5"><label class="form-label required">户口所在地</label><input type="text" class="form-control" name="residence" value="${Fmt.v(data, "residence")}" required></div>
                <div class="col-md-3"><label class="form-label required">政治面貌</label>
                    <select class="form-select" name="political_status" required>
                        <option value="">请选择</option>
                        @for(var o : politicalOpts)<option value="${o.value()}" selected="${Fmt.is(Fmt.v(data, "political_status"), o.value())}">${o.value()}</option>@endfor
                    </select>
                </div>
                <div class="col-md-4"><label class="form-label required">工作单位</label><input type="text" class="form-control" name="work_unit" value="${Fmt.v(data, "work_unit")}" required></div>
            </div>
        </div>

        <div class="form-section">
            <h5>报送信息</h5>
            <div class="row g-3">
                <div class="col-md-4"><label class="form-label required">人事主管单位</label>
                    <select class="form-select" name="supervisor_unit" required>
                        <option value="">请选择</option>
                        @for(var o : supervisorOpts)<option value="${o.value()}" selected="${Fmt.is(Fmt.v(data, "supervisor_unit"), o.value())}">${o.value()}</option>@endfor
                    </select>
                </div>
                <div class="col-md-4"><label class="form-label required">报送单位名称</label>
                    <select class="form-select" name="submit_unit_name" id="submitUnit" required onchange="fillSubmitUnit()">
                        <option value="">请选择</option>
                        @for(var u : submitUnits)
                            <option value="${u.name()}" data-contact="${u.contact() == null ? "" : u.contact()}" data-phone="${u.phone() == null ? "" : u.phone()}"
                                    selected="${Fmt.is(Fmt.v(data, "submit_unit_name"), u.name())}">${u.name()}</option>
                        @endfor
                    </select>
                    <div class="form-text">在「系统设置 → 报送单位」中维护。</div>
                </div>
                <div class="col-md-4"><label class="form-label required">报送单位类别</label>
                    <select class="form-select" name="submit_unit_type" required>
                        <option value="">请选择</option>
                        @for(var o : unitTypeOpts)<option value="${o.code()}" selected="${Fmt.is(Fmt.v(data, "submit_unit_type"), o.code())}">${o.value()}</option>@endfor
                    </select>
                </div>
            </div>
            <div class="row g-3 mt-1">
                <div class="col-md-3"><label class="form-label required">联系人</label><input type="text" class="form-control" name="submit_contact" id="suContact" value="${Fmt.v(data, "submit_contact")}" required></div>
                <div class="col-md-3"><label class="form-label required">联系电话</label><input type="text" class="form-control" name="submit_phone" id="suPhone" value="${Fmt.v(data, "submit_phone")}" required></div>
                <div class="col-md-3"><label class="form-label required">入库批号</label><input type="text" class="form-control" name="batch_no" value="${Fmt.v(data, "batch_no")}" placeholder="如 2026-01" required></div>
                <div class="col-md-3"><label class="form-label required">撤控日期</label><input type="text" class="form-control" name="decontrol_date" value="${Fmt.v(data, "decontrol_date")}" placeholder="YYYYMMDD" maxlength="8" required></div>
            </div>
            <div class="row g-3 mt-1">
                <div class="col-md-3"><label class="form-label">证件移交日期</label><input type="text" class="form-control" name="cert_handover_date" value="${Fmt.v(data, "cert_handover_date")}" placeholder="YYYYMMDD" maxlength="8"></div>
                <div class="col-md-9"><label class="form-label required">撤控原因</label><input type="text" class="form-control" name="reason" value="${Fmt.v(data, "reason")}" placeholder="如：岗位调整 / 退休 / 离职" required></div>
            </div>
        </div>

        <div class="mt-3 mb-4">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> 提交撤控</button>
            <a href="/personnel/${filingId}" class="btn btn-secondary">取消</a>
        </div>
    </form>
`, scripts = @`
    <script>
    // 选报送单位后自动带出联系人/电话
    function fillSubmitUnit() {
        var sel = document.getElementById('submitUnit');
        var opt = sel.options[sel.selectedIndex];
        if (!opt || !opt.value) return;
        var c = opt.getAttribute('data-contact') || '';
        var p = opt.getAttribute('data-phone') || '';
        if (c) document.getElementById('suContact').value = c;
        if (p) document.getElementById('suPhone').value = p;
    }
    </script>
`)
