@import com.potms.web.Fmt
@import com.potms.web.Helpers
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param Map<String, String> data
@param boolean editing
@param Long filingId
@param Long infoId
@param List<Helpers.DictOption> politicalOpts
@param List<Helpers.DictOption> supervisorOpts
@param List<Helpers.OrgOption> orgOpts
!{String idNumber = Fmt.v(data, "id_number");
  boolean lockedId = infoId != null && !idNumber.isEmpty();
  String supervisor = Fmt.v(data, "supervisor_unit");
  boolean supervisorKnown = supervisor.isEmpty()
      || supervisorOpts.stream().anyMatch(o -> o.value().equals(supervisor));
  String action = editing ? "/personnel/filing/" + filingId + "/edit"
      : "/personnel/filing/new" + (infoId == null ? "" : "?info_id=" + infoId);}
@template.layout(ctx = ctx, title = "登记备案表", content = @`
    <h4 class="mb-3 mt-3">
        <i class="bi bi-file-earmark-text"></i> ${editing ? "编辑" : "新增"}因私事出国（境）人员登记备案表
    </h4>

    @if(!editing)
        <div class="d-flex align-items-center mb-4" style="max-width:520px;">
            <div class="text-center" style="width:140px;">
                <span class="badge rounded-pill bg-success" style="width:26px;height:26px;line-height:18px;"><i class="bi bi-check"></i></span>
                <div class="small mt-1 text-success">信息登记表</div>
            </div>
            <div class="flex-fill border-top border-2 border-success mx-2" style="margin-top:-14px;"></div>
            <div class="text-center" style="width:140px;">
                <span class="badge rounded-pill bg-primary" style="width:26px;height:26px;line-height:18px;">2</span>
                <div class="small mt-1 fw-bold text-primary">登记备案表</div>
            </div>
        </div>
    @endif

    <%-- data-draft 必须整个属性出现或整个不出现：main.js 用 form[data-draft] 选择器，
       留一个空值属性会误触发草稿逻辑。JTE 又禁止在属性名位置放表达式，故分两支写。 --%>
    @if(editing)
    <form method="POST" action="${action}" class="needs-validation" novalidate>
    @else
    <form method="POST" action="${action}" class="needs-validation" novalidate data-draft="personnel_filing">
    @endif
        <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">

        <div class="form-section">
            <h5>身份信息</h5>
            <div class="row g-3">
                <div class="col-md-2">
                    <label class="form-label required">中文姓</label>
                    <input type="text" class="form-control" name="surname" value="${Fmt.v(data, "surname")}" placeholder="复姓如欧阳" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label required">中文名</label>
                    <input type="text" class="form-control" name="given_name" value="${Fmt.v(data, "given_name")}" required>
                </div>
                <div class="col-md-2">
                    <label class="form-label required">性别</label>
                    <select class="form-select" name="gender" required>
                        <option value="">请选择</option>
                        <option value="男" selected="${Fmt.is(Fmt.v(data, "gender"), "男")}">男</option>
                        <option value="女" selected="${Fmt.is(Fmt.v(data, "gender"), "女")}">女</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <label class="form-label required">出生日期</label>
                    <input type="text" class="form-control" name="birth_date" value="${Fmt.v(data, "birth_date")}" placeholder="YYYYMMDD" maxlength="8" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label required">身份证号</label>
                    <input type="text" class="form-control" name="id_number" value="${idNumber}" placeholder="18位" maxlength="18" required readonly="${lockedId}">
                    @if(lockedId)<div class="form-text">取自信息登记表，不可修改。</div>@endif
                </div>
            </div>
            <div class="row g-3 mt-1">
                <div class="col-md-8">
                    <label class="form-label required">户口所在地</label>
                    <div class="row g-1 mb-1">
                        <div class="col-4"><select class="form-select form-select-sm" id="resProv"><option value="">省/直辖市</option></select></div>
                        <div class="col-4"><select class="form-select form-select-sm" id="resCity"><option value="">市</option></select></div>
                        <div class="col-4"><select class="form-select form-select-sm" id="resDist"><option value="">区/县</option></select></div>
                    </div>
                    <input type="text" class="form-control" name="residence" id="resInput" value="${Fmt.v(data, "residence")}"
                           placeholder="三级联动选择或手动输入，如：浙江宁波市江北区" required>
                    <div class="form-text">可用上方下拉三级联动，也可手动修正；省份不加“省”字，江东区/鄞县自动归为“鄞州区”。</div>
                </div>
                <div class="col-md-4">
                    <label class="form-label required">政治面貌</label>
                    <select class="form-select" name="political_status" required>
                        <option value="">请选择</option>
                        @for(var o : politicalOpts)<option value="${o.value()}" selected="${Fmt.is(Fmt.v(data, "political_status"), o.value())}">${o.value()}</option>@endfor
                    </select>
                </div>
            </div>
        </div>

        <div class="form-section">
            <h5>单位信息</h5>
            <div class="row g-3">
                <div class="col-md-4">
                    <label class="form-label required">工作单位</label>
                    <select class="form-select" name="work_unit" required>
                        <option value="">请选择单位</option>
                        @for(var o : orgOpts)<option value="${o.name()}" selected="${Fmt.is(Fmt.v(data, "work_unit"), o.name())}">${o.label()}</option>@endfor
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="form-label required">职务（级）或职称</label>
                    <input type="text" class="form-control" name="position_or_title" value="${Fmt.v(data, "position_or_title")}"
                           placeholder="处级/副处级/正科 或 副高/正高" required>
                    <div class="form-text">处级领导填“处级”或“副处级”；副处级单位班子成员填“正科”；其他填“副高”或“正高”。</div>
                </div>
                <div class="col-md-4">
                    <label class="form-label required">人事主管单位</label>
                    <select class="form-select" name="supervisor_unit" required>
                        <option value="">请选择</option>
                        @for(var o : supervisorOpts)<option value="${o.value()}" selected="${Fmt.is(supervisor, o.value())}">${o.value()}</option>@endfor
                        @if(!supervisorKnown)
                            <%-- 字典里已删除但历史记录仍在用的值，保留为一项，避免编辑时被静默清空 --%>
                            <option value="${supervisor}" selected>${supervisor}（历史值）</option>
                        @endif
                    </select>
                    <div class="form-text">在「系统设置 → 数据字典 → 人事主管单位」中维护选项。</div>
                </div>
            </div>
        </div>

        <div class="form-section">
            <h5>备案信息</h5>
            <div class="row g-3">
                <div class="col-md-2">
                    <label class="form-label required">标记</label>
                    <select class="form-select" name="tag" required>
                        <option value="新增" selected="${Fmt.is(Fmt.v(data, "tag", "新增"), "新增")}">新增</option>
                        <option value="更新" selected="${Fmt.is(Fmt.v(data, "tag", "新增"), "更新")}">更新</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <label class="form-label required">已告知本人</label>
                    <select class="form-select" name="informed" required>
                        <option value="是" selected="${Fmt.is(Fmt.v(data, "informed", "否"), "是")}">是</option>
                        <option value="否" selected="${Fmt.is(Fmt.v(data, "informed", "否"), "否")}">否</option>
                    </select>
                </div>
                <div class="col-md-8">
                    <label class="form-label">备注</label>
                    <input type="text" class="form-control" name="remarks" value="${Fmt.v(data, "remarks")}">
                </div>
            </div>
        </div>

        <div class="mt-3 mb-4">
            <button type="submit" class="btn btn-primary"><i class="bi bi-save"></i> 保存</button>
            <a href="/personnel" class="btn btn-secondary">取消</a>
        </div>
    </form>
`, scripts = @`
    <script src="/static/js/regions.js"></script>
    <script>document.addEventListener('DOMContentLoaded', function () { initRegionCascade('resProv', 'resCity', 'resDist', 'resInput'); });</script>
`)
