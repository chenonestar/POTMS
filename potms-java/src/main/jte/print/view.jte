@import java.util.List
@import java.util.Map
@param com.potms.web.Ctx ctx
@param String mode
@param String title
@param List<Map<String, String>> docs
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>${title}</title>
    <link href="/static/vendor/bootstrap/bootstrap.min.css" rel="stylesheet">
    <link href="/static/vendor/bootstrap-icons/bootstrap-icons.min.css" rel="stylesheet">
    <link href="/static/css/style.css" rel="stylesheet">
    <style>
        @@page { size: A4; margin: 1.5cm; }
        body { font-family: "SimSun", "宋体", serif; }
        .doc { page-break-after: always; }
        .doc:last-child { page-break-after: auto; }
        .doc h3 { text-align: center; font-size: 18pt; margin-bottom: 1.2em; letter-spacing: 2px; }
        table.print { width: 100%; border-collapse: collapse; }
        table.print th, table.print td { border: 1px solid #000; padding: 6px 8px; font-size: 10.5pt; }
        table.print th { width: 18%; background: #f5f5f5; text-align: right; font-weight: normal; }
        .sign-img { max-height: 60px; }
        @@media print { .no-print { display: none !important; } }
    </style>
</head>
<body class="bg-white">
<div class="no-print p-3 border-bottom mb-3">
    <button class="btn btn-primary btn-sm" onclick="window.print()"><i class="bi bi-printer"></i> 打印</button>
    <button class="btn btn-secondary btn-sm" onclick="window.close()">关闭</button>
    <span class="text-muted small ms-2">共 ${docs.size()} 份</span>
</div>

<div class="container">
@for(var d : docs)
    <div class="doc">
        <h3>${title}</h3>
        <table class="print">
        @if(mode.equals("info"))
            <tr><th>单位</th><td>${d.get("unit")}</td><th>部门</th><td>${d.get("department")}</td></tr>
            <tr><th>姓名</th><td>${d.get("name")}</td><th>性别</th><td>${d.get("gender")}</td></tr>
            <tr><th>出生日期</th><td>${d.get("birth_date")}</td><th>身份证号</th><td>${d.get("id_number")}</td></tr>
            <tr><th>参加工作日期</th><td>${d.get("work_start_date")}</td><th>政治面貌</th><td>${d.get("political_status")}</td></tr>
            <tr><th>学历</th><td>${d.get("education")}</td><th>学位</th><td>${d.get("degree")}</td></tr>
            <tr><th>职称</th><td>${d.get("title")}</td><th>职级</th><td>${d.get("rank")}</td></tr>
            <tr><th>入党日期</th><td>${d.get("party_join_date")}</td><th>职务（岗位名称）</th><td>${d.get("position")}</td></tr>
        @elseif(mode.equals("filing"))
            <tr><th>中文姓</th><td>${d.get("surname")}</td><th>中文名</th><td>${d.get("given_name")}</td></tr>
            <tr><th>性别</th><td>${d.get("gender")}</td><th>出生日期</th><td>${d.get("birth_date")}</td></tr>
            <tr><th>身份证号</th><td colspan="3">${d.get("id_number")}</td></tr>
            <tr><th>户口所在地</th><td colspan="3">${d.get("residence")}</td></tr>
            <tr><th>政治面貌</th><td>${d.get("political_status")}</td><th>工作单位</th><td>${d.get("work_unit")}</td></tr>
            <tr><th>职务（级）或职称</th><td>${d.get("position_or_title")}</td><th>人事主管单位</th><td>${d.get("supervisor_unit")}</td></tr>
            <tr><th>标记</th><td>${d.get("tag")}</td><th>已告知本人</th><td>${d.get("informed")}</td></tr>
            <tr><th>备注</th><td colspan="3">${d.get("remarks")}</td></tr>
        @elseif(mode.equals("certificate"))
            <tr><th>单位</th><td>${d.get("unit")}</td><th>部门</th><td>${d.get("department")}</td></tr>
            <tr><th>姓名</th><td colspan="3">${d.get("name")}</td></tr>
            <tr><th>普通护照号</th><td>${d.get("passport_no")}</td><th>护照有效期</th><td>${d.get("passport_expiry")}</td></tr>
            <tr><th>护照上交日期</th><td colspan="3">${d.get("passport_submit_date")}</td></tr>
            <tr><th>港澳通行证号</th><td>${d.get("hm_pass_no")}</td><th>港澳有效期</th><td>${d.get("hm_pass_expiry")}</td></tr>
            <tr><th>港澳上交日期</th><td colspan="3">${d.get("hm_pass_submit_date")}</td></tr>
            <tr><th>台湾通行证号</th><td>${d.get("tw_pass_no")}</td><th>台湾有效期</th><td>${d.get("tw_pass_expiry")}</td></tr>
            <tr><th>台湾上交日期</th><td colspan="3">${d.get("tw_pass_submit_date")}</td></tr>
        @elseif(mode.equals("travel"))
            <tr><th>单位</th><td>${d.get("unit")}</td><th>部门</th><td>${d.get("department")}</td></tr>
            <tr><th>姓名</th><td>${d.get("name")}</td><th>职务</th><td>${d.get("position")}</td></tr>
            <tr><th>身份证号</th><td colspan="3">${d.get("id_number")}</td></tr>
            <tr><th>地点、证照</th><td colspan="3">${d.get("destination_passport")}</td></tr>
            <tr><th>类别</th><td>${d.get("category")}</td><th>计划出行日期</th><td>${d.get("travel_dates")}</td></tr>
            <tr><th>批准日期</th><td>${d.get("approval_date")}</td><th>是否做证</th><td>${d.get("need_new_passport")}</td></tr>
            <tr><th>证件号码</th><td>${d.get("passport_no")}</td><th>实际回国日期</th><td>${d.get("actual_return_date")}</td></tr>
            <tr><th>证件领用日期</th><td>${d.get("passport_collect_date")}</td><th>证件归还日期</th><td>${d.get("passport_return_date")}</td></tr>
        @elseif(mode.equals("decontrol"))
            <tr><th>中文姓</th><td>${d.get("surname")}</td><th>中文名</th><td>${d.get("given_name")}</td></tr>
            <tr><th>性别</th><td>${d.get("gender")}</td><th>出生日期</th><td>${d.get("birth_date")}</td></tr>
            <tr><th>身份证号</th><td colspan="3">${d.get("id_number")}</td></tr>
            <tr><th>户口所在地</th><td colspan="3">${d.get("residence")}</td></tr>
            <tr><th>政治面貌</th><td>${d.get("political_status")}</td><th>工作单位</th><td>${d.get("work_unit")}</td></tr>
            <tr><th>人事主管单位</th><td>${d.get("supervisor_unit")}</td><th>报送单位</th><td>${d.get("submit_unit_name")}</td></tr>
            <tr><th>联系人</th><td>${d.get("submit_contact")}</td><th>联系电话</th><td>${d.get("submit_phone")}</td></tr>
            <tr><th>入库批号</th><td>${d.get("batch_no")}</td><th>撤控日期</th><td>${d.get("decontrol_date")}</td></tr>
            <tr><th>证件移交日期</th><td colspan="3">${d.get("cert_handover_date")}</td></tr>
            <tr><th>撤控原因</th><td colspan="3">${d.get("reason")}</td></tr>
        @elseif(mode.equals("issuance"))
            <tr><th>领用人</th><td>${d.get("holder_name")}</td><th>工作单位</th><td>${d.get("work_unit")}</td></tr>
            <tr><th>身份证号</th><td colspan="3">${d.get("id_number")}</td></tr>
            <tr><th>证件种类</th><td>${d.get("cert_types_label")}</td><th>证件号码</th><td>${d.get("cert_nos")}</td></tr>
            <tr><th>领用日期</th><td>${d.get("issue_date")}</td><th>发放人</th><td>${d.get("issuer")}</td></tr>
            <tr><th>领用人签名</th><td colspan="3"><img class="sign-img" src="/issuance/${d.get("_id")}/signature.png?kind=issue" alt="领用签名"></td></tr>
            <tr><th>归还日期</th><td>${d.get("return_date")}</td><th>接收人</th><td>${d.get("return_operator")}</td></tr>
            @if(d.get("status").equals("returned"))
                <tr><th>归还人签名</th><td colspan="3"><img class="sign-img" src="/issuance/${d.get("_id")}/signature.png?kind=return" alt="归还签名"></td></tr>
            @endif
            <tr><th>状态</th><td>${d.get("status_label")}</td><th>备注</th><td>${d.get("remarks")}</td></tr>
        @endif
        </table>
    </div>
@endfor
</div>
</body>
</html>
