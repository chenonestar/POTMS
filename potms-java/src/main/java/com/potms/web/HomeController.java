package com.potms.web;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

/** 仪表盘占位 — 业务实现见任务 #5。 */
@Controller
public class HomeController {

    @GetMapping("/")
    public String index(HttpServletRequest req, Model model) {
        model.addAttribute("ctx", Ctx.of(req));
        return "index";
    }
}
