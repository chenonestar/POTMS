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

    // --- 自动关闭 Alert（错误/警告不自动消失，避免用户没看清就没了）---
    document.querySelectorAll('.alert-dismissible:not(.alert-danger):not(.alert-warning)').forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) bsAlert.close();
        }, 5000);
    });

    // --- 侧边栏活跃状态（首页需精确匹配，避免恒亮）---
    const currentPath = window.location.pathname;
    document.querySelectorAll('.sidebar .nav-link').forEach(function (link) {
        const href = link.getAttribute('href');
        const active = (href === '/') ? (currentPath === '/') : currentPath.startsWith(href);
        if (active) link.classList.add('active');
    });

    // --- 侧边栏移动端折叠 ---
    const sbToggle = document.getElementById('sidebarToggle');
    if (sbToggle) {
        sbToggle.addEventListener('click', function () {
            const sb = document.querySelector('.sidebar');
            if (sb) sb.classList.toggle('show');
        });
    }

    // --- 可访问性：图标按钮 title → aria-label ---
    document.querySelectorAll('[title]:not([aria-label])').forEach(function (el) {
        el.setAttribute('aria-label', el.getAttribute('title'));
    });

    // --- 日期字段即时校验：拒绝不存在的日期（如 20260230） ---
    function isRealDate(s) {
        if (!/^\d{8}$/.test(s)) return false;
        var y = +s.slice(0, 4), m = +s.slice(4, 6), d = +s.slice(6, 8);
        if (m < 1 || m > 12 || d < 1 || d > 31) return false;
        var dt = new Date(y, m - 1, d);
        return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d;
    }
    document.querySelectorAll('input[placeholder="YYYYMMDD"]').forEach(function (el) {
        function check() {
            var v = el.value.trim();
            if (v && !isRealDate(v)) {
                el.setCustomValidity('日期不合法，请输入存在的日期（YYYYMMDD）。');
            } else {
                el.setCustomValidity('');
            }
        }
        el.addEventListener('blur', check);
        el.addEventListener('input', function () { el.setCustomValidity(''); });
    });

    // --- 计划出行日期：固定格式 YYYY/MM/DD-YYYY/MM/DD 输入掩码 + 即时校验 ---
    document.querySelectorAll('input[name="travel_dates"]').forEach(function (el) {
        el.setAttribute('maxlength', '21');
        // 掩码：仅保留数字，按 YYYY/MM/DD-YYYY/MM/DD 自动补分隔符
        function mask() {
            var ds = el.value.replace(/\D/g, '').slice(0, 16);
            var out = '';
            for (var i = 0; i < ds.length && i < 8; i++) { if (i === 4 || i === 6) out += '/'; out += ds[i]; }
            if (ds.length > 8) {
                out += '-';
                for (var j = 8; j < ds.length; j++) { if (j === 12 || j === 14) out += '/'; out += ds[j]; }
            }
            el.value = out;
        }
        function check() {
            var ds = el.value.replace(/\D/g, '');
            if (!ds) { el.setCustomValidity(''); return; }
            if (ds.length !== 8 && ds.length !== 16) {
                el.setCustomValidity('请按 YYYY/MM/DD-YYYY/MM/DD 完整填写起止日期。');
                return;
            }
            var start = ds.slice(0, 8), end = ds.length === 16 ? ds.slice(8, 16) : start;
            if (!isRealDate(start)) { el.setCustomValidity('起始日期不合法（' + start + '）。'); return; }
            if (!isRealDate(end)) { el.setCustomValidity('结束日期不合法（' + end + '）。'); return; }
            if (start > end) { el.setCustomValidity('起始日期不应晚于结束日期。'); return; }
            el.setCustomValidity('');
        }
        el.addEventListener('input', function () { mask(); el.setCustomValidity(''); });
        el.addEventListener('blur', check);
        mask();  // 载入时把已有值规整为统一格式
    });

    // --- 身份证号即时校验：18位 + 校验位；并与性别顺序码交叉核对 ---
    var ID_W = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2], ID_C = '10X98765432';
    function idCheckMsg(id) {
        id = (id || '').toUpperCase();
        if (!id) return '';
        if (!/^\d{17}[0-9X]$/.test(id)) return '身份证号须为18位（前17位数字，末位数字或X）。';
        var sum = 0;
        for (var i = 0; i < 17; i++) sum += (+id[i]) * ID_W[i];
        if (ID_C[sum % 11] !== id[17]) return '身份证校验位不正确，应为 ' + ID_C[sum % 11] + '。';
        var b = id.slice(6, 14), y = +b.slice(0, 4), m = +b.slice(4, 6), d = +b.slice(6, 8);
        var dt = new Date(y, m - 1, d);
        if (!(dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d)) return '身份证号中出生日期不合法。';
        return '';
    }
    document.querySelectorAll('input[name="id_number"]').forEach(function (el) {
        if (el.readOnly) return;
        var genderEl = el.form ? el.form.querySelector('[name="gender"]') : null;
        function check() {
            var id = el.value.trim().toUpperCase();
            var msg = idCheckMsg(id);
            if (!msg && genderEl && genderEl.value && /^\d{17}[0-9X]$/.test(id)) {
                var expect = (+id[16]) % 2 === 1 ? '男' : '女';
                if (genderEl.value !== expect) msg = '性别与身份证号不一致（身份证中为 ' + expect + '）。';
            }
            el.setCustomValidity(msg);
        }
        el.addEventListener('blur', check);
        el.addEventListener('input', function () { el.setCustomValidity(''); });
        if (genderEl) genderEl.addEventListener('change', check);
    });

    // --- 表单前端必填校验：阻止提交并定位首个错误字段 ---
    document.querySelectorAll('form.needs-validation').forEach(function (form) {
        form.addEventListener('submit', function (e) {
            if (!form.checkValidity()) {
                e.preventDefault();
                e.stopPropagation();
                const first = form.querySelector(':invalid');
                if (first) {
                    first.scrollIntoView({ block: 'center', behavior: 'smooth' });
                    // 显示原生校验气泡（含自定义日期/身份证/性别错误信息）
                    form.reportValidity();
                }
            }
            form.classList.add('was-validated');
        }, false);
    });
});

// ================= 列表通用：选中导出 / 筛选导出 / 列显示 =================

// 全选/取消全选行复选框
function toggleAll(el) {
    document.querySelectorAll('.row-check').forEach(function (cb) { cb.checked = el.checked; });
}

// 批量打印选中行
function batchPrint(type) {
    var ids = selectedRowIds();
    if (!ids.length) { alert('请先勾选要打印的记录。'); return; }
    window.open('/print/batch/' + type + '?ids=' + ids.join(','), '_blank');
}

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

// 表单暂存草稿：输入自动存 localStorage，加载时可恢复，提交后清除
function initFormDraft(form) {
    var key = 'draft_' + form.getAttribute('data-draft');
    function fieldEls() { return form.querySelectorAll('input[name], select[name], textarea[name]'); }
    function skip(el) { return el.type === 'file' || el.type === 'password' || el.type === 'hidden' || el.name === 'csrf_token'; }
    function serialize() {
        var o = {};
        fieldEls().forEach(function (el) { if (!skip(el)) o[el.name] = el.value; });
        return o;
    }
    function save() { try { localStorage.setItem(key, JSON.stringify(serialize())); } catch (e) {} }
    form.addEventListener('input', save);
    form.addEventListener('change', save);
    form.addEventListener('submit', function () { try { localStorage.removeItem(key); } catch (e) {} });

    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { saved = null; }
    if (saved) {
        var bar = document.createElement('div');
        bar.className = 'alert alert-info d-flex justify-content-between align-items-center py-2';
        bar.innerHTML = '<span><i class="bi bi-clock-history"></i> 发现上次未保存的草稿，是否恢复？</span>' +
            '<span><button type="button" class="btn btn-sm btn-primary me-1" data-act="restore">恢复草稿</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-act="discard">清除</button></span>';
        form.parentNode.insertBefore(bar, form);
        bar.querySelector('[data-act=restore]').addEventListener('click', function () {
            fieldEls().forEach(function (el) {
                if (skip(el) || el.readOnly) return;
                if (Object.prototype.hasOwnProperty.call(saved, el.name)) {
                    el.value = saved[el.name];
                    el.dispatchEvent(new Event('change'));
                }
            });
            bar.remove();
        });
        bar.querySelector('[data-act=discard]').addEventListener('click', function () {
            try { localStorage.removeItem(key); } catch (e) {}
            bar.remove();
        });
    }
}
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-draft]').forEach(initFormDraft);
});

// 户口所在地 省市区三级联动（数据来自 regions.js，写入目标文本框）
function initRegionCascade(provId, cityId, distId, targetId) {
    var regions = window.CHINA_REGIONS || [];
    var prov = document.getElementById(provId), city = document.getElementById(cityId),
        dist = document.getElementById(distId), target = document.getElementById(targetId);
    if (!prov || !city || !dist || !target || !regions.length) return;

    regions.forEach(function (p) { prov.add(new Option(p.n, p.n)); });

    function findProv() { return regions.filter(function (x) { return x.n === prov.value; })[0]; }
    function findCity(p) { return p ? p.c.filter(function (x) { return x.n === city.value; })[0] : null; }

    function fillCities() {
        city.length = 1; dist.length = 1;
        var p = findProv();
        if (p) p.c.forEach(function (c) { city.add(new Option(c.n, c.n)); });
    }
    function fillDists() {
        dist.length = 1;
        var c = findCity(findProv());
        if (c) c.d.forEach(function (d) { dist.add(new Option(d, d)); });
    }
    function updateTarget() {
        var parts = [prov.value];
        if (city.value && city.value !== '市辖区' && city.value !== '县') parts.push(city.value);
        if (dist.value) parts.push(dist.value);
        target.value = parts.filter(Boolean).join('');
    }
    prov.addEventListener('change', function () { fillCities(); updateTarget(); });
    city.addEventListener('change', function () { fillDists(); updateTarget(); });
    dist.addEventListener('change', updateTarget);
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
