# SSH 连接偶发超时：握手阶段排错路径

## 现象

- `ssh user@host` 偶发卡在 `SSH2_MSG_KEXINIT sent` 之后。
- 同网段某些机器正常，某些机器不稳定。

## 排查顺序

1. 先看 DNS 与路由：

```bash
dig host.example.com
ip route get <target_ip>
```

2. 校验 MTU（怀疑分片/路径 MTU）：

```bash
ping -M do -s 1472 <target_ip>
ping -M do -s 1400 <target_ip>
```

3. 抓包确认握手在哪一步丢失：

```bash
sudo tcpdump -nn -i eth0 host <target_ip> and tcp port 22 -w ssh-timeout.pcap
```

4. 临时禁用复杂算法验证：

```bash
ssh -o KexAlgorithms=+diffie-hellman-group14-sha1 \
    -o Ciphers=+aes128-ctr \
    user@host
```

## 根因与修复

- 根因：边界防火墙策略更新后，特定分片包被误拦截。
- 修复：
  - 调整防火墙分片相关策略。
  - 在核心链路设备统一 MTU。

## 复盘

- 这类问题要优先用抓包确认“协议阶段”。
- 不要一开始就盲目改 SSH 配置，先收敛网络层变量。

