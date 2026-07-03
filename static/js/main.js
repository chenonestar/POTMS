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
