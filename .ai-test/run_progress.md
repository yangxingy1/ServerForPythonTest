# 测试进度 — rps_tournament
- run_id: `mcp_15056`
- 开始: 2026-07-07 14:29:29
- 被测项目: rps_tournament

## 总览
- [ ] contract
- [ ] unit
- [ ] integration
- [ ] e2e
- [ ] evaluation

---
## contract
- [contract#s1] ☐ 读源码 + read_contract 推导契约
- [contract#s2] ☐ 按模板逐段填写契约
- [contract#s3] ☐ 攒疑问一次问用户
- [contract#s4] ☐ write_contract 落盘

---
## unit
- [unit#s1] ☐ read_contract 通读契约
- [unit#s2] ☐ 列源码识别纯逻辑模块
- [unit#s3] ☐ 生成用例 + Write 落盘
- [unit#s4] ☐ run_pytest 运行并修复(循环到达标)
- [unit#s5] ☐ 阶段总结

---
## integration
- [integration#s1] ☐ read_contract 推导不变式
- [integration#s2] ☐ 每条不变式生成 pytest 用例(故障注入 + checker)
- [integration#s3] ☐ run_pytest 运行并修复
- [integration#s4] ☐ 阶段总结

---
## e2e
- [e2e#s1] ☐ read_contract 看协议格式与指令集
- [e2e#s2] ☐ start_server 起进程 + client_send 探通协议
- [e2e#s3] ☐ 生成 e2e 用例 + Write 落盘
- [e2e#s4] ☐ run_pytest 运行并修复
- [e2e#s5] ☐ stop_server 收尾
- [e2e#s6] ☐ 阶段总结

---
## evaluation
- [evaluation#s1] ☐ set_stage 标记
- [evaluation#s2] ☐ 读 found bug(test_report.md 或 trace.jsonl)
- [evaluation#s3] ☐ 读预埋 bug 清单
- [evaluation#s4] ☐ 语义比对(命中/疑似/漏检)
- [evaluation#s5] ☐ 算召回率
- [evaluation#s6] ☐ Write recall_report.md 落盘
[2026-07-07 14:31:54] ■ MCP server 退出(run_id=mcp_15056)
