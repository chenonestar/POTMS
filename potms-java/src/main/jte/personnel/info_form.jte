@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, String> data
@param boolean editing
@param Long infoId
@param List<Helpers.DictOption> educationOpts
@param List<Helpers.DictOption> degreeOpts
@param List<Helpers.DictOption> titleOpts
@param List<Helpers.DictOption> rankOpts
@param List<Helpers.DictOption> politicalOpts
@param List<Helpers.OrgFlatOption> orgOpts
@template.layout(ctx = ctx, title = "备案人员信息登记表", content = @`
    <h4 class="mb-3 mt-3">
        <i class="bi bi-person-plus"></i> ${editing ? "编辑" : "新增"}备案人员信息登记表
    </h4>

    @if(!editing)
        <div class="d-flex align-items-center mb-4" style="max-width:520px;">
            <div class="text-center" style="width:140px;">
                <span class="badge rounded-pill bg-primary" style="width:26px;height:26px;line-height:18px;">1</span>
                <div class="small mt-1 fw-bold text-primary">信息登记表</div>
            </div>
            <div class="flex-fill border-top border-2 mx-2" style="margin-top:-14px;"></div>
            <div class="text-center" style="width:140px;">
                <span class="badge rounded-pill bg-secondary" style="width:26px;height:26px;line-height:18px;">2</span>
                <div class="small mt-1 text-muted">登记备案表</div>
            </div>
        </div>
    @endif

    <%-- 同 filing_form：data-draft 分两支写，避免空值属性误触发草稿逻辑 --%>
    @if(editing)
    <form method="POST" action="/personnel/info/${infoId}/edit" class="needs-validation" novalidate>
    @else
    <form method="POST" action="/personnel/info/new" class="needs-validation" novalidate data-draft="personnel_info">
    @endif
        <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">

        <div class="form-section">
            <h5>基本信息</h5>
            <div class="row g-3">
                <div class="col-md-6">
                    <label class="form-label required">单位</label>
                    <select class="form-select" name="unit" id="orgUnit" required onchange="updateDept()">
                        <option value="">请选择单位</option>
                        @for(var o : orgOpts)
                            @if(o.depth() == 0)
                                <option value="${o.name()}" data-oid="${o.id()}" selected="${Fmt.is(Fmt.v(data, "unit"), o.name())}">${o.name()}</option>
                            @endif
                        @endfor
                    </select>
                    <div class="form-text">单位为顶级组织；部门为其下级。可在“组织架构”中维护层级。</div>
                </div>
                <div class="col-md-6">
                    <label class="form-label required">部门</label>
                    <select class="form-select" name="department" id="orgDept" required>
                        <option value="">请先选择单位</option>
                        @for(var o : orgOpts)
                            @if(o.depth() >= 1)
                                <option value="${o.name()}" data-root="${o.rootId()}" data-oid="${o.id()}" data-depth="${o.depth()}" style="display:none" selected="${Fmt.is(Fmt.v(data, "department"), o.name())}">${o.indent()}${o.name()}</option>
                            @endif
                        @endfor
                        @for(var o : orgOpts)
                            @if(o.depth() == 0)
                                <%-- 无下级部门的单位：回退为可选「单位本身」 --%>
                                <option value="${o.name()}" data-root="${o.id()}" data-oid="${o.id()}" data-depth="0" style="display:none" selected="${Fmt.is(Fmt.v(data, "department"), o.name())}">${o.name()}</option>
                            @endif
                        @endfor
                    </select>
                    <div class="form-text">按层级缩进展示部门 / 子部门，任意层级均可选。</div>
                </div>
                <div class="col-md-4">
                    <label class="form-label required">姓名</label>
                    <input type="text" class="form-control" name="name" value="${Fmt.v(data, "name")}" placeholder="与身份证一致" required>
                </div>
                <div class="col-md-2">
                    <label class="form-label required">性别</label>
                    <select class="form-select" name="gender" required>
                        <option value="">请选择</option>
                        <option value="男" selected="${Fmt.is(Fmt.v(data, "gender"), "男")}">男</option>
                        <option value="女" selected="${Fmt.is(Fmt.v(data, "gender"), "女")}">女</option>
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label required">出生日期</label>
                    <input type="text" class="form-control" name="birth_date" value="${Fmt.v(data, "birth_date")}" placeholder="YYYYMMDD 如19800103" maxlength="8" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label required">参加工作日期</label>
                    <input type="text" class="form-control" name="work_start_date" value="${Fmt.v(data, "work_start_date")}" placeholder="YYYYMMDD" maxlength="8" required>
                </div>
            </div>
            <div class="row g-3 mt-1">
                <div class="col-md-6">
                    <label class="form-label required">身份证号</label>
                    <input type="text" class="form-control" name="id_number" value="${Fmt.v(data, "id_number")}" placeholder="18位，需与出生日期一致" maxlength="18" required>
                    <div class="form-text">系统校验校验位并核对出生日期；登记备案表、明细表将自动带入此身份证。</div>
                </div>
            </div>
        </div>

        <div class="form-section">
            <h5>学历与职称</h5>
            <div class="row g-3">
                <div class="col-md-3">
                    <label class="form-label required">学历</label>
                    <select class="form-select" name="education" required>
                        <option value="">请选择</option>
                        @for(var o : educationOpts)<option value="${o.code()}" selected="${Fmt.is(Fmt.v(data, "education"), o.code())}">${o.value()}</option>@endfor
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label required">学位</label>
                    <select class="form-select" name="degree" required>
                        <option value="">请选择</option>
                        @for(var o : degreeOpts)<option value="${o.code()}" selected="${Fmt.is(Fmt.v(data, "degree"), o.code())}">${o.value()}</option>@endfor
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label required">职称</label>
                    <select class="form-select" name="title" required>
                        <option value="">请选择</option>
                        @for(var o : titleOpts)<option value="${o.code()}" selected="${Fmt.is(Fmt.v(data, "title"), o.code())}">${o.value()}</option>@endfor
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label required">职级</label>
                    <select class="form-select" name="rank" required>
                        <option value="">请选择</option>
                        @for(var o : rankOpts)<option value="${o.code()}" selected="${Fmt.is(Fmt.v(data, "rank"), o.code())}">${o.value()}</option>@endfor
                    </select>
                </div>
            </div>
        </div>

        <div class="form-section">
            <h5>政治面貌与职务</h5>
            <div class="row g-3">
                <div class="col-md-3">
                    <label class="form-label required">政治面貌</label>
                    <select class="form-select" name="political_status" id="politicalStatus" required>
                        <option value="">请选择</option>
                        @for(var o : politicalOpts)<option value="${o.value()}" selected="${Fmt.is(Fmt.v(data, "political_status"), o.value())}">${o.value()}</option>@endfor
                    </select>
                </div>
                <div class="col-md-3">
                    <label class="form-label" id="partyDateLabel">入党日期</label>
                    <input type="text" class="form-control" name="party_join_date" id="partyJoinDate"
                           value="${Fmt.v(data, "party_join_date")}" placeholder="中共党员时必填" maxlength="8">
                </div>
                <div class="col-md-6">
                    <label class="form-label required">职务（岗位名称）</label>
                    <input type="text" class="form-control" name="position" value="${Fmt.v(data, "position")}" required>
                </div>
            </div>
        </div>

        <div class="mt-3 mb-4">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> 保存</button>
            <a href="/personnel" class="btn btn-secondary">取消</a>
        </div>
    </form>
`, scripts = @`
    <script>
    // 单位→部门树状级联：显示该单位下的所有部门/子部门（按层级缩进），任意层级可选
    function updateDept(preserve) {
        var unitSel = document.getElementById('orgUnit');
        var deptSel = document.getElementById('orgDept');
        var keep = preserve ? deptSel.value : '';
        var oid = unitSel.options[unitSel.selectedIndex].getAttribute('data-oid') || '';
        var opts = deptSel.options, firstReal = -1, selfIdx = -1, realCount = 0;
        for (var i = 0; i < opts.length; i++) {
            if (!opts[i].value) { continue; }
            var belongs = ((opts[i].getAttribute('data-root') || '') === oid);
            var isSelf = (opts[i].getAttribute('data-depth') === '0');
            if (belongs && !isSelf) {
                opts[i].style.display = '';
                if (firstReal < 0) firstReal = i;
                realCount++;
            } else {
                opts[i].style.display = 'none';
                if (belongs && isSelf) selfIdx = i;
            }
        }
        if (realCount === 0 && selfIdx >= 0) {
            opts[selfIdx].style.display = '';
            firstReal = selfIdx;
        }
        if (keep) deptSel.value = keep;
        var cur = deptSel.selectedIndex;
        var valid = cur > 0 && opts[cur].style.display !== 'none';
        if (!valid) deptSel.selectedIndex = firstReal >= 0 ? firstReal : 0;
    }
    document.addEventListener('DOMContentLoaded', function() {
        if (document.getElementById('orgUnit').value) updateDept(true);
    });
    // 入党日期联动：中共党员/预备党员时显示
    (function() {
        var sel = document.getElementById('politicalStatus');
        var input = document.getElementById('partyJoinDate');
        var label = document.getElementById('partyDateLabel');
        function toggle() {
            var v = sel.value;
            var show = v === '中共党员' || v === '中共预备党员';
            input.style.display = show ? '' : 'none';
            label.style.display = show ? '' : 'none';
            if (!show) input.value = '';
        }
        sel.addEventListener('change', toggle);
        toggle();
    })();
    </script>
`)
