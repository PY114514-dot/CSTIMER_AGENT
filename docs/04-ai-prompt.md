# 04 AI 分析 Prompt 模板

> 模板版本: **v1.0**（每次写入 `ai_reports.prompt_version`）
> 输出格式: 强制 JSON（OpenAI `response_format=json_object` / Claude tool use）
> 模型: 默认 `gpt-4o-mini` / `claude-haiku-4-5` / `deepseek-chat`

---

## 4.1 System Prompt（系统角色）

```text
你是一位经验丰富的魔方速拧高级教练, 同时也是数据分析师。
你的工作是基于一个选手最近一个 Session(默认 12 次复原) 的统计指标,
准确指出其当前的瓶颈, 并给出具体可执行的训练建议。

约束:
1. 必须严格基于提供的数据, 不要凭空捏造数字。
2. 最多指出 2 个最主要的瓶颈, 不要泛泛而谈。
3. 给出的训练建议必须可以立即被一名普通用户执行 (具体动作/次数/节拍)。
4. 响应必须是合法 JSON, 不要包含 JSON 以外的任何文字。
```

---

## 4.2 User Prompt 模板（Python 端用 Jinja2 渲染）

```text
你是一位魔方高级教练。以下是某选手最近一个 Session 的数据摘要。

## 基础信息
- 用户水平自评: {{ user_level }}
- 训练项目: 3x3x3 标准 CFOP
- 本 Session 次数: {{ solve_count }} (含 DNF {{ dnf_count }})

## 总成绩
- 平均总时长: {{ avg_total_ms }}ms (即 {{ avg_total_sec }}s)
- 单次最佳: {{ best_ms }}ms / 单次最差: {{ worst_ms }}ms
- 标准差: {{ std_dev_ms }}ms
- 去尾平均(avg3 / avg5): {{ avg3_ms }}ms / {{ avg5_ms }}ms
- 完整 12 次 avg12: {{ avg12_ms or "样本不足" }}ms

## 阶段耗时(平均)
- Cross: {{ avg_cross_ms or "未识别" }}ms
- F2L:   {{ avg_f2l_ms or "未识别" }}ms
- OLL:   {{ avg_oll_ms or "未识别" }}ms
- PLL:   {{ avg_pll_ms or "未识别" }}ms
- 各阶段占总时长百分比: cross {{ pct_cross }}% / f2l {{ pct_f2l }}% / oll {{ pct_oll }}% / pll {{ pct_pll }}%

## 转动效率
- 平均 move count: {{ avg_moves }}
- 取消废动后等效 move: {{ avg_effective_moves }} (废动率 {{ waste_rate }}%)
- F2L 每对平均动数: {{ f2l_per_pair }}

## 停顿分析
- 平均停顿总时长/把: {{ avg_pause_ms }}ms
- 停顿次数/把: {{ avg_pause_count }}
- 停顿时长分布(占总停顿): {{ pause_stage_distribution }}
  (例如: {"f2l": 0.7, "oll": 0.2, "pll": 0.1})
- 停顿类型分布: observe {{ pct_observe }}% / think {{ pct_think }}% / lockup {{ pct_lockup }}%
- 最长一次停顿: {{ longest_pause_ms }}ms, 发生阶段: {{ longest_pause_stage }}

## 速率趋势
- 前半段(前 {{ first_n }} 次)平均: {{ first_half_ms }}ms
- 后半段(后 {{ second_n }} 次)平均: {{ second_half_ms }}ms
- 比值(后半/前半): {{ speed_trend }}  (>1 = 后半掉速, <1 = 后半越快)

## 与历史对比(最近 5 个 Session)
- 历史 avg3: [{{ hist_avg3_list }}]ms (当前: {{ avg3_ms }}ms)
- 历史 avg5: [{{ hist_avg5_list }}]ms (当前: {{ avg5_ms }}ms)
- 趋势: {{ trend_qualitative }}  (improving / stable / regressing)

请输出 JSON, 严格按以下 schema:
{
  "bottlenecks":          [string, string],          // 最多 2 个, 取自: "cross" / "f2l" / "oll" / "pll_recognition" / "f2l_lookahead" / "cross_efficiency" / "move_efficiency" / "endurance"
  "root_causes":          [string],                 // 1~3 条根因
  "speed_pattern":        "front_heavy" | "back_heavy" | "even",
  "confidence":           number,                   // 0~1
  "recommendations": [
    {
      "id":               string,                    // 形如 "R1"
      "category":         string,                    // cross / f2l / oll / pll / lookahead / fingers / metronome
      "metric_to_improve": string,                   // 形如 "f2l_observation_ms"
      "text":             string,                    // 1~2 句具体动作
      "duration_min":     number,                    // 预计耗时
      "frequency":        "daily" | "every_other_day" | "weekly"
    }
  ],
  "summary":              string                     // 1 句话总结
}

只输出 JSON, 不要解释, 不要 markdown 代码块标记。
```

---

## 4.3 Few-shot 示例（用于提升稳定性, 可选）

```text
示例输入 (省略):
- avg_f2l_ms: 9800  (占总 60%)
- pause_stage_distribution: {"f2l": 0.72, "oll": 0.18, "pll": 0.10}
- avg_pause_count: 4.2
- speed_trend: 1.15

示例输出:
{
  "bottlenecks": ["f2l_lookahead", "f2l_observation"],
  "root_causes": [
    "F2L 停顿占比 72%, 远高于其它阶段, 主要为组间观察停顿",
    "F2L 总耗时占比 60%, 说明不仅停顿多, 转动本身也慢"
  ],
  "speed_pattern": "back_heavy",
  "confidence": 0.85,
  "recommendations": [
    {
      "id": "R1",
      "category": "f2l",
      "metric_to_improve": "f2l_observation_ms",
      "text": "慢拧 5 把 F2L: 节拍器 0.6s/动, 强制在动 A 的后段观察下一组 slot",
      "duration_min": 15,
      "frequency": "daily"
    },
    {
      "id": "R2",
      "category": "lookahead",
      "metric_to_improve": "f2l_pairs_per_min",
      "text": "盲拧一组 F2L 预判练习: 闭眼识别 5 对, 目标每对 ≤ 2s",
      "duration_min": 10,
      "frequency": "every_other_day"
    }
  ],
  "summary": "F2L 观察停顿是当前最大瓶颈, 建议每日 15 分钟慢拧预判 + 隔日盲拧预判。"
}
```

---

## 4.4 解析与校验

后端解析时做以下检查:

```pseudo
ALLOWED_BOTTLENECKS = {
    "cross", "f2l", "oll", "pll_recognition",
    "f2l_lookahead", "cross_efficiency", "move_efficiency", "endurance"
}

def validate(parsed: dict) -> dict:
    parsed["bottlenecks"] = [b for b in parsed.get("bottlenecks", []) if b in ALLOWED_BOTTLENECKS][:2]
    if not parsed["bottlenecks"]:
        parsed["bottlenecks"] = ["f2l"]  # 兜底
    if len(parsed.get("recommendations", [])) < 1:
        raise ValidationError("no recommendations")
    return parsed
```

---

## 4.5 降级策略

- LLM 调用失败 (网络 / 5xx) -> 写入 `ai_reports.status='failed'`，重试 3 次
- 3 次后仍失败 -> 使用**规则库兜底**（见 05），不阻塞看板
- 解析失败 -> 保存 `raw_response` 供人工复盘，标记 `parsed_json=NULL`
