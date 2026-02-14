# Python 进程随机崩溃：C 扩展段错误复盘

## 现象

- 服务进程无告警退出，系统日志出现 `Segmentation fault (core dumped)`。
- 仅在高并发路径下触发，复现概率低。

## 关键步骤

1. 打开 core dump：

```bash
ulimit -c unlimited
sudo sysctl -w kernel.core_pattern=/tmp/core.%e.%p.%t
```

2. 用 gdb 定位崩溃栈：

```bash
gdb /usr/bin/python3 /tmp/core.python3.12345.1700000000
(gdb) bt
(gdb) frame 3
```

3. 从地址反查源码行：

```bash
addr2line -e build/lib.linux-x86_64-3.11/my_ext.so 0x0000000000012a4f
```

## 根因

- C 扩展中缓存数组写入时缺少边界判断。
- 同时存在 GIL 释放后共享结构访问竞争，放大了触发概率。

## 修复

1. 增加长度检查与 `NULL` 判断。
2. 对共享状态增加互斥保护。
3. 在 CI 引入 `asan/ubsan` 构建任务。

## 验证

- 压测 24h 无崩溃。
- `asan` 模式下未再出现越界写告警。

