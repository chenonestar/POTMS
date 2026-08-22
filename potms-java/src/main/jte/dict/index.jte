@import com.potms.web.ConfigController.Category
@import com.potms.web.ConfigController.DictItem
@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param List<Category> categories
@param Map<String, List<DictItem>> grouped
@template.layout(ctx = ctx, title = "数据字典", content = @`
    <h4 class="mb-3 mt-3"><i class="bi bi-card-list"></i> 数据字典</h4>
    <div class="alert alert-light border small text-muted py-2">
        被业务记录引用的字典项不能删除；引用数按「代码或显示值命中」统计。
    </div>

    <ul class="nav nav-tabs" role="tablist">
        @for(int i = 0; i < categories.size(); i++)
            !{var c = categories.get(i);}
            <li class="nav-item">
                <button class="nav-link ${i == 0 ? "active" : ""}" data-bs-toggle="tab"
                        data-bs-target="#tab-${c.key()}" type="button">${c.label()}
                    <span class="badge bg-light text-dark">${grouped.get(c.key()).size()}</span>
                </button>
            </li>
        @endfor
    </ul>

    <div class="tab-content border border-top-0 rounded-bottom p-3 mb-4">
        @for(int i = 0; i < categories.size(); i++)
            !{var c = categories.get(i); var items = grouped.get(c.key());}
            <div class="tab-pane fade ${i == 0 ? "show active" : ""}" id="tab-${c.key()}">
                <form method="POST" action="/dict/add" class="row g-2 align-items-end mb-3">
                    <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                    <input type="hidden" name="category" value="${c.key()}">
                    <div class="col-md-2"><label class="form-label small">代码</label><input type="text" class="form-control form-control-sm" name="code" required></div>
                    <div class="col-md-4"><label class="form-label small">显示值</label><input type="text" class="form-control form-control-sm" name="value" required></div>
                    <div class="col-md-2"><label class="form-label small">排序</label><input type="number" class="form-control form-control-sm" name="sort_order" value="0"></div>
                    <div class="col-auto"><button class="btn btn-sm btn-primary"><i class="bi bi-plus-lg"></i> 添加</button></div>
                </form>

                <div class="table-responsive">
                    <table class="table table-sm table-hover mb-0">
                        <thead class="table-light"><tr><th>代码</th><th>显示值</th><th>排序</th><th>引用数</th><th style="width:220px">操作</th></tr></thead>
                        <tbody>
                        @if(items.isEmpty())
                            <tr><td colspan="5" class="text-muted small">该分类下暂无字典项</td></tr>
                        @endif
                        @for(var it : items)
                            <tr>
                                <td><code>${it.code()}</code></td>
                                <td>
                                    <form method="POST" action="/dict/${it.id()}/edit" class="d-flex gap-1">
                                        <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                                        <input type="text" class="form-control form-control-sm" name="value" value="${it.value()}" required>
                                        <input type="number" class="form-control form-control-sm" name="sort_order" value="${it.sortOrder()}" style="width:80px">
                                        <button class="btn btn-sm btn-outline-warning" title="保存"><i class="bi bi-check-lg"></i></button>
                                    </form>
                                </td>
                                <td>${it.sortOrder()}</td>
                                <td>
                                    @if(it.usage() > 0)<span class="badge bg-success">${it.usage()}</span>
                                    @else<span class="badge bg-secondary">0</span>@endif
                                </td>
                                <td>
                                    @if(it.usage() == 0)
                                        <button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#confirmModal"
                                                data-action="/dict/${it.id()}/delete"
                                                data-message="确定要删除字典项「${it.value()}」吗？"><i class="bi bi-trash"></i></button>
                                    @else
                                        <button type="button" class="btn btn-sm btn-outline-danger" disabled title="有业务记录引用，不能删除"><i class="bi bi-trash"></i></button>
                                    @endif
                                </td>
                            </tr>
                        @endfor
                        </tbody>
                    </table>
                </div>
            </div>
        @endfor
    </div>
    @template.components.confirm_modal()
`)
