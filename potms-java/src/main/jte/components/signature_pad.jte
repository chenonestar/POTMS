@param boolean required
@param String label = "领用人手写签名"
<%-- 手写签名控件（鼠标 / 触摸屏 / 手写板 / 触摸型签批屏通用）。
   外层表单须带 id="signForm"；提交时由 signature.js 写入隐藏域 sign_png / sign_meta。

   required 来自 Config.requireSignature（环境变量 POTMS_REQUIRE_SIGNATURE，默认强制）。
   放宽时签名板照常显示——能签就签，只是留空也能提交。 --%>
<div class="mb-3">
    <label class="form-label">${label}
        @if(required)<span class="text-danger">*</span>
        @else<span class="badge bg-secondary fw-normal">可留空</span>@endif</label>
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
        @if(!required)<br>
        <i class="bi bi-exclamation-triangle text-warning"></i>
        当前为<strong>非强制</strong>模式：留空也能提交，但该笔记录会被标注「无签名」。
        配齐手写板后请去掉 POTMS_REQUIRE_SIGNATURE=0 恢复强制。@endif
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
    // 不把 form 交给 attach()：signature.js 是五版共用的同一份文件（md5 一致），
    // 不能为了「是否强制」这条本版配置去改它。这里自己绑 submit——留空时是否拦下，
    // 由服务端下发的 requireSignature 决定。
    var pad = POTMSSignature.attach({
        canvas: document.getElementById('signCanvas'),
        clearBtn: document.getElementById('signClear'),
        undoBtn: document.getElementById('signUndo'),
        pngInput: document.getElementById('signPng'),
        metaInput: document.getElementById('signMeta'),
        hintEl: document.getElementById('signHint')
    });
    var signRequired = ${required};
    document.getElementById('signForm').addEventListener('submit', function (ev) {
        if (!pad.commit() && signRequired) {
            ev.preventDefault();
            ev.stopPropagation();
            alert('请先手写签名后再提交。');
        }
    });
});
</script>
