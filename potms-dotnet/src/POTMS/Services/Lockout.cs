using System.Collections.Concurrent;

namespace POTMS.Services;

/// <summary>登录防爆破：每 IP 失败计数（进程内，与其它三版一致）。</summary>
public sealed class Lockout
{
    private readonly ConcurrentDictionary<string, (int Fails, DateTimeOffset Until)> _map = new();

    /// <summary>剩余锁定秒数；未锁定返回 0。</summary>
    public int Remaining(string ip)
    {
        if (!_map.TryGetValue(ip, out var e)) return 0;
        var left = (int)(e.Until - DateTimeOffset.UtcNow).TotalSeconds;
        return left > 0 ? left : 0;
    }

    public void RecordFailure(string ip) =>
        _map.AddOrUpdate(ip,
            _ => (1, DateTimeOffset.MinValue),
            (_, old) =>
            {
                var fails = old.Fails + 1;
                var until = fails >= Config.LockThreshold
                    ? DateTimeOffset.UtcNow.AddSeconds(Config.LockSeconds)
                    : old.Until;
                return (fails, until);
            });

    public void Reset(string ip) => _map.TryRemove(ip, out _);

    /// <summary>本次失败是否恰好触发锁定。</summary>
    public bool JustLocked(string ip) =>
        _map.TryGetValue(ip, out var e) && e.Fails == Config.LockThreshold;

    /// <summary>剩余可失败次数（&lt;=0 表示已锁定）。</summary>
    public int FailsLeft(string ip) =>
        Config.LockThreshold - (_map.TryGetValue(ip, out var e) ? e.Fails : 0);
}
