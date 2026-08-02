@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, String> data
@param boolean editing
@param Long certId
@param List<Helpers.PersonOption> people
!{String action = editing ? "/certificate/" + certId + "/edit" : "/certificate/new";
  String selected = Fmt.v(data, "personnel_filing_id");}
@template.layout(ctx = ctx, title = "证照登记表", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-card-checklist"></i> ${editing ? "编辑" : "新增"}因私出国（境）备案人员证照登记表</h4>

    @* data-draft 分两支写：JTE 禁止属性名位置出现表达式，且空值属性会误触发草稿逻辑 *@
    @if(editing)
    <form method="POST" action="${action}" class="needs-validation" novalidate>
    @else
    <form method="POST" action="${action}" class="needs-validation" novalidate data-draft="certificate">
    @endif
        <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">

        <div class="form-section">
            <h5>选择备案人员</h5>
            <p class="text-muted small mb-2">选择人员后，单位/部门/姓名自动从备案信息带入。</p>
            <div class="row g-3">
                <div class="col-md-5">
                    <label class="form-label">搜索备案人员</label>
                    <input type="text" class="form-control" id="personSearch" placeholder="输入姓名 / 身份证号 / 单位 过滤"
                           oninput="filterPersons('personSearch','personSelect')" autocomplete="off">
                </div>
                <div class="col-md-5">
                    <label class="form-label required">备案人员</label>
                    <select class="form-select" name="personnel_filing_id" id="personSelect" required onchange="autoFillCert()" size="6">
                        <option value="">请选择备案人员</option>
                        @for(var p : people)
                            <option value="${p.id()}" data-unit="${p.unit()}" data-dept="${p.department()}" data-name="${p.name()}"
                                    data-search="${(p.name() + p.idNumber() + p.unit()).toLowerCase()}"
                                    selected="${Fmt.is(selected, String.valueOf(p.id()))}">${p.fullName()}</option>
                        @endfor
                    </select>
                </div>
            </div>
            <div class="row g-3 mt-2">
                <div class="col-md-3">
                    <label class="form-label">单位 <span class="text-muted">(自动带入)</span></label>
                    <input type="text" class="form-control" name="unit" id="certUnit" value="${Fmt.v(data, "unit")}" readonly>
                </div>
                <div class="col-md-3">
                    <label class="form-label">部门 <span class="text-muted">(自动带入)</span></label>
                    <input type="text" class="form-control" name="department" id="certDept" value="${Fmt.v(data, "department")}" readonly>
                </div>
                <div class="col-md-3">
                    <label class="form-label">姓名 <span class="text-muted">(自动带入)</span></label>
                    <input type="text" class="form-control" name="name" id="certName" value="${Fmt.v(data, "name")}" readonly>
                </div>
            </div>
        </div>

        <div class="form-section"><h5>普通护照</h5><div class="row g-3">
            <div class="col-md-4"><label class="form-label">证件号</label><input type="text" class="form-control" name="passport_no" value="${Fmt.v(data, "passport_no")}"></div>
            <div class="col-md-4"><label class="form-label">有效日期</label><input type="text" class="form-control" name="passport_expiry" value="${Fmt.v(data, "passport_expiry")}" placeholder="YYYYMMDD" maxlength="8"></div>
            <div class="col-md-4"><label class="form-label">上交日期</label><input type="text" class="form-control" name="passport_submit_date" value="${Fmt.v(data, "passport_submit_date")}" placeholder="YYYYMMDD" maxlength="8"></div>
        </div></div>

        <div class="form-section"><h5>往来港澳通行证</h5><div class="row g-3">
            <div class="col-md-4"><label class="form-label">证件号</label><input type="text" class="form-control" name="hm_pass_no" value="${Fmt.v(data, "hm_pass_no")}"></div>
            <div class="col-md-4"><label class="form-label">有效日期</label><input type="text" class="form-control" name="hm_pass_expiry" value="${Fmt.v(data, "hm_pass_expiry")}" placeholder="YYYYMMDD" maxlength="8"></div>
            <div class="col-md-4"><label class="form-label">上交日期</label><input type="text" class="form-control" name="hm_pass_submit_date" value="${Fmt.v(data, "hm_pass_submit_date")}" placeholder="YYYYMMDD" maxlength="8"></div>
        </div></div>

        <div class="form-section"><h5>大陆居民往来台湾通行证</h5><div class="row g-3">
            <div class="col-md-4"><label class="form-label">证件号</label><input type="text" class="form-control" name="tw_pass_no" value="${Fmt.v(data, "tw_pass_no")}"></div>
            <div class="col-md-4"><label class="form-label">有效日期</label><input type="text" class="form-control" name="tw_pass_expiry" value="${Fmt.v(data, "tw_pass_expiry")}" placeholder="YYYYMMDD" maxlength="8"></div>
            <div class="col-md-4"><label class="form-label">上交日期</label><input type="text" class="form-control" name="tw_pass_submit_date" value="${Fmt.v(data, "tw_pass_submit_date")}" placeholder="YYYYMMDD" maxlength="8"></div>
        </div></div>

        <div class="mt-3 mb-4">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> 保存</button>
            <a href="/certificate" class="btn btn-secondary">取消</a>
        </div>
    </form>
`, scripts = @`
    <script>
    function autoFillCert() {
        var sel = document.getElementById('personSelect');
        var opt = sel.options[sel.selectedIndex];
        document.getElementById('certUnit').value = opt.getAttribute('data-unit') || '';
        document.getElementById('certDept').value = opt.getAttribute('data-dept') || '';
        document.getElementById('certName').value = opt.getAttribute('data-name') || '';
    }
    function filterPersons(searchId, selectId) {
        var q = document.getElementById(searchId).value.trim().toLowerCase();
        var sel = document.getElementById(selectId);
        for (var i = 0; i < sel.options.length; i++) {
            var o = sel.options[i];
            if (!o.value) continue;
            var hay = (o.getAttribute('data-search') || o.text).toLowerCase();
            o.hidden = q !== '' && hay.indexOf(q) === -1;
        }
    }
    // 填写证件号时，有效日期/上交日期变为必填（显示 * 并触发校验）
    function bindCertRequired(noName, expName, subName) {
        var no = document.querySelector('[name=' + noName + ']');
        var exp = document.querySelector('[name=' + expName + ']');
        var sub = document.querySelector('[name=' + subName + ']');
        if (!no || !exp || !sub) return;
        function upd() {
            var on = no.value.trim() !== '';
            [exp, sub].forEach(function (el) {
                el.required = on;
                var lbl = el.previousElementSibling;
                if (lbl && lbl.classList.contains('form-label')) lbl.classList.toggle('required', on);
            });
        }
        no.addEventListener('input', upd);
        upd();
    }
    document.addEventListener('DOMContentLoaded', function() {
        if (document.getElementById('personSelect').value) autoFillCert();
        bindCertRequired('passport_no', 'passport_expiry', 'passport_submit_date');
        bindCertRequired('hm_pass_no', 'hm_pass_expiry', 'hm_pass_submit_date');
        bindCertRequired('tw_pass_no', 'tw_pass_expiry', 'tw_pass_submit_date');
    });
    </script>
`)
