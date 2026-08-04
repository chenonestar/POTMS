@import com.potms.web.Helpers
@import java.util.List
@param com.potms.web.Ctx ctx
@param List<Helpers.OrgFlatOption> nodes
@param List<Helpers.OrgOption> options
@template.layout(ctx = ctx, title = "组织架构", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-diagram-3"></i> 组织架构</h4>
    <div class="alert alert-light border small text-muted py-2">
        顶级节点即「单位」，其下为部门 / 子部门，层级不限。有子节点或已被业务记录引用时不能删除。<br>
        <strong>排序</strong>只在<strong>同一个上级之下</strong>比较：数字小的排前面，数字相同则按添加先后。
        它决定的是各处「单位 / 部门」下拉框里的先后次序。改动顶级单位的排序，其下部门会跟着整体移动。
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="POST" action="/org/add" class="row g-2 align-items-end">
            <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
            <div class="col-md-4"><label class="form-label small">名称</label><input type="text" class="form-control form-control-sm" name="name" required></div>
            <div class="col-md-4"><label class="form-label small">上级</label>
                <select class="form-select form-select-sm" name="parent_id">
                    <option value="0">（顶级单位）</option>
                    @for(var o : options)<option value="${o.id()}">${o.label()}</option>@endfor
                </select>
            </div>
            <div class="col-md-2"><label class="form-label small">排序</label><input type="number" class="form-control form-control-sm" name="sort_order" value="0"></div>
            <div class="col-auto"><button class="btn btn-sm btn-primary"><i class="bi bi-plus-lg"></i> 添加</button></div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table class="table table-hover mb-0">
            <thead class="table-light"><tr><th>名称 / 上级 / 排序（改完点 ✓ 保存）</th><th style="width:260px">层级</th><th style="width:110px" title="同级内升序，相同则按添加先后">当前排序值</th><th style="width:120px">操作</th></tr></thead>
            <tbody>
            @if(nodes.isEmpty())
                <tr><td colspan="4" class="text-center text-muted py-4">暂无组织节点</td></tr>
            @endif
            @for(var n : nodes)
                <tr>
                    <td>
                        <form method="POST" action="/org/${n.id()}/edit" class="d-flex gap-1 align-items-center">
                            <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                            <span class="text-muted">${n.indent()}</span>
                            <input type="text" class="form-control form-control-sm" name="name" value="${n.name()}" required style="max-width:260px">
                            <select class="form-select form-select-sm" name="parent_id" style="max-width:220px">
                                <option value="0">（顶级单位）</option>
                                @for(var o : options)
                                    @if(o.id() != n.id())
                                        <option value="${o.id()}" selected="${o.id() == n.parentId()}">${o.label()}</option>
                                    @endif
                                @endfor
                            </select>
                            <input type="number" class="form-control form-control-sm" name="sort_order" value="${n.sortOrder()}" style="width:80px">
                            <button class="btn btn-sm btn-outline-warning" title="保存"><i class="bi bi-check-lg"></i></button>
                        </form>
                    </td>
                    <td class="text-muted small">${n.depth() == 0 ? "（顶级）" : "层级 " + n.depth()}</td>
                    <td>${n.sortOrder()}</td>
                    <td>
                        <button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmModal"
                                data-action="/org/${n.id()}/delete"
                                data-message="确定要删除「${n.name()}」吗？"><i class="bi bi-trash"></i></button>
                    </td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>
    @template.components.confirm_modal()
`)
