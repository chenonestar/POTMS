package com.potms.web;

import com.potms.Config;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/** 把配置里的展示时区偏移与签名强制开关灌进 Ctx，供模板使用。 */
@Component
public class CtxAdvice {

    private final Config cfg;

    public CtxAdvice(Config cfg) {
        this.cfg = cfg;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void applyConfig() {
        Ctx.defaultTzOffset = cfg.tzOffsetHours;
        Ctx.defaultRequireSignature = cfg.requireSignature;
    }
}
