# Agent-Pilot v7 · A/B 矩阵真实测试报告

- 运行时间：2026-04-29 05:50:11
- 配置档：single_agent_baseline, orchestrator_worker, +builder_validator, +citation, +debate
- 模型供应商：doubao, minimax, deepseek
- 任务集：T1, T2, T3, T4, T5

## 综合得分（按配置档聚合）

| 配置档 | 平均综合分 (overall) | N | 总调用数 |
| --- | ---: | ---: | ---: |
| single_agent_baseline | 74.41 | 10 | 15 |
| orchestrator_worker | 67.66 | 10 | 15 |
| +builder_validator | 70.70 | 10 | 15 |
| +citation | 69.43 | 10 | 15 |
| +debate | 68.76 | 10 | 15 |

- single_agent_baseline → +debate 增量：**-5.65 绝对值**（-7.6%）

## 每条调用明细（按 provider × task × config）

| Provider | Task | Config | overall | duration_s | output_chars | error |
| --- | --- | --- | ---: | ---: | ---: | --- |
| doubao | T1 | single_agent_baseline | 60.0 | 31.4 | 656 |  |
| doubao | T2 | single_agent_baseline | 72.0 | 24.6 | 622 |  |
| doubao | T3 | single_agent_baseline | 64.8 | 23.6 | 545 |  |
| doubao | T4 | single_agent_baseline | 67.8 | 33.5 | 689 |  |
| doubao | T5 | single_agent_baseline | 68.0 | 34.6 | 709 |  |
| doubao | T1 | orchestrator_worker | 59.3 | 36.8 | 580 |  |
| doubao | T2 | orchestrator_worker | 64.8 | 41.4 | 505 |  |
| doubao | T3 | orchestrator_worker | 65.4 | 41.4 | 563 |  |
| doubao | T4 | orchestrator_worker | 70.0 | 41.9 | 646 |  |
| doubao | T5 | orchestrator_worker | 70.8 | 44.6 | 564 |  |
| doubao | T1 | +builder_validator | 60.0 | 104.3 | 954 |  |
| doubao | T2 | +builder_validator | 72.0 | 103.3 | 975 |  |
| doubao | T3 | +builder_validator | 66.7 | 105.4 | 989 |  |
| doubao | T4 | +builder_validator | 70.0 | 98.5 | 969 |  |
| doubao | T5 | +builder_validator | 68.0 | 101.7 | 956 |  |
| doubao | T1 | +citation | 61.6 | 141.6 | 1007 |  |
| doubao | T2 | +citation | 68.0 | 138.5 | 973 |  |
| doubao | T3 | +citation | 63.0 | 143.6 | 1040 |  |
| doubao | T4 | +citation | 81.8 | 158.8 | 1070 |  |
| doubao | T5 | +citation | 79.8 | 140.5 | 1014 |  |
| doubao | T1 | +debate | 50.0 | 102.8 | 918 |  |
| doubao | T2 | +debate | 68.0 | 125.8 | 941 |  |
| doubao | T3 | +debate | 66.7 | 102.3 | 972 |  |
| doubao | T4 | +debate | 70.0 | 121.1 | 966 |  |
| doubao | T5 | +debate | 68.0 | 134.3 | 962 |  |
| minimax | T1 | single_agent_baseline | 80.0 | 9.3 | 1305 |  |
| minimax | T2 | single_agent_baseline | 84.6 | 6.8 | 870 |  |
| minimax | T3 | single_agent_baseline | 80.0 | 6.8 | 832 |  |
| minimax | T4 | single_agent_baseline | 80.0 | 8.4 | 1107 |  |
| minimax | T5 | single_agent_baseline | 86.8 | 8.4 | 2240 |  |
| minimax | T1 | orchestrator_worker | 65.2 | 10.5 | 985 |  |
| minimax | T2 | orchestrator_worker | 74.7 | 10.0 | 1861 |  |
| minimax | T3 | orchestrator_worker | 58.2 | 7.3 | 329 |  |
| minimax | T4 | orchestrator_worker | 85.5 | 12.1 | 2246 |  |
| minimax | T5 | orchestrator_worker | 62.5 | 15.1 | 2019 |  |
| minimax | T1 | +builder_validator | 84.5 | 19.4 | 794 |  |
| minimax | T2 | +builder_validator | 80.3 | 25.7 | 2267 |  |
| minimax | T3 | +builder_validator | 65.3 | 17.9 | 1065 |  |
| minimax | T4 | +builder_validator | 72.7 | 27.8 | 2088 |  |
| minimax | T5 | +builder_validator | 67.6 | 31.5 | 1703 |  |
| minimax | T1 | +citation | 53.3 | 20.4 | 443 |  |
| minimax | T2 | +citation | 83.2 | 33.6 | 2450 |  |
| minimax | T3 | +citation | 67.4 | 30.4 | 1148 |  |
| minimax | T4 | +citation | 79.3 | 17.3 | 346 |  |
| minimax | T5 | +citation | 56.8 | 29.4 | 2720 |  |
| minimax | T1 | +debate | 82.2 | 20.4 | 2194 |  |
| minimax | T2 | +debate | 81.5 | 19.9 | 2512 |  |
| minimax | T3 | +debate | 70.0 | 19.9 | 2545 |  |
| minimax | T4 | +debate | 73.3 | 21.5 | 1325 |  |
| minimax | T5 | +debate | 58.0 | 19.9 | 2678 |  |
| deepseek | T1 | single_agent_baseline | 0.0 | 0.0 | 26 |  |
| deepseek | T2 | single_agent_baseline | 0.0 | 0.0 | 26 |  |
| deepseek | T3 | single_agent_baseline | 0.0 | 0.0 | 26 |  |
| deepseek | T4 | single_agent_baseline | 0.0 | 0.0 | 26 |  |
| deepseek | T5 | single_agent_baseline | 0.0 | 0.0 | 26 |  |
| deepseek | T1 | orchestrator_worker | 0.0 | 0.0 | 26 |  |
| deepseek | T2 | orchestrator_worker | 0.0 | 0.0 | 26 |  |
| deepseek | T3 | orchestrator_worker | 0.0 | 0.0 | 26 |  |
| deepseek | T4 | orchestrator_worker | 0.0 | 0.0 | 26 |  |
| deepseek | T5 | orchestrator_worker | 0.0 | 0.0 | 26 |  |
| deepseek | T1 | +builder_validator | 0.0 | 0.0 | 26 |  |
| deepseek | T2 | +builder_validator | 0.0 | 0.0 | 26 |  |
| deepseek | T3 | +builder_validator | 0.0 | 0.0 | 26 |  |
| deepseek | T4 | +builder_validator | 0.0 | 0.0 | 26 |  |
| deepseek | T5 | +builder_validator | 0.0 | 0.0 | 26 |  |
| deepseek | T1 | +citation | 0.0 | 0.0 | 26 |  |
| deepseek | T2 | +citation | 0.0 | 0.0 | 26 |  |
| deepseek | T3 | +citation | 0.0 | 0.0 | 26 |  |
| deepseek | T4 | +citation | 0.0 | 0.0 | 26 |  |
| deepseek | T5 | +citation | 0.0 | 0.0 | 26 |  |
| deepseek | T1 | +debate | 0.0 | 0.0 | 26 |  |
| deepseek | T2 | +debate | 0.0 | 0.0 | 26 |  |
| deepseek | T3 | +debate | 0.0 | 0.0 | 26 |  |
| deepseek | T4 | +debate | 0.0 | 0.0 | 26 |  |
| deepseek | T5 | +debate | 0.0 | 0.0 | 26 |  |

> 真实 LLM 调用产生，无 mock。原始 JSON 见同目录 `ab_matrix.json`。

