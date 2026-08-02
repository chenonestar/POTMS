@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, String> data
@param Map<String, Object> travel
@param List<Helpers.PersonOption> people
@param List<Helpers.DictOption> certTypeOpts
!{String selected = Fmt.v(data, "personnel_filing_id");
  java.util.Set<String> picked = new java.util.HashSet<>(
      java.util.Arrays.asList(Fmt.v(data, "cert_types").split(",")));
  boolean locked = travel != null;}
@template.layout(ctx = ctx, title = "证件领用登记", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-vector-pen"></i> 证件领用登记</h4>

    @if(travel != null)
        <div class="alert alert-info py-2">
            <i class="bi bi-airplane"></i> 关联出行记录 #${Fmt.n(travel, "id")}：
            <strong>${Fmt.s(travel, "name")}</strong> · ${Fmt.s(travel, "destination_passport")} · 计划出行 ${Fmt.s(travel, "travel_dates")}
            @if(!Fmt.s(travel, "approval_date").isEmpty())· 批准日期 ${Fmt.s(travel, "approval_date")}@endif
        </div>
    @endif

    <form method="POST" action="/issuance/new" id="signForm" class="needs-validation" novalidate>
        <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
        <input type="hidden" name="travel_id" value="${Fmt.v(data, "travel_id")}">

        <div class="form-section">
            <h5>领用人</h5>
            <p class="text-muted small mb-2">选择备案人员后，姓名 / 身份证号自动带入；勾选证件种类后自动填入已登记的证件号码。</p>
            <div class="row g-3">
                <div class="col-md-5">
                    <label class="form-label">搜索备案人员</label>
                    <input type="text" class="form-control" id="personSearch" placeholder="输入姓名 / 身份证号 / 单位 过滤"
                           oninput="filterPersons('personSearch','personSelect')" autocomplete="off">
                </div>
                <div class="col-md-5">
                    <label class="form-label required">备案人员</label>
                    <select class="form-select" name="personnel_filing_id" id="personSelect" required size="6" data-locked="${locked}">
                        <option value="">请选择备案人员</option>
                        @for(var p : people)
                            <option value="${p.id()}" data-name="${p.name()}" data-idno="${p.idNumber()}"
                                    data-cert01="${p.certByType().getOrDefault("01", "")}"
                                    data-cert02="${p.certByType().getOrDefault("02", "")}"
                                    data-cert03="${p.certByType().getOrDefault("03", "")}"
                                    data-search="${(p.name() + p.idNumber() + p.unit()).toLowerCase()}"
                                    selected="${Fmt.is(selected, String.valueOf(p.id()))}">${p.fullName()}</option>
                        @endfor
                    </select>
                </div>
            </div>
            <div class="row g-3 mt-2">
                <div class="col-md-3">
                    <label class="form-label required">领用人姓名</label>
                    <input type="text" class="form-control" name="holder_name" id="holderName" value="${Fmt.v(data, "holder_name")}" required readonly>
                </div>
                <div class="col-md-3">
                    <label class="form-label">身份证号 <span class="text-muted">(自动带入)</span></label>
                    <input type="text" class="form-control" name="id_number" id="holderIdNo" value="${Fmt.v(data, "id_number")}" readonly>
                </div>
            </div>
        </div>

        <div class="form-section">
            <h5>领用证件</h5>
            <div class="row g-3">
                <div class="col-md-6">
                    <label class="form-label required">证件种类（可多选）</label>
                    <div>
                        @for(var o : certTypeOpts)
                            <div class="form-check">
                                <input class="form-check-input cert-type" type="checkbox" name="cert_types" value="${o.code()}" id="ct${o.code()}" checked="${picked.contains(o.code())}">
                                <label class="form-check-label" for="ct${o.code()}">${o.value()}</label>
                            </div>
                        @endfor
                    </div>
                </div>
                <div class="col-md-6">
                    <label class="form-label">证件号码 <span class="text-muted">(按勾选种类自动带入，可修改)</span></label>
                    <input type="text" class="form-control" name="cert_nos" id="certNos" value="${Fmt.v(data, "cert_nos")}" placeholder="多本证件以顿号分隔">
                    <div class="form-text">号码会随记录固化保存，后续修改证照信息不影响本次领用凭证。</div>
                </div>
            </div>
            <div class="row g-3 mt-2">
                <div class="col-md-3">
                    <label class="form-label required">领用日期</label>
                    <input type="text" class="form-control" name="issue_date" value="${Fmt.v(data, "issue_date")}" placeholder="YYYYMMDD" maxlength="8" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label">经办人（发放人）</label>
                    <input type="text" class="form-control" value="${ctx.user()}" readonly>
                </div>
                <div class="col-md-6">
                    <label class="form-label">备注</label>
                    <input type="text" class="form-control" name="remarks" value="${Fmt.v(data, "remarks")}">
                </div>
            </div>
        </div>

        <div class="form-section">
            <h5>领用人签名</h5>
            @template.components.signature_pad(label = "领用人手写签名")
        </div>

        <div class="mt-3 mb-4">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> 保存领用登记</button>
            <a href="/issuance" class="btn btn-secondary">取消</a>
        </div>
    </form>
`, scripts = @`
    <script src="/static/js/signature.js"></script>
    <script>
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
    document.addEventListener('DOMContentLoaded', function () {
        var sel = document.getElementById('personSelect');
        var nameEl = document.getElementById('holderName');
        var idEl = document.getElementById('holderIdNo');
        var nosEl = document.getElementById('certNos');
        function syncCertNos() {
            var o = sel.options[sel.selectedIndex];
            if (!o || !o.value) return;
            var picked = [];
            document.querySelectorAll('.cert-type:checked').forEach(function (cb) {
                var no = o.getAttribute('data-cert' + cb.value);
                if (no) picked.push(no);
            });
            nosEl.value = picked.join('、');
        }
        function fillPerson() {
            var o = sel.options[sel.selectedIndex];
            if (!o || !o.value) { nameEl.value = ''; idEl.value = ''; return; }
            nameEl.value = o.getAttribute('data-name') || '';
            idEl.value = o.getAttribute('data-idno') || '';
            syncCertNos();
        }
        sel.addEventListener('change', fillPerson);
        document.querySelectorAll('.cert-type').forEach(function (cb) {
            cb.addEventListener('change', syncCertNos);
        });
        // 从出行记录带入时人员已确定，禁止改选以免与出行记录脱节
        if (sel.getAttribute('data-locked') === 'true') {
            sel.querySelectorAll('option').forEach(function (op) {
                if (op.value && !op.selected) op.disabled = true;
            });
        }
    });
    </script>
`)
