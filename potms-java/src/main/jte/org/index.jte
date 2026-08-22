@import com.potms.web.Helpers
@import java.util.List
@param com.potms.web.Ctx ctx
@param List<Helpers.OrgFlatOption> nodes
<%-- 树形界面，与 Python / Go / Rust 三版一致。
   原先是扁平表格 + 行内「排序」编辑框，那是照 .NET 版做的：Python 建节点时把
   sort_order 写死成 0、页面上从不暴露，排序等于按添加先后。既然四版里三版都
   没有这个字段，留着只会让人猜「这个数字是干什么的」，索性去掉。
   注意只是不再从界面上改它——查询仍按 parent_id, sort_order, id 排序，
   老库里已有的非零排序值照样生效，与 Python 版对同一个库的表现完全一致。 --%>
@template.layout(ctx = ctx, title = "组织架构", content = @`
    <div class="d-flex justify-content-between align-items-center mb-3 mt-3">
        <h4><i class="bi bi-diagram-3"></i> 单位 / 部门维护</h4>
        <button class="btn btn-primary btn-sm" id="orgAddRoot">
            <i class="bi bi-building-add"></i> 添加单位
        </button>
    </div>

    <div class="alert alert-info d-flex align-items-center py-2">
        <i class="bi bi-info-circle me-2"></i>
        <div class="small">
            本系统采用<strong>两级组织</strong>：<span class="badge bg-primary">单位</span>为顶级组织，<span class="badge bg-info">部门</span>为其下级。
            在「备案人员信息登记表」中，<strong>单位</strong>下拉只列顶级单位，选中后<strong>部门</strong>联动出其下级部门。
        </div>
    </div>

    <div class="card mb-4">
        <div class="card-body">
            @if(nodes.isEmpty())
                <p class="text-muted text-center py-4">暂无组织，请点击右上角「添加单位」。</p>
            @else
                @template.org.node(nodes = nodes, parentId = 0L, level = 0)
            @endif
        </div>
    </div>

    <div class="modal fade" id="addModal" tabindex="-1">
        <div class="modal-dialog modal-sm">
            <div class="modal-content">
                <form method="POST" action="/org/add">
                    <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                    <div class="modal-header">
                        <h5 class="modal-title" id="addTitle">添加单位</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <input type="hidden" name="parent_id" id="addParentId" value="0">
                        <label class="form-label" id="addHint">新增一个顶级<strong>单位</strong>。</label>
                        <input type="text" class="form-control mt-2" name="name" id="addName" placeholder="请输入名称" required>
                    </div>
                    <div class="modal-footer"><button type="submit" class="btn btn-primary">添加</button></div>
                </form>
            </div>
        </div>
    </div>

    <div class="modal fade" id="editModal" tabindex="-1">
        <div class="modal-dialog modal-sm">
            <div class="modal-content">
                <form method="POST" id="editForm">
                    <input type="hidden" name="csrf_token" value="${ctx.csrfToken()}">
                    <div class="modal-header">
                        <h5 class="modal-title">重命名</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <label class="form-label">名称</label>
                        <input type="text" class="form-control" name="name" id="editName" required>
                        <input type="hidden" name="parent_id" id="editParentId" value="0">
                    </div>
                    <div class="modal-footer"><button type="submit" class="btn btn-primary">保存</button></div>
                </form>
            </div>
        </div>
    </div>

    @template.components.confirm_modal()
`, scripts = @`
    <script>
    document.addEventListener('DOMContentLoaded', function () {
        var addModal = new bootstrap.Modal(document.getElementById('addModal'));
        var editModal = new bootstrap.Modal(document.getElementById('editModal'));

        document.getElementById('orgAddRoot').addEventListener('click', function () {
            document.getElementById('addParentId').value = 0;
            document.getElementById('addTitle').textContent = '添加单位';
            document.getElementById('addHint').innerHTML = '新增一个顶级<strong>单位</strong>。';
            document.getElementById('addName').value = '';
            addModal.show();
        });

        document.querySelectorAll('.js-org-add').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var isUnit = btn.dataset.level === '0';
                document.getElementById('addParentId').value = btn.dataset.pid;
                document.getElementById('addTitle').textContent = isUnit ? '添加部门' : '添加子部门';
                document.getElementById('addHint').innerHTML =
                    '在「' + btn.dataset.pname + '」下新增' + (isUnit ? '<strong>部门</strong>' : '<strong>子部门</strong>') + '。';
                document.getElementById('addName').value = '';
                addModal.show();
            });
        });

        document.querySelectorAll('.js-org-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                document.getElementById('editName').value = btn.dataset.name;
                document.getElementById('editParentId').value = btn.dataset.pid;
                document.getElementById('editForm').action = '/org/' + btn.dataset.id + '/edit';
                editModal.show();
            });
        });
    });
    </script>
`)
