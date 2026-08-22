@import com.potms.web.Helpers
@import java.util.List
@param com.potms.web.Ctx ctx
@param List<Helpers.SubmitUnit> units
@template.layout(ctx = ctx, title = "报送单位", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-building"></i> 报送单位</h4>
    <div class="alert alert-light border small text-muted py-2">
        撤控备案表里选定报送单位后，联系人与电话会自动带出。已被撤控记录引用的单位不能删除。
    </div>

    <div class="card mb-3"><div class="card-body py-2">
        <form method="POST" action="/submit-unit/add" class="row g-2 align-items-end">
            <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
            <div class="col-md-4"><label class="form-label small">单位名称</label><input type="text" class="form-control form-control-sm" name="name" required></div>
            <div class="col-md-2"><label class="form-label small">联系人</label><input type="text" class="form-control form-control-sm" name="contact"></div>
            <div class="col-md-3"><label class="form-label small">联系电话</label><input type="text" class="form-control form-control-sm" name="phone"></div>
            <div class="col-md-1"><label class="form-label small">排序</label><input type="number" class="form-control form-control-sm" name="sort_order" value="0"></div>
            <div class="col-auto"><button class="btn btn-sm btn-primary"><i class="bi bi-plus-lg"></i> 添加</button></div>
        </form>
    </div></div>

    <div class="table-card"><div class="table-responsive">
        <table class="table table-hover mb-0">
            <thead class="table-light"><tr><th>单位名称</th><th>联系人</th><th>联系电话</th><th style="width:120px">操作</th></tr></thead>
            <tbody>
            @if(units.isEmpty())
                <tr><td colspan="4" class="text-center text-muted py-4">暂无报送单位</td></tr>
            @endif
            @for(var u : units)
                <tr>
                    <td colspan="3">
                        <form method="POST" action="/submit-unit/${u.id()}/edit" class="row g-1">
                            <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                            <div class="col-md-5"><input type="text" class="form-control form-control-sm" name="name" value="${u.name()}" required></div>
                            <div class="col-md-2"><input type="text" class="form-control form-control-sm" name="contact" value="${u.contact() == null ? "" : u.contact()}" placeholder="联系人"></div>
                            <div class="col-md-3"><input type="text" class="form-control form-control-sm" name="phone" value="${u.phone() == null ? "" : u.phone()}" placeholder="电话"></div>
                            <div class="col-auto"><button class="btn btn-sm btn-outline-warning" title="保存"><i class="bi bi-check-lg"></i></button></div>
                        </form>
                    </td>
                    <td>
                        <button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmModal"
                                data-action="/submit-unit/${u.id()}/delete"
                                data-message="确定要删除报送单位「${u.name()}」吗？"><i class="bi bi-trash"></i></button>
                    </td>
                </tr>
            @endfor
            </tbody>
        </table>
    </div></div>
    @template.components.confirm_modal()
`)
