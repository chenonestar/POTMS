package com.potms.web;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.bind.annotation.ResponseStatus;

/**
 * 浏览器无条件索要的 /favicon.ico。
 *
 * <p>五个版本都不带站点图标，但浏览器每开一个标签页都要问一次。没有映射时
 * Spring MVC 会为每次请求打两行 WARN（PageNotFound: No mapping / No endpoint），
 * 控制台版启动器把这些直接怼在用户脸上，看着像出了故障。
 *
 * <p>这里明确应答 204 而不是去调日志级别：把 PageNotFound 整个降级会连真正
 * 「路由写错了」的告警一起吞掉，那种告警是要留着的。
 */
@Controller
public class FaviconController {

    @GetMapping("/favicon.ico")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    @ResponseBody
    public void favicon() {
        // 无图标可给，204 即可：浏览器会记住并停止追问
    }
}
