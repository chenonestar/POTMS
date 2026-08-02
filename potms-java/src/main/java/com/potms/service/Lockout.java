package com.potms.service;

import com.potms.Config;
import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

/** 登录防爆破：每 IP 失败计数（进程内，与其它四版一致）。 */
@Component
public class Lockout {

    private record Entry(int fails, Instant until) {}

    private final ConcurrentHashMap<String, Entry> map = new ConcurrentHashMap<>();

    /** 剩余锁定秒数；未锁定返回 0。 */
    public int remaining(String ip) {
        Entry e = map.get(ip);
        if (e == null || e.until() == null) {
            return 0;
        }
        long left = e.until().getEpochSecond() - Instant.now().getEpochSecond();
        return left > 0 ? (int) left : 0;
    }

    public void recordFailure(String ip) {
        map.compute(ip, (k, old) -> {
            int fails = (old == null ? 0 : old.fails()) + 1;
            Instant until = fails >= Config.LOCK_THRESHOLD
                    ? Instant.now().plusSeconds(Config.LOCK_SECONDS)
                    : (old == null ? null : old.until());
            return new Entry(fails, until);
        });
    }

    public void reset(String ip) {
        map.remove(ip);
    }

    /** 本次失败是否恰好触发锁定。 */
    public boolean justLocked(String ip) {
        Entry e = map.get(ip);
        return e != null && e.fails() == Config.LOCK_THRESHOLD;
    }

    /** 剩余可失败次数（&lt;=0 表示已锁定）。 */
    public int failsLeft(String ip) {
        Entry e = map.get(ip);
        return Config.LOCK_THRESHOLD - (e == null ? 0 : e.fails());
    }

    /** 供测试使用：清空全部计数（进程级状态，用例间必须隔离）。 */
    public void clear() {
        map.clear();
    }
}
