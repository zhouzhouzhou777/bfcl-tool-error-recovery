# BFCL 工具调用纠错实验

这个实验比较通用报错和具体报错对工具调用恢复的影响。每题两组共享 BFCL 用户对话、参考操作回放、模拟状态、失败调用、模型和一次重试机会。具体反馈说明出错字段和约束，正确参数由模型根据上下文推断。成功需要完成正确的目标操作并得到参考结果。

## 已记录的实验结果

模型使用 `deepseek-flash`，关闭思考模式，温度为 0，每次输出上限为 384 tokens。

| 样本 | 配对题数 | 通用报错组成功 | 具体报错组成功 |
| --- | ---: | ---: | ---: |
| 试跑 | 3 | 3/3（100%） | 3/3（100%） |
| 正式实验 | 30 | 25/30（83.3%） | 25/30（83.3%） |

正式实验中两组共同成功 25 道，共同失败 5 道，成功率差为 0 个百分点。失败调用均提出了列目录或查找文件等探索操作，未在单次调用内完成目标操作。本次样本中未观察到具体报错提高单次恢复成功率。

故障由实验脚本预设为文件不存在。30 道正式题中，11 道使用完整原对话，19 道保留到可独立完成的较早用户轮次。结果的适用范围是本次模型、筛选后的模拟文件系统任务和预设错误。

## 复现

使用 Python 3.9 或更新版本，实验脚本使用 Python 标准库。先在本地验证样本，并从现有日志重算结果。

```sh
python3 -B prepare_cases.py
python3 -B analyze.py results.jsonl
```

重新调用模型时，可以从环境变量 `DEEPSEEK_API_KEY` 读取 DeepSeek 密钥，也可以通过 `--prompt-key` 在终端关闭回显后输入。

```sh
python3 run.py --prompt-key --output rerun.jsonl
python3 analyze.py rerun.jsonl --output rerun-summary.json
```

`run.py` 默认先完成试跑，再运行正式样本。相同输出文件中的已记录调用会跳过。需要独立重跑时，使用新的输出文件名。`analyze.py` 分开汇总试跑与正式实验，主要统计两组成功率、配对差异、精确 McNemar 检验及 DeepSeek 返回的 token 用量。

```sh
python3 prepare_cases.py
```

该命令可在本地验证每题的参考调用和故障调用。`case_manifest.json` 列出实际样本、保留的对话轮次和故障参数。`results.jsonl` 和 `summary.json` 分别保存实验的逐次记录和配对统计。

## 数据来源

`source/` 保存 Berkeley Function Calling Leaderboard V4 的 `multi_turn_base`、官方参考调用、模拟文件系统与工具定义。具体 Git 版本及上游许可见 `source/REVISION` 和 `source/LICENSE.bfcl`。实验用例的筛选与故障构造见 `prepare_cases.py`。

实验结果适用于筛选后的 BFCL 模拟文件系统用例和指定模型设置。预设错误的恢复率不代表模型在首次工具调用时的出错率。

OpenAI Codex 协助编写实验脚本和整理说明，已记录的模型结果来自实际 DeepSeek API 调用。
