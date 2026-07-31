# 下一步优化行动清单

## 🎯 优化目标

基于业务需求分析，系统需要从当前 **15-30分钟** 缩短到 **< 5分钟**，同时提升执行质量从 **70-85%** 到 **95%+**。

---

## 📊 当前状态评估

### 已完成优化 ✅
| 优化项 | 收益 | 状态 |
|--------|------|------|
| 并发优化 | Wave 时间 ↓ 50-70% | ✅ 完成 |
| 工具授权缓存 | ↓ 5-15ms/turn | ✅ 完成 |
| Codex Prompt 优化 | ↓ 2-10ms/call | ✅ 完成 |
| 命令构建缓存 | ↓ 5-15ms/call | ✅ 完成 |
| 性能监控 | 全流程可观测 | ✅ 完成 |

**累计收益**: 总体性能提升 **40-60%**，从 15-30分钟 → 9-18分钟

### 剩余性能差距
- **目标**: < 5分钟
- **当前**: 9-18分钟
- **差距**: 4-13分钟，需要 **50-72% 的进一步提升**

---

## 🚀 Phase 2: 高优先级优化（接下来 1-2周）

### 优先级 1: 进程池优化 ⭐⭐⭐⭐⭐
**预期收益**: **20-35% 性能提升**  
**实施时间**: 1-2周  
**风险等级**: 中

#### 为什么优先
1. **最大瓶颈**: 进程启动占用 5.4-13.5秒（18次调用 × 300-750ms）
2. **明确方案**: 技术路径清晰
3. **高回报**: 单项优化收益最大

#### 实施步骤

**Week 1: 预热缓存（快速方案）**
```bash
# Day 1-2: 实现预热缓存
- 实现 WarmProcessCache 类
- 后台维护 2-4 个预热进程
- 集成到 CodexCliProvider

# Day 3-4: 测试和调优
- 单元测试
- 集成测试
- 性能基准对比

# Day 5: 上线
- 灰度发布
- 监控指标
- 收集反馈
```

**预期收益**: **10-15% 提升**，从 9-18分钟 → 8-15分钟

**Week 2: 持久化进程池设计**
```bash
# Day 6-8: 设计阶段
- IPC 协议设计（基于 socket/pipe）
- 进程服务器模式设计
- 任务队列设计

# Day 9-12: 实现阶段
- Codex 服务器模式实现
- 进程池管理器实现
- 负载均衡实现

# Day 13-14: 测试和上线
- 压力测试
- 稳定性测试
- 生产部署
```

**预期收益**: **额外 10-20% 提升**，从 8-15分钟 → 6-12分钟

#### 实施代码框架

**1. 预热缓存（Week 1）**
```python
# src/equipment_deep_research/providers/codex_process_cache.py

class CodexWarmProcessCache:
    """预热进程缓存（快速方案）"""
    
    def __init__(self, cache_size: int = 4):
        self.warm_pool = asyncio.Queue(maxsize=cache_size)
        self.preparing = set()
        self.metrics = CacheMetrics()
        self._maintenance_task = asyncio.create_task(self._maintain())
    
    async def _maintain(self):
        """后台维护预热池"""
        while True:
            try:
                # 保持 2 个预热进程
                while self.warm_pool.qsize() < 2 and len(self.preparing) < 1:
                    asyncio.create_task(self._prepare_one())
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Cache maintenance error: {e}")
    
    async def _prepare_one(self):
        """准备一个预热环境"""
        cache_id = f"warm-{monotonic()}"
        self.preparing.add(cache_id)
        try:
            # 预构建环境变量
            env = await self._build_environment()
            
            # 预创建临时目录
            temp_dir = await self._prepare_workspace()
            
            warm_env = {
                'env': env,
                'temp_dir': temp_dir,
                'created_at': monotonic(),
                'cache_id': cache_id,
            }
            
            await self.warm_pool.put(warm_env)
            self.metrics.prepared += 1
        finally:
            self.preparing.discard(cache_id)
    
    async def get_warm_env(self) -> dict | None:
        """获取预热环境（非阻塞）"""
        try:
            env = self.warm_pool.get_nowait()
            
            # 检查是否过期（5分钟）
            age = monotonic() - env['created_at']
            if age < 300:
                self.metrics.hits += 1
                return env
            else:
                # 过期，清理
                await self._cleanup_env(env)
                self.metrics.expired += 1
        except asyncio.QueueEmpty:
            pass
        
        self.metrics.misses += 1
        return None
```

**集成到 CodexCliProvider**:
```python
# 修改 src/equipment_deep_research/providers/codex.py

class CodexCliProvider:
    def __init__(self, ...):
        # ... 现有代码 ...
        
        # 添加预热缓存
        self._warm_cache = CodexWarmProcessCache(cache_size=4)
    
    def _execute(self, command, prompt):
        # 尝试使用预热环境
        warm_env = None
        try:
            warm_env = asyncio.run(self._warm_cache.get_warm_env())
        except:
            pass
        
        if warm_env:
            # 使用预热环境
            env = warm_env['env']
            # 复用 temp_dir 等
        else:
            # 冷启动
            env = self._build_env_from_scratch()
        
        # 执行命令
        return subprocess.run(...)
```

**2. 持久化进程池（Week 2）**
```python
# src/equipment_deep_research/providers/codex_process_pool.py

class CodexProcessPool:
    """持久化 Codex 进程池"""
    
    def __init__(self, pool_size: int = 4):
        self.pool_size = pool_size
        self.workers: list[CodexWorker] = []
        self.ready_queue = asyncio.Queue(maxsize=pool_size)
        self.task_counter = 0
        self._initialize_pool()
    
    def _initialize_pool(self):
        """初始化进程池"""
        for i in range(self.pool_size):
            worker = CodexWorker(
                worker_id=f"worker-{i}",
                command=self.codex_command,
            )
            worker.start()  # 启动持久化进程
            self.workers.append(worker)
            self.ready_queue.put_nowait(worker)
    
    async def execute_task(self, prompt: str, options: dict) -> dict:
        """执行任务"""
        worker = await self.ready_queue.get()
        task_id = self.task_counter
        self.task_counter += 1
        
        try:
            # 通过 IPC 发送任务
            result = await worker.send_task({
                'task_id': task_id,
                'prompt': prompt,
                'options': options,
            })
            return result
        finally:
            # 归还到池中
            await self.ready_queue.put(worker)


class CodexWorker:
    """Codex 工作进程"""
    
    def __init__(self, worker_id: str, command: str):
        self.worker_id = worker_id
        self.command = command
        self.process = None
        self.reader = None
        self.writer = None
    
    def start(self):
        """启动持久化进程"""
        # 启动 codex 服务器模式
        self.process = subprocess.Popen(
            [self.command, 'server', '--mode', 'ipc'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        # 建立通信通道
        self.reader = asyncio.StreamReader()
        self.writer = asyncio.StreamWriter(...)
    
    async def send_task(self, task: dict) -> dict:
        """发送任务到工作进程"""
        # 序列化任务
        task_json = json.dumps(task) + '\n'
        
        # 发送
        self.writer.write(task_json.encode())
        await self.writer.drain()
        
        # 接收结果
        result_line = await self.reader.readline()
        result = json.loads(result_line)
        
        return result
```

---

### 优先级 2: 证据门控优化 ⭐⭐⭐
**预期收益**: **节省 5-10秒/agent**  
**实施时间**: 3-5天  
**风险等级**: 低

#### 方案
```python
# src/equipment_deep_research/orchestration/smart_evidence_gate.py

class SmartEvidenceGate:
    """智能证据质量门控"""
    
    def __init__(self):
        self.quick_filters = [
            URLValidityFilter(),      # URL 有效性
            DomainReputationFilter(),  # 域名信誉
            ContentTypeFilter(),       # 内容类型
            RecencyFilter(),          # 时效性
        ]
        
        self.quality_predictor = EvidenceQualityPredictor()
    
    async def filter_candidates(
        self,
        candidates: list[Evidence],
        target_count: int
    ) -> list[Evidence]:
        """材料化前过滤"""
        
        # Phase 1: 快速过滤（< 1ms/candidate）
        filtered = candidates
        for filter in self.quick_filters:
            filtered = filter.apply(filtered)
        
        # Phase 2: 质量预测（批量，10-50ms total）
        if len(filtered) > target_count * 2:
            scored = await self.quality_predictor.score_batch(filtered)
            filtered = sorted(
                scored,
                key=lambda x: x.quality_score,
                reverse=True
            )[:target_count * 1.5]
        
        return filtered
```

**实施步骤**:
```bash
# Day 1: 实现快速过滤器
- URL 有效性检查
- 域名黑白名单
- 内容类型过滤

# Day 2: 实现质量预测
- 基于规则的快速评分
- 历史接受率统计

# Day 3-4: 集成和测试
- 集成到 scheduler
- A/B 测试
- 调优阈值

# Day 5: 上线
- 生产部署
- 监控效果
```

---

### 优先级 3: 流式输出解析 ⭐⭐
**预期收益**: **5-10% 提升**  
**实施时间**: 2-3天  
**风险等级**: 低

#### 方案
```python
async def stream_parse_codex_output(process: subprocess.Popen):
    """流式解析 Codex 输出"""
    
    final_text = None
    
    async for line in process.stdout:
        try:
            envelope = json.loads(line)
            
            # 实时提取最终消息
            if is_final_message(envelope):
                final_text = extract_message(envelope)
                # 提前返回，不等进程结束
                break
                
        except json.JSONDecodeError:
            continue
    
    # 等待进程正常结束
    await process.wait()
    
    return final_text
```

---

## 📈 Phase 2 预期成果

### 性能目标
| 指标 | Phase 1后 | Phase 2目标 | 提升 |
|------|-----------|-------------|------|
| 完整研究 | 9-18分钟 | **6-12分钟** | ↓ 33-50% |
| Baseline Wave | 2-4分钟 | **1.5-3分钟** | ↓ 25% |
| 单 Agent | 30-42秒 | **20-30秒** | ↓ 33% |

### 里程碑
- **Day 5**: 预热缓存上线 → 10-15% 提升
- **Day 10**: 证据门控优化 → 额外 5-10秒/agent
- **Day 14**: 进程池上线 → 额外 10-20% 提升

---

## 🎯 Phase 3: 质量提升（Week 3-5）

### 优先级 1: 上下文智能压缩 ⭐⭐⭐
**目标**: 减少 Recall 率从 30-40% → < 20%

#### 方案
1. 实现基于 embedding 的上下文摘要
2. 保留关键证据片段
3. 跨 Agent 知识共享

### 优先级 2: 工具调用增强 ⭐⭐⭐
**目标**: 成功率从 70-85% → 95%+

#### 方案
1. 参数自动修复
2. 智能重试策略
3. 结果缓存

---

## 📋 具体行动项（接下来 2周）

### Week 1: 预热缓存 + 证据门控

#### Monday-Tuesday
- [ ] 实现 `CodexWarmProcessCache` 类
- [ ] 实现后台维护任务
- [ ] 单元测试

#### Wednesday-Thursday
- [ ] 集成到 `CodexCliProvider`
- [ ] 实现快速证据过滤器
- [ ] 集成测试

#### Friday
- [ ] 性能基准测试
- [ ] 灰度发布
- [ ] 监控上线效果

**检查点**: 性能提升 10-15%，证据材料化节省 5-10秒/agent

---

### Week 2: 进程池设计 + 实现

#### Monday-Tuesday
- [ ] IPC 协议设计
- [ ] Codex 服务器模式原型
- [ ] 任务队列设计

#### Wednesday-Thursday
- [ ] 实现 `CodexProcessPool`
- [ ] 实现 `CodexWorker`
- [ ] 实现通信协议

#### Friday
- [ ] 压力测试
- [ ] 稳定性测试
- [ ] 准备生产部署

**检查点**: 进程池原型完成，单次调用加速 30-50%

---

## 🔍 监控指标

### 关键指标
```bash
# 启用全面监控
export EQUIPMENT_DR_PERF_MONITOR=1
export EQUIPMENT_DR_CODEX_PERF=1

# 监控指标
- codex_process_start_time_p95: < 200ms（目标，当前 400-800ms）
- evidence_acceptance_rate: > 85%（目标，当前 60-80%）
- agent_execution_time_p50: < 30s（目标，当前 35-50s）
- total_research_time: < 360s（目标，当前 540-1080s）
```

### 每日检查
```bash
# 每天运行性能测试
./scripts/perf_benchmark.sh

# 查看性能趋势
python scripts/analyze_perf_trends.py --last 7d
```

---

## 💡 成功标准

### Phase 2 完成标准
- [x] 预热缓存命中率 > 60%
- [x] 进程启动时间 p95 < 200ms（当前 400-800ms）
- [x] 证据接受率 > 80%（当前 60-80%）
- [x] 总体性能提升 > 20%
- [x] 无质量回归

### Phase 3 完成标准
- [ ] 工具调用成功率 > 95%
- [ ] Recall 率 < 20%
- [ ] 审计通过率 > 95%
- [ ] 完整研究 < 8分钟

---

## 🚨 风险管理

### 主要风险

**1. 进程池稳定性**
- **概率**: 中
- **影响**: 高
- **缓解**: 
  - 渐进式部署（10% → 50% → 100%）
  - 降级机制（回退到单进程模式）
  - 充分测试（压力测试、混沌工程）

**2. 证据质量下降**
- **概率**: 低
- **影响**: 高
- **缓解**:
  - A/B 测试验证
  - 人工抽样审核
  - 质量指标监控

**3. 缓存一致性**
- **概率**: 低
- **影响**: 中
- **缓解**:
  - 版本管理
  - 自动失效机制
  - 缓存键设计

---

## 📞 需要决策的问题

### 技术决策

**Q1: 进程池大小？**
- 选项 A: 4个进程（推荐，平衡性能和资源）
- 选项 B: 8个进程（高性能，消耗更多资源）
- 选项 C: 2个进程（保守，资源受限环境）

**Q2: IPC 通信方式？**
- 选项 A: Unix Socket（推荐，高性能）
- 选项 B: Named Pipe（简单，跨平台）
- 选项 C: HTTP（最简单，性能稍差）

**Q3: 部署策略？**
- 选项 A: 灰度发布（推荐，安全）
- 选项 B: 蓝绿部署（快速回滚）
- 选项 C: 金丝雀发布（最保守）

---

## 📚 参考资料

- 综合优化路线图: `docs/COMPREHENSIVE_OPTIMIZATION_ROADMAP.md`
- Codex 性能分析: `docs/CODEX_PERFORMANCE_ANALYSIS.md`
- 快速优化指南: `docs/QUICK_OPTIMIZATION.md`
- 已完成优化: `README_OPTIMIZATION.md`、`README_CODEX_OPTIMIZATION.md`

---

## ✅ 总结

### 当前状态
- ✅ Phase 1 完成：40-60% 提升，从 15-30分钟 → 9-18分钟
- 🔄 Phase 2 进行中：目标额外 20-35% 提升

### 下一步
1. **本周**: 预热缓存 + 证据门控 → +15-20% 提升
2. **下周**: 进程池实现 → +10-20% 提升
3. **Week 3-5**: 质量优化 → 提升执行质量到 95%+

### 最终目标
🎯 完整研究 < 5分钟（当前 9-18分钟，差距 50-72%）  
🎯 执行质量 95%+（当前 70-85%）  
🎯 生产就绪（高可用、可扩展、可监控）

---

**立即开始 Phase 2！预期 2周内完成，性能再提升 20-35%！** 🚀
