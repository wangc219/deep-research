# Codex CLI 全链路综合优化路线图

## 业务背景

基于《基于多智能体协作的JS装备市场需求深度挖掘系统架构设计》，系统需要：

### 业务目标
1. **执行质量目标**
   - 6个业务 Agent（国际形势、作战场景、武器装备、作战运用、对手监测、体系对抗）
   - L1/L2/L3 制胜机理三层推理
   - 五判据审计（证据、覆盖、门控、追溯、轮次）
   - 深度报告和能力画像交付

2. **性能目标**
   - 单次完整研究：目标 < 5分钟（当前 15-30分钟）
   - Baseline Wave：目标 < 2分钟（当前 5-10分钟）
   - 单 Agent 执行：目标 < 30秒（当前 45-60秒）
   - 证据材料化：目标 < 5秒（当前 15-25秒）

### 当前性能现状

| 阶段 | 当前耗时 | 瓶颈 |
|------|----------|------|
| Baseline 6 Agent Wave | 5-10分钟 | 串行执行、进程启动 |
| 制胜机理推理 | 3-5分钟 | 模型调用、上下文构建 |
| 证据材料化 | 15-25秒/agent | 网络I/O、串行批次 |
| 审计和报告 | 1-2分钟 | 模型调用 |
| **总计** | **15-30分钟** | 多个环节累加 |

---

## 一、执行质量优化（智能体能力提升）

### 1.1 上下文优化 ⭐⭐⭐

#### 问题
- 当前 token_budget: 6500-12000
- 大量上下文被压缩或丢弃
- 跨 Agent 信息传递不充分

#### 方案
```yaml
# 优化后的上下文策略
profiles:
  - profile_id: strategic_research_v1_optimized
    context_policy:
      token_budget: 10000  # 增加 50%
      compression_strategy: smart_summary  # 智能摘要
      preserve_key_evidence: true  # 保留关键证据
      cross_agent_memory: enabled  # 跨 Agent 记忆
```

**实施**:
1. 引入上下文压缩算法（embedding-based）
2. 关键证据自动提取和保留
3. Agent 间共享知识库

**收益**: 
- 推理质量 ↑ 15-25%
- 减少 recall 次数 ↓ 30%

---

### 1.2 工具增强 ⭐⭐⭐

#### 问题
- 工具调用成功率 70-85%
- 参数验证不足
- 错误重试机制简单

#### 方案
```python
class EnhancedToolDefinition:
    """增强的工具定义"""
    
    def __init__(self, ...):
        self.parameter_validator = SmartValidator()
        self.auto_fix = True  # 自动修复常见错误
        self.retry_strategy = ExponentialBackoff(max_attempts=3)
        self.result_cache = LRUCache(maxsize=100)
    
    async def execute(self, call: ToolCall):
        # 参数自动修复
        fixed_params = self.parameter_validator.fix(call.parameters)
        
        # 带缓存的执行
        cache_key = self._make_cache_key(call)
        if cache_key in self.result_cache:
            return self.result_cache[cache_key]
        
        # 带重试的执行
        result = await self.retry_strategy.execute(
            lambda: self._do_execute(fixed_params)
        )
        
        self.result_cache[cache_key] = result
        return result
```

**收益**:
- 工具调用成功率 ↑ 到 95%+
- 减少失败重试时间 ↓ 50%

---

### 1.3 Skill 优化 ⭐⭐

#### 当前 Skills 分析
```yaml
# configs/equipment_deep_research/harness.yaml
skills:
  - strategic_osint: 事件时间线、行为体验证、来源交叉印证
  - threat_forecasting: 指标预警、情景区间、竞争假设
  - equipment_osint: 型号归一、参数区间、批次差异
```

#### 优化方向
1. **Skill 预编译**：将常用推理模式编译为 few-shot 示例
2. **Skill 链式调用**：支持 Skill 间组合
3. **Skill 性能监控**：跟踪 Skill 使用效果

**实施**:
```python
# 新增 Skill 管理器
class SkillOrchestrator:
    def __init__(self):
        self.skills = self._load_skills()
        self.chains = self._build_skill_chains()
        self.metrics = SkillMetrics()
    
    def suggest_skills(self, task: Task) -> list[Skill]:
        """基于任务特征推荐 Skill"""
        return self.skill_recommender.recommend(task)
    
    def chain_skills(self, skills: list[Skill]) -> SkillChain:
        """构建 Skill 链"""
        return SkillChain(skills, optimizer=self.optimizer)
```

**收益**:
- Skill 使用准确率 ↑ 20%
- 推理链路优化 ↓ 15% 时间

---

### 1.4 证据质量门控 ⭐⭐⭐

#### 问题
- 当前接受率：60-80%
- 大量低质量证据材料化后被拒绝
- 浪费网络 I/O 和处理时间

#### 方案
```python
class SmartEvidenceGate:
    """智能证据门控"""
    
    def __init__(self):
        self.pre_filter = PreMaterializationFilter()
        self.quality_predictor = EvidenceQualityPredictor()
    
    async def filter_candidates(
        self, 
        candidates: list[Evidence]
    ) -> list[Evidence]:
        """材料化前过滤"""
        
        # 快速过滤明显不合格的
        filtered = self.pre_filter.filter(candidates)
        
        # 预测质量分数
        scored = await self.quality_predictor.score_batch(filtered)
        
        # 优先级排序
        sorted_candidates = sorted(
            scored, 
            key=lambda x: x.predicted_quality,
            reverse=True
        )
        
        return sorted_candidates[:target_count * 1.5]  # 适度冗余
```

**收益**:
- 材料化成功率 ↑ 到 85%+
- 减少无效材料化 ↓ 40%
- 节省 5-10秒/agent

---

## 二、执行速度优化（性能提升）

### 2.1 已完成的优化 ✅

1. **工具授权缓存** - 减少 5-15ms/turn
2. **并发度提升** - Wave 时间减少 50-70%
3. **Codex Prompt 优化** - 减少 2-10ms/call
4. **命令构建缓存** - 减少 5-15ms/call

### 2.2 进程池优化 ⭐⭐⭐⭐⭐ (最高优先级)

#### 当前瓶颈
- 每次 Codex 调用启动新进程：300-750ms
- 18 次调用（6 agent × 3 turns）= 5.4-13.5秒纯开销

#### 方案 A：持久化进程池（推荐）

```python
class CodexProcessPool:
    """持久化 Codex 进程池"""
    
    def __init__(self, pool_size: int = 4):
        self.pool = []
        self.ready_queue = asyncio.Queue(maxsize=pool_size)
        self._init_pool(pool_size)
    
    def _init_pool(self, size: int):
        """预启动进程"""
        for i in range(size):
            proc = self._spawn_persistent_codex(
                worker_id=f"pool-{i}",
                mode="server"  # 服务器模式
            )
            self.pool.append(proc)
            self.ready_queue.put_nowait(proc)
    
    async def execute(self, prompt: str, options: dict) -> dict:
        """从池中获取进程执行"""
        worker = await self.ready_queue.get()
        try:
            # 通过 IPC 发送任务
            result = await worker.execute_task({
                'prompt': prompt,
                'options': options
            })
            return result
        finally:
            await self.ready_queue.put(worker)
```

**实施步骤**:
1. 修改 Codex CLI 支持服务器模式（接受多个任务）
2. 实现基于管道/socket的进程通信
3. 实现任务队列和负载均衡

**收益**:
- 消除 300-750ms 启动开销
- 单次调用加速 30-50%
- **总体提升 20-35%**

#### 方案 B：预热进程缓存（快速实施）

```python
class WarmProcessCache:
    """预热进程缓存（当前可用）"""
    
    def __init__(self):
        self.warm_pool = asyncio.Queue(maxsize=4)
        asyncio.create_task(self._maintain_pool())
    
    async def _maintain_pool(self):
        while True:
            if self.warm_pool.qsize() < 2:
                # 后台预启动进程
                proc_env = await self._prepare_env()
                await self.warm_pool.put(proc_env)
            await asyncio.sleep(0.5)
    
    async def get_env(self) -> dict:
        """获取预热环境"""
        try:
            env = self.warm_pool.get_nowait()
            if not self._is_expired(env):
                return env
        except asyncio.QueueEmpty:
            pass
        return await self._prepare_env()
```

**收益**:
- 减少 40-60% 启动时间
- 实施简单，2-3天完成
- **提升 10-15%**

---

### 2.3 智能预取 ⭐⭐⭐

#### 当前问题
- 串行等待模型响应
- 下一个 Agent 等待前一个完成

#### 方案：预测性预取

```python
class PredictivePrefetcher:
    """预测性预取器"""
    
    def __init__(self):
        self.predictor = NextAgentPredictor()
        self.prefetch_cache = {}
    
    async def prefetch_next_agents(
        self, 
        current_agent: Agent,
        context: dict
    ):
        """预测并预取下一波 Agent 需要的资源"""
        
        # 预测下一批 Agent
        next_agents = self.predictor.predict(
            current_agent, 
            context
        )
        
        for agent in next_agents:
            # 后台预热环境
            asyncio.create_task(self._prefetch_agent_env(agent))
            
            # 预加载可能需要的证据
            asyncio.create_task(self._prefetch_evidence(agent, context))
    
    async def _prefetch_agent_env(self, agent: Agent):
        """预热 Agent 环境"""
        env = await prepare_agent_environment(agent)
        self.prefetch_cache[agent.agent_id] = env
```

**收益**:
- 减少等待时间 20-30%
- 提升用户体验

---

### 2.4 流式处理 ⭐⭐⭐

#### 方案：Pipeline 架构

```python
class StreamingPipeline:
    """流式处理管道"""
    
    def __init__(self):
        self.stages = [
            Stage('discovery', self.discovery_stage),
            Stage('materialization', self.materialization_stage),
            Stage('analysis', self.analysis_stage),
            Stage('synthesis', self.synthesis_stage),
        ]
    
    async def run(self, task: Task):
        """流式执行"""
        async with create_pipeline() as pipeline:
            async for item in pipeline.stream(task):
                # 每个阶段完成立即传递给下一阶段
                yield item
```

**实施**:
1. 将线性执行改为流式管道
2. 证据材料化完成一个立即分析一个
3. 分析完成立即传递给制胜机理

**收益**:
- 减少总体等待时间 15-25%
- 提早获得部分结果

---

### 2.5 增量计算 ⭐⭐

#### 方案：缓存中间结果

```python
class IncrementalComputation:
    """增量计算管理器"""
    
    def __init__(self):
        self.cache = PersistentCache()
        self.hasher = ContentHasher()
    
    async def compute_with_cache(
        self,
        input_data: dict,
        compute_fn: Callable
    ) -> dict:
        """带缓存的计算"""
        
        # 计算输入哈希
        input_hash = self.hasher.hash(input_data)
        
        # 检查缓存
        if cached := self.cache.get(input_hash):
            return cached
        
        # 计算
        result = await compute_fn(input_data)
        
        # 缓存结果
        self.cache.put(input_hash, result)
        return result
```

**应用场景**:
- 相同主题的重复研究
- Recall 时复用已有分析
- 制胜机理阶段复用

**收益**:
- Recall 场景加速 50%+
- 相似主题研究加速 30%+

---

## 三、架构优化

### 3.1 分布式执行 ⭐⭐⭐⭐

#### 当前架构
```
单机 Worker → 串行/有限并发
```

#### 优化架构
```
           ┌──────────────┐
           │ API Gateway  │
           └──────┬───────┘
                  │
         ┌────────┴────────┐
         │  Task Queue     │
         │  (Redis)        │
         └────────┬────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
┌───▼───┐    ┌───▼───┐    ┌───▼───┐
│Worker1│    │Worker2│    │Worker3│
│(4 GPU)│    │(4 GPU)│    │(4 GPU)│
└───────┘    └───────┘    └───────┘
```

**实施**:
1. 任务队列（Redis/RabbitMQ）
2. Worker 横向扩展
3. 负载均衡

**收益**:
- 吞吐量 ↑ 3-10倍
- 支持并发用户

---

### 3.2 资源池化 ⭐⭐⭐

#### 方案
```python
class ResourcePool:
    """统一资源池"""
    
    def __init__(self):
        self.codex_pool = CodexProcessPool(size=8)
        self.evidence_pool = EvidenceMaterializationPool(size=12)
        self.model_pool = ModelConnectionPool(size=4)
    
    async def acquire(self, resource_type: str):
        """获取资源"""
        if resource_type == 'codex':
            return await self.codex_pool.acquire()
        elif resource_type == 'evidence':
            return await self.evidence_pool.acquire()
        # ...
```

**收益**:
- 资源利用率 ↑ 30-50%
- 减少资源竞争

---

## 四、优化实施路线图

### Phase 1: 快速优化（已完成） ✅
**时间**: 完成
**收益**: 40-60% 提升

1. ✅ 工具授权缓存
2. ✅ 并发度优化
3. ✅ Codex Prompt 优化
4. ✅ 命令构建缓存
5. ✅ 性能监控

---

### Phase 2: 进程池优化（1-2周） 🔄
**时间**: 1-2周
**收益**: +20-35% 提升

1. **Week 1**: 预热进程缓存（快速方案）
   - 实现 WarmProcessCache
   - 集成到 CodexCliProvider
   - 测试和调优
   
2. **Week 2**: 持久化进程池设计
   - 设计 IPC 协议
   - 实现进程服务器模式
   - 实现任务队列

**里程碑**:
- Day 3: 预热缓存上线
- Day 7: 进程池原型
- Day 14: 进程池生产就绪

---

### Phase 3: 质量提升（2-3周） 🔄
**时间**: 2-3周
**收益**: +15-25% 质量提升

1. **Week 1**: 上下文优化
   - 实现智能压缩
   - 跨 Agent 记忆
   
2. **Week 2**: 工具增强
   - 参数自动修复
   - 结果缓存
   
3. **Week 3**: 证据门控
   - 质量预测模型
   - 预过滤机制

---

### Phase 4: 架构演进（4-8周） 🔮
**时间**: 4-8周
**收益**: +2-10倍吞吐量

1. **Week 1-2**: 流式处理
2. **Week 3-4**: 增量计算
3. **Week 5-6**: 分布式队列
4. **Week 7-8**: 横向扩展

---

## 五、性能目标

### 当前性能
| 指标 | 当前 | 已优化 | Phase 2后 | Phase 3后 | 最终目标 |
|------|------|--------|-----------|-----------|----------|
| 完整研究 | 15-30分钟 | 9-18分钟 | 7-12分钟 | 6-10分钟 | **< 5分钟** |
| Baseline Wave | 5-10分钟 | 2-4分钟 | 1.5-3分钟 | 1.5-2.5分钟 | **< 2分钟** |
| 单 Agent | 45-60秒 | 30-42秒 | 20-30秒 | 18-25秒 | **< 30秒** |
| 证据材料化 | 15-25秒 | 6-12秒 | 4-8秒 | 3-6秒 | **< 5秒** |

### 质量目标
| 指标 | 当前 | 目标 |
|------|------|------|
| 工具调用成功率 | 70-85% | 95%+ |
| 证据接受率 | 60-80% | 85%+ |
| Recall 率 | 30-40% | < 20% |
| 审计通过率 | 80-90% | 95%+ |

---

## 六、监控指标

### 性能指标
```python
metrics = {
    # 执行时间
    'agent_execution_time': histogram,
    'codex_process_start_time': histogram,
    'evidence_materialization_time': histogram,
    
    # 吞吐量
    'tasks_per_hour': counter,
    'agents_per_minute': counter,
    
    # 资源利用
    'codex_pool_utilization': gauge,
    'evidence_pool_utilization': gauge,
    
    # 缓存效率
    'command_cache_hit_rate': gauge,
    'authorization_cache_hit_rate': gauge,
}
```

### 质量指标
```python
quality_metrics = {
    # 成功率
    'tool_call_success_rate': gauge,
    'evidence_acceptance_rate': gauge,
    'audit_pass_rate': gauge,
    
    # 召回
    'recall_request_count': counter,
    'recall_success_rate': gauge,
    
    # 置信度
    'average_confidence': gauge,
    'low_confidence_rate': gauge,
}
```

---

## 七、风险与缓解

### 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 进程池不稳定 | 中 | 高 | 渐进式部署、降级机制 |
| 缓存失效 | 低 | 中 | 版本管理、自动失效 |
| 并发竞争 | 中 | 中 | 锁机制、事务隔离 |

### 质量风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 上下文丢失 | 中 | 高 | 智能摘要、关键信息保留 |
| 工具调用错误增加 | 低 | 中 | 充分测试、渐进部署 |
| 证据质量下降 | 低 | 高 | A/B 测试、人工审核 |

---

## 八、总结

### 已完成
✅ 并发优化 - 50-70% 提升  
✅ 缓存优化 - 10-15% 提升  
✅ Codex 优化 - 3-4% 提升  
✅ 监控框架 - 完整覆盖  

### 进行中
🔄 进程池设计  
🔄 质量提升方案  

### 待启动
⏳ 流式处理  
⏳ 分布式架构  

### 最终目标
🎯 完整研究 < 5分钟（当前 15-30分钟）  
🎯 执行质量 95%+（当前 70-85%）  
🎯 吞吐量 10倍（分布式）  

---

**下一步行动**: 实施 Phase 2 进程池优化，预期 1-2周完成，性能提升 20-35%
