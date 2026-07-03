/**
 * 通用前端功能
 */
document.addEventListener('DOMContentLoaded', function () {
    // --- 确认删除对话框 ---
    const confirmModal = document.getElementById('confirmModal');
    if (confirmModal) {
        confirmModal.addEventListener('show.bs.modal', function (event) {
            const trigger = event.relatedTarget;
            const message = trigger.getAttribute('data-message') || '确定要执行此操作吗？';
            const actionUrl = trigger.getAttribute('data-action');
            document.getElementById('confirmMessage').textContent = message;
            document.getElementById('confirmForm').action = actionUrl;
        });
    }

    // --- 自动关闭 Alert ---
    document.querySelectorAll('.alert-dismissible').forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) bsAlert.close();
        }, 5000);
    });

    // --- 侧边栏活跃状态 ---
    const currentPath = window.location.pathname;
    document.querySelectorAll('.sidebar .nav-link').forEach(function (link) {
        if (currentPath.startsWith(link.getAttribute('href'))) {
            link.classList.add('active');
        }
    });
});

// ================= 列表通用：选中导出 / 筛选导出 / 列显示 =================

// 收集已勾选行的 ID
function selectedRowIds() {
    var ids = [];
    document.querySelectorAll('.row-check:checked').forEach(function (cb) { ids.push(cb.value); });
    return ids;
}

// 导出选中行
function exportSelected(baseUrl) {
    var ids = selectedRowIds();
    if (!ids.length) { alert('请先勾选要导出的记录。'); return; }
    window.location = baseUrl + '?ids=' + ids.join(',');
}

// 按当前筛选条件导出（沿用地址栏查询串）
function exportFiltered(baseUrl) {
    window.location = baseUrl + window.location.search;
}

// 自定义列显示/隐藏：从 thead th[data-col] 生成菜单，localStorage 持久化
function initColumnToggle(tableId, menuId, storageKey) {
    var table = document.getElementById(tableId);
    var menu = document.getElementById(menuId);
    if (!table || !menu) return;
    var ths = table.querySelectorAll('thead th');
    var hidden = [];
    try { hidden = JSON.parse(localStorage.getItem(storageKey) || '[]'); } catch (e) { hidden = []; }

    function apply() {
        ths.forEach(function (th, idx) {
            var col = th.getAttribute('data-col');
            if (!col) return;
            var hide = hidden.indexOf(col) !== -1;
            th.style.display = hide ? 'none' : '';
            table.querySelectorAll('tbody tr').forEach(function (tr) {
                var cell = tr.children[idx];
                if (cell) cell.style.display = hide ? 'none' : '';
            });
        });
    }

    ths.forEach(function (th) {
        var col = th.getAttribute('data-col');
        if (!col) return;
        var li = document.createElement('li');
        var checked = hidden.indexOf(col) === -1;
        li.innerHTML = '<label class="dropdown-item mb-0" style="cursor:pointer;">' +
            '<input type="checkbox" class="me-1" ' + (checked ? 'checked' : '') + '> ' + col + '</label>';
        var cb = li.querySelector('input');
        cb.addEventListener('change', function () {
            if (cb.checked) { hidden = hidden.filter(function (c) { return c !== col; }); }
            else if (hidden.indexOf(col) === -1) { hidden.push(col); }
            localStorage.setItem(storageKey, JSON.stringify(hidden));
            apply();
        });
        menu.appendChild(li);
    });
    apply();
}
