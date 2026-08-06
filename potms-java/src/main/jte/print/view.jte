@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param String mode
@param String title
@param List<Map<String, String>> docs
<%-- 单据式打印，与 Python 版 templates/export/print.html 逐行对齐。

   这里刻意**不引 Bootstrap**：打印页是独立文档，Bootstrap 的 reset 会改掉
   表格边框、字号与行距，出来的纸面跟其它四版对不上。政务表单要能拿去归档，
   版式必须一致，所以样式全部内联，字体固定宋体。 --%>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>${title} — 打印</title>
<style>
  @@page { size: A4; margin: 1.5cm; }
  body { font-family: "SimSun", "Microsoft YaHei", serif; font-size: 12pt; color: #000; }
  h3 { text-align: center; margin-bottom: 6px; font-size: 15pt; }
  h4 { margin: 18px 0 6px; font-size: 13pt; border-bottom: 1px solid #999; padding-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { border: 1px solid #000; padding: 5px 8px; text-align: left; font-size: 10.5pt; }
  th { background: #eee; font-weight: bold; }
  .label { font-weight: bold; width: 18%; background: #f5f5f5; }
  .meta { text-align: right; margin-top: 20px; font-size: 10pt; color: #666; }
  .sig-block { margin-top: 50px; display: flex; justify-content: space-between; gap: 40px; }
  .sig-item { flex: 1; display: flex; align-items: flex-end; font-size: 10.5pt; }
  .sig-label { white-space: nowrap; }
  .sig-line { flex: 1; border-bottom: 1px solid #000; height: 24px; margin-left: 4px; }
  .doc { page-break-after: always; }
  .doc:last-child { page-break-after: auto; }
  @@media print { .no-print { display: none; } }
</style>
</head>
<body>

<div class="no-print" style="margin-bottom:12px;">
  <button onclick="window.print()" style="padding:7px 18px;font-size:14px;cursor:pointer;">打印 / 导出 PDF</button>
  <button onclick="window.close()" style="padding:7px 18px;font-size:14px;cursor:pointer;margin-left:8px;">关闭</button>
</div>

@for(var d : docs)
<div class="doc">
<h3>${title}</h3>

@if(mode.equals("info"))
<table>
    <tr><td class="label">单位</td><td>${d.get("unit")}</td><td class="label">部门</td><td>${d.get("department")}</td></tr>
    <tr><td class="label">姓名</td><td>${d.get("name")}</td><td class="label">性别</td><td>${d.get("gender")}</td></tr>
    <tr><td class="label">身份证号</td><td>${d.get("id_number")}</td><td class="label">参加工作日期</td><td>${d.get("work_start_date")}</td></tr>
    <tr><td class="label">出生日期</td><td colspan="3">${d.get("birth_date")}</td></tr>
    <tr><td class="label">学历</td><td>${d.get("education")}</td><td class="label">学位</td><td>${d.get("degree")}</td></tr>
    <tr><td class="label">职称</td><td>${d.get("title")}</td><td class="label">职级</td><td>${d.get("rank")}</td></tr>
    <tr><td class="label">政治面貌</td><td>${d.get("political_status")}</td><td class="label">入党日期</td><td>${d.get("party_join_date")}</td></tr>
    <tr><td class="label">职务（岗位名称）</td><td colspan="3">${d.get("position")}</td></tr>
</table>

@elseif(mode.equals("filing"))
<table>
    <tr><td class="label">中文姓</td><td>${d.get("surname")}</td><td class="label">中文名</td><td>${d.get("given_name")}</td></tr>
    <tr><td class="label">性别</td><td>${d.get("gender")}</td><td class="label">出生日期</td><td>${d.get("birth_date")}</td></tr>
    <tr><td class="label">身份证号</td><td colspan="3">${d.get("id_number")}</td></tr>
    <tr><td class="label">户口所在地</td><td colspan="3">${d.get("residence")}</td></tr>
    <tr><td class="label">政治面貌</td><td>${d.get("political_status")}</td><td class="label">工作单位</td><td>${d.get("work_unit")}</td></tr>
    <tr><td class="label">职务（级）或职称</td><td>${d.get("position_or_title")}</td><td class="label">人事主管单位</td><td>${d.get("supervisor_unit")}</td></tr>
    <tr><td class="label">标记</td><td>${d.get("tag")}</td><td class="label">已告知本人</td><td>${d.get("informed")}</td></tr>
    <tr><td class="label">备注</td><td colspan="3">${d.get("remarks")}</td></tr>
</table>
@if(!d.getOrDefault("info_name", "").isEmpty())
<h4>关联：备案人员信息登记表</h4>
<table>
    <tr><td class="label">单位</td><td>${d.get("info_unit")}</td><td class="label">部门</td><td>${d.get("info_department")}</td></tr>
    <tr><td class="label">姓名</td><td>${d.get("info_name")}</td><td class="label">性别</td><td>${d.get("info_gender")}</td></tr>
    <tr><td class="label">出生日期</td><td>${d.get("info_birth_date")}</td><td class="label">参加工作日期</td><td>${d.get("info_work_start_date")}</td></tr>
    <tr><td class="label">学历</td><td>${d.get("info_education")}</td><td class="label">学位</td><td>${d.get("info_degree")}</td></tr>
    <tr><td class="label">职称</td><td>${d.get("info_title")}</td><td class="label">职级</td><td>${d.get("info_rank")}</td></tr>
    <tr><td class="label">政治面貌</td><td>${d.get("info_political_status")}</td><td class="label">入党日期</td><td>${d.get("info_party_join_date")}</td></tr>
    <tr><td class="label">职务（岗位名称）</td><td colspan="3">${d.get("info_position")}</td></tr>
</table>
@endif

@elseif(mode.equals("certificate"))
<table>
    <tr><td class="label">单位</td><td>${d.get("unit")}</td><td class="label">部门</td><td>${d.get("department")}</td></tr>
    <tr><td class="label">姓名</td><td colspan="3">${d.get("name")}</td></tr>
    <tr><td class="label">普通护照号</td><td>${d.get("passport_no")}</td><td class="label">护照有效期</td><td>${d.get("passport_expiry")}</td></tr>
    <tr><td class="label">护照上交日期</td><td colspan="3">${d.get("passport_submit_date")}</td></tr>
    <tr><td class="label">港澳通行证号</td><td>${d.get("hm_pass_no")}</td><td class="label">港澳有效期</td><td>${d.get("hm_pass_expiry")}</td></tr>
    <tr><td class="label">港澳上交日期</td><td colspan="3">${d.get("hm_pass_submit_date")}</td></tr>
    <tr><td class="label">台湾通行证号</td><td>${d.get("tw_pass_no")}</td><td class="label">台湾有效期</td><td>${d.get("tw_pass_expiry")}</td></tr>
    <tr><td class="label">台湾上交日期</td><td colspan="3">${d.get("tw_pass_submit_date")}</td></tr>
</table>

@elseif(mode.equals("travel"))
<table>
    <tr><td class="label">单位</td><td>${d.get("unit")}</td><td class="label">部门</td><td>${d.get("department")}</td></tr>
    <tr><td class="label">姓名</td><td>${d.get("name")}</td><td class="label">职务</td><td>${d.get("position")}</td></tr>
    <tr><td class="label">职称</td><td>${d.get("title")}</td><td class="label">身份证号</td><td>${d.get("id_number")}</td></tr>
    <tr><td class="label">地点、证照</td><td colspan="3">${d.get("destination_passport")}</td></tr>
    <tr><td class="label">类别</td><td>${d.get("category")}</td><td class="label">计划出行日期</td><td>${d.get("travel_dates")}</td></tr>
    <tr><td class="label">批准日期</td><td>${d.get("approval_date")}</td><td class="label">是否做证</td><td>${d.get("need_new_passport")}</td></tr>
    <tr><td class="label">证件号码</td><td>${d.get("passport_no")}</td><td class="label">证件领用日期</td><td>${d.get("passport_collect_date")}</td></tr>
    <tr><td class="label">实际回国日期</td><td>${d.get("actual_return_date")}</td><td class="label">证件归还日期</td><td>${d.get("passport_return_date")}</td></tr>
    <tr><td class="label">行程状态</td><td>${d.get("trip_status_label")}</td><td class="label">取消日期</td><td>${d.get("cancel_date")}</td></tr>
</table>

@elseif(mode.equals("decontrol"))
<table>
    <tr><td class="label">中文姓</td><td>${d.get("surname")}</td><td class="label">中文名</td><td>${d.get("given_name")}</td></tr>
    <tr><td class="label">性别</td><td>${d.get("gender")}</td><td class="label">出生日期</td><td>${d.get("birth_date")}</td></tr>
    <tr><td class="label">身份证号</td><td colspan="3">${d.get("id_number")}</td></tr>
    <tr><td class="label">户口所在地</td><td colspan="3">${d.get("residence")}</td></tr>
    <tr><td class="label">政治面貌</td><td>${d.get("political_status")}</td><td class="label">工作单位</td><td>${d.get("work_unit")}</td></tr>
    <tr><td class="label">人事主管单位</td><td colspan="3">${d.get("supervisor_unit")}</td></tr>
    <tr><td class="label">报送单位名称</td><td colspan="3">${d.get("submit_unit_name")}</td></tr>
    <tr><td class="label">报送单位类别</td><td>${d.get("submit_unit_type")}</td><td class="label">报送单位联系人</td><td>${d.get("submit_contact")}</td></tr>
    <tr><td class="label">联系电话</td><td>${d.get("submit_phone")}</td><td class="label">入库批号</td><td>${d.get("batch_no")}</td></tr>
    <tr><td class="label">撤控日期</td><td>${d.get("decontrol_date")}</td><td class="label">证件移交日期</td><td>${d.get("cert_handover_date")}</td></tr>
    <tr><td class="label">撤控原因</td><td colspan="3">${d.get("reason")}</td></tr>
</table>

@elseif(mode.equals("issuance"))
<table>
    <tr><td class="label">单位</td><td colspan="3">${d.get("work_unit")}</td></tr>
    <tr><td class="label">领用人</td><td>${d.get("holder_name")}</td><td class="label">身份证号</td><td>${d.get("id_number")}</td></tr>
    <tr><td class="label">领用证件种类</td><td colspan="3">${d.get("cert_types_label")}</td></tr>
    <tr><td class="label">证件号码</td><td colspan="3">${d.get("cert_nos")}</td></tr>
    <tr><td class="label">领用日期</td><td>${d.get("issue_date")}</td><td class="label">经办人（发放）</td><td>${d.get("issuer")}</td></tr>
    <tr><td class="label">归还日期</td><td>${d.get("return_date")}</td><td class="label">经办人（接收）</td><td>${d.get("return_operator")}</td></tr>
    <tr><td class="label">备注</td><td colspan="3">${d.get("remarks")}</td></tr>
    @if(d.getOrDefault("status", "").equals("voided"))
    <tr><td class="label">作废原因</td><td colspan="3">${d.get("void_reason")}</td></tr>
    @endif
</table>
@endif

@if(mode.equals("issuance"))
<%-- 领用/归还手写签名：直接呈现采集到的签名图 --%>
<div class="sig-block">
    <div class="sig-item" style="text-align:center;">
        <div class="sig-label">领用人签名</div>
        @if(d.getOrDefault("has_sign", "").equals("1"))
        <img src="/issuance/${d.get("_id")}/signature.png" alt="领用人签名" style="height:60px;">
        @else<span class="sig-line"></span>@endif
    </div>
    <div class="sig-item" style="text-align:center;">
        <div class="sig-label">归还人签名</div>
        @if(d.getOrDefault("has_return_sign", "").equals("1"))
        <img src="/issuance/${d.get("_id")}/signature.png?kind=return" alt="归还人签名" style="height:60px;">
        @else<span class="sig-line"></span>@endif
    </div>
</div>
@else
<%-- 签章栏：标签在前、下划线在后、三者均匀分布，为签字留足空间 --%>
<div class="sig-block">
    <div class="sig-item"><span class="sig-label">填表人：</span><span class="sig-line"></span></div>
    <div class="sig-item"><span class="sig-label">审核人：</span><span class="sig-line"></span></div>
    <div class="sig-item"><span class="sig-label">批准人：</span><span class="sig-line"></span></div>
</div>
@endif

<p class="meta">打印日期：<span class="print-date"></span>　｜　操作人：${ctx.user()}</p>
</div>
@endfor

<script>
document.querySelectorAll('.print-date').forEach(function (el) {
    el.textContent = new Date().toISOString().slice(0, 10);
});
</script>
</body>
</html>
