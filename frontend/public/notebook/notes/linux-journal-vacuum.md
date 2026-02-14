# Ubuntu 日志暴涨排查：journalctl 占满磁盘

## 现象

- 机器磁盘持续告警，`df -h` 显示根分区接近 100%。
- `du -sh /var/log/*` 发现 `journal` 目录异常大。

## 快速确认

```bash
sudo journalctl --disk-usage
sudo du -h /var/log/journal --max-depth=2 | sort -h | tail
```

## 处理步骤

1. 清理历史日志：

```bash
sudo journalctl --vacuum-time=7d
sudo journalctl --vacuum-size=1G
```

2. 配置持久化配额（`/etc/systemd/journald.conf`）：

```ini
[Journal]
SystemMaxUse=1G
SystemKeepFree=500M
MaxRetentionSec=7day
```

3. 重启服务生效：

```bash
sudo systemctl restart systemd-journald
```

## 验证

- `journalctl --disk-usage` 应稳定在配额附近。
- 一周内监控磁盘曲线，确认不再线性上涨。

## 注意事项

- 不建议直接 `rm -rf /var/log/journal/*`，可能导致日志索引状态不一致。
- 若机器写日志非常频繁，优先排查高频错误源头，再调整配额。

