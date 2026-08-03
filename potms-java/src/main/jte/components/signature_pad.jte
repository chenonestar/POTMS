@param String label = "领用人手写签名"
<%-- 手写签名控件（鼠标 / 触摸屏 / 手写板 / 触摸型签批屏通用）。
   外层表单须带 id="signForm"；提交时由 signature.js 写入隐藏域 sign_png / sign_meta。 --%>
<div class="mb-3">
    <label class="form-label">${label} <span class="text-danger">*</span></label>
    <div class="border rounded bg-white p-2">
        <canvas id="signCanvas" class="d-block w-100" style="cursor: crosshair;"></canvas>
        <div class="d-flex justify-content-between align-items-center mt-2">
            <small id="signHint" class="form-text text-muted">请在上方区域签名</small>
            <div class="btn-group btn-group-sm">
                <button type="button" id="signUndo" class="btn btn-outline-secondary"><i class="bi bi-arrow-counterclockwise"></i> 撤销一笔</button>
                <button type="button" id="signClear" class="btn btn-outline-danger"><i class="bi bi-eraser"></i> 清除重签</button>
            </div>
        </div>
    </div>
    <div class="form-text">
        <i class="bi bi-info-circle"></i>
        支持鼠标、触摸屏、手写板与触控笔。签名保存后<strong>不可修改</strong>，如登记有误请作废后重新登记。
    </div>
    <input type="hidden" name="sign_png" id="signPng">
    <input type="hidden" name="sign_meta" id="signMeta">
</div>
<%-- 采集脚本与初始化就放在组件里，不外包给引用页的 scripts 块。
   Python 版是分开写的，Java 版照抄时把 attach 漏在了外面：画布照常渲染、
   页面照常 200，只是没人绑事件，鼠标画不出任何东西。放在一起就不存在
   「包含了组件却忘了初始化」这种半拉子状态。 --%>
<script src="/static/js/signature.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function () {
    POTMSSignature.attach({
        canvas: document.getElementById('signCanvas'),
        clearBtn: document.getElementById('signClear'),
        undoBtn: document.getElementById('signUndo'),
        pngInput: document.getElementById('signPng'),
        metaInput: document.getElementById('signMeta'),
        hintEl: document.getElementById('signHint'),
        form: document.getElementById('signForm')
    });
});
</script>
