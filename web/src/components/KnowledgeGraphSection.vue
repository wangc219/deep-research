<template>
  <div class="graph-section" v-if="isGraphSupported">
    <div class="graph-container-compact">
      <div v-if="!isGraphSupported" class="graph-disabled">
        <div class="disabled-content">
          <h4>知识图谱不可用</h4>
          <p>当前知识库类型 "{{ kbTypeLabel }}" 不支持知识图谱功能。</p>
          <p>只有本平台类型的知识库支持知识图谱。</p>
        </div>
      </div>
      <div v-else class="graph-wrapper">
        <GraphCanvas
          ref="graphRef"
          :graph-data="graph.graphData"
          :layout-mode="layoutMode"
          @node-click="handleNodeDetailClick"
          @edge-click="handleEdgeDetailClick"
          @canvas-click="handleCanvasDetailClick"
        >
          <template #top>
            <div class="compact-actions">
              <div class="actions-left">
                <a-input
                  v-model:value="searchInput"
                  placeholder="搜索实体"
                  class="graph-search-input"
                  @keydown.enter="onSearch"
                  allow-clear
                >
                  <template #suffix>
                    <component
                      :is="graph.fetching ? Loader2 : Search"
                      :size="14"
                      class="search-suffix-icon"
                      @click="onSearch"
                    />
                  </template>
                </a-input>
                <a-button class="action-btn" @click="loadGraph" title="刷新">
                  <RefreshCw :size="16" :class="{ spin: graph.fetching }" />
                </a-button>
                <a-button class="action-btn" @click="openPathDiscovery" title="链路发现">
                  <Waypoints :size="16" />
                </a-button>
              </div>
              <div class="actions-right">
                <div class="layout-control" title="切换图谱排列方式">
                  <span class="layout-control-label">布局</span>
                  <div class="layout-options" role="group" aria-label="图谱布局">
                    <button
                      v-for="option in layoutOptions"
                      :key="option.value"
                      type="button"
                      class="layout-option"
                      :class="{ active: layoutMode === option.value }"
                      :aria-pressed="layoutMode === option.value"
                      @click="setLayoutMode(option.value)"
                    >
                      {{ option.label }}
                    </button>
                  </div>
                </div>
                <a-button
                  v-if="isMilvus && !readonly"
                  class="action-btn"
                  title="人工审核"
                  aria-label="打开知识图谱人工审核"
                  @click="showReviewWorkbench = true"
                >
                  <ClipboardCheck :size="16" />
                </a-button>
                <a-button
                  v-if="isMilvus && !readonly"
                  class="action-btn index-action-btn"
                  :class="{ 'has-index-label': hasPendingGraphChunks }"
                  @click="toggleBuildPanel"
                  :title="graphIndexButtonTitle"
                  :aria-label="graphIndexButtonTitle"
                >
                  <Database :size="16" />
                  <span v-if="hasPendingGraphChunks" class="index-status-label"
                    >{{ pendingGraphChunks }} 待索引</span
                  >
                  <span
                    v-if="graphIndexDotStatus"
                    class="status-dot"
                    :class="`status-dot--${graphIndexDotStatus}`"
                  ></span>
                </a-button>
                <a-button class="action-btn" @click="toggleSettingsPanel" title="设置">
                  <Settings :size="16" />
                </a-button>
                <a-button
                  v-if="isMilvus"
                  class="action-btn labeled-action"
                  title="文档知识审计与高价值重点复抽"
                  aria-label="打开文档知识卡与研究链审计"
                  @click="showDocumentAudit = true"
                >
                  <FileSearch :size="16" />
                  <span>知识审计</span>
                </a-button>
                <a-button
                  v-if="isMilvus"
                  class="action-btn"
                  title="图谱版本历史"
                  aria-label="打开图谱版本与变更历史"
                  @click="showRevisionHistory = true"
                >
                  <History :size="16" />
                </a-button>
              </div>
            </div>
            <nav class="graph-workflow-rail" aria-label="知识图谱全流程导航">
              <button
                v-for="step in graphWorkflowSteps"
                :key="step.key"
                type="button"
                class="graph-workflow-step"
                :class="`graph-workflow-step--${step.status}`"
                :aria-current="step.status === 'active' ? 'step' : undefined"
                @click="step.action"
              >
                <span class="graph-workflow-step__icon">
                  <component :is="step.icon" :size="15" />
                </span>
                <span>
                  <strong>{{ step.label }}</strong>
                  <small>{{ step.detail }}</small>
                </span>
              </button>
            </nav>
          </template>
        </GraphCanvas>
        <ResourceEmptyState
          v-if="showGraphConfigEmpty"
          class="graph-empty-state"
          title="暂无知识图谱"
          :description="
            readonly
              ? '图谱尚未构建，请等待知识库管理员配置抽取器并索引后查看。'
              : '配置抽取器后，才能从当前知识库构建实体与关系。'
          "
          :icon="Network"
          full-height
        >
          <template v-if="!readonly" #actions>
            <a-button type="primary" class="lucide-icon-btn" @click="openGraphConfig">
              <Settings :size="16" />
              配置抽取器
            </a-button>
          </template>
        </ResourceEmptyState>
        <ResourceEmptyState
          v-else-if="showGraphDataEmpty"
          class="graph-empty-state"
          :title="graphDataEmptyTitle"
          :description="graphDataEmptyDescription"
          :icon="Network"
          full-height
        >
          <template #actions>
            <a-button v-if="searchInput.trim()" class="lucide-icon-btn" @click="clearGraphSearch">
              <Search :size="16" />
              清空搜索
            </a-button>
            <template v-else-if="hasReviewableKnowledge">
              <a-button class="lucide-icon-btn" @click="showDocumentAudit = true">
                <FileSearch :size="16" />
                查看知识审计
              </a-button>
              <a-button
                v-if="!readonly"
                type="primary"
                class="lucide-icon-btn"
                @click="showReviewWorkbench = true"
              >
                <ClipboardCheck :size="16" />
                审核候选知识
              </a-button>
            </template>
            <a-button
              v-else-if="!readonly && hasPendingGraphChunks && !isBuildActive"
              type="primary"
              class="lucide-icon-btn"
              @click="startGraphBuild"
            >
              <Database :size="16" />
              开始索引
            </a-button>
            <a-button v-else class="lucide-icon-btn" @click="loadGraph">
              <RefreshCw :size="16" :class="{ spin: graph.fetching }" />
              刷新图谱
            </a-button>
          </template>
        </ResourceEmptyState>

        <!-- 详情浮动卡片 -->
        <GraphDetailPanel
          :visible="graph.showDetailDrawer"
          :item="graph.selectedItem"
          :type="graph.selectedItemType"
          :authoritative-eligible="Boolean(authorityReference)"
          :authoritative-detail="authorityDetail"
          :authoritative-loading="authorityLoading"
          :authoritative-loading-more="authorityLoadingMore"
          :authoritative-can-load-more="authorityCanLoadMore"
          :authoritative-load-more-error="authorityLoadMoreError"
          :authoritative-error="authorityError"
          @load-more="authority.loadMore"
          @close="handleCanvasDetailClick"
        />

        <!-- 设置浮动面板 -->
        <transition name="slide-fade">
          <div v-if="showSettings" class="floating-panel settings-panel">
            <div class="panel-header">
              <span class="panel-title">图谱设置</span>
            </div>
            <div class="panel-body">
              <a-form layout="vertical">
                <a-form-item label="最大节点数 (limit)">
                  <a-input-number
                    v-model:value="subgraphParams.maxNodes"
                    :min="10"
                    :max="1000"
                    :step="10"
                    style="width: 100%"
                  />
                </a-form-item>
                <a-form-item label="搜索深度 (depth)">
                  <a-input-number
                    v-model:value="subgraphParams.maxDepth"
                    :min="1"
                    :max="5"
                    :step="1"
                    style="width: 100%"
                  />
                </a-form-item>
                <a-form-item label="排除 Chunk 节点">
                  <a-switch v-model:checked="subgraphParams.excludeChunk" />
                </a-form-item>
                <a-form-item>
                  <a-button type="primary" @click="applySettings" style="width: 100%">
                    应用
                  </a-button>
                </a-form-item>
              </a-form>
            </div>
          </div>
        </transition>

        <!-- 索引管理浮动面板 -->
        <transition name="slide-fade">
          <div v-if="isMilvus && !readonly && showBuildPanel" class="floating-panel build-panel">
            <div class="panel-header">
              <span class="panel-title">索引管理</span>
              <a-button
                size="small"
                type="text"
                :disabled="graphBuildLoading"
                @click="loadGraphBuildStatus"
                class="panel-refresh-btn"
              >
                <RefreshCw :size="14" :class="{ spin: graphBuildLoading }" />
              </a-button>
            </div>
            <div class="panel-body">
              <div class="status-row">
                <span class="status-label">状态</span>
                <a-tag v-if="isBuildActive" color="blue" size="small">构建中</a-tag>
                <a-tag v-else-if="isBuildFailed" color="red" size="small">执行异常</a-tag>
                <a-tag
                  v-else-if="graphBuildStatus?.build_task_status === 'completed'"
                  color="green"
                  size="small"
                >
                  执行完成
                </a-tag>
                <a-tag v-else-if="graphBuildStatus?.locked" color="green" size="small">
                  已配置
                </a-tag>
                <a-tag v-else color="orange" size="small">未配置</a-tag>
              </div>
              <div v-if="graphBuildStatus?.locked" class="config-summary">
                <div>
                  <span class="config-summary-label">抽取配置</span>
                  <strong>{{ graphConfigSummary }}</strong>
                </div>
                <a-button size="small" type="link" @click="openGraphConfig">调整</a-button>
              </div>
              <a-progress
                v-if="isBuildActive"
                :percent="graphBuildStatus?.build_task_progress ?? 0"
                :stroke-color="{ '0%': '#108ee9', '100%': '#87d068' }"
                size="small"
                style="margin-bottom: 10px"
              />
              <div class="stats-grid">
                <div class="stat-item">
                  <span class="stat-value">{{ graphBuildStatus?.total_chunks ?? '-' }}</span>
                  <span class="stat-label">总 Chunk</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ graphBuildStatus?.pending_chunks ?? '-' }}</span>
                  <span class="stat-label">待构建</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ graphBuildStatus?.indexed_chunks ?? '-' }}</span>
                  <span class="stat-label">已构建</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ graphBuildStatus?.structured_chunks ?? '-' }}</span>
                  <span class="stat-label">结构完成</span>
                </div>
                <div
                  class="stat-item"
                  :class="{ 'is-clickable': extractionFailedCount > 0 }"
                  :role="extractionFailedCount > 0 ? 'button' : undefined"
                  :tabindex="extractionFailedCount > 0 ? 0 : undefined"
                  @click="openFailedChunkSamples"
                  @keydown.enter.prevent="openFailedChunkSamples"
                  @keydown.space.prevent="openFailedChunkSamples"
                >
                  <span class="stat-value">{{ extractionFailedCount }}</span>
                  <span class="stat-label">抽取失败</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ vectorPendingCount }}</span>
                  <span class="stat-label">向量待处理</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ vectorFailedCount }}</span>
                  <span class="stat-label">向量失败</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ graphBuildStatus?.entity_count ?? '-' }}</span>
                  <span class="stat-label">实体</span>
                </div>
                <div class="stat-item">
                  <span class="stat-value">{{ graphBuildStatus?.relationship_count ?? '-' }}</span>
                  <span class="stat-label">关系</span>
                </div>
              </div>
              <section class="acceptance-card" aria-label="知识图谱 Pilot 验收状态">
                <div class="acceptance-header">
                  <span>本地 Pilot 验收</span>
                  <a-tag v-if="acceptanceLoading" color="blue">读取中</a-tag>
                  <a-tag v-else-if="acceptanceStatus?.passed" color="green">已通过</a-tag>
                  <a-tag v-else color="orange">未通过</a-tag>
                </div>
                <div class="acceptance-scale-grid">
                  <div>
                    <strong
                      >{{ acceptanceStatus?.stats?.source_documents ?? 0 }}/{{
                        acceptanceStatus?.requirements?.source_documents ?? 999
                      }}</strong
                    >
                    <span>来源</span>
                  </div>
                  <div>
                    <strong
                      >{{ acceptanceStatus?.stats?.accepted_entities ?? 0 }}/{{
                        acceptanceStatus?.requirements?.accepted_entities ?? 5000
                      }}</strong
                    >
                    <span>实体</span>
                  </div>
                  <div>
                    <strong
                      >{{ acceptanceStatus?.stats?.accepted_relations ?? 0 }}/{{
                        acceptanceStatus?.requirements?.accepted_relations ?? 20000
                      }}</strong
                    >
                    <span>关系</span>
                  </div>
                </div>
                <div v-if="acceptanceStatus?.latest_evaluation" class="acceptance-quality-grid">
                  <span>实体 F1 {{ acceptanceMetric('entity_f1') }}</span>
                  <span>关系 F1 {{ acceptanceMetric('relation_f1') }}</span>
                  <span>对齐 {{ acceptanceMetric('alignment_accuracy') }}</span>
                  <span>证据回切 {{ acceptanceMetric('evidence_span_rebuild') }}</span>
                </div>
                <p v-else class="acceptance-note">尚未登记密封测试报告，验收按未通过处理。</p>
                <p v-if="acceptanceFailedSummary" class="acceptance-failures">
                  未通过：{{ acceptanceFailedSummary }}
                </p>
                <p class="acceptance-note">结论由后端权威报告判定，界面不自行放宽阈值。</p>
              </section>
              <GraphFailedRetryCard
                v-if="extractionFailedCount > 0"
                :count="extractionFailedCount"
                :loading="retryingFailedChunks"
                :disabled="isBuildActive"
                @retry="confirmRetryFailedGraphChunks"
              />
              <div class="build-actions">
                <a-button
                  v-if="!graphBuildStatus?.locked"
                  type="primary"
                  block
                  @click="openGraphConfig"
                >
                  配置抽取器
                </a-button>
                <a-button v-else-if="isBuildActive" type="primary" block disabled>
                  构建中 {{ graphBuildStatus?.build_task_progress ?? 0 }}%
                </a-button>
                <a-button
                  v-else-if="isBuildFailed"
                  type="primary"
                  block
                  :disabled="!graphBuildStatus?.pending_chunks"
                  @click="vectorFailedCount ? retryGraphVectors() : startGraphBuild()"
                >
                  {{ vectorFailedCount ? '重试失败向量' : '重试索引' }}
                </a-button>
                <a-button
                  v-else
                  type="primary"
                  block
                  :disabled="!graphBuildStatus?.pending_chunks"
                  @click="startGraphBuild"
                >
                  开始索引
                </a-button>
                <div class="actions-secondary">
                  <a-button
                    v-if="graphBuildStatus?.locked && !isBuildActive"
                    size="small"
                    type="text"
                    @click="openGraphConfig"
                  >
                    修改配置
                  </a-button>
                  <a-button
                    size="small"
                    type="text"
                    v-if="graphBuildStatus?.locked && !isBuildActive"
                    @click="confirmRebuildGraphProjections"
                    >重建投影</a-button
                  >
                </div>
              </div>
            </div>
          </div>
        </transition>
      </div>
    </div>

    <a-modal
      v-model:open="showGraphConfig"
      :title="graphConfigTitle"
      width="920px"
      wrap-class-name="graph-config-modal-wrap"
      ok-text="保存并应用"
      cancel-text="取消"
      :confirm-loading="graphConfigSaving"
      @ok="configureGraphBuild"
    >
      <a-form layout="vertical">
        <a-alert
          v-if="isEditingGraphConfig"
          class="config-warning"
          type="warning"
          show-icon
          message="修改配置仅影响后续构建；已构建的图谱不会自动重算，如需一致请重置后重新抽取。抽取器类型创建后不可修改。"
        />
        <a-form-item v-if="isLlmExtractor" label="抽取方案">
          <div class="extraction-presets">
            <button
              v-for="preset in GRAPH_EXTRACTION_PRESETS"
              :key="preset.key"
              type="button"
              class="extraction-preset"
              :class="{ active: activeExtractionPreset === preset.key }"
              @click="selectExtractionPreset(preset.key)"
            >
              <span class="preset-title">
                {{ preset.label }}
                <small v-if="preset.key === 'balanced'">推荐</small>
              </span>
              <span class="preset-values"
                >并发 {{ preset.concurrency_count }} · 超时 {{ preset.timeout_seconds }} 秒</span
              >
              <span class="preset-description">{{ preset.description }}</span>
            </button>
          </div>
          <div class="form-item-hint">
            选择方案即可完成常用运行参数；手动修改并发或超时后会显示为“自定义”。
          </div>
        </a-form-item>
        <a-alert
          v-if="isLlmExtractor && graphConfigRiskMessage"
          class="config-warning"
          type="warning"
          show-icon
          :message="graphConfigRiskMessage"
          description="建议直接选择‘均衡’或‘稳定’方案后保存。"
        />
        <a-form-item label="抽取器类型">
          <div class="extractor-type-cards" role="radiogroup" aria-label="抽取器类型">
            <div
              v-for="option in extractorTypeOptions"
              :key="option.value"
              class="extractor-type-card"
              :class="{
                active: graphConfigForm.extractor_type === option.value,
                disabled: isEditingGraphConfig || option.disabled
              }"
              role="radio"
              :aria-checked="graphConfigForm.extractor_type === option.value"
              :aria-disabled="isEditingGraphConfig || option.disabled"
              :tabindex="isEditingGraphConfig || option.disabled ? -1 : 0"
              @click="selectExtractorType(option)"
              @keydown.enter.prevent="selectExtractorType(option)"
              @keydown.space.prevent="selectExtractorType(option)"
            >
              <div class="card-header">
                <component :is="option.icon" class="type-icon" />
                <span class="type-title">{{ option.label }}</span>
              </div>
              <div class="card-description">{{ option.description }}</div>
              <div v-if="option.helper" class="card-helper" :class="{ warning: option.disabled }">
                {{ option.helper }}
              </div>
            </div>
          </div>
        </a-form-item>
        <section
          v-if="isLightRAGGraphExtractor"
          class="graph-config-guide"
          aria-labelledby="graph-config-guide-title"
        >
          <header class="graph-config-guide__header">
            <div>
              <span class="graph-config-guide__eyebrow">快速配置</span>
              <h3 id="graph-config-guide-title">三步完成轻量化 RAG 知识图谱构建设置</h3>
              <p>使用项目模型设置中的可更换 LLM；证据约束、文档增强与安全降级已采用推荐值。</p>
            </div>
            <a-tag color="blue">推荐配置已启用</a-tag>
          </header>

          <div class="graph-config-step">
            <div class="graph-config-step__index">1</div>
            <div class="graph-config-step__content">
              <div class="graph-config-step__heading">
                <div>
                  <h4>确认轻量化 RAG 主链</h4>
                  <p>项目 LLM 直接完成初抽、命名复核和查漏，不启动本地神经抽取 sidecar。</p>
                </div>
              </div>
              <a-alert
                type="success"
                show-icon
                message="轻量化 RAG / 项目 LLM 全链路"
                description="Chunk 可有界并发抽取，随后执行一次 gleaning、文档级补漏、跨文档关系与实体消歧；所有新增知识仍保留原文证据并进入待审核状态。"
              />
            </div>
          </div>

          <div class="graph-config-step">
            <div class="graph-config-step__index">2</div>
            <div class="graph-config-step__content">
              <div class="graph-config-step__heading">
                <div>
                  <h4>选择统一增强模型</h4>
                  <p>模型和凭证来自项目“模型设置”，不会启动本地 7B/MLX 模型。</p>
                </div>
                <a-button
                  size="small"
                  :disabled="!configStore.config?.default_model"
                  @click="applyDefaultGraphModel"
                >
                  使用项目默认模型
                </a-button>
              </div>
              <ModelSelectorComponent
                :model_spec="graphConfigForm.llm_enhancement_model_spec"
                placeholder="选择用于实体、关系和跨文档增强的项目模型"
                @select-model="selectUnifiedGraphModel"
              />
              <div class="form-item-hint">
                此处选择会同步到文档实体补抽、文档关系、跨文档关系和实体消歧；如需分别指定，可在高级设置中修改。
              </div>
            </div>
          </div>

          <div class="graph-config-step">
            <div class="graph-config-step__index">3</div>
            <div class="graph-config-step__content">
              <div class="graph-config-step__heading">
                <div>
                  <h4>确认增强范围</h4>
                  <p>推荐保持开启，首次构建即可获得文档内与跨文档关系。</p>
                </div>
              </div>
              <div class="graph-quick-switches">
                <label class="graph-quick-switch">
                  <span>
                    <strong>文档级增强</strong>
                    <small>跨段实体与关系补漏</small>
                  </span>
                  <a-switch v-model:checked="graphConfigForm.document_enhancement_enabled" />
                </label>
                <label class="graph-quick-switch">
                  <span>
                    <strong>跨文档关联</strong>
                    <small>发现多源共同技术链路</small>
                  </span>
                  <a-switch
                    v-model:checked="graphConfigForm.document_cross_relation_enabled"
                    :disabled="!graphConfigForm.document_enhancement_enabled"
                  />
                </label>
                <label class="graph-quick-switch">
                  <span>
                    <strong>高价值重点复抽</strong>
                    <small>优先识别新质军事技术弱信号</small>
                  </span>
                  <a-switch
                    v-model:checked="graphConfigForm.document_value_routing_enabled"
                    :disabled="!configStore.config?.default_model"
                  />
                </label>
              </div>
              <div v-if="!configStore.config?.default_model" class="form-item-hint">
                高价值重点复抽需要先在“模型设置”中指定项目默认模型；其余构建能力不受影响。
              </div>
              <div class="graph-pipeline-preview" aria-label="当前构建流程">
                <span
                  v-for="(stage, index) in activeOrchestrationOption.stages"
                  :key="stage"
                  class="graph-pipeline-preview__stage"
                >
                  {{ stage }}
                  <span
                    v-if="index < activeOrchestrationOption.stages.length - 1"
                    class="graph-pipeline-preview__arrow"
                    aria-hidden="true"
                    >→</span
                  >
                </span>
              </div>
            </div>
          </div>
        </section>

        <button
          v-if="isLightRAGGraphExtractor"
          type="button"
          class="advanced-config-toggle"
          :aria-expanded="showAdvancedGraphConfig"
          @click="showAdvancedGraphConfig = !showAdvancedGraphConfig"
        >
          <span>
            <SlidersHorizontal :size="16" />
            {{ showAdvancedGraphConfig ? '收起高级设置' : '展开高级设置' }}
          </span>
          <small>端点、本体、阈值、并发和严格模式</small>
          <ChevronUp v-if="showAdvancedGraphConfig" :size="16" />
          <ChevronDown v-else :size="16" />
        </button>

        <template v-if="showAdvancedGraphConfig || !isLightRAGGraphExtractor">
          <a-form-item v-if="isLlmExtractor" label="模型">
            <ModelSelectorComponent
              :model_spec="graphConfigForm.model_spec"
              placeholder="选择抽取模型"
              @select-model="(spec) => (graphConfigForm.model_spec = spec)"
            />
          </a-form-item>
          <a-form-item v-if="isLlmExtractor" label="Schema">
            <a-textarea
              v-model:value="graphConfigForm.schema"
              :rows="6"
              placeholder="描述实体类型、关系类型和属性约束。后端会把 Schema 拼接到固定抽取 Prompt 中。"
            />
            <div class="form-item-hint">
              已内置武器装备研发质量门槛：聚焦原理、实质性技术、可验证能力、工程约束与有证据的转化潜力；
              Schema 用于进一步限定本知识库术语。
            </div>
          </a-form-item>
          <div v-if="isLlmExtractor" class="form-grid two-columns">
            <a-form-item label="相邻前文 Chunk 数">
              <a-input-number
                v-model:value="graphConfigForm.context_window_size"
                :min="0"
                :max="5"
                :step="1"
                style="width: 100%"
              />
              <div class="form-item-hint">
                默认 1。用于补全跨 Chunk 关系和指代；设为 0 可关闭，数值越大模型成本越高。
              </div>
            </a-form-item>
            <a-form-item label="相邻前文字符预算">
              <a-input-number
                v-model:value="graphConfigForm.context_max_chars"
                :min="500"
                :max="20000"
                :step="500"
                style="width: 100%"
              />
              <div class="form-item-hint">默认 4000 字符。优先保留距离当前 Chunk 最近的前文。</div>
            </a-form-item>
            <a-form-item label="受控创新假设">
              <a-switch v-model:checked="graphConfigForm.enable_hypothesis_extraction" />
              <div class="form-item-hint">
                只连接已有证据实体，并明确标为假设和专家复核项；不会作为事实入链。
              </div>
            </a-form-item>
            <a-form-item label="每 Chunk 假设上限">
              <a-input-number
                v-model:value="graphConfigForm.max_hypotheses_per_chunk"
                :min="0"
                :max="3"
                :step="1"
                :disabled="!graphConfigForm.enable_hypothesis_extraction"
                style="width: 100%"
              />
              <div class="form-item-hint">
                默认 2，最多 3。增强模型内部推理，不增加每个 Chunk 的模型调用次数。
              </div>
            </a-form-item>
            <a-form-item label="LLM 抽取并发数">
              <a-input-number
                v-model:value="graphConfigForm.concurrency_count"
                :min="1"
                :max="1000"
                :step="1"
                style="width: 100%"
              />
              <div class="form-item-hint">
                推荐 8。SiliconFlow 运行时最多使用 16，其他模型最多使用
                64，避免大量请求同时排队导致超时。
              </div>
            </a-form-item>
            <a-form-item label="单次抽取超时（秒）">
              <a-input-number
                v-model:value="graphConfigForm.timeout_seconds"
                :min="1"
                :max="600"
                :step="10"
                style="width: 100%"
              />
              <div class="form-item-hint">
                默认 180 秒。复杂 Schema 或推理型模型可选“稳定”方案调大到 300 秒。
              </div>
            </a-form-item>
            <a-form-item label="抽取最大输出（tokens）">
              <a-input-number
                v-model:value="graphConfigForm.max_output_tokens"
                :min="256"
                :max="32768"
                :step="512"
                style="width: 100%"
              />
              <div class="form-item-hint">
                推荐 8192。检测到输出截断时自动扩大预算补跑，避免保存不完整关系。
              </div>
            </a-form-item>
            <a-form-item label="模型深度思考">
              <a-switch v-model:checked="graphConfigForm.enable_thinking" />
              <div class="form-item-hint">
                均衡方案保留受控思考以照顾复杂关系。当前应用于 SiliconFlow；关闭适合简单文本。
              </div>
            </a-form-item>
            <a-form-item label="思考预算（tokens）">
              <a-input-number
                v-model:value="graphConfigForm.thinking_budget"
                :min="128"
                :max="32768"
                :step="512"
                :disabled="!graphConfigForm.enable_thinking"
                style="width: 100%"
              />
              <div class="form-item-hint">
                均衡 2048，稳定 4096。限制长时间思考，同时保留证据和关系自检。
              </div>
            </a-form-item>
          </div>
          <a-form-item v-if="isLlmExtractor" label="模型参数 JSON">
            <a-input
              v-model:value="graphConfigForm.model_params_text"
              placeholder='例如 {"temperature":0.1}（不能用于设置超时，请用上方字段）'
            />
          </a-form-item>
          <template v-if="!isLlmExtractor">
            <a-alert
              class="config-warning"
              type="info"
              show-icon
              message="Schema 由所选不可变本体版本提供；模型只返回 Span，原文证据由平台回切。"
            />
            <div class="form-grid two-columns">
              <a-form-item label="本体版本">
                <a-select
                  v-model:value="graphConfigForm.ontology_version"
                  :options="ontologyVersionOptions"
                  :loading="ontologyVersionsLoading"
                  show-search
                  option-filter-prop="label"
                />
                <div class="form-item-hint">
                  <template v-if="selectedOntologyVersion">
                    {{ selectedOntologyVersion.entity_type_count }} 类实体 ·
                    {{ selectedOntologyVersion.relation_type_count }} 类关系 ·
                    {{ selectedOntologyVersion.change_reason || '未记录变更原因' }}
                  </template>
                  <template v-else>构建任务会固定保存所选版本的完整本体快照。</template>
                </div>
              </a-form-item>
              <a-form-item label="Pipeline revision">
                <a-input v-model:value="graphConfigForm.pipeline_revision" />
              </a-form-item>
              <a-form-item label="文档知识审计">
                <a-switch v-model:checked="graphConfigForm.document_audit_enabled" />
                <div class="form-item-hint">抽取前识别非研究材料，抽取后生成研究链和知识卡。</div>
              </a-form-item>
              <a-form-item v-if="graphConfigForm.document_audit_enabled" label="过滤明确非研究材料">
                <a-switch v-model:checked="graphConfigForm.filter_non_research" />
                <div class="form-item-hint">
                  只排除强证据命中的非研究或正文不足材料，不确定资料仍进入抽取。
                </div>
              </a-form-item>
              <a-form-item
                v-if="graphConfigForm.document_audit_enabled && isLightRAGGraphExtractor"
                label="高价值技术重点复抽"
              >
                <a-switch v-model:checked="graphConfigForm.document_value_routing_enabled" />
                <div class="form-item-hint">
                  使用项目模型识别有原文证据的高新质军事/军民两用技术论文，并提高文档级实体、关系复抽预算。
                </div>
              </a-form-item>
              <a-form-item
                v-if="graphConfigForm.extractor_type !== 'lightrag_primary'"
                label="窗口 token 数"
              >
                <a-input-number
                  v-model:value="graphConfigForm.ie_chunk_size"
                  :min="64"
                  :max="4096"
                  style="width: 100%"
                />
              </a-form-item>
              <a-form-item
                v-if="graphConfigForm.extractor_type !== 'lightrag_primary'"
                label="窗口重叠 token 数"
              >
                <a-input-number
                  v-model:value="graphConfigForm.ie_chunk_overlap"
                  :min="0"
                  :max="1024"
                  style="width: 100%"
                />
              </a-form-item>
              <a-form-item
                v-if="graphConfigForm.extractor_type !== 'lightrag_primary'"
                label="实体阈值"
              >
                <a-input-number
                  v-model:value="graphConfigForm.entity_threshold"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  style="width: 100%"
                />
              </a-form-item>
              <a-form-item
                v-if="graphConfigForm.extractor_type !== 'lightrag_primary'"
                label="关系阈值"
              >
                <a-input-number
                  v-model:value="graphConfigForm.relation_threshold"
                  :min="0"
                  :max="1"
                  :step="0.05"
                  style="width: 100%"
                />
              </a-form-item>
              <a-form-item v-if="isLightRAGGraphExtractor" label="LLM 抽取质量增强">
                <a-switch v-model:checked="graphConfigForm.llm_enhancement_enabled" />
                <div class="form-item-hint">
                  项目 LLM 执行实体关系初抽、命名规范化、证据约束和一次 gleaning；不启动本地
                  神经抽取 sidecar，新增知识进入待审核队列。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.llm_enhancement_enabled"
                label="封闭端点关系补抽"
              >
                <a-switch v-model:checked="graphConfigForm.llm_relation_completion_enabled" />
                <div class="form-item-hint">
                  LLM
                  只能判断平台生成的同句实体对；端点需至少两个模型阶段支持，且关系必须通过触发词、
                  本体方向、证据 Span 和置信度门禁。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.llm_enhancement_enabled"
                label="排版损伤规范化初抽"
              >
                <a-switch v-model:checked="graphConfigForm.llm_layout_normalization_enabled" />
                <div class="form-item-hint">
                  对断字、异常空白和表格换行构造临时文本视图，候选会映射回原始字符 Span。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.llm_enhancement_enabled"
                label="OCR 损伤修复复抽"
              >
                <a-switch v-model:checked="graphConfigForm.llm_ocr_repair_enabled" />
                <div class="form-item-hint">
                  针对 @AB、粘连字符等高确定性损伤生成修复视图；原文保持不变，新增候选进入待审核。
                </div>
              </a-form-item>
              <a-form-item v-if="isLightRAGGraphExtractor" label="文档级跨段关系增强">
                <a-switch v-model:checked="graphConfigForm.document_enhancement_enabled" />
                <div class="form-item-hint">
                  实体对齐后使用轻量化 RAG 补抽跨 Block 关系；结果仍为待审核 Inference。
                </div>
              </a-form-item>
              <a-form-item v-if="isLightRAGGraphExtractor" label="跨文档 LLM 实体消歧">
                <a-switch v-model:checked="graphConfigForm.entity_alignment_enabled" />
                <div class="form-item-hint">
                  仅对别名与向量召回后仍有歧义的同类型实体调用；默认只给出审核推荐，不自动合并实体
                  ID。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.entity_alignment_enabled"
                label="实体消歧模型"
              >
                <ModelSelectorComponent
                  :model_spec="graphConfigForm.entity_alignment_model_spec"
                  placeholder="选择项目模型设置中的通用模型"
                  @select-model="(spec) => (graphConfigForm.entity_alignment_model_spec = spec)"
                />
                <div class="form-item-hint">
                  只发送实体名、属性、邻接关系和封闭候选集；模型与凭证统一来自项目模型设置。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.entity_alignment_enabled"
                label="实体消歧失败阻断"
              >
                <a-switch v-model:checked="graphConfigForm.entity_alignment_strict" />
                <div class="form-item-hint">
                  关闭时保留规则与向量对齐结果；需要强一致失败语义时可开启。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.entity_alignment_enabled"
                label="高置信实体自动链接"
              >
                <a-switch v-model:checked="graphConfigForm.entity_alignment_auto_link_enabled" />
                <div class="form-item-hint">
                  仅当 LLM 选择向量首选实体，且模型置信度不低于 0.95、向量分数不低于 0.90 时复用稳定
                  ID；其余情况仍进入人工审核。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.document_enhancement_enabled"
                label="文档窗口字符预算"
              >
                <a-input-number
                  v-model:value="graphConfigForm.document_enhancement_max_chars"
                  :min="512"
                  :max="1000000"
                  :step="1000"
                  style="width: 100%"
                />
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.document_enhancement_enabled"
                label="文档增强并发"
              >
                <a-input-number
                  v-model:value="graphConfigForm.document_enhancement_concurrency"
                  :min="1"
                  :max="8"
                  :step="1"
                  style="width: 100%"
                />
                <div class="form-item-hint">
                  所有活跃文档共享的 LLM 在途上限；窗口、文档与跨文档批次不会乘法叠加。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.document_enhancement_enabled"
                label="同时活跃文档"
              >
                <a-input-number
                  v-model:value="graphConfigForm.document_concurrency_count"
                  :min="1"
                  :max="8"
                  :step="1"
                  style="width: 100%"
                />
                <div class="form-item-hint">
                  多篇短文档可并发推进；每篇内部窗口仍受上方共享预算约束，默认 2。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.document_enhancement_enabled"
                label="文档级遗漏实体补抽"
              >
                <a-switch v-model:checked="graphConfigForm.document_entity_enhancement_enabled" />
                <div class="form-item-hint">
                  在 Chunk 主抽之后跨 Block 查漏；只接受原文 Span 和本体类型，新增实体仍为待审核。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_entity_enhancement_enabled
                "
                label="文档实体补抽模型"
              >
                <ModelSelectorComponent
                  :model_spec="graphConfigForm.document_entity_enhancement_model_spec"
                  placeholder="选择项目模型设置中的通用模型"
                  @select-model="
                    (spec) => (graphConfigForm.document_entity_enhancement_model_spec = spec)
                  "
                />
                <div class="form-item-hint">
                  模型不能创建稳定 ID；平台会执行别名、向量及受约束 LLM 消歧后再写入 pending
                  mention。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_entity_enhancement_enabled
                "
                label="文档实体补抽失败阻断"
              >
                <a-switch v-model:checked="graphConfigForm.document_entity_enhancement_strict" />
                <div class="form-item-hint">
                  默认降级保留已完成的 Chunk 抽取结果；需要任何文档补抽失败都阻断任务时可开启。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_entity_enhancement_enabled
                "
                label="文档实体二次查漏"
              >
                <a-switch v-model:checked="graphConfigForm.document_entity_gleaning_enabled" />
                <div class="form-item-hint">
                  首轮候选稀疏或检测到排版损伤时最多再调用一次
                  gleaning，复用同一窗口并限制候选预算。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_entity_enhancement_enabled
                "
                label="文档排版规范化"
              >
                <a-switch
                  v-model:checked="graphConfigForm.document_entity_layout_normalization_enabled"
                />
                <div class="form-item-hint">
                  只构造可双向回切 Span 的临时视图，不改写 PostgreSQL 中的原始 Block。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.document_enhancement_enabled"
                label="文档级轻量化 RAG 补抽"
              >
                <a-switch v-model:checked="graphConfigForm.document_llm_enhancement_enabled" />
                <div class="form-item-hint">
                  只能连接已有 canonical 实体并返回原文 Span，不能新增实体或创新假设。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_llm_enhancement_enabled
                "
                label="文档补抽模型"
              >
                <ModelSelectorComponent
                  :model_spec="graphConfigForm.document_llm_enhancement_model_spec"
                  placeholder="选择项目模型设置中的通用模型"
                  @select-model="
                    (spec) => (graphConfigForm.document_llm_enhancement_model_spec = spec)
                  "
                />
                <div class="form-item-hint">
                  文档窗口会发送给项目模型设置中选定的模型；数据目的地与凭证统一由模型设置管理。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_llm_enhancement_enabled
                "
                label="文档补抽失败阻断"
              >
                <a-switch v-model:checked="graphConfigForm.document_llm_enhancement_strict" />
                <div class="form-item-hint">
                  关闭时保留其他已成功分支；需要全阶段强一致失败语义时可开启。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.document_enhancement_enabled"
                label="跨文档多源关系增强"
              >
                <a-switch v-model:checked="graphConfigForm.document_cross_relation_enabled" />
                <div class="form-item-hint">
                  只比较至少两篇文档共同出现的 canonical 实体对；新增关系固定为 Inference/pending，
                  并保存每篇来源的独立证据 Span。候选预算可避免大知识库产生无界实体笛卡尔积。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_cross_relation_enabled
                "
                label="跨文档候选范围"
              >
                <a-select v-model:value="graphConfigForm.document_cross_relation_review_scope">
                  <a-select-option value="pending_candidates">
                    待审候选（新知识库推荐）
                  </a-select-option>
                  <a-select-option value="accepted_only">仅人工接受实体</a-select-option>
                </a-select>
                <div class="form-item-hint">
                  待审模式可在首次构建时运行跨文档增强，但所有结果仍需专家复核；仅接受模式适合已审核知识库。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_cross_relation_enabled
                "
                label="跨文档关系模型"
              >
                <ModelSelectorComponent
                  :model_spec="graphConfigForm.document_cross_relation_model_spec"
                  placeholder="选择项目模型设置中的通用关系分析模型"
                  @select-model="
                    (spec) => (graphConfigForm.document_cross_relation_model_spec = spec)
                  "
                />
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_cross_relation_enabled
                "
                label="最少独立文档数"
              >
                <a-input-number
                  v-model:value="graphConfigForm.document_cross_relation_min_documents"
                  :min="2"
                  :max="8"
                  style="width: 100%"
                />
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_cross_relation_enabled
                "
                label="最大实体对数"
              >
                <a-input-number
                  v-model:value="graphConfigForm.document_cross_relation_max_pairs"
                  :min="1"
                  :max="128"
                  style="width: 100%"
                />
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_cross_relation_enabled
                "
                label="每批实体对"
              >
                <a-input-number
                  v-model:value="graphConfigForm.document_cross_relation_pairs_per_batch"
                  :min="1"
                  :max="24"
                  style="width: 100%"
                />
                <div class="form-item-hint">
                  将封闭候选稳定拆批，默认每批 6 对；每批仅携带相关实体、mention 与原文 Block。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_cross_relation_enabled
                "
                label="跨文档批次并发"
              >
                <a-input-number
                  v-model:value="graphConfigForm.document_cross_relation_concurrency"
                  :min="1"
                  :max="8"
                  style="width: 100%"
                />
                <div class="form-item-hint">
                  默认 2；与文档窗口共享总 LLM 在途预算，不会形成文档数 × 窗口数的无界并发。
                </div>
              </a-form-item>
              <a-form-item
                v-if="
                  isLightRAGGraphExtractor &&
                  graphConfigForm.document_enhancement_enabled &&
                  graphConfigForm.document_cross_relation_enabled
                "
                label="跨文档失败阻断"
              >
                <a-switch v-model:checked="graphConfigForm.document_cross_relation_strict" />
                <div class="form-item-hint">关闭时记录降级原因并保留同文档抽取结果。</div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.llm_enhancement_enabled"
                label="增强模型"
              >
                <ModelSelectorComponent
                  :model_spec="graphConfigForm.llm_enhancement_model_spec"
                  placeholder="选择项目模型设置中的通用模型"
                  @select-model="(spec) => (graphConfigForm.llm_enhancement_model_spec = spec)"
                />
                <div class="form-item-hint">
                  原始文献会发送给项目模型设置中选定的模型；不会启动本地 7B/MLX 模型。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.llm_enhancement_enabled"
                label="Agent/LLM 并行槽位"
              >
                <a-segmented
                  v-model:value="graphConfigForm.llm_enhancement_concurrency"
                  :options="agentParallelismPresets"
                  block
                  style="margin-bottom: 8px"
                />
                <a-input-number
                  v-model:value="graphConfigForm.llm_enhancement_concurrency"
                  :min="1"
                  :max="8"
                  :step="1"
                  style="width: 100%"
                />
                <div class="form-item-hint">
                  独立 Chunk 并行；同一 Chunk 的初抽、命名复核和补抽顺序执行。建议均衡
                  4，模型限流稳定后可升至 8；不会与外层 worker 相乘。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.llm_enhancement_enabled"
                label="增强相邻前文 Chunk 数"
              >
                <a-input-number
                  v-model:value="graphConfigForm.context_window_size"
                  :min="0"
                  :max="4"
                  :step="1"
                  style="width: 100%"
                />
                <div class="form-item-hint">
                  默认 1，仅用于术语和指代消歧；新增实体及关系证据仍必须落在当前 Block。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.llm_enhancement_enabled"
                label="增强上下文字符预算"
              >
                <a-input-number
                  v-model:value="graphConfigForm.context_max_chars"
                  :min="500"
                  :max="8000"
                  :step="100"
                  style="width: 100%"
                />
                <div class="form-item-hint">
                  默认 1200 字符，优先保留最近前文，避免无界增加模型成本。
                </div>
              </a-form-item>
              <a-form-item
                v-if="isLightRAGGraphExtractor && graphConfigForm.llm_enhancement_enabled"
                label="增强失败阻断"
              >
                <a-switch v-model:checked="graphConfigForm.llm_enhancement_strict" />
                <div class="form-item-hint">
                  关闭时模型故障会保留已完成的抽取结果并记录降级原因；需要全阶段强一致失败语义时可开启。
                </div>
              </a-form-item>
              <a-form-item label="服务调用超时（秒）">
                <a-input-number
                  v-model:value="graphConfigForm.timeout_seconds"
                  :min="1"
                  :max="600"
                  style="width: 100%"
                />
              </a-form-item>
            </div>
          </template>
        </template>
      </a-form>
    </a-modal>

    <a-modal v-model:open="showFailedChunkSamples" title="样例 Chunk" width="760px" :footer="null">
      <div v-if="failedChunkSamplesLoading" class="failed-chunk-loading">
        <Loader2 :size="18" class="spin" />
        正在加载失败 Chunk
      </div>
      <a-empty v-else-if="!failedChunkSamples.length" description="暂无抽取失败的 Chunk" />
      <a-tabs v-else v-model:activeKey="activeFailedChunkKey" class="failed-chunk-tabs">
        <a-tab-pane
          v-for="(chunk, index) in failedChunkSamples"
          :key="chunk.chunk_id"
          :tab="`样例 ${index + 1}`"
        >
          <div class="failed-chunk-meta">
            <span>Chunk {{ Number(chunk.chunk_index) + 1 }}</span>
            <span>{{ chunk.file_id }}</span>
            <span>尝试 {{ chunk.details?.attempt_count ?? '-' }} 次</span>
          </div>
          <a-alert
            type="error"
            :message="chunk.details?.last_error || '未记录失败原因'"
            show-icon
          />
          <pre class="failed-chunk-content">{{ chunk.content }}</pre>
        </a-tab-pane>
      </a-tabs>
    </a-modal>

    <a-modal
      v-model:open="showPathDiscovery"
      title="轻量化 RAG 多跳检索与创新预测"
      width="min(1180px, calc(100vw - 32px))"
      wrap-class-name="innovation-workbench-modal"
      :footer="null"
    >
      <section class="innovation-workbench-hero" aria-label="创新发现能力概览">
        <div class="innovation-hero-copy">
          <span class="innovation-hero-kicker">LIGHTWEIGHT GRAPH DISCOVERY</span>
          <h3>证据链结论与创新想法，两个并列工作区</h3>
          <p>
            多跳检索负责沿图谱证据形成完整结论；创新预测负责探索技术组合与潜在链路。
            两者都支持自上而下与自下而上，并使用项目模型设置中的 LLM。
          </p>
        </div>
        <div class="discovery-feature-switch" role="tablist" aria-label="知识发现功能">
          <button
            type="button"
            :class="{ active: activeDiscoveryFeature === 'multihop' }"
            role="tab"
            :aria-selected="activeDiscoveryFeature === 'multihop'"
            @click="activeDiscoveryFeature = 'multihop'"
          >
            <Waypoints :size="18" />
            <span><strong>多跳检索</strong><small>证据路径 + LLM 完整结论</small></span>
          </button>
          <button
            type="button"
            :class="{ active: activeDiscoveryFeature === 'innovation' }"
            role="tab"
            :aria-selected="activeDiscoveryFeature === 'innovation'"
            @click="activeDiscoveryFeature = 'innovation'"
          >
            <Sparkles :size="18" />
            <span><strong>创新预测</strong><small>技术组合 + 待验证 Hypothesis</small></span>
          </button>
        </div>
      </section>
      <a-alert
        class="path-discovery-notice"
        type="info"
        show-icon
        :message="
          activeDiscoveryFeature === 'multihop'
            ? '多跳检索只解释当前图谱与原文证据，LLM 不新增实体、关系或创新假设。'
            : '创新预测可探索技术组合和潜在链路；所有结果均标记为待验证 Hypothesis，不自动写入知识事实。'
        "
      />
      <a-form layout="vertical" class="path-query-form">
        <div class="discovery-mode-grid" role="radiogroup" aria-label="创新发现路线">
          <button
            v-for="option in innovationModeOptions"
            :key="option.value"
            type="button"
            class="discovery-mode-card"
            :class="{ active: pathQuery.mode === option.value }"
            role="radio"
            :aria-checked="pathQuery.mode === option.value"
            @click="pathQuery.mode = option.value"
          >
            <span class="discovery-mode-icon"><component :is="option.icon" :size="18" /></span>
            <span>
              <strong>{{ option.label }}</strong>
              <small>{{ option.description }}</small>
            </span>
            <em>{{ option.badge }}</em>
          </button>
        </div>
        <div class="innovation-template-row" aria-label="创新任务快捷模板">
          <span>推荐起点</span>
          <button
            v-for="template in activeInnovationTemplates"
            :key="template.label"
            type="button"
            @click="applyInnovationTemplate(template)"
          >
            <strong>{{ template.label }}</strong>
            <small>{{ template.description }}</small>
          </button>
        </div>
        <a-form-item :label="activeDiscoveryGuide.inputLabel" class="innovation-query-input">
          <a-input
            v-model:value="pathQuery.query"
            :placeholder="activeDiscoveryGuide.placeholder"
            :maxlength="500"
            @keydown.enter="runActiveDiscovery"
          />
          <span class="form-item-hint">{{ activeDiscoveryGuide.hint }}</span>
        </a-form-item>
        <div class="exploration-preset-row" role="radiogroup" aria-label="探索深度预设">
          <span>探索深度</span>
          <button
            v-for="preset in explorationPresets"
            :key="preset.value"
            type="button"
            :class="{ active: pathQuery.exploration_preset === preset.value }"
            role="radio"
            :aria-checked="pathQuery.exploration_preset === preset.value"
            @click="applyExplorationPreset(preset)"
          >
            <strong>{{ preset.label }}</strong>
            <small>{{ preset.description }}</small>
          </button>
        </div>
        <div class="path-query-options">
          <a-form-item label="最大跳数">
            <a-input-number v-model:value="pathQuery.max_hops" :min="1" :max="6" />
          </a-form-item>
          <a-form-item label="检索策略">
            <a-select v-model:value="pathQuery.retrieval_mode">
              <a-select-option value="naive">原文向量</a-select-option>
              <a-select-option value="local">实体优先</a-select-option>
              <a-select-option value="global">关系优先</a-select-option>
              <a-select-option value="hybrid">实体 + 关系</a-select-option>
              <a-select-option value="mix">图谱 + 原文 + 关键词</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item v-if="activeDiscoveryFeature === 'multihop'" label="探索性组合">
            <a-switch v-model:checked="pathQuery.include_combinations" />
          </a-form-item>
          <a-form-item v-if="activeDiscoveryFeature === 'innovation'" label="创新证据范围">
            <a-select v-model:value="pathQuery.evidence_scope">
              <a-select-option value="any">全部已接受路径</a-select-option>
              <a-select-option value="cross_document">仅跨文档路径</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item v-if="!readonly && activeDiscoveryFeature === 'innovation'" label=" ">
            <a-button
              type="primary"
              class="innovation-primary-action"
              :loading="innovationDiscoveryLoading"
              title="独立运行证据约束创新预测"
              @click="runInnovationDiscovery"
            >
              <Sparkles v-if="!innovationDiscoveryLoading" :size="15" />
              生成创新想法
            </a-button>
          </a-form-item>
          <a-form-item v-if="activeDiscoveryFeature === 'multihop'" label=" ">
            <a-button
              type="primary"
              :loading="pathDiscoveryLoading"
              title="运行多跳检索并由项目 LLM 生成完整结论"
              @click="runPathDiscovery"
            >
              <Waypoints v-if="!pathDiscoveryLoading" :size="15" />
              检索并生成结论
            </a-button>
          </a-form-item>
        </div>
        <details v-if="!readonly" class="model-enhancement-disclosure">
          <summary>
            <span>
              <BrainCircuit :size="16" />
              <strong>模型增强与证据约束</strong>
            </span>
            <small>
              {{
                activeDiscoveryFeature === 'multihop'
                  ? '配置查询规划、路径重排和证据约束完整结论'
                  : '配置查询规划、路径重排和创新假设解释'
              }}
            </small>
          </summary>
          <div class="model-enhancement-grid">
            <div class="solution-generation-controls">
              <a-form-item label="LLM 检索规划增强">
                <a-switch v-model:checked="queryEnhancement.enabled" />
                <span class="form-item-hint solution-generation-hint">
                  默认启用；仅拆分实体级与关系级检索词，不写入图谱事实，模型来自项目模型设置。
                </span>
              </a-form-item>
              <a-form-item v-if="queryEnhancement.enabled" label="规划模型">
                <ModelSelectorComponent
                  :model_spec="queryEnhancement.model_spec"
                  placeholder="选择项目模型设置中的检索规划模型"
                  @select-model="(spec) => (queryEnhancement.model_spec = spec)"
                />
              </a-form-item>
              <a-form-item v-if="queryEnhancement.enabled" label="严格模式">
                <a-switch v-model:checked="queryEnhancement.strict" />
                <span class="form-item-hint solution-generation-hint">
                  关闭时模型异常会退回原始查询；开启时异常将阻断本次检索，适合质量对照实验。
                </span>
              </a-form-item>
            </div>
            <div v-if="!readonly" class="solution-generation-controls">
              <a-form-item label="LLM 多跳路径重排">
                <a-switch v-model:checked="pathReranking.enabled" />
                <span class="form-item-hint solution-generation-hint">
                  默认启用；只对已接受的封闭路径候选评分和重排，不能新增节点、关系或证据。
                </span>
              </a-form-item>
              <a-form-item v-if="pathReranking.enabled" label="路径重排模型">
                <ModelSelectorComponent
                  :model_spec="pathReranking.model_spec"
                  placeholder="选择项目模型设置中的路径重排模型"
                  @select-model="(spec) => (pathReranking.model_spec = spec)"
                />
              </a-form-item>
              <a-form-item v-if="pathReranking.enabled" label="严格模式">
                <a-switch v-model:checked="pathReranking.strict" />
                <span class="form-item-hint solution-generation-hint">
                  关闭时模型异常保留确定性路径顺序；开启时异常阻断本次检索，仅用于质量对照。
                </span>
              </a-form-item>
            </div>
            <div
              v-if="!readonly && activeDiscoveryFeature === 'multihop'"
              class="solution-generation-controls"
            >
              <a-form-item label="LLM 完整结论撰述">
                <a-switch v-model:checked="narrativeEnhancement.enabled" />
                <span class="form-item-hint solution-generation-hint">
                  使用项目 Agent 模型详细解释证据路径；结论必须引用现有 Path、Relation、Chunk 和 File ID。
                </span>
              </a-form-item>
              <a-form-item v-if="narrativeEnhancement.enabled" label="结论撰述模型">
                <ModelSelectorComponent
                  :model_spec="narrativeEnhancement.model_spec"
                  placeholder="选择项目模型设置中的结论撰述模型"
                  @select-model="(spec) => (narrativeEnhancement.model_spec = spec)"
                />
              </a-form-item>
              <a-form-item v-if="narrativeEnhancement.enabled" label="严格模式">
                <a-switch v-model:checked="narrativeEnhancement.strict" />
                <span class="form-item-hint solution-generation-hint">
                  关闭时模型异常仍返回路径；开启时撰述失败会阻断本次请求。
                </span>
              </a-form-item>
            </div>
            <div
              v-if="!readonly && activeDiscoveryFeature === 'innovation'"
              class="solution-generation-controls"
            >
              <a-form-item label="LLM 创新预测增强">
                <a-switch v-model:checked="innovationEnhancement.enabled" />
                <span class="form-item-hint solution-generation-hint">
                  默认启用；只增强已发现 Hypothesis
                  的机理解释、不确定性和排序，不允许改变实体端点、关系类型或证据 ID。
                </span>
              </a-form-item>
              <a-form-item v-if="innovationEnhancement.enabled" label="创新分析模型">
                <ModelSelectorComponent
                  :model_spec="innovationEnhancement.model_spec"
                  placeholder="选择项目模型设置中的创新分析模型"
                  @select-model="(spec) => (innovationEnhancement.model_spec = spec)"
                />
              </a-form-item>
              <a-form-item v-if="innovationEnhancement.enabled" label="候选批次并发">
                <a-input-number
                  v-model:value="innovationEnhancement.concurrency_count"
                  :min="1"
                  :max="8"
                  :step="1"
                  style="width: 100%"
                />
                <span class="form-item-hint solution-generation-hint">
                  不同候选批次有界并行，单批结构修复仍顺序执行；默认 2，避免触发模型限流。
                </span>
              </a-form-item>
              <a-form-item v-if="innovationEnhancement.enabled" label="严格模式">
                <a-switch v-model:checked="innovationEnhancement.strict" />
                <span class="form-item-hint solution-generation-hint">
                  关闭时模型异常保留确定性候选；开启时异常阻断本次创新发现，适合质量评测。
                </span>
              </a-form-item>
            </div>
            <div v-if="!readonly" class="solution-generation-controls">
              <a-form-item label="证据约束 LLM 方案生成">
                <a-switch v-model:checked="solutionGeneration.enabled" />
                <span class="form-item-hint solution-generation-hint">
                  默认关闭；开启后会产生模型调用，只使用已接受图路径和可定位原文 Chunk。
                </span>
              </a-form-item>
              <a-form-item v-if="solutionGeneration.enabled" label="生成模型">
                <ModelSelectorComponent
                  :model_spec="solutionGeneration.model_spec"
                  placeholder="选择技术方案生成模型"
                  @select-model="(spec) => (solutionGeneration.model_spec = spec)"
                />
              </a-form-item>
              <a-button
                v-if="solutionGeneration.enabled"
                :disabled="!solutionGeneration.model_spec"
                :loading="solutionGenerationLoading"
                @click="runEvidenceGroundedSolution"
              >
                <Sparkles v-if="!solutionGenerationLoading" :size="15" />
                生成证据约束技术方案
              </a-button>
            </div>
          </div>
        </details>
      </a-form>

      <section
        v-if="
          (activeDiscoveryFeature === 'multihop' && pathDiscoverySearched) ||
          (activeDiscoveryFeature === 'innovation' && innovationDiscoverySearched)
        "
        class="innovation-overview"
        aria-label="创新发现结果总览"
      >
        <header>
          <div>
            <span>DISCOVERY OVERVIEW</span>
            <h3>发现结果总览</h3>
          </div>
          <a-tag :color="pathQuery.evidence_scope === 'cross_document' ? 'blue' : 'default'">
            {{ pathQuery.evidence_scope === 'cross_document' ? '跨文档证据' : '全部已接受证据' }}
          </a-tag>
        </header>
        <div class="innovation-overview-grid">
          <div v-if="activeDiscoveryFeature === 'multihop'">
            <span>可信路径</span><strong>{{ innovationResultOverview.trustedPaths }}</strong>
          </div>
          <div v-if="activeDiscoveryFeature === 'innovation'">
            <span>待审核假设</span><strong>{{ innovationResultOverview.pendingHypotheses }}</strong>
          </div>
          <div>
            <span>跨文档候选</span><strong>{{ innovationResultOverview.crossDocument }}</strong>
          </div>
          <div>
            <span>高价值弱信号</span><strong>{{ innovationResultOverview.weakSignals }}</strong>
          </div>
          <div>
            <span>平均证据强度</span>
            <strong>{{ innovationResultOverview.averageEvidenceStrength }}%</strong>
          </div>
        </div>
      </section>

      <section
        v-if="activeQueryPipelineTrace?.stages?.length"
        class="query-pipeline-trace"
        aria-label="多跳检索执行轨迹"
      >
        <header>
          <div>
            <span>LIGHTWEIGHT RAG QUERY TRACE</span>
            <h3>多跳检索执行轨迹</h3>
          </div>
          <a-tag :color="activeQueryPipelineTrace.degraded ? 'orange' : 'green'">
            {{ activeQueryPipelineTrace.degraded ? '部分降级' : '链路完整' }}
          </a-tag>
        </header>
        <ol>
          <li v-for="stage in activeQueryPipelineTrace.stages" :key="stage.key">
            <div class="query-trace-step">
              <span>{{ stage.label }}</span>
              <a-tag :color="queryTraceStatusColor(stage.status)">
                {{ queryTraceStatusLabel(stage.status) }}
              </a-tag>
            </div>
            <strong v-if="stage.count !== undefined">{{ stage.count }}</strong>
            <small v-if="stage.failure_channels?.length">
              降级通道：{{ stage.failure_channels.join('、') }}
            </small>
          </li>
        </ol>
      </section>

      <div
        v-if="activeDiscoveryFeature === 'multihop' && pathDiscoveryLoading"
        class="path-discovery-loading"
      >
        <Loader2 :size="20" class="spin" />
        正在检索并整理跨 Chunk 技术链路
      </div>
      <a-empty
        v-else-if="
          activeDiscoveryFeature === 'multihop' &&
          pathDiscoverySearched &&
          !pathDiscoveryResult.paths.length
        "
        description="未发现满足约束的链路，可尝试更具体的需求、实体名称或增加跳数。"
      />
      <div
        v-else-if="activeDiscoveryFeature === 'multihop' && pathDiscoveryResult.paths.length"
        class="path-results"
      >
        <section
          v-if="pathDiscoveryResult.narrative"
          class="multihop-narrative"
          aria-label="LLM 多跳检索完整结论"
        >
          <header>
            <div>
              <span>GROUNDED MULTI-HOP CONCLUSION</span>
              <h3>多跳检索完整结论</h3>
            </div>
            <a-tag color="blue">{{ discoveryDirectionLabel(pathDiscoveryResult.discovery_mode) }}</a-tag>
          </header>
          <div class="multihop-executive-conclusion">
            <strong>管理摘要</strong>
            <p>{{ pathDiscoveryResult.narrative.executive_conclusion }}</p>
            <small>
              引用路径：{{ pathDiscoveryResult.narrative.conclusion_path_ids?.join('、') || '-' }}
            </small>
          </div>
          <div class="multihop-narrative-grid">
            <section
              v-for="section in narrativeResultSections"
              :key="section.key"
              v-show="section.items.length"
            >
              <h4>{{ section.label }}</h4>
              <ol>
                <li v-for="(item, index) in section.items" :key="`${section.key}-${index}`">
                  <p>{{ item.statement }}</p>
                  <small>
                    Path {{ item.path_ids?.join('、') || '-' }}
                    <template v-if="item.relation_ids?.length">
                      · Relation {{ item.relation_ids.join('、') }}
                    </template>
                    <template v-if="item.file_ids?.length"> · File {{ item.file_ids.join('、') }}</template>
                  </small>
                </li>
              </ol>
            </section>
          </div>
        </section>
        <a-alert
          v-else-if="pathDiscoveryResult.narrative_provenance?.status === 'degraded'"
          type="warning"
          show-icon
          message="证据路径检索成功，但 LLM 完整结论生成已降级；以下仍展示原始可追溯路径。"
        />
        <div class="path-result-summary">
          展示 {{ visiblePaths.length }}/{{ pathDiscoveryResult.paths.length }} 条去重后的最大链路 ·
          {{ retrievalModeLabel(pathDiscoveryResult.summary?.retrieval_mode) }}
          <template v-if="pathDiscoveryResult.summary?.entity_hit_count !== undefined">
            · 实体命中 {{ pathDiscoveryResult.summary.entity_hit_count }} · 关系命中
            {{ pathDiscoveryResult.summary.triple_hit_count }}
          </template>
        </div>
        <div class="result-toolbar" aria-label="多跳路径筛选与排序">
          <div class="result-toolbar__summary">
            <strong>{{ pathQualitySummary.trusted_path_count }}</strong
            ><span>可信路径</span>
            <strong>{{ pathQualitySummary.cross_document_path_count }}</strong
            ><span>跨文档</span>
            <strong>{{ pathQualitySummary.complete_semantic_chain_count }}</strong
            ><span>五类语义完整</span>
            <strong>{{ Math.round(pathQualitySummary.average_semantic_coverage * 100) }}%</strong
            ><span>平均语义覆盖</span>
          </div>
          <div class="result-toolbar__controls">
            <a-select
              v-model:value="pathResultView.claimLevel"
              size="small"
              aria-label="路径事实等级"
            >
              <a-select-option value="all">全部等级</a-select-option>
              <a-select-option value="trusted">仅可信事实/推理</a-select-option>
              <a-select-option value="hypothesis">仅假设路径</a-select-option>
              <a-select-option value="pending">含待审证据</a-select-option>
            </a-select>
            <a-select v-model:value="pathResultView.sortBy" size="small" aria-label="路径排序">
              <a-select-option value="score">综合得分优先</a-select-option>
              <a-select-option value="coverage">语义覆盖优先</a-select-option>
              <a-select-option value="evidence">证据数量优先</a-select-option>
            </a-select>
          </div>
        </div>
        <div v-if="pathDiscoveryResult.query_plan" class="path-evidence-summary">
          <span>
            查询规划：{{ pathDiscoveryResult.query_plan.provenance?.status || 'unknown' }}
          </span>
          <span v-if="pathDiscoveryResult.query_plan.low_level_keywords?.length">
            实体词 {{ pathDiscoveryResult.query_plan.low_level_keywords.join('；') }}
          </span>
          <span v-if="pathDiscoveryResult.query_plan.high_level_keywords?.length">
            关系词 {{ pathDiscoveryResult.query_plan.high_level_keywords.join('；') }}
          </span>
          <span v-if="pathDiscoveryResult.query_plan.military_value_dimensions?.length">
            军事价值 {{ pathDiscoveryResult.query_plan.military_value_dimensions.join('；') }}
          </span>
          <span v-if="pathDiscoveryResult.query_plan.weak_signal_terms?.length">
            弱信号 {{ pathDiscoveryResult.query_plan.weak_signal_terms.join('；') }}
          </span>
        </div>
        <div v-if="pathDiscoveryResult.path_reranking" class="path-evidence-summary">
          <span> 路径重排：{{ pathDiscoveryResult.path_reranking.status || 'unknown' }} </span>
          <span v-if="pathDiscoveryResult.path_reranking.ranked_count">
            已约束重排 {{ pathDiscoveryResult.path_reranking.ranked_count }} 条候选
          </span>
        </div>
        <a-empty
          v-if="!visiblePaths.length"
          description="当前筛选条件下没有链路，请调整事实等级筛选。"
        />
        <article
          v-for="(path, pathIndex) in visiblePaths"
          :key="path.path_id"
          class="path-card"
          :class="`path-card--${String(path.claim_level || 'unknown').toLowerCase()}`"
        >
          <header class="path-card-header">
            <div class="path-card-title">
              <span>链路 {{ pathIndex + 1 }}</span>
              <a-tag :color="pathClaimColor(path.claim_level)">{{ path.claim_level }}</a-tag>
              <a-tag :color="pathRouteColor(path.route_kind)">
                {{ pathRouteLabel(path.route_kind) }}
              </a-tag>
              <a-tag v-if="path.research_inspiration.expert_review_required" color="red">
                需要专家复核
              </a-tag>
            </div>
            <div class="path-card-score">
              <strong>{{ formatScore(path.score) }}</strong>
              <span>综合路径分</span>
            </div>
          </header>

          <div class="path-chain">
            <template v-for="(node, nodeIndex) in path.nodes" :key="node.id">
              <div class="path-node">
                <span class="path-node-role">{{ semanticRoleLabel(node.semantic_role) }}</span>
                <strong>{{ node.name }}</strong>
              </div>
              <div v-if="path.relations[nodeIndex]" class="path-relation">
                <span>{{ path.relations[nodeIndex].traversed_reverse ? '←' : '→' }}</span>
                <span>{{ path.relations[nodeIndex].type }}</span>
                <small>证据 {{ path.relations[nodeIndex].evidence_count }}</small>
              </div>
            </template>
          </div>

          <div class="result-quality-strip" aria-label="路径质量摘要">
            <div>
              <span>语义覆盖</span>
              <strong>{{ Math.round(Number(path.semantic_coverage || 0) * 100) }}%</strong>
            </div>
            <div>
              <span>关系证据</span>
              <strong>{{ path.evidence?.mention_count || 0 }}</strong>
            </div>
            <div>
              <span>来源文件</span>
              <strong>{{ path.evidence?.file_ids?.length || 0 }}</strong>
            </div>
            <div>
              <span>证据状态</span>
              <strong :class="path.pending_evidence ? 'status-warning' : 'status-success'">
                {{ path.pending_evidence ? '含待审关系' : '已接受路径' }}
              </strong>
            </div>
          </div>

          <div v-if="researchThreadEntries(path).length" class="research-thread-map">
            <div
              v-for="thread in researchThreadEntries(path)"
              :key="thread.key"
              :class="`research-thread research-thread--${thread.key}`"
            >
              <header>
                <span>{{ thread.label }}</span>
                <small>{{ thread.description }}</small>
              </header>
              <div>
                <a-tag v-for="entity in thread.entities" :key="entity">{{ entity }}</a-tag>
              </div>
            </div>
          </div>

          <details class="result-audit-disclosure">
            <summary>
              <span>查看证据、价值线索与评审问题</span>
              <small>{{ path.evidence?.chunk_ids?.length || 0 }} 个 Chunk 可追溯</small>
            </summary>
            <div v-if="path.research_inspiration?.value_signals?.length" class="path-section">
              <h4>研发价值线索（原文属性）</h4>
              <ul>
                <li
                  v-for="signal in path.research_inspiration.value_signals"
                  :key="`${signal.entity}-${signal.label}-${signal.text}`"
                >
                  {{ signal.entity }} · {{ signal.label }}：{{ signal.text }}
                </li>
              </ul>
            </div>
            <div
              v-if="path.research_inspiration?.military_value_dimensions?.length"
              class="path-section"
            >
              <h4>军事价值维度</h4>
              <div class="path-value-tags">
                <a-tag
                  v-for="dimension in path.research_inspiration.military_value_dimensions"
                  :key="dimension"
                  color="geekblue"
                >
                  {{ dimension }}
                </a-tag>
              </div>
            </div>
            <div
              v-if="path.research_inspiration?.expected_capability_gains?.length"
              class="path-section"
            >
              <h4>预期能力收益</h4>
              <ul>
                <li v-for="gain in path.research_inspiration.expected_capability_gains" :key="gain">
                  {{ gain }}
                </li>
              </ul>
            </div>
            <div
              v-if="path.research_inspiration?.application_directions?.length"
              class="path-section"
            >
              <h4>应用 / 转化方向</h4>
              <ul>
                <li
                  v-for="direction in path.research_inspiration.application_directions"
                  :key="direction"
                >
                  {{ direction }}
                </li>
              </ul>
            </div>
            <div
              v-if="path.research_inspiration?.applicable_conditions?.length"
              class="path-section"
            >
              <h4>适用条件</h4>
              <ul>
                <li
                  v-for="condition in path.research_inspiration.applicable_conditions"
                  :key="condition"
                >
                  {{ condition }}
                </li>
              </ul>
            </div>
            <div
              v-if="path.research_inspiration?.uncertainties?.length"
              class="path-section path-gaps"
            >
              <h4>不确定性与边界</h4>
              <ul>
                <li
                  v-for="uncertainty in path.research_inspiration.uncertainties"
                  :key="uncertainty"
                >
                  {{ uncertainty }}
                </li>
              </ul>
            </div>
            <div v-if="path.evidence_gaps?.length" class="path-section path-gaps">
              <h4>证据缺口</h4>
              <ul>
                <li v-for="gap in path.evidence_gaps" :key="gap">{{ gap }}</li>
              </ul>
            </div>
            <div v-if="path.research_inspiration?.review_questions?.length" class="path-section">
              <h4>建议研发评审问题</h4>
              <ul>
                <li v-for="question in path.research_inspiration.review_questions" :key="question">
                  {{ question }}
                </li>
              </ul>
            </div>
          </details>
          <footer class="path-card-footer">
            <a-button size="small" @click="copyPathSummary(path)">复制链路摘要</a-button>
            <a-button size="small" @click="viewPathInGraph(path)">在图中查看</a-button>
          </footer>
        </article>
      </div>

      <section
        v-if="activeDiscoveryFeature === 'innovation' && innovationDiscoverySearched"
        class="innovation-results"
      >
        <div class="innovation-heading">
          <div>
            <h3>预测创新关联</h3>
            <p>
              {{
                activeDiscoveryGuide.resultDescription
              }}；以下候选均为待验证假设，不会自动晋升为事实。
            </p>
          </div>
          <div>
            <a-tag color="purple">{{ activeDiscoveryGuide.label }}</a-tag>
            <a-tag
              v-if="innovationDiscoveryResult.innovation_enhancement?.status"
              :color="
                innovationDiscoveryResult.innovation_enhancement.status === 'completed'
                  ? 'blue'
                  : innovationDiscoveryResult.innovation_enhancement.status === 'degraded'
                    ? 'red'
                    : 'default'
              "
            >
              LLM {{ innovationDiscoveryResult.innovation_enhancement.status }}
            </a-tag>
            <a-tag color="orange">Hypothesis</a-tag>
            <a-tag
              v-if="innovationDiscoveryResult.evidence_scope === 'cross_document'"
              color="blue"
            >
              仅跨文档
            </a-tag>
          </div>
        </div>
        <section
          v-if="innovationDiscoveryResult.query_analysis?.analysis_version"
          class="requirement-analysis"
        >
          <header>
            <div>
              <h4>需求解析与实体映射</h4>
              <p>{{ innovationDiscoveryResult.query_analysis.analysis_version }}</p>
            </div>
            <a-tag
              :color="
                innovationDiscoveryResult.query_analysis.needs_human_review ? 'orange' : 'green'
              "
            >
              {{
                innovationDiscoveryResult.query_analysis.needs_human_review
                  ? '建议人工复核'
                  : '字段已映射'
              }}
            </a-tag>
          </header>
          <dl>
            <div v-if="innovationDiscoveryResult.query_analysis.concept_targets?.length">
              <dt>需求 / 问题空间</dt>
              <dd>{{ innovationDiscoveryResult.query_analysis.concept_targets.join('；') }}</dd>
            </div>
            <div v-if="innovationDiscoveryResult.query_analysis.principle_terms?.length">
              <dt>作用原理</dt>
              <dd>{{ innovationDiscoveryResult.query_analysis.principle_terms.join('；') }}</dd>
            </div>
            <div v-if="innovationDiscoveryResult.query_analysis.target_capabilities?.length">
              <dt>目标能力</dt>
              <dd>{{ innovationDiscoveryResult.query_analysis.target_capabilities.join('；') }}</dd>
            </div>
            <div v-if="innovationDiscoveryResult.query_analysis.application_scenarios?.length">
              <dt>应用场景</dt>
              <dd>
                {{ innovationDiscoveryResult.query_analysis.application_scenarios.join('；') }}
              </dd>
            </div>
            <div v-if="innovationDiscoveryResult.query_analysis.constraints?.length">
              <dt>技术约束</dt>
              <dd>{{ innovationDiscoveryResult.query_analysis.constraints.join('；') }}</dd>
            </div>
            <div v-if="innovationDiscoveryResult.query_analysis.key_technical_elements?.length">
              <dt>技术要素</dt>
              <dd>
                {{ innovationDiscoveryResult.query_analysis.key_technical_elements.join('；') }}
              </dd>
            </div>
          </dl>
          <div
            v-if="innovationDiscoveryResult.query_analysis.entity_mappings?.length"
            class="requirement-mappings"
          >
            <a-tag
              v-for="mapping in innovationDiscoveryResult.query_analysis.entity_mappings"
              :key="`${mapping.requirement_field}-${mapping.entity_id}`"
              color="blue"
            >
              {{ mapping.name }} · {{ Math.round(mapping.mapping_score * 100) }}%
            </a-tag>
          </div>
        </section>
        <section
          v-if="innovationDiscoveryResult.feedback_loop"
          class="innovation-feedback-loop"
          aria-label="创新发现证据回环"
        >
          <header>
            <div>
              <span>DISCOVERY FEEDBACK LOOP</span>
              <h4>发现回环建议</h4>
              <p>把证据缺口转成再检索与定向复抽任务；所有结果仍保持 Hypothesis。</p>
            </div>
            <a-tag :color="feedbackLoopStatusColor(innovationDiscoveryResult.feedback_loop.status)">
              {{ feedbackLoopStatusLabel(innovationDiscoveryResult.feedback_loop.status) }}
            </a-tag>
          </header>
          <div class="feedback-loop-grid">
            <div>
              <strong>建议再检索词</strong>
              <p v-if="innovationDiscoveryResult.feedback_loop.requery_terms?.length">
                {{ innovationDiscoveryResult.feedback_loop.requery_terms.join('；') }}
              </p>
              <p v-else>当前没有新增检索词。</p>
              <a-button
                v-if="innovationDiscoveryResult.feedback_loop.requery_terms?.length"
                size="small"
                @click="applyFeedbackRequeryTerms"
              >
                应用检索词
              </a-button>
            </div>
            <div>
              <strong>证据缺口</strong>
              <ul v-if="innovationDiscoveryResult.feedback_loop.evidence_gaps?.length">
                <li v-for="gap in innovationDiscoveryResult.feedback_loop.evidence_gaps" :key="gap">
                  {{ gap }}
                </li>
              </ul>
              <p v-else>未发现显式证据缺口。</p>
            </div>
            <div>
              <strong>待验证任务</strong>
              <ul v-if="innovationDiscoveryResult.feedback_loop.validation_tasks?.length">
                <li
                  v-for="task in innovationDiscoveryResult.feedback_loop.validation_tasks"
                  :key="task"
                >
                  {{ task }}
                </li>
              </ul>
              <p v-else>当前没有新增验证任务。</p>
            </div>
            <div>
              <strong>定向复抽范围</strong>
              <p v-if="innovationDiscoveryResult.feedback_loop.reextraction?.recommended">
                建议复抽
                {{ innovationDiscoveryResult.feedback_loop.reextraction.file_ids.length }}
                篇文档、{{ innovationDiscoveryResult.feedback_loop.reextraction.chunk_ids.length }}
                个 Chunk。
              </p>
              <p v-else>现有证据不足以安全定位复抽目标。</p>
            </div>
          </div>
          <footer>
            不会自动写入事实图谱；复抽、新边与创新结论仍需经过现有证据治理与人工审核。
          </footer>
        </section>
        <a-empty
          v-if="!innovationDiscoveryResult.hypotheses.length"
          description="当前证据路径不足以形成新的候选关联。"
        />
        <div
          v-if="innovationDiscoveryResult.hypotheses.length"
          class="result-toolbar result-toolbar--innovation"
          aria-label="创新预测筛选与排序"
        >
          <div class="result-toolbar__summary">
            <strong>{{ visibleHypotheses.length }}</strong
            ><span>当前候选</span> <strong>{{ innovationResultOverview.pendingHypotheses }}</strong
            ><span>待审核</span> <strong>{{ innovationResultOverview.crossDocument }}</strong
            ><span>跨文档</span> <strong>{{ innovationResultOverview.weakSignals }}</strong
            ><span>弱信号</span>
          </div>
          <div class="result-toolbar__controls">
            <a-select
              v-model:value="innovationResultView.scope"
              size="small"
              aria-label="创新候选筛选"
            >
              <a-select-option value="all">全部候选</a-select-option>
              <a-select-option value="pending">仅待审核</a-select-option>
              <a-select-option value="priority">优先论证</a-select-option>
              <a-select-option value="cross_document">跨文档支持</a-select-option>
              <a-select-option value="weak_signal">高价值弱信号</a-select-option>
            </a-select>
            <a-select
              v-model:value="innovationResultView.sortBy"
              size="small"
              aria-label="创新候选排序"
            >
              <a-select-option value="strategic">战略价值优先</a-select-option>
              <a-select-option value="evidence">证据强度优先</a-select-option>
              <a-select-option value="confidence">候选可信度优先</a-select-option>
            </a-select>
          </div>
        </div>
        <a-empty
          v-if="innovationDiscoveryResult.hypotheses.length && !visibleHypotheses.length"
          description="当前筛选条件下没有创新候选。"
        />
        <article
          v-for="hypothesis in visibleHypotheses"
          :key="hypothesis.hypothesis_id"
          class="path-card innovation-card"
        >
          <header class="path-card-header">
            <div class="path-card-title hypothesis-card-title">
              <a-tag color="orange">{{ hypothesis.review_status }}</a-tag>
              <a-tag v-if="hypothesis.evidence_path.cross_document" color="blue">
                {{ hypothesis.evidence_path.document_count }} 文档交叉支持
              </a-tag>
              <a-tag v-if="hypothesis.pending_evidence" color="red">包含待审证据</a-tag>
            </div>
            <div class="path-card-score path-card-score--innovation">
              <strong>{{ formatPercent(hypothesis.score) }}</strong>
              <span>候选可信度</span>
            </div>
          </header>
          <div class="hypothesis-route" aria-label="创新假设关联">
            <div>
              <span>起点实体</span>
              <strong>{{ hypothesis.source.name }}</strong>
              <small>{{
                semanticRoleLabel(hypothesis.source.semantic_role || 'technology')
              }}</small>
            </div>
            <div class="hypothesis-relation">
              <span>{{ innovationRelationLabel(hypothesis.relation_type) }}</span>
              <small>{{ hypothesis.relation_type }}</small>
            </div>
            <div>
              <span>潜在目标</span>
              <strong>{{ hypothesis.target.name }}</strong>
              <small>{{
                semanticRoleLabel(hypothesis.target.semantic_role || 'capability')
              }}</small>
            </div>
          </div>
          <p class="innovation-mechanism">{{ hypothesis.mechanism_hypothesis }}</p>
          <section v-if="hypothesis.innovation_profile?.dimensions" class="innovation-profile">
            <header>
              <div>
                <h4>新质创新价值剖面</h4>
                <p>按当前发现模式加权；弱信号表示低频但可追溯的潜在线索，不等同于事实结论。</p>
              </div>
              <a-tag :color="innovationPriorityColor(hypothesis.innovation_profile.priority)">
                {{ innovationPriorityLabel(hypothesis.innovation_profile.priority) }}
              </a-tag>
            </header>
            <div class="innovation-dimension-grid">
              <div>
                <span>军事价值</span>
                <strong>{{ innovationPercent(hypothesis, 'military_value') }}</strong>
              </div>
              <div>
                <span>新颖性</span>
                <strong>{{ innovationPercent(hypothesis, 'novelty') }}</strong>
              </div>
              <div>
                <span>工程可行性</span>
                <strong>{{ innovationPercent(hypothesis, 'feasibility') }}</strong>
              </div>
              <div>
                <span>迁移组合潜力</span>
                <strong>{{ innovationPercent(hypothesis, 'transferability') }}</strong>
              </div>
              <div>
                <span>证据强度</span>
                <strong>{{ innovationPercent(hypothesis, 'evidence_strength') }}</strong>
              </div>
              <div>
                <span>弱信号潜力</span>
                <strong>{{ innovationPercent(hypothesis, 'weak_signal_potential') }}</strong>
              </div>
            </div>
            <div class="innovation-profile-summary">
              <span
                >战略综合分
                {{ Math.round(hypothesis.innovation_profile.strategic_score * 100) }}%</span
              >
              <span v-if="hypothesis.innovation_profile.signals?.source_document_count">
                {{ hypothesis.innovation_profile.signals.source_document_count }} 个来源交叉验证
              </span>
              <span v-if="hypothesis.innovation_profile.weak_signal">已识别为高价值弱信号候选</span>
            </div>
          </section>
          <div
            class="result-quality-strip result-quality-strip--innovation"
            aria-label="假设证据摘要"
          >
            <div>
              <span>支撑关系</span>
              <strong>{{ hypothesis.evidence_path?.relation_ids?.length || 0 }}</strong>
            </div>
            <div>
              <span>证据 Chunk</span>
              <strong>{{ hypothesis.evidence_path?.chunk_ids?.length || 0 }}</strong>
            </div>
            <div>
              <span>来源文件</span>
              <strong>{{ hypothesis.evidence_path?.file_ids?.length || 0 }}</strong>
            </div>
            <div>
              <span>证据强度</span>
              <strong>{{ innovationPercent(hypothesis, 'evidence_strength') }}</strong>
            </div>
          </div>

          <div
            v-if="innovationResearchThreadEntries(hypothesis).length"
            class="research-thread-map"
          >
            <div
              v-for="thread in innovationResearchThreadEntries(hypothesis)"
              :key="thread.key"
              :class="`research-thread research-thread--${thread.key}`"
            >
              <header>
                <span>{{ thread.label }}</span>
                <small>{{ thread.description }}</small>
              </header>
              <div>
                <a-tag v-for="entity in thread.entities" :key="entity">{{ entity }}</a-tag>
              </div>
            </div>
          </div>

          <details class="result-audit-disclosure innovation-audit-disclosure">
            <summary>
              <span>展开论证依据与验证门槛</span>
              <small>Hypothesis · 不作为既成事实</small>
            </summary>
            <div v-if="hypothesis.feasibility_basis?.length" class="path-section">
              <h4>可行性依据</h4>
              <ul>
                <li v-for="basis in hypothesis.feasibility_basis" :key="basis">{{ basis }}</li>
              </ul>
            </div>
            <div v-if="hypothesis.expected_effects?.length" class="path-section">
              <h4>预期效果</h4>
              <ul>
                <li v-for="effect in hypothesis.expected_effects" :key="effect">{{ effect }}</li>
              </ul>
            </div>
            <div v-if="hypothesis.applicable_conditions?.length" class="path-section">
              <h4>适用条件</h4>
              <ul>
                <li v-for="condition in hypothesis.applicable_conditions" :key="condition">
                  {{ condition }}
                </li>
              </ul>
            </div>
            <div
              v-if="hypothesis.validation_requirements?.length"
              class="path-section validation-section"
            >
              <h4>必须完成的验证</h4>
              <ul>
                <li v-for="requirement in hypothesis.validation_requirements" :key="requirement">
                  {{ requirement }}
                </li>
              </ul>
            </div>
            <div
              v-if="hypothesis.falsification_criteria?.length"
              class="path-section falsification-section"
            >
              <h4>可证伪标准</h4>
              <ul>
                <li v-for="criterion in hypothesis.falsification_criteria" :key="criterion">
                  {{ criterion }}
                </li>
              </ul>
            </div>
            <div v-if="hypothesis.constraint_conflicts?.length" class="path-section path-gaps">
              <h4>约束冲突</h4>
              <ul>
                <li v-for="conflict in hypothesis.constraint_conflicts" :key="conflict">
                  {{ conflict }}
                </li>
              </ul>
            </div>
            <div v-if="hypothesis.uncertainties?.length" class="path-section path-gaps">
              <h4>不确定性</h4>
              <ul>
                <li v-for="uncertainty in hypothesis.uncertainties" :key="uncertainty">
                  {{ uncertainty }}
                </li>
              </ul>
            </div>
          </details>
          <div class="decision-next-action">
            <span>建议下一步</span>
            <strong>{{ innovationNextAction(hypothesis) }}</strong>
          </div>
          <footer class="path-card-footer">
            <a-button size="small" @click="copyInnovationSummary(hypothesis)"
              >复制论证摘要</a-button
            >
            <template v-if="hypothesis.review_status === 'pending'">
              <a-button size="small" @click="reviewInnovation(hypothesis, 'rejected')"
                >拒绝</a-button
              >
              <a-button
                size="small"
                type="primary"
                @click="reviewInnovation(hypothesis, 'accepted')"
              >
                接受为待验证方向
              </a-button>
            </template>
          </footer>
        </article>
      </section>
      <section v-if="solutionGenerationResult" class="innovation-results grounded-solution-results">
        <div class="innovation-heading">
          <div>
            <h3>证据约束技术方案</h3>
            <p>结果不会写入事实图谱，必须经过专家复核和独立验证。</p>
          </div>
          <div class="innovation-heading-tags">
            <a-tag v-if="solutionGenerationResult.evidence_scope === 'cross_document'" color="blue">
              {{ solutionGenerationResult.source_document_count }} 文档交叉支持
            </a-tag>
            <a-tag color="orange">{{ solutionGenerationResult.claim_level }}</a-tag>
          </div>
        </div>
        <article class="path-card innovation-card">
          <div class="path-section">
            <h4>机理假说</h4>
            <p class="innovation-mechanism">
              {{ solutionGenerationResult.mechanism_hypothesis }}
            </p>
          </div>
          <div class="path-section">
            <h4>可行性依据</h4>
            <ul>
              <li v-for="item in solutionGenerationResult.feasibility_basis" :key="item">
                {{ item }}
              </li>
            </ul>
          </div>
          <div class="path-section">
            <h4>预期效果</h4>
            <ul>
              <li v-for="item in solutionGenerationResult.expected_effects" :key="item">
                {{ item }}
              </li>
            </ul>
          </div>
          <div class="path-section path-gaps">
            <h4>不确定性与待验证条件</h4>
            <ul>
              <li v-for="item in solutionGenerationResult.uncertainties" :key="item">
                {{ item }}
              </li>
            </ul>
          </div>
          <div v-if="solutionGenerationResult.confidence" class="path-section">
            <h4>可信度分解</h4>
            <p>
              {{ (solutionGenerationResult.confidence.score * 100).toFixed(1) }}% ·
              {{ solutionGenerationResult.confidence.level }}
            </p>
            <ul>
              <li>
                图路径质量
                {{
                  (solutionGenerationResult.confidence.components.path_quality * 100).toFixed(1)
                }}%
              </li>
              <li>
                来源多样性
                {{
                  (solutionGenerationResult.confidence.components.source_diversity * 100).toFixed(
                    1
                  )
                }}%
              </li>
              <li>
                引用覆盖率
                {{
                  (solutionGenerationResult.confidence.components.citation_coverage * 100).toFixed(
                    1
                  )
                }}%
              </li>
              <li>
                Span 完整度
                {{
                  (solutionGenerationResult.confidence.components.span_completeness * 100).toFixed(
                    1
                  )
                }}%
              </li>
            </ul>
            <p class="form-item-hint">{{ solutionGenerationResult.confidence.interpretation }}</p>
          </div>
          <div v-if="solutionGenerationResult.innovation_brief" class="path-section">
            <h4>创新简报</h4>
            <p>{{ solutionGenerationResult.innovation_brief.title }}</p>
            <p class="form-item-hint">
              {{ solutionGenerationResult.innovation_brief.review_statement }}
            </p>
          </div>
          <div class="path-evidence-summary">
            <span>{{ solutionGenerationResult.evidence.length }} 个原文证据 Chunk</span>
            <span>{{ solutionGenerationResult.path.length }} 条已接受图路径</span>
            <span>图谱版本 {{ solutionGenerationResult.graph_revision || '未登记' }}</span>
          </div>
          <div class="solution-evidence-list">
            <details
              v-for="evidence in solutionGenerationResult.evidence"
              :key="evidence.evidence_id"
            >
              <summary>
                {{ evidence.evidence_id }} · {{ evidence.file_id }}
                <span v-if="evidence.page"> · 第 {{ evidence.page }} 页</span>
              </summary>
              <p>{{ evidence.text }}</p>
            </details>
          </div>
        </article>
      </section>
    </a-modal>
    <GraphReviewWorkbench
      v-if="isMilvus && !readonly"
      v-model:open="showReviewWorkbench"
      :kb-id="kbId"
      @reviewed="handleGraphReviewed"
    />
    <GraphRevisionHistoryWorkbench
      v-if="isMilvus"
      v-model:open="showRevisionHistory"
      :kb-id="kbId"
    />
    <DocumentKnowledgeCardWorkbench
      v-if="isMilvus"
      v-model:open="showDocumentAudit"
      :kb-id="kbId"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onUnmounted, reactive, defineAsyncComponent } from 'vue'
import { useDatabaseStore } from '@/stores/database'
import { useTaskerStore } from '@/stores/tasker'
import { useConfigStore } from '@/stores/config'
import {
  RefreshCw,
  Settings,
  Search,
  Loader2,
  Database,
  Network,
  BrainCircuit,
  Waypoints,
  ClipboardCheck,
  Sparkles,
  History,
  FileSearch,
  SlidersHorizontal,
  ChevronDown,
  ChevronUp
} from '@lucide/vue'
import GraphCanvas from '@/components/GraphCanvas.vue'
import GraphDetailPanel from '@/components/GraphDetailPanel.vue'
import ResourceEmptyState from '@/components/shared/ResourceEmptyState.vue'
import GraphFailedRetryCard from '@/components/knowledge/GraphFailedRetryCard.vue'
import { getKbTypeLabel } from '@/utils/kb_utils'
import { KNOWLEDGE_GRAPH_LAYOUTS } from '@/utils/knowledgeGraphLayout'
import {
  DEFAULT_GRAPH_EXTRACTION_CONCURRENCY,
  DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
  DEFAULT_GRAPH_EXTRACTION_MAX_TOKENS,
  DEFAULT_GRAPH_THINKING_BUDGET,
  GRAPH_EXTRACTION_PRESETS,
  applyGraphExtractionPreset,
  graphExtractionRiskMessage,
  graphPerformanceOptions,
  unmanagedGraphModelParams,
  matchGraphExtractionPreset
} from '@/utils/graphExtractionConfig'
import { unifiedApi } from '@/apis/graph_api'
import { graphBuildApi } from '@/apis/knowledge_api'
import { Modal, message } from 'ant-design-vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import { useGraph } from '@/composables/useGraph'
import { useAuthoritativeGraphDetail } from '@/composables/useAuthoritativeGraphDetail'

const GRAPH_BUILD_TASK_TYPE = 'knowledge_graph_index'
const MILVUS_KB_TYPE = 'milvus'
const GRAPH_SUPPORTED_KB_TYPES = new Set([MILVUS_KB_TYPE])
const GraphReviewWorkbench = defineAsyncComponent(
  () => import('@/components/knowledge/GraphReviewWorkbench.vue')
)
const GraphRevisionHistoryWorkbench = defineAsyncComponent(
  () => import('@/components/knowledge/GraphRevisionHistoryWorkbench.vue')
)
const DocumentKnowledgeCardWorkbench = defineAsyncComponent(
  () => import('@/components/knowledge/DocumentKnowledgeCardWorkbench.vue')
)

const props = defineProps({
  active: {
    type: Boolean,
    default: false
  },
  readonly: {
    type: Boolean,
    default: false
  }
})

const store = useDatabaseStore()
const taskerStore = useTaskerStore()
const configStore = useConfigStore()

const kbId = computed(() => store.kbId)
const kbType = computed(() => store.database.kb_type)
const kbTypeLabel = computed(() => getKbTypeLabel(kbType.value || 'milvus'))
const isMilvus = computed(() => kbType.value?.toLowerCase() === MILVUS_KB_TYPE)

const graphRef = ref(null)
const layoutMode = ref(KNOWLEDGE_GRAPH_LAYOUTS.FORCE)
const layoutOptions = [
  { label: '自由', value: KNOWLEDGE_GRAPH_LAYOUTS.FORCE },
  { label: '按标签', value: KNOWLEDGE_GRAPH_LAYOUTS.GROUPED }
]
const setLayoutMode = (mode) => {
  layoutMode.value = mode
}
const showSettings = ref(false)
const showBuildPanel = ref(false)
const showReviewWorkbench = ref(false)
const showRevisionHistory = ref(false)
const showDocumentAudit = ref(false)
const subgraphParams = reactive({
  maxNodes: 100,
  maxDepth: 2,
  excludeChunk: true
})
const searchInput = ref('')
const graphBuildStatus = ref(null)
const graphBuildLoading = ref(false)
const acceptanceStatus = ref(null)
const acceptanceLoading = ref(false)
const retryingFailedChunks = ref(false)
const showGraphConfig = ref(false)
const showAdvancedGraphConfig = ref(false)
const graphConfigSaving = ref(false)
const showFailedChunkSamples = ref(false)
const failedChunkSamplesLoading = ref(false)
const failedChunkSamples = ref([])
const activeFailedChunkKey = ref('')
const showPathDiscovery = ref(false)
const activeDiscoveryFeature = ref('multihop')
const pathDiscoveryLoading = ref(false)
const pathDiscoverySearched = ref(false)
const pathDiscoveryResult = reactive({
  paths: [],
  summary: {},
  query_plan: null,
  path_reranking: null,
  pipeline_trace: null,
  narrative: null,
  narrative_provenance: null,
  discovery_mode: null,
  feature_kind: null
})
const innovationDiscoveryLoading = ref(false)
const innovationDiscoverySearched = ref(false)
const innovationDiscoveryResult = reactive({
  hypotheses: [],
  graph_revision: null,
  query_analysis: null,
  innovation_enhancement: null,
  pipeline_trace: null,
  feedback_loop: null,
  evidence_scope: 'any',
  cross_document_candidate_count: 0
})
const solutionGeneration = reactive({
  enabled: false,
  model_spec: ''
})
const queryEnhancement = reactive({
  enabled: true,
  model_spec: '',
  strict: false
})
const pathReranking = reactive({
  enabled: true,
  model_spec: '',
  strict: false
})
const narrativeEnhancement = reactive({
  enabled: true,
  model_spec: '',
  strict: false
})
const innovationEnhancement = reactive({
  enabled: true,
  model_spec: '',
  strict: false,
  concurrency_count: 2
})
const solutionGenerationLoading = ref(false)
const solutionGenerationResult = ref(null)
const pathQuery = reactive({
  query: '',
  mode: 'requirement_driven',
  retrieval_mode: 'mix',
  max_hops: 5,
  max_paths: 10,
  include_combinations: true,
  evidence_scope: 'any',
  exploration_preset: 'deep'
})
const pathResultView = reactive({
  claimLevel: 'all',
  sortBy: 'score'
})
const innovationResultView = reactive({
  scope: 'all',
  sortBy: 'strategic'
})
const explorationPresets = [
  {
    value: 'quick',
    label: '快速研判',
    description: '3 跳 · 关闭探索组合',
    max_hops: 3,
    max_paths: 6,
    retrieval_mode: 'hybrid',
    include_combinations: false,
    evidence_scope: 'any'
  },
  {
    value: 'deep',
    label: '深度发现',
    description: '5 跳 · Mix · 跨文档扩展',
    max_hops: 5,
    max_paths: 10,
    retrieval_mode: 'mix',
    include_combinations: true,
    evidence_scope: 'any'
  },
  {
    value: 'evidence',
    label: '证据优先',
    description: '4 跳 · 仅跨文档 · 不做组合',
    max_hops: 4,
    max_paths: 8,
    retrieval_mode: 'mix',
    include_combinations: false,
    evidence_scope: 'cross_document'
  }
]
const innovationTemplates = {
  auto: [
    {
      label: '复杂电磁环境能力提升',
      description: '从能力缺口联合发现原理、技术与应用链路',
      query: '复杂电磁环境下协同感知、抗干扰与持续任务能力提升'
    },
    {
      label: '无人系统协同感知',
      description: '融合多源感知、组网协同与边缘智能证据',
      query: '通信受限条件下无人系统多源协同感知与自主任务能力'
    },
    {
      label: '装备防护韧性',
      description: '探索材料、结构、监测与恢复技术组合',
      query: '面向高强度对抗的装备生存、防护与快速恢复韧性'
    }
  ],
  requirement_driven: [
    {
      label: '受限通信协同探测',
      description: '能力与场景牵引的自上而下路线',
      query: '在强干扰和通信受限条件下提升无人集群协同探测能力'
    },
    {
      label: '远程持续保障',
      description: '从持续任务能力回溯关键技术与约束',
      query: '复杂环境下远程无人装备持续任务与自主保障能力'
    },
    {
      label: '低可探测生存',
      description: '从生存需求定位材料、结构与控制链路',
      query: '多谱段探测威胁下装备低可探测与生存能力提升'
    }
  ],
  entity_expansion: [
    {
      label: '新材料跨域迁移',
      description: '发现材料机理向装备能力的迁移路径',
      query: '超材料与智能材料在感知、防护和能量调控中的跨域迁移'
    },
    {
      label: '新原理能力涌现',
      description: '从弱信号原理推演潜在能力与场景',
      query: '太赫兹探测与分布式孔径原理可形成的潜在装备能力'
    },
    {
      label: '多技术互补组合',
      description: '探索技术间尚未显式连接的互补边',
      query: '边缘智能、认知通信与协同感知的互补技术组合'
    }
  ]
}
const innovationModeOptions = [
  {
    value: 'requirement_driven',
    label: '自上而下 · 需求牵引',
    badge: '能力 → 技术',
    description: '从作战能力、应用场景与约束出发，寻找可组合技术路线',
    inputLabel: '输入目标能力、任务场景与关键约束',
    placeholder: '例如：在强干扰和通信受限条件下提升无人集群协同探测能力',
    hint: 'LLM 先解析目标能力、场景和约束，再由轻量化 RAG 回溯多跳技术链路。',
    resultDescription: '从目标能力向下映射技术要素、原理与装备候选',
    icon: BrainCircuit
  },
  {
    value: 'entity_expansion',
    label: '自下而上 · 技术涌现',
    badge: '技术 → 能力',
    description: '从新原理、材料或器件出发，发现跨域组合和潜在能力增益',
    inputLabel: '输入技术原理、材料、器件或装备实体',
    placeholder: '例如：超材料、太赫兹探测或分布式孔径雷达',
    hint: '轻量化 RAG 扩展技术邻域与跨文档关系，LLM 归纳可迁移场景和能力增益。',
    resultDescription: '从技术实体向上推演跨域应用、装备集成与能力增益',
    icon: Sparkles
  }
]
const activeDiscoveryGuide = computed(
  () =>
    innovationModeOptions.find((option) => option.value === pathQuery.mode) ||
    innovationModeOptions[0]
)
const activeInnovationTemplates = computed(
  () => innovationTemplates[pathQuery.mode] || innovationTemplates.auto
)
const innovationResultOverview = computed(() => {
  const hypotheses = innovationDiscoveryResult.hypotheses || []
  const trustedPaths = (pathDiscoveryResult.paths || []).filter((path) => {
    const claimLevel = String(path?.claim_level || '').toLowerCase()
    return claimLevel !== 'hypothesis' && Number(path?.evidence?.mention_count || 0) > 0
  }).length
  const pendingHypotheses = hypotheses.filter(
    (hypothesis) => String(hypothesis?.review_status || 'pending') === 'pending'
  ).length
  const crossDocumentFromResults = hypotheses.filter(
    (hypothesis) => hypothesis?.evidence_path?.cross_document
  ).length
  const weakSignals = hypotheses.filter(
    (hypothesis) => hypothesis?.innovation_profile?.weak_signal === true
  ).length
  const evidenceStrengths = hypotheses
    .map((hypothesis) => Number(hypothesis?.innovation_profile?.dimensions?.evidence_strength))
    .filter((value) => Number.isFinite(value))
  const averageEvidenceStrength = evidenceStrengths.length
    ? Math.round(
        (evidenceStrengths.reduce((total, value) => total + value, 0) / evidenceStrengths.length) *
          100
      )
    : 0
  return {
    trustedPaths,
    pendingHypotheses,
    crossDocument: Math.max(
      Number(innovationDiscoveryResult.cross_document_candidate_count || 0),
      crossDocumentFromResults
    ),
    weakSignals,
    averageEvidenceStrength
  }
})
const activeQueryPipelineTrace = computed(() => {
  if (
    activeDiscoveryFeature.value === 'innovation' &&
    innovationDiscoveryResult.pipeline_trace?.stages?.length
  ) {
    return innovationDiscoveryResult.pipeline_trace
  }
  return pathDiscoveryResult.pipeline_trace
})

const narrativeResultSections = computed(() => {
  const narrative = pathDiscoveryResult.narrative || {}
  return [
    { key: 'reasoning_chain', label: '逐步推理链', items: narrative.reasoning_chain || [] },
    { key: 'key_findings', label: '关键发现', items: narrative.key_findings || [] },
    { key: 'technology_routes', label: '技术路线', items: narrative.technology_routes || [] },
    {
      key: 'capability_implications',
      label: '能力含义',
      items: narrative.capability_implications || []
    },
    {
      key: 'application_directions',
      label: '应用方向',
      items: narrative.application_directions || []
    },
    {
      key: 'evidence_boundaries',
      label: '证据边界',
      items: narrative.evidence_boundaries || []
    },
    {
      key: 'unresolved_questions',
      label: '待验证问题',
      items: narrative.unresolved_questions || []
    }
  ]
})
const queryTraceStatusLabel = (status) =>
  ({ completed: '完成', warning: '降级', skipped: '未启用' })[status] || '未知'
const queryTraceStatusColor = (status) =>
  ({ completed: 'green', warning: 'orange', skipped: 'default' })[status] || 'default'
const feedbackLoopStatusLabel = (status) =>
  ({ ready: '可进入验证', requires_evidence: '需要补证', no_candidate: '暂无候选' })[status] ||
  '待研判'
const feedbackLoopStatusColor = (status) =>
  ({ ready: 'green', requires_evidence: 'orange', no_candidate: 'default' })[status] || 'default'
const pathQualitySummary = computed(() => {
  const quality = pathDiscoveryResult.summary?.quality
  if (quality) return quality

  const paths = pathDiscoveryResult.paths || []
  const fileIds = new Set(paths.flatMap((path) => path?.evidence?.file_ids || []))
  const relationIds = new Set(paths.flatMap((path) => path?.relation_ids || []))
  const coverage = paths.map((path) => Number(path?.semantic_coverage || 0))
  return {
    trusted_path_count: paths.filter(
      (path) => path?.claim_level !== 'Hypothesis' && !path?.pending_evidence
    ).length,
    hypothesis_path_count: paths.filter((path) => path?.claim_level === 'Hypothesis').length,
    pending_review_count: paths.filter((path) => path?.pending_evidence).length,
    cross_document_path_count: paths.filter((path) => (path?.evidence?.file_ids || []).length > 1)
      .length,
    complete_semantic_chain_count: coverage.filter((value) => value >= 1).length,
    unique_source_count: fileIds.size,
    unique_relation_count: relationIds.size,
    average_semantic_coverage: coverage.length
      ? coverage.reduce((total, value) => total + value, 0) / coverage.length
      : 0,
    average_score: paths.length
      ? paths.reduce((total, path) => total + Number(path?.score || 0), 0) / paths.length
      : 0
  }
})
const visiblePaths = computed(() => {
  const paths = [...(pathDiscoveryResult.paths || [])].filter((path) => {
    if (pathResultView.claimLevel === 'trusted') {
      return path?.claim_level !== 'Hypothesis' && !path?.pending_evidence
    }
    if (pathResultView.claimLevel === 'hypothesis') return path?.claim_level === 'Hypothesis'
    if (pathResultView.claimLevel === 'pending') return Boolean(path?.pending_evidence)
    return true
  })
  const sortValue = (path) => {
    if (pathResultView.sortBy === 'coverage') return Number(path?.semantic_coverage || 0)
    if (pathResultView.sortBy === 'evidence') return Number(path?.evidence?.mention_count || 0)
    return Number(path?.score || 0)
  }
  return paths.sort((left, right) => sortValue(right) - sortValue(left))
})
const visibleHypotheses = computed(() => {
  const hypotheses = [...(innovationDiscoveryResult.hypotheses || [])].filter((hypothesis) => {
    if (innovationResultView.scope === 'pending') return hypothesis?.review_status === 'pending'
    if (innovationResultView.scope === 'priority') {
      return hypothesis?.innovation_profile?.priority === 'priority'
    }
    if (innovationResultView.scope === 'cross_document') {
      return Boolean(hypothesis?.evidence_path?.cross_document)
    }
    if (innovationResultView.scope === 'weak_signal') {
      return hypothesis?.innovation_profile?.weak_signal === true
    }
    return true
  })
  const sortValue = (hypothesis) => {
    if (innovationResultView.sortBy === 'evidence') {
      return Number(hypothesis?.innovation_profile?.dimensions?.evidence_strength || 0)
    }
    if (innovationResultView.sortBy === 'confidence') return Number(hypothesis?.score || 0)
    return Number(hypothesis?.innovation_profile?.strategic_score || 0)
  }
  return hypotheses.sort((left, right) => sortValue(right) - sortValue(left))
})
const applyInnovationTemplate = (template) => {
  pathQuery.query = template.query
}

const applyFeedbackRequeryTerms = () => {
  const terms = innovationDiscoveryResult.feedback_loop?.requery_terms || []
  if (!terms.length) return
  pathQuery.query = terms.join('；').slice(0, 500)
  message.info('已填入建议检索词，请确认后重新检索；系统不会自动发起请求。')
}

const applyExplorationPreset = (preset) => {
  pathQuery.max_hops = preset.max_hops
  pathQuery.max_paths = preset.max_paths
  pathQuery.retrieval_mode = preset.retrieval_mode
  pathQuery.include_combinations = preset.include_combinations
  pathQuery.evidence_scope = preset.evidence_scope
  pathQuery.exploration_preset = preset.value
}

watch(
  () => [
    pathQuery.max_hops,
    pathQuery.max_paths,
    pathQuery.retrieval_mode,
    pathQuery.include_combinations,
    pathQuery.evidence_scope
  ],
  ([maxHops, maxPaths, retrievalMode, includeCombinations, evidenceScope]) => {
    const matchingPreset = explorationPresets.find(
      (preset) =>
        preset.max_hops === maxHops &&
        preset.max_paths === maxPaths &&
        preset.retrieval_mode === retrievalMode &&
        preset.include_combinations === includeCombinations &&
        preset.evidence_scope === evidenceScope
    )
    pathQuery.exploration_preset = matchingPreset?.value || 'custom'
  }
)

let buildStatusPollTimer = null

const extractorTypeOptions = [
  {
    value: 'lightrag_primary',
    label: '轻量化 RAG',
    description: '项目 LLM 并发完成实体关系初抽、gleaning 与跨文档增强',
    helper: '低资源占用，支持五种检索模式与双向创新预测',
    icon: Network,
    disabled: false
  }
]

const graphOrchestrationOptions = [
  {
    value: 'lightrag_primary',
    label: '轻量化 RAG / 项目 LLM 全链路',
    badge: '低本机负载',
    description: '由可更换项目 LLM 完成 Chunk、文档和跨文档抽取。',
    features: ['不占用本机 MPS', '统一模型易切换', '适合批量后台处理'],
    stages: ['文档解析', '轻量化 RAG 初抽', '一次查漏', '文档/跨文档增强', '图谱投影']
  }
]

const agentParallelismPresets = [
  { label: '稳定 · 2', value: 2 },
  { label: '均衡 · 4', value: 4 },
  { label: '高吞吐 · 8', value: 8 }
]

const activeOrchestrationOption = computed(
  () =>
    graphOrchestrationOptions.find(
      (option) => option.value === graphConfigForm.orchestration_mode
    ) || graphOrchestrationOptions[0]
)

const selectUnifiedGraphModel = (modelSpec) => {
  const spec = String(modelSpec || '').trim()
  graphConfigForm.llm_enhancement_model_spec = spec
  graphConfigForm.document_entity_enhancement_model_spec = spec
  graphConfigForm.document_llm_enhancement_model_spec = spec
  graphConfigForm.document_cross_relation_model_spec = spec
  graphConfigForm.entity_alignment_model_spec = spec
}

const applyDefaultGraphModel = () => {
  selectUnifiedGraphModel(configStore.config?.default_model)
}

const handleOrchestrationModeChange = () => {
  graphConfigForm.llm_enhancement_enabled = true
  graphConfigForm.document_enhancement_enabled = true
  graphConfigForm.document_entity_enhancement_enabled = true
  graphConfigForm.document_llm_enhancement_enabled = true
  graphConfigForm.document_cross_relation_enabled = true
  if (!graphConfigForm.llm_enhancement_model_spec && configStore.config?.default_model) {
    applyDefaultGraphModel()
  }
  graphConfigForm.llm_enhancement_concurrency = Math.max(
    Number(graphConfigForm.llm_enhancement_concurrency || 1),
    4
  )
}

const isBuildActive = computed(() => {
  const s = graphBuildStatus.value?.build_task_status
  return s === 'pending' || s === 'running'
})

const isBuildFailed = computed(() => {
  return graphBuildStatus.value?.build_task_status === 'failed'
})

const pendingGraphChunks = computed(() => {
  return Number(graphBuildStatus.value?.pending_chunks ?? 0)
})

const hasPendingGraphChunks = computed(() => pendingGraphChunks.value > 0)
const extractionFailedCount = computed(() =>
  Number(graphBuildStatus.value?.extraction_counts?.failed || 0)
)
const vectorPendingCount = computed(() => {
  const counts = graphBuildStatus.value?.vector_counts || {}
  return Number(counts.pending || 0) + Number(counts.processing || 0)
})
const vectorFailedCount = computed(() => Number(graphBuildStatus.value?.vector_counts?.failed || 0))

const acceptanceCriteria = computed(
  () => acceptanceStatus.value?.latest_evaluation?.report?.criteria || []
)
const acceptanceMetric = (criterionId) => {
  const value = acceptanceCriteria.value.find((item) => item.id === criterionId)?.actual
  return typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '-'
}
const acceptanceCriterionLabels = {
  evaluation_missing: '未登记评测',
  evaluation_contract_outdated: '评测契约已过期',
  gold_dataset: '评测数据准备度',
  source_documents: '来源文档',
  paper_documents: '论文数量',
  patent_documents: '专利数量',
  documents_with_build_runs: '构建谱系',
  accepted_entities: '有效实体',
  accepted_relations: '有效关系',
  relation_count_semantics: '关系统计口径',
  entity_precision: '实体准确率',
  entity_f1: '实体 F1',
  relation_precision: '关系准确率',
  relation_f1: '关系 F1',
  alignment_accuracy: '实体对齐',
  evidence_span_rebuild: '证据回切',
  evidence_completeness: '证据完整率',
  innovation_quality_complete: '创新评测完整性',
  requirement_entity_match: '需求实体匹配',
  path_validity: '路径有效性',
  multi_hop_relevance: '多跳相关性',
  candidate_relation_rationality: '候选关系合理性',
  solution_evidence_consistency: '方案证据一致性',
  unsupported_claim_rate: '无依据声明率',
  innovation_expert_acceptance: '创新专家接受率'
}
const acceptanceFailedSummary = computed(() => {
  const failed = acceptanceStatus.value?.failed_criteria || []
  if (!failed.length) return ''
  const visible = failed.slice(0, 4).map((id) => acceptanceCriterionLabels[id] || id)
  return failed.length > visible.length
    ? `${visible.join('、')}等 ${failed.length} 项`
    : visible.join('、')
})

const isGraphIndexComplete = computed(() => {
  return (
    Boolean(graphBuildStatus.value?.locked) &&
    !isBuildActive.value &&
    pendingGraphChunks.value === 0
  )
})

const graphIndexDotStatus = computed(() => {
  if (isBuildActive.value) return 'active'
  if (hasPendingGraphChunks.value) return 'pending'
  if (isGraphIndexComplete.value) return 'complete'
  return ''
})

const graphIndexButtonTitle = computed(() => {
  if (hasPendingGraphChunks.value) return `索引管理，${pendingGraphChunks.value} 待索引`
  if (isGraphIndexComplete.value) return '索引管理，已全部索引'
  if (isBuildActive.value) return '索引管理，索引中'
  return '索引管理'
})

const authoritativePipelineStages = computed(() =>
  Object.fromEntries(
    (graphBuildStatus.value?.pipeline_stages?.stages || []).map((stage) => [stage.key, stage])
  )
)

const normalizedPipelineStatus = (status, fallback = 'idle') => {
  if (!status) return fallback
  return status === 'completed' ? 'complete' : status
}

const combinedPipelineStatus = (keys, fallback) => {
  const statuses = keys.map((key) => authoritativePipelineStages.value[key]?.status).filter(Boolean)
  if (!statuses.length) return fallback
  if (statuses.includes('warning')) return 'warning'
  if (statuses.includes('active')) return 'active'
  if (statuses.every((status) => status === 'completed')) return 'complete'
  return 'idle'
}

const graphWorkflowSteps = computed(() => {
  const totalChunks = Number(graphBuildStatus.value?.total_chunks || 0)
  const indexedChunks = Number(graphBuildStatus.value?.indexed_chunks || 0)
  const entityCount = candidateEntityCount.value
  const relationCount = candidateRelationCount.value
  return [
    {
      key: 'document',
      label: '文档解析',
      detail: totalChunks ? `${totalChunks} 个 Chunk` : '等待文档',
      icon: FileSearch,
      status: normalizedPipelineStatus(
        authoritativePipelineStages.value.document_parse?.status,
        totalChunks ? 'complete' : graphBuildStatus.value?.locked ? 'active' : 'idle'
      ),
      action: () => {
        showDocumentAudit.value = true
      }
    },
    {
      key: 'extraction',
      label: '抽取构建',
      detail: isBuildActive.value
        ? `${graphBuildStatus.value?.build_task_progress || 0}%`
        : hasPendingGraphChunks.value
          ? `${pendingGraphChunks.value} 待处理`
          : indexedChunks
            ? `${indexedChunks} 已完成`
            : '配置并启动',
      icon: Database,
      status: combinedPipelineStatus(
        ['information_extraction', 'entity_alignment', 'authoritative_commit'],
        isBuildFailed.value
          ? 'warning'
          : isBuildActive.value
            ? 'active'
            : indexedChunks
              ? 'complete'
              : 'idle'
      ),
      action: toggleBuildPanel
    },
    {
      key: 'graph',
      label: '图谱构建',
      detail:
        entityCount || relationCount ? `${entityCount} 实体 · ${relationCount} 关系` : '等待知识',
      icon: Network,
      status: combinedPipelineStatus(
        ['graph_projection', 'vector_projection'],
        hasGraphNodes.value ? 'complete' : entityCount || relationCount ? 'active' : 'idle'
      ),
      action: loadGraph
    },
    {
      key: 'paths',
      label: '多跳查询',
      detail: pathDiscoverySearched.value
        ? `${pathDiscoveryResult.paths.length} 条路径`
        : '需求/技术检索',
      icon: Waypoints,
      status: pathDiscoveryLoading.value
        ? 'active'
        : pathDiscoverySearched.value
          ? 'complete'
          : 'idle',
      action: openPathDiscovery
    },
    {
      key: 'innovation',
      label: '创新预测',
      detail: innovationDiscoverySearched.value
        ? `${innovationDiscoveryResult.hypotheses.length} 个候选`
        : '证据约束推演',
      icon: Sparkles,
      status: innovationDiscoveryLoading.value
        ? 'active'
        : innovationDiscoverySearched.value
          ? 'complete'
          : 'idle',
      action: openPathDiscovery
    }
  ]
})

const toggleBuildPanel = () => {
  showBuildPanel.value = !showBuildPanel.value
  showSettings.value = false
  if (showBuildPanel.value) {
    loadAcceptanceStatus()
  }
}

const toggleSettingsPanel = () => {
  showSettings.value = !showSettings.value
  showBuildPanel.value = false
}

const isEditingGraphConfig = computed(() => Boolean(graphBuildStatus.value?.locked))

const graphConfigTitle = computed(() =>
  isEditingGraphConfig.value ? '修改图谱抽取配置' : '配置图谱抽取器'
)

const stopBuildStatusPoll = () => {
  if (buildStatusPollTimer) {
    clearInterval(buildStatusPollTimer)
    buildStatusPollTimer = null
  }
}

const startBuildStatusPoll = () => {
  stopBuildStatusPoll()
  buildStatusPollTimer = setInterval(() => {
    loadGraphBuildStatus()
  }, 5000)
}

watch(
  isBuildActive,
  (active) => {
    if (active) {
      startBuildStatusPoll()
    } else {
      stopBuildStatusPoll()
    }
  },
  { immediate: true }
)
const DEFAULT_CONTEXT_WINDOW_SIZE = 1
const DEFAULT_CONTEXT_MAX_CHARS = 4000
const DEFAULT_ENABLE_HYPOTHESIS_EXTRACTION = true
const DEFAULT_MAX_HYPOTHESES_PER_CHUNK = 2
const DEFAULT_ONTOLOGY_VERSION = 'defense-kg-1.0'
const DEFAULT_LIGHTRAG_PIPELINE_REVISION = 'lightrag-primary-v1'
const ontologyVersions = ref([])
const ontologyVersionsLoading = ref(false)
const graphConfigForm = reactive({
  extractor_type: 'lightrag_primary',
  model_spec: '',
  schema: '',
  concurrency_count: DEFAULT_GRAPH_EXTRACTION_CONCURRENCY,
  timeout_seconds: DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
  max_output_tokens: DEFAULT_GRAPH_EXTRACTION_MAX_TOKENS,
  enable_thinking: true,
  thinking_budget: DEFAULT_GRAPH_THINKING_BUDGET,
  context_window_size: DEFAULT_CONTEXT_WINDOW_SIZE,
  context_max_chars: DEFAULT_CONTEXT_MAX_CHARS,
  enable_hypothesis_extraction: DEFAULT_ENABLE_HYPOTHESIS_EXTRACTION,
  max_hypotheses_per_chunk: DEFAULT_MAX_HYPOTHESES_PER_CHUNK,
  model_params_text: '',
  orchestration_mode: 'lightrag_primary',
  llm_enhancement_enabled: true,
  llm_enhancement_model_spec: '',
  llm_enhancement_concurrency: 2,
  llm_enhancement_strict: false,
  llm_relation_completion_enabled: true,
  llm_layout_normalization_enabled: true,
  llm_ocr_repair_enabled: true,
  document_enhancement_enabled: true,
  document_enhancement_max_chars: 16000,
  document_enhancement_concurrency: 2,
  document_concurrency_count: 2,
  document_entity_enhancement_enabled: true,
  document_entity_enhancement_model_spec: '',
  document_entity_enhancement_strict: false,
  document_entity_gleaning_enabled: true,
  document_entity_layout_normalization_enabled: true,
  document_llm_enhancement_enabled: true,
  document_llm_enhancement_model_spec: '',
  document_llm_enhancement_strict: false,
  document_cross_relation_enabled: true,
  document_cross_relation_model_spec: '',
  document_cross_relation_review_scope: 'pending_candidates',
  document_cross_relation_min_documents: 2,
  document_cross_relation_max_pairs: 24,
  document_cross_relation_pairs_per_batch: 6,
  document_cross_relation_concurrency: 2,
  document_cross_relation_strict: false,
  entity_alignment_enabled: true,
  entity_alignment_model_spec: '',
  entity_alignment_strict: false,
  entity_alignment_auto_link_enabled: false,
  ontology_version: DEFAULT_ONTOLOGY_VERSION,
  pipeline_revision: DEFAULT_LIGHTRAG_PIPELINE_REVISION,
  document_audit_enabled: true,
  filter_non_research: true,
  document_value_routing_enabled: true
})

const isLlmExtractor = computed(() => graphConfigForm.extractor_type === 'llm')
const isLightRAGGraphExtractor = computed(
  () => graphConfigForm.extractor_type === 'lightrag_primary'
)
const ontologyVersionOptions = computed(() => {
  const items = ontologyVersions.value.map((item) => ({
    label: `${item.version} · ${item.name}`,
    value: item.version
  }))
  if (!items.some((item) => item.value === graphConfigForm.ontology_version)) {
    items.unshift({
      label: graphConfigForm.ontology_version,
      value: graphConfigForm.ontology_version
    })
  }
  return items
})
const selectedOntologyVersion = computed(() =>
  ontologyVersions.value.find((item) => item.version === graphConfigForm.ontology_version)
)
const activeExtractionPreset = computed(() => matchGraphExtractionPreset(graphConfigForm))
const graphConfigRiskMessage = computed(() => graphExtractionRiskMessage(graphConfigForm))
const selectExtractionPreset = (key) => applyGraphExtractionPreset(graphConfigForm, key)

const graphConfigSummary = computed(() => {
  const extractorType = 'lightrag_primary'
  const options = graphBuildStatus.value?.config?.extractor_options || {}
  if (extractorType === 'lightrag_primary') {
    const label =
      extractorTypeOptions.find((item) => item.value === extractorType)?.label || extractorType
    const ontologyVersion =
      options.ontology_version || options.primary?.ontology_version || DEFAULT_ONTOLOGY_VERSION
    const orchestration = ' · 轻量化 RAG/项目 LLM 全链路'
    const llmEnhancement =
      options.llm_enhancement?.enabled
        ? ' · LLM 命名增强 + gleaning'
        : ''
    const entityAlignment =
      options.entity_alignment?.enabled
        ? ' · LLM 跨文档实体消歧'
        : ''
    const agentParallelism = graphBuildStatus.value?.runtime?.agent_parallelism_effective
    const parallelism = agentParallelism ? ` · Agent 并行 ${agentParallelism}` : ''
    return `${label} · ${ontologyVersion}${orchestration}${llmEnhancement}${entityAlignment}${parallelism}`
  }
  const presetKey = matchGraphExtractionPreset({
    concurrency_count: options.concurrency_count ?? DEFAULT_GRAPH_EXTRACTION_CONCURRENCY,
    timeout_seconds: options.timeout_seconds ?? DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS
  })
  const preset = GRAPH_EXTRACTION_PRESETS.find((item) => item.key === presetKey)
  const concurrency = options.concurrency_count ?? DEFAULT_GRAPH_EXTRACTION_CONCURRENCY
  const timeout = options.timeout_seconds ?? DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS
  const effectiveConcurrency = graphBuildStatus.value?.runtime?.effective_concurrency_count
  const concurrencyText =
    effectiveConcurrency && effectiveConcurrency !== Number(concurrency)
      ? `并发 ${concurrency}→运行 ${effectiveConcurrency}`
      : `并发 ${concurrency}`
  const performance = graphPerformanceOptions(options)
  const thinkingText = performance.enable_thinking
    ? `思考预算 ${performance.thinking_budget}`
    : '关闭思考'
  return `${preset?.label || '自定义'} · ${concurrencyText} · ${timeout} 秒 · ${thinkingText}`
})

const graph = reactive(useGraph(graphRef))
const authority = useAuthoritativeGraphDetail(unifiedApi)
const {
  detail: authorityDetail,
  loading: authorityLoading,
  loadingMore: authorityLoadingMore,
  error: authorityError,
  loadMoreError: authorityLoadMoreError,
  reference: authorityReference,
  canLoadMore: authorityCanLoadMore
} = authority
const graphLoaded = ref(false)

const handleNodeDetailClick = (nodeData) => {
  graph.handleNodeClick(nodeData)
  void authority.load({ kbId: kbId.value, type: 'node', item: nodeData })
}

const handleEdgeDetailClick = (edgeData) => {
  graph.handleEdgeClick(edgeData)
  void authority.load({ kbId: kbId.value, type: 'edge', item: edgeData })
}

const handleCanvasDetailClick = () => {
  authority.clear()
  graph.handleCanvasClick()
}

// 计算属性：是否支持知识图谱
const isGraphSupported = computed(() => GRAPH_SUPPORTED_KB_TYPES.has(kbType.value?.toLowerCase()))
const hasGraphNodes = computed(() => graph.graphData.nodes.length > 0)
const candidateEntityCount = computed(() => Number(graphBuildStatus.value?.entity_count || 0))
const candidateRelationCount = computed(() =>
  Number(graphBuildStatus.value?.relationship_count || 0)
)
const hasReviewableKnowledge = computed(
  () =>
    !hasGraphNodes.value &&
    !isBuildActive.value &&
    !hasPendingGraphChunks.value &&
    (candidateEntityCount.value > 0 || candidateRelationCount.value > 0)
)
const showGraphConfigEmpty = computed(
  () => isMilvus.value && !graphBuildStatus.value?.locked && !graphBuildLoading.value
)
const showGraphDataEmpty = computed(
  () =>
    isMilvus.value &&
    Boolean(graphBuildStatus.value?.locked) &&
    graphLoaded.value &&
    !graph.fetching &&
    !hasGraphNodes.value
)
const graphDataEmptyTitle = computed(() => {
  if (searchInput.value.trim()) return '未找到匹配实体'
  if (hasReviewableKnowledge.value) return '候选知识等待审核'
  return '暂无知识图谱'
})
const graphDataEmptyDescription = computed(() => {
  if (searchInput.value.trim()) return '换个关键词或调整图谱设置后再搜索。'
  if (isBuildActive.value) return '图谱索引正在运行，完成后会展示实体与关系。'
  if (hasPendingGraphChunks.value) return '当前还有待索引 Chunk，完成索引后会展示实体与关系。'
  if (hasReviewableKnowledge.value) {
    return `已抽取 ${candidateEntityCount.value} 个实体和 ${candidateRelationCount.value} 条关系候选。默认主图只展示已接受知识，请先在知识审计中核对证据，再审核候选。`
  }
  return '当前知识库还没有可展示的实体与关系。'
})

let pendingLoadTimer = null
let graphStatusRequestSeq = 0
let acceptanceStatusRequestSeq = 0
let graphLoadRequestSeq = 0
let pathDiscoveryRequestSeq = 0
let innovationDiscoveryRequestSeq = 0
let solutionGenerationRequestSeq = 0

const getErrorDetail = (e, fallback) => {
  return e?.response?.data?.detail || e?.response?.data?.message || e?.message || fallback
}

const loadGraphBuildStatus = async () => {
  if (!kbId.value || !isMilvus.value) return
  const requestSeq = ++graphStatusRequestSeq
  const currentDatabaseId = kbId.value
  graphBuildLoading.value = true
  try {
    const status = await graphBuildApi.getStatus(currentDatabaseId)
    if (requestSeq === graphStatusRequestSeq && currentDatabaseId === kbId.value) {
      graphBuildStatus.value = status
    }
  } catch (e) {
    console.error('Failed to load graph build status:', e)
    message.error('加载图谱构建状态失败')
  } finally {
    if (requestSeq === graphStatusRequestSeq) {
      graphBuildLoading.value = false
    }
  }
}

const loadAcceptanceStatus = async () => {
  if (!kbId.value || !isMilvus.value) return
  const requestSeq = ++acceptanceStatusRequestSeq
  const currentDatabaseId = kbId.value
  acceptanceLoading.value = true
  try {
    const response = await unifiedApi.getAcceptanceStatus(currentDatabaseId)
    if (requestSeq === acceptanceStatusRequestSeq && currentDatabaseId === kbId.value) {
      acceptanceStatus.value = response.data
    }
  } catch (e) {
    console.error('Failed to load graph acceptance status:', e)
    if (requestSeq === acceptanceStatusRequestSeq) {
      acceptanceStatus.value = null
    }
  } finally {
    if (requestSeq === acceptanceStatusRequestSeq) {
      acceptanceLoading.value = false
    }
  }
}

const handleGraphReviewed = async () => {
  await Promise.all([loadGraphBuildStatus(), loadAcceptanceStatus(), loadGraph()])
}

const parseModelParams = () => {
  const text = graphConfigForm.model_params_text.trim()
  if (!text) return {}
  let params
  try {
    params = JSON.parse(text)
  } catch {
    throw new Error('模型参数必须是合法 JSON 对象')
  }
  if (!params || Array.isArray(params) || typeof params !== 'object') {
    throw new Error('模型参数必须是 JSON 对象')
  }
  return params
}

const fillGraphConfigForm = () => {
  const config = graphBuildStatus.value?.config
  const options = config?.extractor_options || {}
  const isNewGraphConfig = !config
  // 生产界面只提供轻量化 RAG；载入历史配置时收敛到兼容协议，不再回填旧 sidecar。
  graphConfigForm.extractor_type = 'lightrag_primary'
  graphConfigForm.model_spec = options.model_spec || configStore.config?.default_model || ''
  graphConfigForm.schema = options.schema || ''
  graphConfigForm.concurrency_count = Number(
    options.concurrency_count || DEFAULT_GRAPH_EXTRACTION_CONCURRENCY
  )
  graphConfigForm.timeout_seconds = Number(
    options.timeout_seconds || DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS
  )
  graphConfigForm.context_window_size = Number(
    options.context_window_size ?? DEFAULT_CONTEXT_WINDOW_SIZE
  )
  graphConfigForm.context_max_chars = Number(options.context_max_chars || DEFAULT_CONTEXT_MAX_CHARS)
  graphConfigForm.enable_hypothesis_extraction =
    options.enable_hypothesis_extraction ?? DEFAULT_ENABLE_HYPOTHESIS_EXTRACTION
  graphConfigForm.max_hypotheses_per_chunk = Number(
    options.max_hypotheses_per_chunk ?? DEFAULT_MAX_HYPOTHESES_PER_CHUNK
  )
  Object.assign(graphConfigForm, graphPerformanceOptions(options))
  const modelParams = unmanagedGraphModelParams(options.model_params)
  graphConfigForm.model_params_text = Object.keys(modelParams).length
    ? JSON.stringify(modelParams)
    : ''
  graphConfigForm.orchestration_mode = 'lightrag_primary'
  const llmEnhancement = options.llm_enhancement || {}
  graphConfigForm.llm_enhancement_enabled =
    llmEnhancement.enabled ??
    (isNewGraphConfig || graphConfigForm.orchestration_mode === 'lightrag_primary')
  graphConfigForm.llm_enhancement_model_spec =
    llmEnhancement.model_spec || configStore.config?.default_model || ''
  graphConfigForm.llm_enhancement_concurrency = Number(
    llmEnhancement.concurrency_count || 4
  )
  graphConfigForm.llm_enhancement_strict = llmEnhancement.strict === true
  graphConfigForm.llm_relation_completion_enabled =
    llmEnhancement.relation_completion?.enabled ?? true
  graphConfigForm.llm_layout_normalization_enabled =
    llmEnhancement.layout_normalization?.enabled ?? true
  graphConfigForm.llm_ocr_repair_enabled = llmEnhancement.ocr_repair_extraction?.enabled ?? true
  if (isLightRAGGraphExtractor.value && graphConfigForm.llm_enhancement_enabled) {
    graphConfigForm.context_window_size = Number(llmEnhancement.context_window_size ?? 1)
    graphConfigForm.context_max_chars = Number(llmEnhancement.context_max_chars || 1200)
  }
  const documentEnhancement = options.document_enhancement || {}
  const documentEntityEnhancement = documentEnhancement.entity_enhancement || {}
  const documentLlmEnhancement = documentEnhancement.llm_enhancement || {}
  const crossDocumentRelation = documentEnhancement.cross_document_relation_enhancement || {}
  const defaultDocumentLlm =
    isLightRAGGraphExtractor.value && (isNewGraphConfig || llmEnhancement.enabled === true)
  graphConfigForm.document_enhancement_enabled = documentEnhancement.enabled ?? defaultDocumentLlm
  graphConfigForm.document_enhancement_max_chars = Number(documentEnhancement.max_chars || 16000)
  graphConfigForm.document_enhancement_concurrency = Number(
    documentEnhancement.concurrency_count || 2
  )
  graphConfigForm.document_concurrency_count = Number(
    documentEnhancement.document_concurrency_count || 2
  )
  graphConfigForm.document_entity_enhancement_enabled =
    documentEntityEnhancement.enabled ?? defaultDocumentLlm
  graphConfigForm.document_entity_enhancement_model_spec =
    documentEntityEnhancement.model_spec || configStore.config?.default_model || ''
  graphConfigForm.document_entity_enhancement_strict = documentEntityEnhancement.strict === true
  graphConfigForm.document_entity_gleaning_enabled =
    documentEntityEnhancement.max_gleanings === undefined
      ? defaultDocumentLlm
      : Number(documentEntityEnhancement.max_gleanings) > 0
  graphConfigForm.document_entity_layout_normalization_enabled =
    documentEntityEnhancement.layout_normalization?.enabled ?? true
  graphConfigForm.document_llm_enhancement_enabled =
    documentLlmEnhancement.enabled ?? defaultDocumentLlm
  graphConfigForm.document_llm_enhancement_model_spec =
    documentLlmEnhancement.model_spec || configStore.config?.default_model || ''
  graphConfigForm.document_llm_enhancement_strict = documentLlmEnhancement.strict === true
  graphConfigForm.document_cross_relation_enabled =
    crossDocumentRelation.enabled ?? defaultDocumentLlm
  graphConfigForm.document_cross_relation_model_spec =
    crossDocumentRelation.model_spec || configStore.config?.default_model || ''
  graphConfigForm.document_cross_relation_review_scope =
    crossDocumentRelation.review_scope ||
    (isNewGraphConfig ? 'pending_candidates' : 'accepted_only')
  graphConfigForm.document_cross_relation_min_documents = Number(
    crossDocumentRelation.min_document_support || 2
  )
  graphConfigForm.document_cross_relation_max_pairs = Number(crossDocumentRelation.max_pairs || 24)
  graphConfigForm.document_cross_relation_pairs_per_batch = Number(
    crossDocumentRelation.pairs_per_batch || 6
  )
  graphConfigForm.document_cross_relation_concurrency = Number(
    crossDocumentRelation.concurrency_count || 2
  )
  graphConfigForm.document_cross_relation_strict = crossDocumentRelation.strict === true
  const entityAlignment = options.entity_alignment || {}
  graphConfigForm.entity_alignment_enabled = entityAlignment.enabled ?? defaultDocumentLlm
  graphConfigForm.entity_alignment_model_spec =
    entityAlignment.model_spec || configStore.config?.default_model || ''
  graphConfigForm.entity_alignment_strict = entityAlignment.strict === true
  graphConfigForm.entity_alignment_auto_link_enabled = entityAlignment.auto_link_enabled === true
  graphConfigForm.ontology_version =
    options.ontology_version || DEFAULT_ONTOLOGY_VERSION
  graphConfigForm.pipeline_revision =
    options.pipeline_revision || DEFAULT_LIGHTRAG_PIPELINE_REVISION
  graphConfigForm.document_audit_enabled = options.document_audit?.enabled ?? true
  graphConfigForm.filter_non_research = options.document_audit?.filter_non_research ?? true
  graphConfigForm.document_value_routing_enabled =
    options.document_audit?.value_routing?.enabled ??
    (isNewGraphConfig && Boolean(configStore.config?.default_model))
}

const loadOntologyVersions = async () => {
  ontologyVersionsLoading.value = true
  try {
    const response = await unifiedApi.getOntologyVersions({ limit: 200 })
    ontologyVersions.value = Array.isArray(response?.data?.items) ? response.data.items : []
  } catch (e) {
    console.error('Failed to load ontology versions:', e)
  } finally {
    ontologyVersionsLoading.value = false
  }
}

const openGraphConfig = () => {
  fillGraphConfigForm()
  showAdvancedGraphConfig.value = false
  showGraphConfig.value = true
  if (!isLlmExtractor.value) void loadOntologyVersions()
}

const selectExtractorType = (option) => {
  if (isEditingGraphConfig.value || option.disabled) return
  graphConfigForm.extractor_type = option.value
  if (option.value === 'lightrag_primary') {
    graphConfigForm.pipeline_revision = DEFAULT_LIGHTRAG_PIPELINE_REVISION
    handleOrchestrationModeChange('lightrag_primary')
  }
}

const buildExtractorOptions = () => {
  if (!isLlmExtractor.value) return buildIEExtractorOptions()
  return {
    model_spec: graphConfigForm.model_spec,
    schema: graphConfigForm.schema.trim(),
    concurrency_count: graphConfigForm.concurrency_count || DEFAULT_GRAPH_EXTRACTION_CONCURRENCY,
    timeout_seconds: graphConfigForm.timeout_seconds || DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
    max_output_tokens: graphConfigForm.max_output_tokens ?? DEFAULT_GRAPH_EXTRACTION_MAX_TOKENS,
    enable_thinking: graphConfigForm.enable_thinking,
    thinking_budget: graphConfigForm.thinking_budget ?? DEFAULT_GRAPH_THINKING_BUDGET,
    context_window_size: graphConfigForm.context_window_size ?? DEFAULT_CONTEXT_WINDOW_SIZE,
    context_max_chars: graphConfigForm.context_max_chars || DEFAULT_CONTEXT_MAX_CHARS,
    enable_hypothesis_extraction: graphConfigForm.enable_hypothesis_extraction,
    max_hypotheses_per_chunk: graphConfigForm.max_hypotheses_per_chunk,
    model_params: parseModelParams()
  }
}

const buildRelationCompletionOptions = () => {
  return {
    enabled: graphConfigForm.llm_relation_completion_enabled,
    max_entities: 48,
    max_candidate_pairs: 32,
    max_distance_chars: 480,
    min_entity_confidence: 0.5,
    min_relation_confidence: 0.82,
    min_entity_model_sources: 1,
    require_same_sentence: false,
    require_relation_cue: true
  }
}

const buildIEExtractorOptions = () => {
  const common = {
    ontology_version: graphConfigForm.ontology_version,
    pipeline_revision: graphConfigForm.pipeline_revision.trim(),
    concurrency_count: 1,
    context_window_size: 0,
    enable_hypothesis_extraction: graphConfigForm.enable_hypothesis_extraction,
    max_hypotheses_per_chunk: graphConfigForm.max_hypotheses_per_chunk,
    document_audit: {
      enabled: graphConfigForm.document_audit_enabled,
      filter_non_research: graphConfigForm.filter_non_research,
      value_routing: {
        enabled: isLightRAGGraphExtractor.value && graphConfigForm.document_value_routing_enabled,
        ...(isLightRAGGraphExtractor.value && graphConfigForm.document_value_routing_enabled
          ? {
              model_spec: configStore.config?.default_model || '',
              max_chars: 12000,
              max_output_tokens: 1200,
              min_confidence: 0.8,
              concurrency_count: 2,
              strict: false
            }
          : {})
      }
    }
  }
  return {
    ...common,
    orchestration_mode: 'lightrag_primary',
    orchestration_release_channel: 'stable',
    llm_enhancement: {
      enabled: graphConfigForm.llm_enhancement_enabled,
      ...(graphConfigForm.llm_enhancement_enabled
        ? {
            model_spec: graphConfigForm.llm_enhancement_model_spec,
            max_gleanings: 1,
            entity_review_mode: 'apply_experiment',
            entity_review_trigger: 'all',
            entity_review_min_confidence: 0.95,
            concurrency_count: graphConfigForm.llm_enhancement_concurrency,
            context_window_size: graphConfigForm.context_window_size ?? 1,
            context_max_chars: graphConfigForm.context_max_chars || 1200,
            adaptive_routing: { enabled: false },
            layout_normalization: {
              enabled: graphConfigForm.llm_layout_normalization_enabled
            },
            ocr_repair_extraction: {
              enabled: graphConfigForm.llm_ocr_repair_enabled
            },
            relation_completion: buildRelationCompletionOptions(),
            timeout_seconds:
              graphConfigForm.timeout_seconds || DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
            strict: graphConfigForm.llm_enhancement_strict
          }
        : {})
    },
    document_enhancement: {
      enabled: graphConfigForm.document_enhancement_enabled,
      ...(graphConfigForm.document_enhancement_enabled
        ? {
            max_chars: graphConfigForm.document_enhancement_max_chars || 16000,
            concurrency_count: graphConfigForm.document_enhancement_concurrency || 2,
            document_concurrency_count: graphConfigForm.document_concurrency_count || 2,
            entity_enhancement: {
              enabled: graphConfigForm.document_entity_enhancement_enabled,
              ...(graphConfigForm.document_entity_enhancement_enabled
                ? {
                    model_spec: graphConfigForm.document_entity_enhancement_model_spec,
                    max_output_tokens: 4096,
                    timeout_seconds:
                      graphConfigForm.timeout_seconds || DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
                    max_blocks: 48,
                    max_chars: Math.min(
                      graphConfigForm.document_enhancement_max_chars || 16000,
                      12000
                    ),
                    max_candidates: 100,
                    max_gleanings: graphConfigForm.document_entity_gleaning_enabled ? 1 : 0,
                    gleaning_on_layout_damage: true,
                    layout_normalization: {
                      enabled: graphConfigForm.document_entity_layout_normalization_enabled
                    },
                    strict: graphConfigForm.document_entity_enhancement_strict
                  }
                : {})
            },
            llm_enhancement: {
              enabled: graphConfigForm.document_llm_enhancement_enabled,
              ...(graphConfigForm.document_llm_enhancement_enabled
                ? {
                    model_spec: graphConfigForm.document_llm_enhancement_model_spec,
                    max_output_tokens: 4096,
                    timeout_seconds:
                      graphConfigForm.timeout_seconds || DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
                    strict: graphConfigForm.document_llm_enhancement_strict
                  }
                : {})
            },
            cross_document_relation_enhancement: {
              enabled: graphConfigForm.document_cross_relation_enabled,
              ...(graphConfigForm.document_cross_relation_enabled
                ? {
                    model_spec: graphConfigForm.document_cross_relation_model_spec,
                    min_document_support:
                      graphConfigForm.document_cross_relation_min_documents || 2,
                    max_documents_per_pair: Math.max(
                      graphConfigForm.document_cross_relation_min_documents || 2,
                      3
                    ),
                    max_scope_documents: 128,
                    max_pairs: graphConfigForm.document_cross_relation_max_pairs || 24,
                    pairs_per_batch:
                      graphConfigForm.document_cross_relation_pairs_per_batch || 6,
                    concurrency_count:
                      graphConfigForm.document_cross_relation_concurrency || 2,
                    review_scope: graphConfigForm.document_cross_relation_review_scope,
                    max_entities_per_document: 96,
                    max_pairs_per_document: 512,
                    min_entity_confidence:
                      graphConfigForm.document_cross_relation_review_scope === 'pending_candidates'
                        ? 0.3
                        : 0,
                    min_confidence: 0.85,
                    strict: graphConfigForm.document_cross_relation_strict
                  }
                : {})
            }
          }
        : {})
    },
    entity_alignment: {
      enabled: graphConfigForm.entity_alignment_enabled,
      ...(graphConfigForm.entity_alignment_enabled
        ? {
            model_spec: graphConfigForm.entity_alignment_model_spec,
            strict: graphConfigForm.entity_alignment_strict,
            auto_link_enabled: graphConfigForm.entity_alignment_auto_link_enabled,
            min_confidence: 0.95,
            min_vector_score: 0.9,
            max_candidates: 5,
            timeout_seconds:
              graphConfigForm.timeout_seconds || DEFAULT_GRAPH_EXTRACTION_TIMEOUT_SECONDS,
            max_output_tokens: 4096
          }
        : {})
    }
  }
}

const configureGraphBuild = async () => {
  if (graphConfigSaving.value) return
  graphConfigSaving.value = true
  try {
    if (
      isLightRAGGraphExtractor.value &&
      (graphConfigForm.extractor_type === 'lightrag_primary' ||
        graphConfigForm.orchestration_mode === 'lightrag_primary') &&
      !graphConfigForm.llm_enhancement_enabled
    ) {
      throw new Error('轻量化 RAG 主抽模式必须启用 LLM 抽取质量增强')
    }
    if (
      isLightRAGGraphExtractor.value &&
      graphConfigForm.llm_enhancement_enabled &&
      !graphConfigForm.llm_enhancement_model_spec
    ) {
      throw new Error('启用 LLM 抽取质量增强时必须选择模型')
    }
    if (
      isLightRAGGraphExtractor.value &&
      graphConfigForm.document_audit_enabled &&
      graphConfigForm.document_value_routing_enabled &&
      !configStore.config?.default_model
    ) {
      throw new Error('启用高价值技术重点复抽时必须在项目模型设置中选择默认模型')
    }
    if (
      isLightRAGGraphExtractor.value &&
      graphConfigForm.document_enhancement_enabled &&
      !graphConfigForm.document_entity_enhancement_enabled &&
      !graphConfigForm.document_llm_enhancement_enabled &&
      !graphConfigForm.document_cross_relation_enabled
    ) {
      throw new Error('文档级增强至少需要启用一种轻量化 RAG 能力')
    }
    if (
      isLightRAGGraphExtractor.value &&
      graphConfigForm.document_enhancement_enabled &&
      graphConfigForm.document_entity_enhancement_enabled &&
      !graphConfigForm.document_entity_enhancement_model_spec
    ) {
      throw new Error('启用文档级遗漏实体补抽时必须选择模型')
    }
    if (
      isLightRAGGraphExtractor.value &&
      graphConfigForm.document_enhancement_enabled &&
      graphConfigForm.document_llm_enhancement_enabled &&
      !graphConfigForm.document_llm_enhancement_model_spec
    ) {
      throw new Error('启用文档级轻量化 RAG 补抽时必须选择模型')
    }
    if (
      isLightRAGGraphExtractor.value &&
      graphConfigForm.document_enhancement_enabled &&
      graphConfigForm.document_cross_relation_enabled &&
      !graphConfigForm.document_cross_relation_model_spec
    ) {
      throw new Error('启用跨文档多源关系增强时必须选择模型')
    }
    if (
      isLightRAGGraphExtractor.value &&
      graphConfigForm.entity_alignment_enabled &&
      !graphConfigForm.entity_alignment_model_spec
    ) {
      throw new Error('启用跨文档 LLM 实体消歧时必须选择模型')
    }
    document.activeElement?.blur()
    await nextTick()
    await graphBuildApi.configure(kbId.value, {
      extractor_type: 'lightrag_primary',
      extractor_options: buildExtractorOptions()
    })
    message.success(isEditingGraphConfig.value ? '图谱抽取配置已更新' : '图谱抽取配置已保存')
    showGraphConfig.value = false
    await loadGraphBuildStatus()
  } catch (e) {
    console.error('Failed to configure graph build:', e)
    message.error(getErrorDetail(e, '配置图谱抽取失败'))
  } finally {
    graphConfigSaving.value = false
  }
}

const startGraphBuild = async () => {
  const registerTask = taskerStore.createTaskRegistration()
  try {
    const data = await graphBuildApi.startIndex(kbId.value)
    message.success(data.message || '图谱构建任务已提交')
    if (data.task_id) {
      registerTask({
        task_id: data.task_id,
        name: `图谱构建 (${kbId.value})`,
        task_type: GRAPH_BUILD_TASK_TYPE,
        message: data.message,
        payload: { kb_id: kbId.value }
      })
    }
    await loadGraphBuildStatus()
  } catch (e) {
    console.error('Failed to start graph build:', e)
    message.error(getErrorDetail(e, '提交图谱构建任务失败'))
  }
}

const retryGraphVectors = async () => {
  const registerTask = taskerStore.createTaskRegistration()
  try {
    const data = await graphBuildApi.reconcile(kbId.value, 'failed')
    message.success(data.message || '图谱向量索引修复任务已提交')
    if (data.task_id) {
      registerTask({
        task_id: data.task_id,
        name: `图谱向量索引修复 (${kbId.value})`,
        task_type: GRAPH_BUILD_TASK_TYPE,
        message: data.message,
        payload: { kb_id: kbId.value, reconcile_mode: 'failed' }
      })
    }
    await loadGraphBuildStatus()
  } catch (e) {
    console.error('Failed to reconcile graph vectors:', e)
    message.error(getErrorDetail(e, '提交图谱向量索引修复任务失败'))
  }
}

const confirmRetryFailedGraphChunks = () => {
  if (!extractionFailedCount.value || isBuildActive.value) return
  Modal.confirm({
    title: `重跑 ${extractionFailedCount.value} 个抽取失败项`,
    content: '仅重新调用模型处理抽取失败的 Chunk，不会清空或重跑已成功数据。',
    okText: '确认重跑',
    cancelText: '取消',
    onOk: retryFailedGraphChunks
  })
}

const retryFailedGraphChunks = async () => {
  const registerTask = taskerStore.createTaskRegistration()
  retryingFailedChunks.value = true
  try {
    const data = await graphBuildApi.retryFailed(kbId.value)
    message.success(data.message || '抽取失败项重跑任务已提交')
    if (data.task_id) {
      registerTask({
        task_id: data.task_id,
        name: `重跑图谱抽取失败项 (${kbId.value})`,
        task_type: GRAPH_BUILD_TASK_TYPE,
        message: data.message,
        payload: { kb_id: kbId.value, action: 'retry_failed' }
      })
    }
    await loadGraphBuildStatus()
  } catch (e) {
    console.error('Failed to retry graph extraction failures:', e)
    message.error(getErrorDetail(e, '提交抽取失败项重跑任务失败'))
  } finally {
    retryingFailedChunks.value = false
  }
}

const openFailedChunkSamples = async () => {
  if (!extractionFailedCount.value || failedChunkSamplesLoading.value) return
  showFailedChunkSamples.value = true
  failedChunkSamplesLoading.value = true
  failedChunkSamples.value = []
  activeFailedChunkKey.value = ''
  try {
    const data = await graphBuildApi.getFailedChunks(kbId.value, 10)
    failedChunkSamples.value = data.samples || []
    activeFailedChunkKey.value = failedChunkSamples.value[0]?.chunk_id || ''
  } catch (e) {
    console.error('Failed to load graph extraction failed chunks:', e)
    message.error(getErrorDetail(e, '加载抽取失败 Chunk 失败'))
  } finally {
    failedChunkSamplesLoading.value = false
  }
}

const confirmRebuildGraphProjections = () => {
  Modal.confirm({
    title: '从 PostgreSQL 重建图投影',
    content:
      '仅重建 Neo4j 与 Milvus 投影，不删除 PostgreSQL 中的实体、关系、证据、审核决定和历史版本。',
    okText: '确认重建',
    cancelText: '取消',
    onOk: rebuildGraphProjections
  })
}

const rebuildGraphProjections = async () => {
  const registerTask = taskerStore.createTaskRegistration()
  try {
    const data = await graphBuildApi.rebuildProjections(kbId.value)
    message.success(data.message || '图谱投影重建任务已提交')
    if (data.task_id) {
      registerTask({
        task_id: data.task_id,
        name: `重建图谱投影 (${kbId.value})`,
        task_type: GRAPH_BUILD_TASK_TYPE,
        message: data.message,
        payload: { kb_id: kbId.value, action: 'rebuild_projections' }
      })
    }
    await loadGraphBuildStatus()
  } catch (e) {
    console.error('Failed to rebuild graph projections:', e)
    message.error(getErrorDetail(e, '提交图谱投影重建任务失败'))
  }
}

const loadGraph = async () => {
  if (!kbId.value || !isGraphSupported.value) return

  const requestSeq = ++graphLoadRequestSeq
  const currentDatabaseId = kbId.value
  graph.fetching = true
  if (!hasGraphNodes.value) {
    graphLoaded.value = false
  }
  try {
    const res = await unifiedApi.getSubgraph({
      kb_id: currentDatabaseId,
      node_label: searchInput.value || '*',
      max_nodes: subgraphParams.maxNodes,
      max_depth: subgraphParams.maxDepth,
      exclude_chunk: subgraphParams.excludeChunk
    })

    if (
      requestSeq === graphLoadRequestSeq &&
      currentDatabaseId === kbId.value &&
      res.success &&
      res.data
    ) {
      graph.updateGraphData(res.data.nodes, res.data.edges)
    }
  } catch (e) {
    console.error('Failed to load graph:', e)
    message.error('加载图谱失败')
  } finally {
    if (requestSeq === graphLoadRequestSeq) {
      graph.fetching = false
      graphLoaded.value = true
    }
  }
}

const applySettings = () => {
  showSettings.value = false
  loadGraph()
}

const onSearch = () => {
  loadGraph()
}

const clearGraphSearch = () => {
  searchInput.value = ''
  loadGraph()
}

const openPathDiscovery = () => {
  if (!pathQuery.query && searchInput.value.trim()) {
    pathQuery.query = searchInput.value.trim()
  }
  const projectModel = configStore.config?.default_model || ''
  queryEnhancement.model_spec ||= projectModel
  pathReranking.model_spec ||= projectModel
  narrativeEnhancement.model_spec ||= projectModel
  innovationEnhancement.model_spec ||= projectModel
  solutionGeneration.model_spec ||= projectModel
  showPathDiscovery.value = true
}

const queryEnhancementReady = () => {
  if (
    queryEnhancement.enabled &&
    !queryEnhancement.model_spec &&
    !configStore.config?.default_model
  ) {
    message.warning('开启 LLM 检索规划后必须选择规划模型')
    return false
  }
  return true
}

const pathRerankingReady = () => {
  if (pathReranking.enabled && !pathReranking.model_spec && !configStore.config?.default_model) {
    message.warning('开启 LLM 多跳路径重排后必须选择模型')
    return false
  }
  return true
}

const narrativeEnhancementReady = () => {
  if (
    narrativeEnhancement.enabled &&
    !narrativeEnhancement.model_spec &&
    !configStore.config?.default_model
  ) {
    message.warning('开启 LLM 完整结论撰述后必须选择项目模型')
    return false
  }
  return true
}

const innovationEnhancementReady = () => {
  if (
    innovationEnhancement.enabled &&
    !innovationEnhancement.model_spec &&
    !configStore.config?.default_model
  ) {
    message.warning('开启 LLM 创新预测增强后必须选择创新分析模型')
    return false
  }
  return true
}

const runActiveDiscovery = () =>
  activeDiscoveryFeature.value === 'innovation' ? runInnovationDiscovery() : runPathDiscovery()

const runPathDiscovery = async () => {
  const query = pathQuery.query.trim()
  if (!query) {
    message.warning('请输入研发需求或实体')
    return false
  }
  if (!queryEnhancementReady()) return false
  if (!pathRerankingReady()) return false
  if (!narrativeEnhancementReady()) return false
  pathDiscoveryResult.pipeline_trace = null
  pathDiscoveryResult.narrative = null
  pathDiscoveryResult.narrative_provenance = null
  pathDiscoveryLoading.value = true
  pathDiscoverySearched.value = true
  const requestSeq = ++pathDiscoveryRequestSeq
  const currentDatabaseId = kbId.value
  try {
    const response = await unifiedApi.discoverPaths({
      kb_id: currentDatabaseId,
      query,
      mode: pathQuery.mode,
      max_hops: pathQuery.max_hops,
      max_paths: pathQuery.max_paths,
      include_combinations: pathQuery.include_combinations,
      retrieval_mode: pathQuery.retrieval_mode,
      query_enhancement_enabled: queryEnhancement.enabled,
      query_model_spec: queryEnhancement.model_spec,
      query_enhancement_strict: queryEnhancement.strict,
      path_reranking_enabled: pathReranking.enabled,
      path_reranking_model_spec: pathReranking.model_spec,
      path_reranking_strict: pathReranking.strict,
      narrative_enabled: narrativeEnhancement.enabled,
      narrative_model_spec: narrativeEnhancement.model_spec,
      narrative_strict: narrativeEnhancement.strict
    })
    if (requestSeq === pathDiscoveryRequestSeq && currentDatabaseId === kbId.value) {
      pathDiscoveryResult.paths = response.data?.paths || []
      pathDiscoveryResult.summary = response.data?.summary || {}
      pathDiscoveryResult.query_plan = response.data?.query_plan || null
      pathDiscoveryResult.path_reranking = response.data?.path_reranking || null
      pathDiscoveryResult.pipeline_trace = response.data?.pipeline_trace || null
      pathDiscoveryResult.narrative = response.data?.narrative || null
      pathDiscoveryResult.narrative_provenance = response.data?.narrative_provenance || null
      pathDiscoveryResult.discovery_mode = response.data?.discovery_mode || null
      pathDiscoveryResult.feature_kind = response.data?.feature_kind || null
      return true
    }
  } catch (e) {
    console.error('Failed to discover graph paths:', e)
    if (requestSeq === pathDiscoveryRequestSeq) {
      pathDiscoveryResult.paths = []
      pathDiscoveryResult.summary = {}
      pathDiscoveryResult.query_plan = null
      pathDiscoveryResult.path_reranking = null
      pathDiscoveryResult.pipeline_trace = null
      pathDiscoveryResult.narrative = null
      pathDiscoveryResult.narrative_provenance = null
      pathDiscoveryResult.discovery_mode = null
      pathDiscoveryResult.feature_kind = null
      message.error(getErrorDetail(e, '链路发现失败'))
    }
    return false
  } finally {
    if (requestSeq === pathDiscoveryRequestSeq) {
      pathDiscoveryLoading.value = false
    }
  }
  return false
}

const runInnovationDiscovery = async () => {
  const query = pathQuery.query.trim()
  if (!query) {
    message.warning('请输入研发需求或实体')
    return
  }
  if (!queryEnhancementReady()) return
  if (!pathRerankingReady()) return
  if (!innovationEnhancementReady()) return
  innovationDiscoveryResult.pipeline_trace = null
  innovationDiscoveryResult.feedback_loop = null
  innovationDiscoveryLoading.value = true
  innovationDiscoverySearched.value = true
  const requestSeq = ++innovationDiscoveryRequestSeq
  const currentDatabaseId = kbId.value
  const discoveryMode = pathQuery.mode === 'entity_expansion' ? 'bottom_up' : 'top_down'
  try {
    const response = await unifiedApi.discoverInnovation(currentDatabaseId, {
      query,
      discovery_mode: discoveryMode,
      max_hops: Math.max(pathQuery.max_hops, 2),
      max_candidates: pathQuery.max_paths,
      persist: true,
      retrieval_mode: pathQuery.retrieval_mode,
      evidence_scope: pathQuery.evidence_scope,
      query_enhancement_enabled: queryEnhancement.enabled,
      query_model_spec: queryEnhancement.model_spec,
      query_enhancement_strict: queryEnhancement.strict,
      path_reranking_enabled: pathReranking.enabled,
      path_reranking_model_spec: pathReranking.model_spec,
      path_reranking_strict: pathReranking.strict,
      innovation_llm_enabled: innovationEnhancement.enabled,
      innovation_model_spec: innovationEnhancement.model_spec,
      innovation_llm_strict: innovationEnhancement.strict,
      innovation_llm_concurrency: innovationEnhancement.concurrency_count
    })
    if (requestSeq === innovationDiscoveryRequestSeq && currentDatabaseId === kbId.value) {
      innovationDiscoveryResult.hypotheses = response.data?.hypotheses || []
      innovationDiscoveryResult.graph_revision = response.data?.graph_revision || null
      innovationDiscoveryResult.query_analysis = response.data?.query_analysis || null
      innovationDiscoveryResult.innovation_enhancement =
        response.data?.innovation_enhancement || null
      innovationDiscoveryResult.pipeline_trace = response.data?.pipeline_trace || null
      innovationDiscoveryResult.feedback_loop = response.data?.feedback_loop || null
      innovationDiscoveryResult.evidence_scope = response.data?.evidence_scope || 'any'
      innovationDiscoveryResult.cross_document_candidate_count =
        response.data?.cross_document_candidate_count || 0
      if (innovationDiscoveryResult.hypotheses.length) {
        message.success(`已生成 ${innovationDiscoveryResult.hypotheses.length} 条待审核创新关联`)
      }
    }
  } catch (e) {
    console.error('Failed to discover innovation hypotheses:', e)
    if (requestSeq === innovationDiscoveryRequestSeq) {
      innovationDiscoveryResult.hypotheses = []
      innovationDiscoveryResult.graph_revision = null
      innovationDiscoveryResult.query_analysis = null
      innovationDiscoveryResult.innovation_enhancement = null
      innovationDiscoveryResult.pipeline_trace = null
      innovationDiscoveryResult.feedback_loop = null
      innovationDiscoveryResult.evidence_scope = 'any'
      innovationDiscoveryResult.cross_document_candidate_count = 0
      message.error(getErrorDetail(e, '创新关联发现失败'))
    }
  } finally {
    if (requestSeq === innovationDiscoveryRequestSeq) {
      innovationDiscoveryLoading.value = false
    }
  }
}

const runEvidenceGroundedSolution = async () => {
  const query = pathQuery.query.trim()
  if (!query) {
    message.warning('请输入研发需求或实体')
    return
  }
  if (!solutionGeneration.enabled) {
    message.warning('请先显式开启证据约束 LLM 方案生成')
    return
  }
  if (!solutionGeneration.model_spec) {
    message.warning('请选择技术方案生成模型')
    return
  }
  if (!queryEnhancementReady()) return
  if (!pathRerankingReady()) return
  solutionGenerationLoading.value = true
  const requestSeq = ++solutionGenerationRequestSeq
  const currentDatabaseId = kbId.value
  const discoveryMode = pathQuery.mode === 'entity_expansion' ? 'bottom_up' : 'top_down'
  try {
    const response = await unifiedApi.generateEvidenceGroundedSolution(currentDatabaseId, {
      query,
      discovery_mode: discoveryMode,
      llm_enabled: true,
      model_spec: solutionGeneration.model_spec,
      max_hops: Math.max(pathQuery.max_hops, 2),
      max_paths: Math.min(pathQuery.max_paths, 5),
      retrieval_mode: pathQuery.retrieval_mode,
      evidence_scope: pathQuery.evidence_scope,
      query_enhancement_enabled: queryEnhancement.enabled,
      query_model_spec: queryEnhancement.model_spec,
      query_enhancement_strict: queryEnhancement.strict,
      path_reranking_enabled: pathReranking.enabled,
      path_reranking_model_spec: pathReranking.model_spec,
      path_reranking_strict: pathReranking.strict
    })
    if (requestSeq === solutionGenerationRequestSeq && currentDatabaseId === kbId.value) {
      solutionGenerationResult.value = response.data || null
      message.success('已生成待专家复核的证据约束技术方案')
    }
  } catch (e) {
    console.error('Failed to generate evidence-grounded solution:', e)
    if (requestSeq === solutionGenerationRequestSeq) {
      solutionGenerationResult.value = null
      message.error(getErrorDetail(e, '证据约束技术方案生成失败'))
    }
  } finally {
    if (requestSeq === solutionGenerationRequestSeq) {
      solutionGenerationLoading.value = false
    }
  }
}

const reviewInnovation = (hypothesis, decision) => {
  const accepted = decision === 'accepted'
  Modal.confirm({
    title: accepted ? '接受为待验证研究方向' : '拒绝创新关联候选',
    content: accepted
      ? '该操作只记录专家认可的研究方向，关联仍保持 Hypothesis，不会进入默认事实查询。'
      : '拒绝后候选会保留在审计历史中。',
    okText: accepted ? '确认接受' : '确认拒绝',
    cancelText: '取消',
    async onOk() {
      const response = await unifiedApi.reviewInnovationCandidate(
        kbId.value,
        hypothesis.hypothesis_id,
        {
          decision,
          reason: accepted ? '人工审核接受为待验证研究方向' : '人工审核拒绝创新关联候选'
        }
      )
      hypothesis.review_status = response.data?.review_status || decision
      message.success(accepted ? '已接受为待验证方向' : '已拒绝候选')
    }
  })
}

const viewPathInGraph = (path) => {
  graph.updateGraphData(path.nodes, path.relations)
  graphLoaded.value = true
  showPathDiscovery.value = false
}

const pathRouteLabel = (routeKind) =>
  ({
    evidence_chain: '证据链',
    same_layer: '同层关联',
    combined: '组合探索',
    predicted: '预测关联'
  })[routeKind] || routeKind

const retrievalModeLabel = (mode) =>
  ({
    semantic: '语义实体锚点',
    naive: '原文向量锚定',
    local: '实体向量召回',
    global: '关系向量召回',
    hybrid: '实体/关系混合召回',
    mix: '图谱/原文/关键词混合召回',
    keyword: '关键词锚点'
  })[mode] ||
  mode ||
  '未知检索'

const discoveryDirectionLabel = (mode) =>
  ({ top_down: '自上而下 · 需求牵引', bottom_up: '自下而上 · 技术扩展' })[mode] || '双向检索'

const pathRouteColor = (routeKind) =>
  ({ evidence_chain: 'green', same_layer: 'blue', combined: 'orange', predicted: 'magenta' })[
    routeKind
  ] || 'default'

const pathClaimColor = (claimLevel) =>
  ({ Fact: 'green', Inference: 'blue', Hypothesis: 'orange' })[claimLevel] || 'default'

const semanticRoleLabel = (role) =>
  ({
    concept: '概念/需求',
    principle: '原理',
    technology: '技术',
    capability: '能力',
    application: '应用',
    other: '实体'
  })[role] || role

const RESEARCH_THREAD_META = {
  main: { label: '贡献主线', description: '核心问题、机理、技术与能力链' },
  side: { label: '支撑辅线', description: '约束、验证、风险与辅助模块' },
  parallel: { label: '并行路线', description: '并列、替代、互补或可组合方案' }
}

const normalizedResearchThreads = (source) =>
  Object.entries(RESEARCH_THREAD_META)
    .map(([key, meta]) => ({
      key,
      ...meta,
      entities: Array.isArray(source?.[key])
        ? [...new Set(source[key].map((item) => String(item || '').trim()).filter(Boolean))]
        : []
    }))
    .filter((thread) => thread.entities.length)

const researchThreadEntries = (path) =>
  normalizedResearchThreads(path?.research_inspiration?.research_threads)

const innovationResearchThreadEntries = (hypothesis) =>
  normalizedResearchThreads(hypothesis?.evidence_path?.research_threads)

const formatScore = (value) => {
  const score = Number(value)
  return Number.isFinite(score) ? score.toFixed(2) : '—'
}

const formatPercent = (value) => {
  const score = Number(value)
  return Number.isFinite(score) ? `${Math.round(Math.max(0, Math.min(score, 1)) * 100)}%` : '—'
}

const innovationRelationLabel = (relationType) =>
  ({
    POTENTIAL_FOR: '潜在形成',
    TRANSFERABLE_TO: '可迁移至',
    COMBINES_WITH: '可组合',
    PREDICTED_LINK: '预测关联'
  })[relationType] || '潜在关联'

const copyResultText = async (text, successMessage) => {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      textarea.remove()
    }
    message.success(successMessage)
  } catch (error) {
    console.error('Failed to copy graph result:', error)
    message.error('复制失败，请稍后重试')
  }
}

const copyPathSummary = (path) => {
  const route = (path?.nodes || [])
    .map((node, index) => {
      const relation = path?.relations?.[index]
      return relation
        ? `${node.name} ${relation.traversed_reverse ? '←' : '→'}[${relation.type}]`
        : node.name
    })
    .join(' ')
  const gaps = (path?.evidence_gaps || []).join('；') || '无显式证据缺口'
  return copyResultText(
    [
      `多跳链路：${route}`,
      `事实等级：${path?.claim_level || '未知'}；综合得分：${formatScore(path?.score)}`,
      `语义覆盖：${Math.round(Number(path?.semantic_coverage || 0) * 100)}%；来源文件：${path?.evidence?.file_ids?.length || 0}`,
      `证据缺口：${gaps}`
    ].join('\n'),
    '已复制链路摘要'
  )
}

const copyInnovationSummary = (hypothesis) => {
  const validations = (hypothesis?.validation_requirements || []).join('；') || '待专家补充验证计划'
  const uncertainties = (hypothesis?.uncertainties || []).join('；') || '暂无显式不确定性记录'
  return copyResultText(
    [
      `创新假设：${hypothesis?.source?.name || '未知实体'} ${innovationRelationLabel(hypothesis?.relation_type)} ${hypothesis?.target?.name || '未知目标'}`,
      `候选可信度：${formatPercent(hypothesis?.score)}；战略综合分：${formatPercent(hypothesis?.innovation_profile?.strategic_score)}`,
      `机理假设：${hypothesis?.mechanism_hypothesis || '待补充'}`,
      `必须验证：${validations}`,
      `不确定性：${uncertainties}`,
      '结论等级：Hypothesis，不作为既成事实。'
    ].join('\n'),
    '已复制创新论证摘要'
  )
}

const innovationNextAction = (hypothesis) => {
  if (hypothesis?.review_status === 'accepted') return '建立验证任务并持续回收实验、仿真或工程证据'
  if (hypothesis?.review_status === 'rejected') return '保留审计记录，等待新证据后再评估'
  if (hypothesis?.validation_requirements?.length) return hypothesis.validation_requirements[0]
  if (hypothesis?.constraint_conflicts?.length)
    return `先核验约束冲突：${hypothesis.constraint_conflicts[0]}`
  return '由领域专家复核实体端点、关系方向和原文证据'
}

const innovationPriorityLabel = (priority) =>
  ({
    priority: '优先论证',
    weak_signal_watch: '弱信号关注',
    promising: '潜力候选',
    observe: '持续观察'
  })[priority] || '待评估'

const innovationPriorityColor = (priority) =>
  ({ priority: 'red', weak_signal_watch: 'purple', promising: 'blue', observe: 'default' })[
    priority
  ] || 'default'

const innovationPercent = (hypothesis, dimension) => {
  const value = Number(hypothesis?.innovation_profile?.dimensions?.[dimension] || 0)
  return `${Math.round(Math.max(0, Math.min(value, 1)) * 100)}%`
}

const scheduleGraphLoad = (delay = 200) => {
  if (!props.active || !isGraphSupported.value || !kbId.value) {
    return
  }

  if (pendingLoadTimer) {
    clearTimeout(pendingLoadTimer)
  }
  pendingLoadTimer = setTimeout(async () => {
    pendingLoadTimer = null
    await nextTick()
    if (props.active && isGraphSupported.value && kbId.value) {
      await loadGraph()
    }
  }, delay)
}

watch(
  () => props.active,
  (active) => {
    if (active) {
      if (isMilvus.value) {
        Promise.all([loadGraphBuildStatus(), loadAcceptanceStatus()])
      }
      scheduleGraphLoad()
    }
  },
  { immediate: true }
)

watch(kbId, () => {
  authority.clear()
  showRevisionHistory.value = false
  graphStatusRequestSeq += 1
  acceptanceStatusRequestSeq += 1
  graphLoadRequestSeq += 1
  pathDiscoveryRequestSeq += 1
  innovationDiscoveryRequestSeq += 1
  solutionGenerationRequestSeq += 1
  pathDiscoveryLoading.value = false
  innovationDiscoveryLoading.value = false
  graphLoaded.value = false
  graph.clearGraph()
  graphBuildStatus.value = null
  acceptanceStatus.value = null
  pathDiscoveryResult.paths = []
  pathDiscoveryResult.summary = {}
  pathDiscoveryResult.query_plan = null
  pathDiscoveryResult.path_reranking = null
  pathDiscoveryResult.pipeline_trace = null
  pathDiscoveryResult.narrative = null
  pathDiscoveryResult.narrative_provenance = null
  pathDiscoveryResult.discovery_mode = null
  pathDiscoveryResult.feature_kind = null
  pathDiscoverySearched.value = false
  innovationDiscoveryResult.hypotheses = []
  innovationDiscoveryResult.graph_revision = null
  innovationDiscoveryResult.query_analysis = null
  innovationDiscoveryResult.innovation_enhancement = null
  innovationDiscoveryResult.pipeline_trace = null
  innovationDiscoveryResult.feedback_loop = null
  innovationDiscoveryResult.evidence_scope = 'any'
  innovationDiscoveryResult.cross_document_candidate_count = 0
  innovationDiscoverySearched.value = false
  solutionGenerationLoading.value = false
  solutionGenerationResult.value = null
  showPathDiscovery.value = false
  showFailedChunkSamples.value = false
  failedChunkSamples.value = []
  if (isMilvus.value) {
    Promise.all([loadGraphBuildStatus(), loadAcceptanceStatus()])
  }
  if (isGraphSupported.value) {
    scheduleGraphLoad(300)
  }
})

watch(isGraphSupported, (supported) => {
  if (!supported) {
    authority.clear()
    showRevisionHistory.value = false
    graphLoaded.value = false
    graph.clearGraph()
    graphBuildStatus.value = null
    acceptanceStatus.value = null
    return
  }
  if (isMilvus.value) {
    Promise.all([loadGraphBuildStatus(), loadAcceptanceStatus()])
  }
  scheduleGraphLoad(200)
})

onUnmounted(() => {
  authority.clear()
  if (pendingLoadTimer) {
    clearTimeout(pendingLoadTimer)
    pendingLoadTimer = null
  }
  stopBuildStatusPoll()
})
</script>

<style scoped lang="less">
.graph-section {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  user-select: none;
}

.graph-container-compact {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  position: relative;
}

.graph-wrapper {
  height: 100%;
  width: 100%;
  position: relative;
}

.graph-empty-state {
  position: absolute;
  inset: 0;
  z-index: 30;
  pointer-events: none;

  :deep(.resource-empty-state__actions) {
    pointer-events: auto;
  }
}

.compact-actions {
  position: absolute;
  top: 10px;
  left: 10px;
  right: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  pointer-events: none; /* Let clicks pass through empty areas */

  .actions-left,
  .actions-right {
    pointer-events: auto; /* Re-enable clicks for buttons/inputs */
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--color-trans-light);
    backdrop-filter: blur(12px);
    padding: 2px;
    border-radius: 8px;
    box-shadow: 0 0 4px 0px var(--shadow-2);
    border: 1px solid var(--gray-100);
  }

  :deep(.ant-input-affix-wrapper) {
    padding: 4px 11px;
    border-radius: 6px;
    border-color: transparent;
    box-shadow: none;
    background: var(--color-trans-light);

    &:hover,
    &:focus,
    &-focused {
      background: var(--main-0);
      border-color: var(--primary-color);
    }

    input {
      background: transparent;
    }
  }

  .action-btn {
    width: 32px;
    height: 32px;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--gray-600);
    border-radius: 6px;
    box-shadow: none;
    position: relative;

    &:hover {
      background: var(--shadow-1);
      color: var(--primary-color);
    }
  }

  .labeled-action {
    width: auto;
    min-width: 32px;
    gap: 6px;
    padding: 0 9px;
    font-size: 12px;
    white-space: nowrap;
  }

  .layout-control {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    padding: 0 4px 0 8px;
    color: var(--gray-600);
    font-size: 12px;
    white-space: nowrap;

    .layout-options {
      display: flex;
      align-items: center;
      gap: 2px;
      padding: 2px;
      border-radius: 6px;
      background: var(--gray-100);
    }

    .layout-option {
      min-width: 42px;
      height: 24px;
      padding: 0 8px;
      border: 0;
      border-radius: 4px;
      background: transparent;
      color: var(--gray-700);
      cursor: pointer;
      font: inherit;

      &:hover {
        color: var(--primary-color);
      }
    }

    .layout-option.active {
      background: var(--color-bg-container);
      color: var(--primary-color);
      box-shadow: 0 1px 2px var(--shadow-1);
    }
  }

  .index-action-btn {
    gap: 6px;
    overflow: visible;

    &.has-index-label {
      width: auto;
      min-width: 84px;
      padding: 0 22px 0 8px;
      justify-content: flex-start;
    }

    .index-status-label {
      font-size: 12px;
      line-height: 1;
      color: var(--gray-700);
      white-space: nowrap;
    }
  }

  .status-dot {
    position: absolute;
    bottom: 4px;
    right: 4px;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    box-shadow: 0 0 0 1px var(--color-trans-light);
  }

  .status-dot--pending {
    background: var(--color-warning-500);
  }

  .status-dot--active {
    background: var(--color-warning-500);
    animation: blink 1.2s ease-in-out infinite;
  }

  .status-dot--complete {
    background: var(--color-success-500);
  }

  .search-suffix-icon {
    cursor: pointer;
  }

  .spin {
    animation: spin 1s linear infinite;
  }
}

.graph-search-input {
  width: 240px;
}

.graph-workflow-rail {
  position: absolute;
  top: 54px;
  left: 50%;
  z-index: 20;
  display: grid;
  width: min(760px, calc(100% - 32px));
  grid-template-columns: repeat(5, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: color-mix(in srgb, var(--color-bg-container) 92%, transparent);
  box-shadow: 0 8px 24px color-mix(in srgb, var(--gray-900) 10%, transparent);
  backdrop-filter: blur(14px);
  pointer-events: auto;
  transform: translateX(-50%);
}

.graph-workflow-step {
  position: relative;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  min-width: 0;
  padding: 8px 10px;
  border: 0;
  border-right: 1px solid var(--gray-100);
  background: transparent;
  color: var(--gray-600);
  cursor: pointer;
  font: inherit;
  text-align: left;

  &:last-child {
    border-right: 0;
  }

  &:hover,
  &:focus-visible {
    z-index: 1;
    background: var(--main-10);
    outline: none;
  }

  strong,
  small {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: var(--gray-900);
    font-size: 11px;
  }

  small {
    margin-top: 2px;
    color: var(--gray-500);
    font-size: 9px;
  }

  &__icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: 8px;
    background: var(--gray-100);
  }

  &--active {
    background: var(--main-10);

    .graph-workflow-step__icon {
      color: var(--main-color);
      background: var(--main-50);
      box-shadow: 0 0 0 3px var(--main-10);
    }
  }

  &--complete .graph-workflow-step__icon {
    color: var(--color-success-700);
    background: var(--color-success-50);
  }

  &--warning .graph-workflow-step__icon {
    color: var(--color-warning-700);
    background: var(--color-warning-50);
  }
}

@media (max-width: 768px) {
  .compact-actions {
    gap: 6px;
  }

  .compact-actions .actions-left {
    flex: 1;
    min-width: 0;
  }

  .compact-actions .actions-right,
  .compact-actions .action-btn {
    flex-shrink: 0;
  }

  .compact-actions .layout-control-label {
    display: none;
  }

  .compact-actions .labeled-action {
    width: 32px;
    padding: 0;
  }

  .compact-actions .labeled-action span {
    display: none;
  }

  .graph-search-input {
    flex: 1;
    width: 0;
    min-width: 0;
  }

  .graph-workflow-rail {
    top: 52px;
    width: calc(100% - 20px);
    overflow-x: auto;
    grid-template-columns: repeat(5, minmax(126px, 1fr));
  }
}

@keyframes blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.2;
  }
}

.graph-disabled {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
}

.disabled-content {
  text-align: center;
  color: var(--gray-400);

  h4 {
    margin-bottom: 8px;
  }
}

.floating-panel {
  position: absolute;
  top: 116px;
  right: 10px;
  width: 300px;
  max-width: calc(100% - 20px);
  max-height: calc(100% - 126px);
  overflow-y: auto;
  z-index: 100;
  background: var(--color-trans-light);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-radius: 8px;
  border: 1px solid var(--gray-100);
  box-shadow: 0 0 4px 0px var(--shadow-2);
  font-size: 13px;

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    border-bottom: 1px solid var(--gray-200);

    .panel-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--gray-1000);
    }

    .panel-refresh-btn {
      padding: 2px 6px;
    }
  }

  .panel-body {
    padding: 10px 14px;
  }
}

.build-panel {
  .status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;

    .status-label {
      color: var(--gray-600);
      font-size: 12px;
    }
  }

  .config-summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin: -2px 0 10px;
    padding: 8px 10px;
    border-radius: 6px;
    background: var(--gray-50);

    > div {
      min-width: 0;
    }

    .config-summary-label,
    strong {
      display: block;
    }

    .config-summary-label {
      margin-bottom: 2px;
      color: var(--gray-500);
      font-size: 11px;
    }

    strong {
      overflow: hidden;
      color: var(--gray-800);
      font-size: 12px;
      font-weight: 500;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 12px;
  }

  .stat-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 6px 4px;
    border-radius: 4px;
    background: var(--gray-50);

    &.is-clickable {
      cursor: pointer;
      border: 1px solid var(--color-error-100);

      &:hover,
      &:focus-visible {
        background: var(--color-error-50);
        outline: none;
      }

      .stat-value,
      .stat-label {
        color: var(--color-error-700);
      }
    }

    .stat-value {
      font-size: 15px;
      font-weight: 600;
      color: var(--gray-1000);
      line-height: 1.2;
    }

    .stat-label {
      font-size: 11px;
      color: var(--gray-500);
      margin-top: 2px;
    }
  }

  .acceptance-card {
    margin-bottom: 12px;
    padding: 10px;
    border: 1px solid var(--gray-200);
    border-radius: 6px;
    background: var(--color-bg-container);
  }

  .acceptance-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
    color: var(--gray-900);
    font-size: 12px;
    font-weight: 600;
  }

  .acceptance-scale-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 6px;

    > div {
      display: flex;
      min-width: 0;
      flex-direction: column;
      padding: 6px;
      border-radius: 4px;
      background: var(--gray-50);
      text-align: center;
    }

    strong {
      overflow: hidden;
      color: var(--gray-900);
      font-size: 12px;
      text-overflow: ellipsis;
    }

    span {
      margin-top: 2px;
      color: var(--gray-500);
      font-size: 10px;
    }
  }

  .acceptance-quality-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px 8px;
    margin-top: 8px;
    color: var(--gray-600);
    font-size: 11px;
  }

  .acceptance-note,
  .acceptance-failures {
    margin: 8px 0 0;
    font-size: 11px;
    line-height: 1.5;
  }

  .acceptance-note {
    color: var(--gray-500);
  }

  .acceptance-failures {
    color: var(--color-warning-700);
  }

  .build-actions {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .actions-secondary {
    display: flex;
    justify-content: space-between;
  }
}

.failed-chunk-loading {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--gray-600);
}

.failed-chunk-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-bottom: 12px;
  color: var(--gray-600);
  font-size: 12px;
}

.failed-chunk-content {
  max-height: 360px;
  overflow: auto;
  margin: 12px 0 0;
  padding: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-50);
  color: var(--gray-900);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.path-discovery-notice {
  margin-bottom: 16px;
}

.innovation-workbench-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(340px, 0.8fr);
  gap: 20px;
  align-items: center;
  margin: -4px 0 14px;
  padding: 18px 20px;
  border: 1px solid var(--main-100);
  border-radius: 12px;
  background:
    radial-gradient(circle at 92% 16%, var(--main-100), transparent 34%),
    linear-gradient(135deg, var(--main-10), var(--gray-0));
}

.innovation-hero-copy {
  min-width: 0;

  h3,
  p {
    margin: 0;
  }

  h3 {
    margin-top: 4px;
    color: var(--gray-900);
    font-size: 18px;
    line-height: 1.4;
  }

  p {
    max-width: 680px;
    margin-top: 5px;
    color: var(--gray-600);
    font-size: 12px;
    line-height: 1.65;
  }
}

.innovation-hero-kicker {
  color: var(--main-color);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
}

.discovery-feature-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;

  button {
    display: grid;
    grid-template-columns: 28px minmax(0, 1fr);
    gap: 8px;
    align-items: center;
    min-width: 0;
    padding: 11px;
    border: 1px solid var(--gray-150);
    border-radius: 9px;
    background: color-mix(in srgb, var(--gray-0) 88%, transparent);
    color: var(--gray-600);
    cursor: pointer;
    font: inherit;
    text-align: left;

    &:hover,
    &.active {
      border-color: var(--main-color);
      background: var(--main-10);
      color: var(--main-color);
    }

    &.active {
      box-shadow: inset 0 0 0 1px var(--main-30);
    }

    span,
    strong,
    small {
      display: block;
      min-width: 0;
    }

    strong {
      color: var(--gray-900);
      font-size: 12px;
    }

    small {
      margin-top: 2px;
      color: var(--gray-500);
      font-size: 10px;
      line-height: 1.4;
    }
  }
}

.innovation-hero-flow {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;

  li {
    position: relative;
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 5px;
    padding: 10px;
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    background: color-mix(in srgb, var(--gray-0) 88%, transparent);
  }

  li:not(:last-child)::after {
    position: absolute;
    top: 18px;
    right: -7px;
    z-index: 1;
    width: 6px;
    height: 6px;
    border-top: 1px solid var(--main-color);
    border-right: 1px solid var(--main-color);
    content: '';
    transform: rotate(45deg);
  }

  li.active {
    border-color: var(--main-color);
    background: var(--main-10);
    box-shadow: inset 0 0 0 1px var(--main-30);
  }

  strong {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 6px;
    color: var(--main-color);
    background: var(--main-50);
    font-size: 11px;
  }

  span {
    color: var(--gray-700);
    font-size: 11px;
    font-weight: 600;
    line-height: 1.4;
  }
}

.discovery-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}

.multihop-narrative {
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid var(--main-100);
  border-radius: 12px;
  background: var(--color-bg-container);

  > header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 15px 18px;
    border-bottom: 1px solid var(--main-50);
    background: linear-gradient(135deg, var(--main-10), var(--color-bg-container));

    span {
      color: var(--main-color);
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 0.12em;
    }

    h3 {
      margin: 3px 0 0;
      color: var(--gray-900);
      font-size: 16px;
    }
  }
}

.multihop-executive-conclusion {
  padding: 16px 18px;
  border-bottom: 1px solid var(--gray-100);

  strong {
    color: var(--gray-900);
    font-size: 13px;
  }

  p {
    margin: 7px 0;
    color: var(--gray-800);
    font-size: 13px;
    line-height: 1.75;
    white-space: pre-wrap;
  }

  small {
    color: var(--gray-500);
    font-size: 10px;
  }
}

.multihop-narrative-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 14px;

  > section {
    min-width: 0;
    padding: 12px;
    border: 1px solid var(--gray-100);
    border-radius: 8px;
    background: var(--gray-50);
  }

  h4 {
    margin: 0 0 8px;
    color: var(--gray-900);
    font-size: 12px;
  }

  ol {
    margin: 0;
    padding-left: 18px;
  }

  li + li {
    margin-top: 8px;
  }

  p {
    margin: 0;
    color: var(--gray-700);
    font-size: 12px;
    line-height: 1.6;
  }

  small {
    display: block;
    margin-top: 3px;
    color: var(--gray-500);
    font-size: 9px;
    word-break: break-all;
  }
}

.discovery-mode-card {
  position: relative;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  min-height: 92px;
  padding: 13px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
  color: var(--gray-700);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition:
    border-color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease;

  &:hover,
  &.active {
    border-color: var(--main-color);
    background: var(--main-10);
  }

  &.active {
    box-shadow: 0 0 0 2px var(--main-30);
  }

  > span:nth-child(2) {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 3px;
  }

  strong {
    color: var(--gray-900);
    font-size: 13px;
  }

  small {
    color: var(--gray-500);
    font-size: 11px;
    line-height: 1.5;
  }

  em {
    position: absolute;
    top: 10px;
    right: 10px;
    padding: 2px 6px;
    border-radius: 999px;
    color: var(--main-color);
    background: var(--main-50);
    font-size: 9px;
    font-style: normal;
    font-weight: 700;
  }
}

.discovery-mode-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  color: var(--main-color);
  background: var(--main-50);
}

.innovation-template-row,
.exploration-preset-row {
  display: grid;
  grid-template-columns: 92px repeat(3, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
  margin-bottom: 12px;

  > span {
    display: flex;
    align-items: center;
    color: var(--gray-600);
    font-size: 11px;
    font-weight: 700;
  }

  button {
    display: flex;
    min-width: 0;
    padding: 9px 10px;
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    background: var(--gray-0);
    color: var(--gray-700);
    cursor: pointer;
    flex-direction: column;
    font-family: inherit;
    text-align: left;
    transition:
      border-color 0.18s ease,
      background 0.18s ease;

    &:hover,
    &.active {
      border-color: var(--main-color);
      background: var(--main-10);
    }

    strong {
      color: var(--gray-900);
      font-size: 11px;
      line-height: 1.4;
    }

    small {
      margin-top: 2px;
      color: var(--gray-500);
      font-size: 10px;
      line-height: 1.45;
    }
  }
}

.exploration-preset-row {
  padding: 10px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-25);
}

.innovation-query-input {
  margin-bottom: 12px;
}

.innovation-primary-action {
  min-width: 132px;
}

.innovation-overview {
  margin: 14px 0;
  padding: 14px;
  border: 1px solid var(--main-100);
  border-radius: 11px;
  background: linear-gradient(135deg, var(--main-10), var(--gray-0));

  > header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
  }

  h3,
  span {
    margin: 0;
  }

  header span {
    color: var(--main-color);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
  }

  h3 {
    margin-top: 2px;
    color: var(--gray-900);
    font-size: 14px;
  }
}

.innovation-overview-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;

  div {
    padding: 10px;
    border: 1px solid color-mix(in srgb, var(--main-100) 72%, var(--gray-150));
    border-radius: 8px;
    background: color-mix(in srgb, var(--gray-0) 90%, transparent);
  }

  span,
  strong {
    display: block;
  }

  span {
    color: var(--gray-600);
    font-size: 10px;
  }

  strong {
    margin-top: 4px;
    color: var(--main-color);
    font-size: 18px;
  }
}

.query-pipeline-trace,
.innovation-feedback-loop {
  margin: 14px 0;
  padding: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 11px;
  background: var(--gray-25);

  > header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 10px;
  }

  h3,
  h4,
  p {
    margin: 0;
  }

  header > div > span {
    color: var(--main-color);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
  }

  h3,
  h4 {
    margin-top: 2px;
    color: var(--gray-900);
    font-size: 14px;
  }
}

.query-pipeline-trace {
  ol {
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 7px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  li {
    min-width: 0;
    padding: 9px;
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    background: var(--gray-0);
  }

  li > strong,
  li > small {
    display: block;
  }

  li > strong {
    margin-top: 7px;
    color: var(--main-color);
    font-size: 16px;
  }

  li > small {
    margin-top: 5px;
    color: var(--color-warning-700);
    font-size: 9px;
    line-height: 1.4;
  }
}

.query-trace-step {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 5px;

  > span {
    color: var(--gray-700);
    font-size: 10px;
    font-weight: 600;
    line-height: 1.4;
  }
}

.innovation-feedback-loop {
  border-color: var(--main-100);
  background: linear-gradient(135deg, var(--main-10), var(--gray-0));

  header p,
  footer,
  .feedback-loop-grid p,
  .feedback-loop-grid li {
    color: var(--gray-600);
    font-size: 11px;
    line-height: 1.55;
  }

  footer {
    margin-top: 10px;
    padding-top: 9px;
    border-top: 1px solid var(--main-100);
  }
}

.feedback-loop-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;

  > div {
    min-width: 0;
    padding: 10px;
    border: 1px solid color-mix(in srgb, var(--main-100) 72%, var(--gray-150));
    border-radius: 8px;
    background: color-mix(in srgb, var(--gray-0) 92%, transparent);
  }

  strong {
    color: var(--gray-900);
    font-size: 11px;
  }

  p,
  ul {
    margin: 6px 0 0;
  }

  ul {
    padding-left: 18px;
  }

  :deep(.ant-btn) {
    margin-top: 8px;
  }
}

.model-enhancement-disclosure {
  margin-top: 2px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-25);

  summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding: 11px 13px;
    color: var(--gray-700);
    cursor: pointer;
    list-style: none;
  }

  summary::-webkit-details-marker {
    display: none;
  }

  summary > span {
    display: inline-flex;
    align-items: center;
    gap: 7px;
  }

  summary small {
    color: var(--gray-500);
    font-size: 11px;
  }
}

.model-enhancement-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 14px;
  padding: 0 13px 13px;
  border-top: 1px solid var(--gray-150);
}

.path-query-form {
  .path-query-options {
    display: grid;
    grid-template-columns: 110px minmax(150px, 1fr) 110px minmax(170px, 1fr) auto auto;
    gap: 12px;
    align-items: end;

    :deep(.ant-select),
    :deep(.ant-input-number) {
      width: 100%;
    }
  }
}

.path-discovery-loading {
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--gray-600);
}

.path-results {
  max-height: 58vh;
  overflow-y: auto;
  padding-right: 4px;
}

.innovation-results {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--gray-150);
}

.innovation-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;

  h3,
  p {
    margin: 0;
  }

  h3 {
    color: var(--gray-900);
    font-size: 15px;
  }

  p {
    margin-top: 3px;
    color: var(--gray-600);
    font-size: 12px;
  }
}

.innovation-card {
  border-color: var(--color-warning-100);
  background: var(--color-warning-50);
}

.innovation-profile {
  padding: 12px;
  margin-top: 12px;
  border: 1px solid var(--main-100);
  border-radius: 9px;
  background: var(--color-bg-container);

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  h4,
  p {
    margin: 0;
  }

  h4 {
    color: var(--gray-900);
    font-size: 13px;
  }

  p {
    margin-top: 3px;
    color: var(--gray-600);
    font-size: 11px;
  }
}

.innovation-dimension-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;

  div {
    min-width: 0;
    padding: 8px;
    border-radius: 7px;
    background: var(--main-10);
  }

  span,
  strong {
    display: block;
  }

  span {
    color: var(--gray-600);
    font-size: 10px;
  }

  strong {
    margin-top: 3px;
    color: var(--main-color);
    font-size: 15px;
  }
}

.innovation-profile-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 9px;
  color: var(--gray-600);
  font-size: 11px;
}

.solution-generation-controls {
  margin-top: 4px;
  padding-top: 14px;
  border-top: 1px solid var(--gray-150);
}

.solution-generation-hint {
  margin-left: 10px;
}

.grounded-solution-results {
  border-top-color: var(--color-warning-100);
}

.solution-evidence-list {
  display: grid;
  gap: 8px;
  margin-top: 14px;

  details {
    padding: 10px 12px;
    border: 1px solid var(--gray-150);
    border-radius: 6px;
    background: var(--gray-0);
  }

  summary {
    cursor: pointer;
    color: var(--gray-800);
    font-weight: 600;
  }

  p {
    margin: 10px 0 0;
    color: var(--gray-700);
    line-height: 1.6;
    white-space: pre-wrap;
  }
}

.requirement-analysis {
  padding: 12px;
  margin-bottom: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-25);

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  h4,
  p,
  dl,
  dd {
    margin: 0;
  }

  h4 {
    color: var(--gray-900);
    font-size: 14px;
  }

  p,
  dt {
    color: var(--gray-600);
    font-size: 12px;
  }

  dl {
    display: grid;
    gap: 7px;
    margin-top: 10px;
  }

  dl > div {
    display: grid;
    grid-template-columns: 72px minmax(0, 1fr);
    gap: 8px;
  }

  dd {
    color: var(--gray-800);
    font-size: 12px;
    line-height: 1.55;
  }
}

.requirement-mappings {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.innovation-mechanism {
  margin: 0;
  color: var(--gray-800);
  font-size: 13px;
  line-height: 1.6;
}

.path-result-summary {
  margin-bottom: 10px;
  color: var(--gray-600);
  font-size: 12px;
}

.result-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-25);

  &--innovation {
    border-color: var(--color-warning-100);
    background: color-mix(in srgb, var(--color-warning-50) 40%, var(--gray-0));
  }

  &__summary,
  &__controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
  }

  &__summary {
    gap: 4px 8px;

    strong {
      color: var(--main-color);
      font-size: 13px;
    }

    span {
      margin-right: 7px;
      color: var(--gray-500);
      font-size: 10px;
    }
  }

  &__controls {
    justify-content: flex-end;
    gap: 8px;

    :deep(.ant-select) {
      min-width: 142px;
    }
  }
}

.path-card {
  position: relative;
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
  box-shadow: 0 8px 24px color-mix(in srgb, var(--gray-900) 5%, transparent);

  &::before {
    position: absolute;
    inset: 12px auto 12px 0;
    width: 3px;
    border-radius: 0 99px 99px 0;
    background: var(--main-color);
    content: '';
  }

  &--fact::before {
    background: var(--color-success-500);
  }

  &--hypothesis::before {
    background: var(--color-warning-500);
  }
}

.path-card-header,
.path-card-title,
.path-evidence-summary,
.path-card-footer {
  display: flex;
  align-items: center;
}

.path-card-header {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.path-card-title {
  flex-wrap: wrap;
  gap: 6px;
  color: var(--gray-900);
  font-weight: 600;
}

.path-evidence-summary {
  color: var(--gray-600);
  font-size: 12px;
}

.path-card-score {
  display: flex;
  min-width: 82px;
  flex-direction: column;
  align-items: flex-end;

  strong {
    color: var(--main-color);
    font-size: 18px;
    line-height: 1;
  }

  span {
    margin-top: 4px;
    color: var(--gray-500);
    font-size: 10px;
  }

  &--innovation strong {
    color: var(--color-warning-700);
  }
}

.path-value-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.path-chain {
  display: flex;
  align-items: stretch;
  gap: 8px;
  overflow-x: auto;
  padding: 2px 0 8px;
}

.result-quality-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 4px;

  > div {
    min-width: 0;
    padding: 9px 10px;
    border: 1px solid var(--gray-100);
    border-radius: 8px;
    background: var(--gray-25);
  }

  span,
  strong {
    display: block;
  }

  span {
    color: var(--gray-500);
    font-size: 10px;
  }

  strong {
    margin-top: 3px;
    color: var(--gray-900);
    font-size: 13px;
  }

  .status-success {
    color: var(--color-success-700);
  }

  .status-warning {
    color: var(--color-warning-700);
  }

  &--innovation > div {
    border-color: color-mix(in srgb, var(--color-warning-100) 80%, var(--gray-100));
    background: color-mix(in srgb, var(--color-warning-50) 58%, var(--gray-0));
  }
}

.research-thread-map {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.research-thread {
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-25);

  header {
    display: flex;
    min-width: 0;
    flex-direction: column;
    margin-bottom: 7px;
  }

  header span {
    color: var(--gray-900);
    font-size: 11px;
    font-weight: 700;
  }

  header small {
    margin-top: 2px;
    color: var(--gray-500);
    font-size: 9px;
    line-height: 1.4;
  }

  > div {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  &--main {
    border-color: var(--main-100);
    background: var(--main-10);
  }

  &--side {
    border-color: var(--color-success-100);
    background: var(--color-success-10);
  }

  &--parallel {
    border-color: var(--color-warning-100);
    background: var(--color-warning-50);
  }
}

.result-audit-disclosure {
  margin-top: 10px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-25);

  summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;
    color: var(--gray-800);
    cursor: pointer;
    font-size: 11px;
    font-weight: 600;
    list-style: none;
  }

  summary::-webkit-details-marker {
    display: none;
  }

  summary::after {
    color: var(--main-color);
    content: '＋';
    font-size: 14px;
  }

  &[open] summary::after {
    content: '－';
  }

  summary small {
    margin-left: auto;
    color: var(--gray-500);
    font-size: 10px;
    font-weight: 400;
  }

  > .path-section {
    margin: 0;
    padding: 9px 12px;
    border-top: 1px solid var(--gray-100);
  }
}

.innovation-audit-disclosure {
  border-color: var(--color-warning-100);
  background: color-mix(in srgb, var(--color-warning-50) 46%, var(--gray-0));
}

.decision-next-action {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--main-100);
  border-radius: 8px;
  background: var(--main-10);

  span {
    color: var(--main-color);
    font-size: 10px;
    font-weight: 700;
  }

  strong {
    color: var(--gray-800);
    font-size: 11px;
    font-weight: 600;
    line-height: 1.55;
  }
}

.validation-section h4,
.validation-section li {
  color: var(--color-success-700);
}

.falsification-section h4,
.falsification-section li {
  color: var(--color-warning-700);
}

.hypothesis-route {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(120px, 0.56fr) minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;

  > div:not(.hypothesis-relation) {
    display: flex;
    min-width: 0;
    min-height: 72px;
    padding: 11px 12px;
    border: 1px solid var(--gray-150);
    border-radius: 9px;
    background: var(--gray-0);
    flex-direction: column;
  }

  span,
  small {
    color: var(--gray-500);
    font-size: 10px;
  }

  strong {
    margin: 4px 0;
    color: var(--gray-900);
    font-size: 13px;
    line-height: 1.45;
  }
}

.hypothesis-relation {
  position: relative;
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: center;
  color: var(--color-warning-700);
  text-align: center;

  &::before,
  &::after {
    position: absolute;
    top: 50%;
    width: calc(50% - 44px);
    height: 1px;
    background: var(--color-warning-500);
    content: '';
  }

  &::before {
    left: 0;
  }

  &::after {
    right: 0;
  }

  span {
    z-index: 1;
    padding: 4px 8px;
    border: 1px solid var(--color-warning-100);
    border-radius: 999px;
    background: var(--color-warning-50);
    color: var(--color-warning-700);
    font-weight: 700;
  }
}

.path-node {
  min-width: 130px;
  max-width: 220px;
  padding: 9px 10px;
  border: 1px solid var(--main-100);
  border-radius: 8px;
  background: var(--main-10);
  color: var(--gray-900);

  strong {
    display: block;
    margin-top: 3px;
    line-height: 1.4;
  }
}

.path-node-role {
  color: var(--main-color);
  font-size: 11px;
}

.path-relation {
  min-width: 90px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--gray-600);
  font-size: 12px;
  text-align: center;

  small {
    margin-top: 2px;
    color: var(--gray-500);
  }
}

.path-evidence-summary {
  flex-wrap: wrap;
  gap: 6px 16px;
  padding: 8px 0;
  border-bottom: 1px solid var(--gray-100);
}

.path-section {
  margin-top: 10px;

  h4 {
    margin: 0 0 4px;
    color: var(--gray-800);
    font-size: 12px;
    font-weight: 600;
  }

  ul {
    margin: 0;
    padding-left: 18px;
    color: var(--gray-700);
    font-size: 12px;
    line-height: 1.6;
  }
}

.path-gaps h4,
.path-gaps li {
  color: var(--color-warning-700);
}

.path-card-footer {
  justify-content: flex-end;
  margin-top: 10px;
}

@media (max-width: 720px) {
  .innovation-workbench-hero {
    grid-template-columns: 1fr;
    padding: 14px;
  }

  .innovation-hero-flow,
  .discovery-mode-grid,
  .model-enhancement-grid {
    grid-template-columns: 1fr;
  }

  .innovation-template-row,
  .exploration-preset-row {
    grid-template-columns: 1fr;

    > span {
      margin-bottom: 2px;
    }
  }

  .innovation-overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .query-pipeline-trace ol,
  .feedback-loop-grid {
    grid-template-columns: 1fr;
  }

  .innovation-hero-flow li {
    flex-direction: row;
    align-items: center;
  }

  .innovation-hero-flow li:not(:last-child)::after {
    display: none;
  }

  .innovation-dimension-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .path-query-form .path-query-options {
    grid-template-columns: 1fr 1fr;
  }

  .model-enhancement-disclosure summary {
    align-items: flex-start;
    flex-direction: column;
  }

  .path-card-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .path-card-score {
    align-items: flex-start;
  }

  .result-quality-strip,
  .research-thread-map,
  .hypothesis-route {
    grid-template-columns: 1fr;
  }

  .result-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .result-toolbar__controls {
    justify-content: stretch;

    :deep(.ant-select) {
      flex: 1;
      min-width: 0;
    }
  }

  .decision-next-action {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .hypothesis-relation {
    padding: 4px 0;
  }
}

.config-warning {
  margin-bottom: 16px;
}

.extraction-presets {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.extraction-preset {
  display: flex;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  color: var(--gray-700);
  cursor: pointer;
  flex-direction: column;
  text-align: left;
  transition:
    border-color 0.2s ease,
    background 0.2s ease,
    box-shadow 0.2s ease;

  &:hover {
    border-color: var(--main-color);
  }

  &.active {
    border-color: var(--main-color);
    background: var(--main-10);
    box-shadow: 0 0 0 1px var(--main-20);
  }

  .preset-title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    color: var(--gray-900);
    font-size: 14px;
    font-weight: 600;

    small {
      padding: 1px 5px;
      border-radius: 8px;
      background: var(--main-100);
      color: var(--main-color);
      font-size: 10px;
      font-weight: 500;
    }
  }

  .preset-values {
    margin-top: 5px;
    color: var(--main-color);
    font-size: 12px;
  }

  .preset-description {
    margin-top: 5px;
    color: var(--gray-500);
    font-size: 11px;
    line-height: 1.4;
  }
}

@media (max-width: 640px) {
  .extraction-presets {
    grid-template-columns: 1fr;
  }
}

.extractor-type-cards {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;

  .extractor-type-card {
    border: 1px solid var(--gray-150);
    border-radius: 8px;
    padding: 14px;
    cursor: pointer;
    transition: all 0.2s ease;
    background: var(--gray-0);

    &:hover {
      border-color: var(--main-color);
    }

    &.active {
      border-color: var(--main-color);
      background: var(--main-10);
      box-shadow: 0 0 0 1px var(--main-20);

      .type-icon {
        color: var(--main-color);
      }
    }

    &.disabled {
      cursor: not-allowed;
      opacity: 0.72;
      background: var(--gray-50);

      &:hover {
        border-color: var(--gray-150);
      }
    }

    .card-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }

    .type-icon {
      width: 20px;
      height: 20px;
      color: var(--main-color);
      flex-shrink: 0;
    }

    .type-title {
      font-size: 15px;
      font-weight: 600;
      color: var(--gray-800);
    }

    .card-description {
      font-size: 13px;
      color: var(--gray-600);
      line-height: 1.5;
    }

    .card-helper {
      margin-top: 8px;
      font-size: 12px;
      color: var(--gray-500);

      &.warning {
        color: var(--color-warning-500);
      }
    }
  }
}

.orchestration-mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;

  @media (max-width: 760px) {
    grid-template-columns: 1fr;
  }
}

:deep(.graph-config-modal-wrap .ant-modal-body) {
  max-height: min(74vh, 760px);
  overflow-y: auto;
  overscroll-behavior: contain;
}

.graph-config-guide {
  margin: 2px 0 18px;
  padding: 18px;
  border: 1px solid color-mix(in srgb, var(--main-color) 18%, var(--gray-200));
  border-radius: 14px;
  background:
    radial-gradient(
      circle at 100% 0,
      color-mix(in srgb, var(--main-color) 10%, transparent),
      transparent 36%
    ),
    var(--gray-10, #fbfcfc);
}

.graph-config-guide__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;

  h3 {
    margin: 2px 0 4px;
    color: var(--gray-1000);
    font-size: 17px;
    line-height: 1.4;
  }

  p {
    margin: 0;
    color: var(--gray-600);
    font-size: 13px;
    line-height: 1.55;
  }
}

.graph-config-guide__eyebrow {
  color: var(--main-color);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.graph-config-step {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 12px;
  padding: 16px 0;
  border-top: 1px solid var(--gray-150, #eef0f0);
}

.graph-config-step__index {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  color: var(--main-color);
  background: var(--main-100);
  font-size: 13px;
  font-weight: 700;
}

.graph-config-step__content {
  min-width: 0;
}

.graph-config-step__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;

  h4 {
    margin: 0 0 2px;
    color: var(--gray-900);
    font-size: 14px;
    line-height: 1.5;
  }

  p {
    margin: 0;
    color: var(--gray-600);
    font-size: 12px;
    line-height: 1.5;
  }
}

.graph-quick-switches {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.graph-quick-switch {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  padding: 11px 12px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  background: var(--gray-0);
  cursor: pointer;

  span {
    display: flex;
    min-width: 0;
    flex-direction: column;
  }

  strong {
    color: var(--gray-900);
    font-size: 12px;
    font-weight: 600;
  }

  small {
    margin-top: 2px;
    overflow: hidden;
    color: var(--gray-500);
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.graph-pipeline-preview {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 10px 12px;
  overflow-x: auto;
  border-radius: 9px;
  color: var(--gray-700);
  background: color-mix(in srgb, var(--main-color) 5%, var(--gray-0));
  font-size: 11px;
  white-space: nowrap;
}

.graph-pipeline-preview__stage {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.graph-pipeline-preview__arrow {
  color: var(--main-400);
}

.advanced-config-toggle {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  width: 100%;
  margin: 0 0 16px;
  padding: 11px 13px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  color: var(--gray-700);
  background: var(--gray-0);
  cursor: pointer;
  text-align: left;
  transition:
    border-color 0.18s ease,
    background 0.18s ease;

  &:hover {
    border-color: var(--main-300);
    background: var(--main-20);
  }

  > span {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    color: var(--gray-900);
    font-size: 13px;
    font-weight: 600;
  }

  small {
    margin-left: 12px;
    color: var(--gray-500);
    font-size: 11px;
  }
}

.orchestration-mode-card {
  display: flex;
  align-items: flex-start;
  min-height: 96px;
  margin: 0;
  padding: 14px;
  border: 1px solid var(--gray-200, #e5e7eb);
  border-radius: 10px;
  background: var(--gray-0, #fff);
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    background 0.18s ease;

  &:hover {
    border-color: var(--main-color, #1677ff);
  }

  :deep(.ant-radio) {
    margin-top: 3px;
  }

  :deep(.ant-radio + span) {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 6px;
    white-space: normal;
  }

  &:has(.ant-radio-checked) {
    border-color: var(--main-color, #1677ff);
    background: color-mix(in srgb, var(--main-color, #1677ff) 6%, transparent);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--main-color, #1677ff) 12%, transparent);
  }
}

.orchestration-mode-card__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.orchestration-mode-card__badge {
  flex: none;
  padding: 2px 7px;
  border-radius: 999px;
  color: var(--main-color);
  background: var(--main-50);
  font-size: 10px;
  font-weight: 600;
}

.orchestration-mode-card__title {
  color: var(--gray-900, #111827);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.orchestration-mode-card__description {
  color: var(--gray-600, #6b7280);
  font-size: 12px;
  line-height: 1.55;
}

.orchestration-mode-card__features {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;

  span {
    padding: 2px 6px;
    border-radius: 5px;
    color: var(--gray-600);
    background: var(--gray-100);
    font-size: 10px;
    line-height: 1.4;
  }
}

@media (max-width: 760px) {
  .graph-config-guide {
    padding: 14px;
  }

  .graph-config-guide__header,
  .graph-config-step__heading {
    flex-direction: column;
  }

  .graph-quick-switches {
    grid-template-columns: 1fr;
  }

  .advanced-config-toggle {
    grid-template-columns: 1fr auto;

    small {
      display: none;
    }
  }
}

.form-grid.two-columns {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 12px;

  @media (max-width: 640px) {
    grid-template-columns: 1fr;
  }
}

.form-item-hint {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--gray-600, #6b7280);
}

.slide-fade-enter-active {
  transition: all 0.25s ease-out;
}

.slide-fade-leave-active {
  transition: all 0.2s cubic-bezier(1, 0.5, 0.8, 1);
}

.slide-fade-enter-from,
.slide-fade-leave-to {
  transform: translateX(20px);
  opacity: 0;
}
</style>
