package com.potms.web;

import static com.potms.web.PersonnelController.operator;
import static com.potms.web.PersonnelController.param;
import static com.potms.web.PersonnelController.str;

import com.potms.Config;
import com.potms.data.Db;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** 操作日志查看与年度归档。对应 Python 版 blueprints/logs.py。 */
@Controller
public class LogsController {

    private static final ObjectMapper JSON = new ObjectMapper();

    /** 字段名 → 中文标签（变更快照展示用）。 */
    static final Map<String, String> FIELD_LABELS = new LinkedHashMap<>();

    /** 动作 / 目标类型的中文名。 */
    static final Map<String, String> ACTION_LABELS = new LinkedHashMap<>();
    static final Map<String, String> TARGET_LABELS = new LinkedHashMap<>();

    static {
        String[][] fields = {
            {"unit", "单位"}, {"department", "部门"}, {"name", "姓名"}, {"gender", "性别"},
            {"birth_date", "出生日期"}, {"id_number", "身份证号"}, {"work_start_date", "参加工作日期"},
            {"education", "学历"}, {"degree", "学位"}, {"title", "职称"}, {"rank", "职级"},
            {"political_status", "政治面貌"}, {"party_join_date", "入党日期"}, {"position", "职务"},
            {"surname", "中文姓"}, {"given_name", "中文名"}, {"residence", "户口所在地"},
            {"work_unit", "工作单位"}, {"position_or_title", "职务/职称"},
            {"supervisor_unit", "人事主管单位"}, {"tag", "标记"}, {"informed", "已告知本人"},
            {"status", "状态"}, {"remarks", "备注"},
            {"passport_no", "护照号"}, {"passport_expiry", "护照有效期"},
            {"passport_submit_date", "护照上交日期"}, {"hm_pass_no", "港澳通行证号"},
            {"hm_pass_expiry", "港澳有效期"}, {"hm_pass_submit_date", "港澳上交日期"},
            {"tw_pass_no", "台湾通行证号"}, {"tw_pass_expiry", "台湾有效期"},
            {"tw_pass_submit_date", "台湾上交日期"},
            {"destination_passport", "地点、证照"}, {"category", "类别"},
            {"travel_dates", "计划出行日期"}, {"travel_start", "出行起始"}, {"travel_end", "出行结束"},
            {"approval_date", "批准日期"}, {"need_new_passport", "是否做证"},
            {"passport_collect_date", "证件领用日期"}, {"passport_return_date", "证件归还日期"},
            {"actual_return_date", "实际回国日期"}, {"trip_status", "行程状态"},
            {"cancel_date", "取消日期"},
            {"submit_unit_name", "报送单位"}, {"submit_unit_type", "报送单位类别"},
            {"submit_contact", "联系人"}, {"submit_phone", "联系电话"},
            {"batch_no", "入库批号"}, {"reason", "撤控原因"}, {"decontrol_date", "撤控日期"},
            {"cert_handover_date", "证件移交日期"},
            {"holder_name", "领用人"}, {"cert_types", "证件种类"}, {"cert_nos", "证件号码"},
            {"issue_date", "领用日期"}, {"issuer", "发放人"}, {"return_date", "归还日期"},
            {"return_operator", "接收人"}, {"void_reason", "作废原因"},
            {"code", "代码"}, {"value", "显示值"}, {"sort_order", "排序"},
            {"parent_id", "上级"}, {"contact", "联系人"}, {"phone", "电话"},
            {"operator", "操作人"}, {"personnel_info_id", "关联信息表"},
            {"personnel_filing_id", "关联备案"}, {"travel_id", "关联出行"},
            {"replaced_by_id", "被替代为"},
        };
        for (String[] f : fields) {
            FIELD_LABELS.put(f[0], f[1]);
        }

        String[][] actions = {
            {"create", "新建"}, {"update", "修改"}, {"delete", "删除"},
            {"cancel", "取消行程"}, {"restore", "恢复行程"}, {"void", "作废"},
            {"login_fail", "登录失败"}, {"lock", "登录锁定"}, {"logout", "退出登录"},
            {"backup", "数据备份"}, {"export", "导出"}, {"import", "导入"},
        };
        for (String[] a : actions) {
            ACTION_LABELS.put(a[0], a[1]);
        }

        String[][] targets = {
            {"personnel_info", "信息登记表"}, {"personnel_filing", "登记备案表"},
            {"certificate", "证照登记"}, {"travel_details", "出国明细"},
            {"decontrol_filing", "撤控备案"}, {"cert_issuance", "证件领用"},
            {"sys_dict", "数据字典"}, {"sys_org", "组织架构"}, {"sys_submit_unit", "报送单位"},
            {"operation_logs", "操作日志"}, {"users", "账户"}, {"auth", "登录认证"},
            {"database", "数据库"},
        };
        for (String[] t : targets) {
            TARGET_LABELS.put(t[0], t[1]);
        }
    }

    /** 一处字段变更。 */
    public record Change(String field, String before, String after) {}

    private final Db db;
    private final Config cfg;

    public LogsController(Db db, Config cfg) {
        this.db = db;
        this.cfg = cfg;
    }

    @GetMapping("/logs")
    public String index(HttpServletRequest req, Model model) {
        Filter f = new Filter();
        f.eq("action", req.getParameter("action"));
        f.eq("target_type", req.getParameter("target_type"));
        String from = param(req, "date_from", "");
        String to = param(req, "date_to", "");
        if (!from.isEmpty()) {
            f.and("date(created_at) >= ?", from);
        }
        if (!to.isEmpty()) {
            f.and("date(created_at) <= ?", to);
        }

        int page = intOr(req.getParameter("page"), 1);
        var pg = Helpers.paginate(db.jdbc(),
                "SELECT * FROM operation_logs WHERE 1=1" + f.where() + " ORDER BY created_at DESC",
                f.params(), page, Config.PAGE_SIZE_LOGS);

        // 解析变更快照，逐行附上「字段：旧值 → 新值」
        Map<Long, List<Change>> changes = new LinkedHashMap<>();
        for (var r : pg.rows()) {
            changes.put(Fmt.n(r, "id"), computeChanges(str(r.get("snapshot"))));
        }

        model.addAttribute("ctx", Ctx.of(req));
        model.addAttribute("items", pg);
        model.addAttribute("changes", changes);
        model.addAttribute("actionLabels", ACTION_LABELS);
        model.addAttribute("targetLabels", TARGET_LABELS);
        model.addAttribute("actionFilter", param(req, "action", ""));
        model.addAttribute("targetFilter", param(req, "target_type", ""));
        model.addAttribute("dateFrom", from);
        model.addAttribute("dateTo", to);
        model.addAttribute("years", logYears());
        return "logs/index";
    }

    /** 日志中出现过的年份（按展示时区换算），倒序。 */
    private List<String> logYears() {
        String tz = (cfg.tzOffsetHours >= 0 ? "+" : "") + cfg.tzOffsetHours + " hours";
        return db.jdbc().queryForList(
                "SELECT DISTINCT strftime('%Y', datetime(created_at, ?)) AS y "
                + "FROM operation_logs WHERE created_at IS NOT NULL ORDER BY y DESC",
                String.class, tz).stream().filter(y -> y != null && !y.isEmpty()).toList();
    }

    /**
     * 从快照 JSON 算出变更清单。
     *
     * <p>只列真正变了的字段：新建时 before 为空、删除时 after 为空，
     * 两种情况都只展示有值的一侧，避免整行字段刷屏。
     */
    static List<Change> computeChanges(String snapshot) {
        List<Change> out = new ArrayList<>();
        if (snapshot == null || snapshot.isBlank()) {
            return out;
        }
        JsonNode root;
        try {
            root = JSON.readTree(snapshot);
        } catch (RuntimeException e) {
            return out;   // 快照损坏不应让日志页打不开
        }
        JsonNode before = root.path("before");
        JsonNode after = root.path("after");

        var keys = new java.util.LinkedHashSet<String>();
        keys.addAll(before.propertyNames());
        keys.addAll(after.propertyNames());

        for (String k : keys) {
            String b = text(before, k);
            String a = text(after, k);
            if (b.equals(a)) {
                continue;
            }
            out.add(new Change(FIELD_LABELS.getOrDefault(k, k), b, a));
        }
        return out;
    }

    private static String text(JsonNode node, String key) {
        if (node == null || node.isMissingNode() || node.isNull()) {
            return "";
        }
        JsonNode v = node.path(key);
        return (v.isMissingNode() || v.isNull()) ? "" : v.asString();
    }

    private static int intOr(String s, int dflt) {
        if (s == null || s.isBlank()) {
            return dflt;
        }
        try {
            return Integer.parseInt(s.trim());
        } catch (NumberFormatException e) {
            return dflt;
        }
    }
}
