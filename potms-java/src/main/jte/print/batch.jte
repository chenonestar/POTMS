@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param String mode
@param String title
@param List<Map<String, String>> docs
<%-- 批量打印，与 Python 版 templates/export/batch_print.html 逐列对齐。

   形态与单据式打印**刻意不同**：这里是一张 A4 横向的宽表，一条记录一行，
   表头只出现一次——用于归档清单与报送，不是逐份签字的单据。Java 版原先偷懒
   复用了单据模板，选 20 条就出 20 页单据，跟其它四版对不上。 --%>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>批量打印 — ${title}</title>
<style>
  @@page { size: A4 landscape; margin: 1.2cm; }
  body { font-family: "SimSun", "Microsoft YaHei", serif; font-size: 9pt; color: #000; }
  h3 { text-align: center; margin-bottom: 8px; font-size: 13pt; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 16px; page-break-inside: avoid; }
  th, td { border: 1px solid #000; padding: 4px 5px; text-align: left; font-size: 8pt; }
  th { background: #eee; font-weight: bold; white-space: nowrap; }
  .meta { text-align: right; margin-top: 12px; font-size: 8pt; color: #666; }
  @@media print { .no-print { display: none; } }
</style>
</head>
<body>
<div class="no-print" style="margin-bottom:10px;">
  <button onclick="window.print()" style="padding:6px 16px;font-size:14px;cursor:pointer;">打印全部（${docs.size()} 条）</button>
  <button onclick="window.close()" style="padding:6px 16px;font-size:14px;cursor:pointer;margin-left:6px;">关闭</button>
</div>

<h3>${title}（共 ${docs.size()} 条）</h3>

@if(mode.equals("filing"))
<table>
    <thead><tr><th>中文姓</th><th>中文名</th><th>性别</th><th>出生日期</th><th>身份证号</th><th>户口所在地</th><th>政治面貌</th><th>工作单位</th><th>职务（级）或职称</th><th>人事主管单位</th><th>标记</th><th>已告知本人</th><th>状态</th><th>备注</th></tr></thead>
    <tbody>
    @for(var r : docs)
    <tr>
        <td>${r.get("surname")}</td><td>${r.get("given_name")}</td><td>${r.get("gender")}</td><td>${r.get("birth_date")}</td>
        <td>${r.get("id_number")}</td><td>${r.get("residence")}</td><td>${r.get("political_status")}</td>
        <td>${r.get("work_unit")}</td><td>${r.get("position_or_title")}</td><td>${r.get("supervisor_unit")}</td>
        <td>${r.get("tag")}</td><td>${r.get("informed")}</td><td>${r.get("status_label")}</td><td>${r.get("remarks")}</td>
    </tr>
    @endfor
    </tbody>
</table>

@elseif(mode.equals("certificate"))
<table>
    <thead><tr><th>单位</th><th>部门</th><th>姓名</th><th>护照证件号</th><th>护照有效日期</th><th>护照上交日期</th><th>港澳通行证号</th><th>港澳有效日期</th><th>港澳上交日期</th><th>台湾通行证号</th><th>台湾有效日期</th><th>台湾上交日期</th></tr></thead>
    <tbody>
    @for(var r : docs)
    <tr>
        <td>${r.get("unit")}</td><td>${r.get("department")}</td><td>${r.get("name")}</td>
        <td>${r.get("passport_no")}</td><td>${r.get("passport_expiry")}</td><td>${r.get("passport_submit_date")}</td>
        <td>${r.get("hm_pass_no")}</td><td>${r.get("hm_pass_expiry")}</td><td>${r.get("hm_pass_submit_date")}</td>
        <td>${r.get("tw_pass_no")}</td><td>${r.get("tw_pass_expiry")}</td><td>${r.get("tw_pass_submit_date")}</td>
    </tr>
    @endfor
    </tbody>
</table>

@elseif(mode.equals("travel"))
<table>
    <thead><tr><th>单位</th><th>部门</th><th>姓名</th><th>职务</th><th>职称</th><th>身份证号</th><th>地点、证照</th><th>类别</th><th>计划出行日期</th><th>批准日期</th><th>是否做证</th><th>证件号码</th><th>领用日期</th><th>实际回国日期</th><th>归还日期</th><th>行程状态</th><th>取消日期</th></tr></thead>
    <tbody>
    @for(var r : docs)
    <tr>
        <td>${r.get("unit")}</td><td>${r.get("department")}</td><td>${r.get("name")}</td><td>${r.get("position")}</td><td>${r.get("title")}</td>
        <td>${r.get("id_number")}</td><td>${r.get("destination_passport")}</td><td>${r.get("category")}</td>
        <td>${r.get("travel_dates")}</td><td>${r.get("approval_date")}</td><td>${r.get("need_new_passport")}</td>
        <td>${r.get("passport_no")}</td><td>${r.get("passport_collect_date")}</td><td>${r.get("actual_return_date")}</td><td>${r.get("passport_return_date")}</td>
        <td>${r.get("trip_status_label")}</td><td>${r.get("cancel_date")}</td>
    </tr>
    @endfor
    </tbody>
</table>

@elseif(mode.equals("decontrol"))
<table>
    <thead><tr><th>中文姓</th><th>中文名</th><th>性别</th><th>出生日期</th><th>身份证号</th><th>户口所在地</th><th>政治面貌</th><th>工作单位</th><th>人事主管单位</th><th>报送单位名称</th><th>报送类别</th><th>联系人</th><th>联系电话</th><th>入库批号</th><th>撤控日期</th><th>证件移交日期</th><th>撤控原因</th></tr></thead>
    <tbody>
    @for(var r : docs)
    <tr>
        <td>${r.get("surname")}</td><td>${r.get("given_name")}</td><td>${r.get("gender")}</td><td>${r.get("birth_date")}</td>
        <td>${r.get("id_number")}</td><td>${r.get("residence")}</td><td>${r.get("political_status")}</td><td>${r.get("work_unit")}</td>
        <td>${r.get("supervisor_unit")}</td><td>${r.get("submit_unit_name")}</td><td>${r.get("submit_unit_type")}</td>
        <td>${r.get("submit_contact")}</td><td>${r.get("submit_phone")}</td><td>${r.get("batch_no")}</td>
        <td>${r.get("decontrol_date")}</td><td>${r.get("cert_handover_date")}</td><td>${r.get("reason")}</td>
    </tr>
    @endfor
    </tbody>
</table>

@elseif(mode.equals("info"))
<table>
    <thead><tr><th>单位</th><th>部门</th><th>姓名</th><th>性别</th><th>出生日期</th><th>身份证号</th><th>参加工作日期</th><th>学历</th><th>学位</th><th>职称</th><th>职级</th><th>政治面貌</th><th>入党日期</th><th>职务（岗位名称）</th></tr></thead>
    <tbody>
    @for(var r : docs)
    <tr>
        <td>${r.get("unit")}</td><td>${r.get("department")}</td><td>${r.get("name")}</td><td>${r.get("gender")}</td>
        <td>${r.get("birth_date")}</td><td>${r.get("id_number")}</td><td>${r.get("work_start_date")}</td>
        <td>${r.get("education")}</td><td>${r.get("degree")}</td><td>${r.get("title")}</td>
        <td>${r.get("rank")}</td><td>${r.get("political_status")}</td><td>${r.get("party_join_date")}</td><td>${r.get("position")}</td>
    </tr>
    @endfor
    </tbody>
</table>

@elseif(mode.equals("issuance"))
<table>
    <thead><tr><th>单位</th><th>领用人</th><th>身份证号</th><th>证件种类</th><th>证件号码</th><th>领用日期</th><th>经办人（发放）</th><th>领用人签名</th><th>归还日期</th><th>经办人（接收）</th><th>归还人签名</th><th>状态</th><th>备注</th></tr></thead>
    <tbody>
    @for(var r : docs)
    <tr>
        <td>${r.get("work_unit")}</td><td>${r.get("holder_name")}</td><td>${r.get("id_number")}</td>
        <%-- 种类标签由后端算好再下发，模板只负责摆 --%>
        <td>${r.get("cert_types_label")}</td><td>${r.get("cert_nos")}</td>
        <td>${r.get("issue_date")}</td><td>${r.get("issuer")}</td>
        <%-- 签名按行取图，不往页面里塞 BLOB；缺签名时留空，与单条打印一致 --%>
        <td>@if(!r.get("has_sign").isEmpty())<img src="/issuance/${r.get("_id")}/signature.png" alt="领用人签名" style="height:32px;">@endif</td>
        <td>${r.get("return_date")}</td><td>${r.get("return_operator")}</td>
        <td>@if(!r.get("has_return_sign").isEmpty())<img src="/issuance/${r.get("_id")}/signature.png?kind=return" alt="归还人签名" style="height:32px;">@endif</td>
        <td>${r.get("status_label")}</td><td>${r.get("remarks")}</td>
    </tr>
    @endfor
    </tbody>
</table>
@endif

<p class="meta">打印日期：<span id="pd"></span>　｜　共 ${docs.size()} 条记录</p>
<script>document.getElementById('pd').textContent = new Date().toISOString().slice(0, 10);</script>
</body>
</html>
