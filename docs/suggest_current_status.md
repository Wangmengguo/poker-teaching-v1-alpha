# Poker Suggest 模块当前实现现状分析

## 概述

Poker Suggest 模块是一个专注于德州扑克 HU (Heads-Up) 游戏的智能建议系统，提供从 preflop 到 river 各阶段的行动建议。该系统采用现代扑克策略理念，结合配置驱动的规则引擎，为教学和实际对局提供可解释的建议。

## 架构设计

### 核心组件

1. **服务层** (`service.py`)
   - 入口函数: `build_suggestion(gs, actor, cfg)`
   - 负责策略选择、金额钳制、解释渲染和调试日志
   - 支持 v0/v1 版本切换，通过环境变量控制

2. **策略引擎** (`policy.py`, `policy_preflop.py`)
   - 实现不同阶段的具体决策逻辑
   - v0: 简单规则-based 实现
   - v1: 配置驱动的复杂策略

3. **配置系统** (`config_loader.py`, `config/`)
   - JSON 配置文件的缓存加载机制
   - 支持 TTL + 文件修改时间双重缓存
   - 包含模式配置、范围定义和规则表

4. **决策系统** (`decision.py`)
   - `Decision` 类: 表达行动意图和尺寸规格
   - `SizeSpec`: 支持 bb 倍数、标签、固定金额三种尺寸表达
   - 统一处理最小重开金额调整

5. **观察系统** (`observations.py`, `types.py`)
   - `Observation` 数据类: 封装游戏状态信息
   - 包含位置、金额、手牌信息、策略相关字段

6. **解释系统** (`explanations.py`, `codes.py`)
   - rationale 代码系统: 结构化决策理由
   - 模板化自然语言解释，支持多语言

### 数据流

```
GameState → build_observation → 选择策略版本 → 执行策略 → Decision.resolve → 金额钳制 → 渲染解释 → 返回建议
```

## 功能实现现状

### Preflop 阶段 (完整实现)

**v0 版本:**
- 简单范围检查 + pot-odds 决策
- 开局: 范围内按固定倍数开局，否则过牌
- 防守: 范围内且价格合适时跟注，否则弃牌

**v1 版本:**
- 配置驱动的复杂策略
- SB 首攻: 基于范围表的开局决策
- BB 防守: 3bet/call/fold 三选一，考虑价格和范围
- SB vs 3bet: 支持 4bet 逻辑
- 尺寸计算: 动态 3bet/4bet 倍数，带 cap 限制

### Flop 阶段 (完整实现)

**核心特性:**
- 基于多维度规则表决策
- 支持 single_raised/limped/threebet 三种 pot 类型
- 考虑 position (ip/oop), texture (dry/semi/wet), spr bucket, role (pfr/caller)
- 手牌分类: value_two_pair_plus, overpair/top_pair, strong_draw 等

**决策逻辑:**
- 无下注时: c-bet 决策，尺寸基于规则表
- 面对下注: MDF 防守 + value raise 支持
- 支持范围优势和坚果优势的特殊处理

### Turn/River 阶段 (基础实现)

**当前状态:**
- 复用 flop 的通用框架
- 支持规则表驱动的决策
- 基础 MDF 防守逻辑
- 准备扩展 value raise 和 bluffing 逻辑

## 配置结构

### 模式配置 (`table_modes_*.json`)
```json
{
  "HU": {
    "open_bb": 2.5,
    "defend_threshold_ip": 0.42,
    "defend_threshold_oop": 0.38,
    "reraise_ip_mult": 3.0,
    "cap_ratio": 0.9
  }
}
```

### Preflop 范围 (`preflop_open_HU_*.json`, `preflop_vs_raise_HU_*.json`)
- 基于 169 组合的精确范围定义
- 支持 loose/medium/tight 三档策略

### Postflop 规则 (`flop_rules_HU_*.json`)
多层嵌套结构:
```
pot_type → role → position → texture → spr → hand_class → action/size_tag
```

## 技术特性

### 版本控制
- v0: 向后兼容的简单实现
- v1: 现代策略，支持灰度发布
- 通过环境变量 `SUGGEST_POLICY_VERSION` 控制

### 教学导向
- 详细的 rationale 代码系统
- 自然语言解释模板
- 策略计划和教学提示
- 调试模式提供完整决策路径

### 性能优化
- 配置文件的智能缓存
- 策略函数的纯函数设计
- 最小化外部依赖

### 安全性
- 金额钳制确保合法性
- 兜底策略防止异常
- 优雅的配置回退

## 测试和验证

### 单测覆盖
- 策略逻辑测试
- 配置加载测试
- 决策解析测试
- 端到端集成测试

### 质量门
- `scripts/check_flop_rules.py`: 规则配置验证
- `scripts/check_preflop_ranges.js`: 范围配置验证
- 快照测试确保行为一致性

## 待优化方向

### 功能扩展
1. **Turn/River 规则完善**
   - 当前规则覆盖不全，需要补充 facing bet 时的决策逻辑
   - 增加 bluffing 和 semi-bluffing 策略

2. **Value Raise 增强**
   - Flop 已实现基础 value raise
   - Turn/River 需要扩展 facing size 的处理

3. **Bluffing 系统**
   - 基于牌面纹理的诈唬决策
   - 平衡范围的诈唬频率控制

### 架构优化
1. **配置管理**
   - 当前 JSON 配置维护成本高
   - 考虑引入 DSL 或可视化配置工具

2. **性能优化**
   - 规则查找的性能 profiling
   - 缓存策略的进一步优化

3. **可扩展性**
   - 支持 6-max 等其他游戏格式
   - 插件化架构支持自定义策略

### 用户体验
1. **解释质量**
   - 当前解释较为技术化
   - 需要更自然的教学语言

2. **调试工具**
   - 增强调试模式的输出信息
   - 提供决策树的图形化展示

## 总结

当前 suggest 模块已经实现了功能完整的 HU 扑克建议系统，特别是在 preflop 和 flop 阶段达到了生产级别。系统采用了现代化的架构设计，具备良好的可维护性和扩展性。

核心优势在于其配置驱动的设计理念，使得策略调整不需要修改代码，同时保持了教学导向的可解释性。v1 版本的重构为后续 turn/river 的完善奠定了坚实基础。

下一步优化应重点关注 turn/river 规则的完善，以及用户体验的提升，特别是解释系统的自然化和决策过程的可视化。