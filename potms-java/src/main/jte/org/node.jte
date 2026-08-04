@import com.potms.web.Helpers
@import java.util.List
@param List<Helpers.OrgFlatOption> nodes
@param long parentId
@param int level
<%-- 递归渲染一层组织节点，结构与 Python 版 organization/tree.html 的
   render_tree 宏一一对应（含逐层嵌套的 margin-left，缩进效果一致）。 --%>
@for(var o : nodes)
    @if(o.parentId() == parentId)
        !{int childCount = (int) nodes.stream().filter(c -> c.parentId() == o.id()).count();}
        <div class="tree-node" style="margin-left: ${level * 26}px;">
            <div class="d-flex align-items-center py-2 px-2 border-bottom ${level == 0 ? "bg-light rounded mt-2" : ""}">
                <i class="bi bi-${level == 0 ? "building" : level == 1 ? "diagram-2" : "folder"} ${level == 0 ? "text-primary" : level == 1 ? "text-info" : "text-muted"} me-2"></i>
                <span class="flex-grow-1">
                    <span class="${level == 0 ? "fw-bold" : ""}">${o.name()}</span>
                    @if(level == 0)
                        <span class="badge bg-primary">单位</span>
                    @elseif(level == 1)
                        <span class="badge bg-info">部门</span>
                    @else
                        <span class="badge bg-secondary">子部门</span>
                    @endif
                    @if(level == 0)<small class="text-muted ms-1">（下辖 ${childCount} 个部门）</small>@endif
                </span>
                <div class="btn-group btn-group-sm">
                    <%-- 节点数据走 data-* 而不是 onclick 里拼字符串：名称含引号时
                       拼出来的 JS 会当场语法错误，data-* 由模板负责转义。 --%>
                    <button type="button" class="btn btn-outline-secondary btn-sm js-org-add"
                            data-pid="${o.id()}" data-pname="${o.name()}" data-level="${level}"
                            title="${level == 0 ? "为该单位添加部门" : "添加子部门"}">
                        <i class="bi bi-plus-lg"></i> ${level == 0 ? "加部门" : "加子部门"}
                    </button>
                    <button type="button" class="btn btn-outline-warning btn-sm js-org-edit"
                            data-id="${o.id()}" data-name="${o.name()}" data-pid="${o.parentId()}"
                            title="重命名"><i class="bi bi-pencil"></i></button>
                    <button type="button" class="btn btn-outline-danger btn-sm" title="删除"
                            data-bs-toggle="modal" data-bs-target="#confirmModal"
                            data-action="/org/${o.id()}/delete"
                            data-message="确定删除「${o.name()}」吗？${childCount > 0 ? "注意：需先删除其下级。" : ""}">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
            @template.org.node(nodes = nodes, parentId = o.id(), level = level + 1)
        </div>
    @endif
@endfor
