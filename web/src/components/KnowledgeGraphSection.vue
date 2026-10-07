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
          @node-click="graph.handleNodeClick"
          @edge-click="graph.handleEdgeClick"
          @canvas-click="graph.handleCanvasClick"
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
              </div>
            </div>
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
          @close="graph.handleCanvasClick"
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
                    danger
                    v-if="graphBuildStatus?.locked && !isBuildActive"
                    @click="confirmResetGraph"
                    >重置</a-button
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
      width="640px"
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
        <a-form-item label="模型">
          <ModelSelectorComponent
            :model_spec="graphConfigForm.model_spec"
            placeholder="选择抽取模型"
            @select-model="(spec) => (graphConfigForm.model_spec = spec)"
          />
        </a-form-item>
        <a-form-item label="Schema">
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
        <div class="form-grid two-columns">
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
              默认 60 秒。推理型抽取模型单块耗时可达数十秒，若日志出现反复超时重试，可调大至
              180–300。
            </div>
          </a-form-item>
        </div>
        <a-form-item label="模型参数 JSON">
          <a-input
            v-model:value="graphConfigForm.model_params_text"
            placeholder='例如 {"temperature":0.1}（不能用于设置超时，请用上方字段）'
          />
        </a-form-item>
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
      title="研发知识链路发现"
      width="min(1000px, calc(100vw - 32px))"
      :footer="null"
    >
      <a-alert
        class="path-discovery-notice"
        type="info"
        show-icon
        message="链路来自现有图谱的确定性检索；组合或预测桥会标为假设，不会自动写回知识图谱。"
      />
      <a-form layout="vertical" class="path-query-form">
        <a-form-item label="研发需求或实体">
          <a-input
            v-model:value="pathQuery.query"
            placeholder="例如：复杂环境感知能力，或某项关键技术"
            :maxlength="500"
            @keydown.enter="runPathDiscovery"
          />
        </a-form-item>
        <div class="path-query-options">
          <a-form-item label="发现模式">
            <a-select v-model:value="pathQuery.mode">
              <a-select-option value="auto">自动判断</a-select-option>
              <a-select-option value="requirement_driven">从需求找技术路线</a-select-option>
              <a-select-option value="entity_expansion">从实体扩展关联</a-select-option>
            </a-select>
          </a-form-item>
          <a-form-item label="最大跳数">
            <a-input-number v-model:value="pathQuery.max_hops" :min="1" :max="6" />
          </a-form-item>
          <a-form-item label="探索性组合">
            <a-switch v-model:checked="pathQuery.include_combinations" />
          </a-form-item>
          <a-form-item label=" ">
            <a-button type="primary" :loading="pathDiscoveryLoading" @click="runPathDiscovery">
              <Waypoints v-if="!pathDiscoveryLoading" :size="15" />
              发现链路
            </a-button>
          </a-form-item>
        </div>
      </a-form>

      <div v-if="pathDiscoveryLoading" class="path-discovery-loading">
        <Loader2 :size="20" class="spin" />
        正在检索并整理跨 Chunk 技术链路
      </div>
      <a-empty
        v-else-if="pathDiscoverySearched && !pathDiscoveryResult.paths.length"
        description="未发现满足约束的链路，可尝试更具体的需求、实体名称或增加跳数。"
      />
      <div v-else-if="pathDiscoveryResult.paths.length" class="path-results">
        <div class="path-result-summary">
          找到 {{ pathDiscoveryResult.paths.length }} 条去重后的最大链路 ·
          {{
            pathDiscoveryResult.summary?.retrieval_mode === 'semantic' ? '语义锚点' : '关键词锚点'
          }}
        </div>
        <article
          v-for="(path, pathIndex) in pathDiscoveryResult.paths"
          :key="path.path_id"
          class="path-card"
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
            <div class="path-card-metrics">
              评分 {{ path.score }} · 语义覆盖 {{ Math.round(path.semantic_coverage * 100) }}%
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

          <div class="path-evidence-summary">
            <span>{{ path.evidence.mention_count }} 条关系证据</span>
            <span>{{ path.evidence.chunk_ids.length }} 个 Chunk</span>
            <span>{{ path.evidence.file_ids.length }} 个文件</span>
          </div>

          <div v-if="path.research_inspiration.value_signals.length" class="path-section">
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
            v-if="path.research_inspiration.military_value_dimensions?.length"
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
            v-if="path.research_inspiration.expected_capability_gains?.length"
            class="path-section"
          >
            <h4>预期能力收益</h4>
            <ul>
              <li v-for="gain in path.research_inspiration.expected_capability_gains" :key="gain">
                {{ gain }}
              </li>
            </ul>
          </div>
          <div v-if="path.research_inspiration.application_directions?.length" class="path-section">
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
            v-if="path.research_inspiration.uncertainties?.length"
            class="path-section path-gaps"
          >
            <h4>不确定性与边界</h4>
            <ul>
              <li v-for="uncertainty in path.research_inspiration.uncertainties" :key="uncertainty">
                {{ uncertainty }}
              </li>
            </ul>
          </div>
          <div v-if="path.evidence_gaps.length" class="path-section path-gaps">
            <h4>证据缺口</h4>
            <ul>
              <li v-for="gap in path.evidence_gaps" :key="gap">{{ gap }}</li>
            </ul>
          </div>
          <div v-if="path.research_inspiration.review_questions.length" class="path-section">
            <h4>建议研发评审问题</h4>
            <ul>
              <li v-for="question in path.research_inspiration.review_questions" :key="question">
                {{ question }}
              </li>
            </ul>
          </div>
          <footer class="path-card-footer">
            <a-button size="small" @click="viewPathInGraph(path)">在图中查看</a-button>
          </footer>
        </article>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onUnmounted, reactive } from 'vue'
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
  ScanText,
  Waypoints
} from '@lucide/vue'
import GraphCanvas from '@/components/GraphCanvas.vue'
import GraphDetailPanel from '@/components/GraphDetailPanel.vue'
import ResourceEmptyState from '@/components/shared/ResourceEmptyState.vue'
import { getKbTypeLabel } from '@/utils/kb_utils'
import { KNOWLEDGE_GRAPH_LAYOUTS } from '@/utils/knowledgeGraphLayout'
import { unifiedApi } from '@/apis/graph_api'
import { graphBuildApi } from '@/apis/knowledge_api'
import { Modal, message } from 'ant-design-vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import { useGraph } from '@/composables/useGraph'

const GRAPH_BUILD_TASK_TYPE = 'knowledge_graph_index'
const MILVUS_KB_TYPE = 'milvus'
const GRAPH_SUPPORTED_KB_TYPES = new Set([MILVUS_KB_TYPE])

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
const subgraphParams = reactive({
  maxNodes: 100,
  maxDepth: 2,
  excludeChunk: true
})
const searchInput = ref('')
const graphBuildStatus = ref(null)
const graphBuildLoading = ref(false)
const showGraphConfig = ref(false)
const showFailedChunkSamples = ref(false)
const failedChunkSamplesLoading = ref(false)
const failedChunkSamples = ref([])
const activeFailedChunkKey = ref('')
const showPathDiscovery = ref(false)
const pathDiscoveryLoading = ref(false)
const pathDiscoverySearched = ref(false)
const pathDiscoveryResult = reactive({ paths: [], summary: {} })
const pathQuery = reactive({
  query: '',
  mode: 'auto',
  max_hops: 5,
  include_combinations: true
})
let buildStatusPollTimer = null

const extractorTypeOptions = [
  {
    value: 'llm',
    label: 'LLM',
    description: '使用大模型按 Schema 抽取实体和关系',
    helper: '当前唯一支持的图谱抽取方式',
    icon: BrainCircuit,
    disabled: false
  },
  {
    value: 'more',
    label: '更多',
    description: '更多抽取方式正在拓展中',
    helper: '拓展中',
    icon: ScanText,
    disabled: true
  }
]

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

const toggleBuildPanel = () => {
  showBuildPanel.value = !showBuildPanel.value
  showSettings.value = false
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
const DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 60
const DEFAULT_CONTEXT_WINDOW_SIZE = 1
const DEFAULT_CONTEXT_MAX_CHARS = 4000
const DEFAULT_ENABLE_HYPOTHESIS_EXTRACTION = true
const DEFAULT_MAX_HYPOTHESES_PER_CHUNK = 2
const graphConfigForm = reactive({
  extractor_type: 'llm',
  model_spec: '',
  schema: '',
  concurrency_count: 50,
  timeout_seconds: DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
  context_window_size: DEFAULT_CONTEXT_WINDOW_SIZE,
  context_max_chars: DEFAULT_CONTEXT_MAX_CHARS,
  enable_hypothesis_extraction: DEFAULT_ENABLE_HYPOTHESIS_EXTRACTION,
  max_hypotheses_per_chunk: DEFAULT_MAX_HYPOTHESES_PER_CHUNK,
  model_params_text: ''
})

const graph = reactive(useGraph(graphRef))
const graphLoaded = ref(false)

// 计算属性：是否支持知识图谱
const isGraphSupported = computed(() => GRAPH_SUPPORTED_KB_TYPES.has(kbType.value?.toLowerCase()))
const hasGraphNodes = computed(() => graph.graphData.nodes.length > 0)
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
const graphDataEmptyTitle = computed(() =>
  searchInput.value.trim() ? '未找到匹配实体' : '暂无知识图谱'
)
const graphDataEmptyDescription = computed(() => {
  if (searchInput.value.trim()) return '换个关键词或调整图谱设置后再搜索。'
  if (isBuildActive.value) return '图谱索引正在运行，完成后会展示实体与关系。'
  if (hasPendingGraphChunks.value) return '当前还有待索引 Chunk，完成索引后会展示实体与关系。'
  return '当前知识库还没有可展示的实体与关系。'
})

let pendingLoadTimer = null
let graphStatusRequestSeq = 0
let graphLoadRequestSeq = 0
let pathDiscoveryRequestSeq = 0

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
  graphConfigForm.extractor_type = 'llm'
  graphConfigForm.model_spec = options.model_spec || configStore.config?.default_model || ''
  graphConfigForm.schema = options.schema || ''
  graphConfigForm.concurrency_count = Number(options.concurrency_count || 50)
  graphConfigForm.timeout_seconds = Number(
    options.timeout_seconds || DEFAULT_EXTRACTION_TIMEOUT_SECONDS
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
  graphConfigForm.model_params_text = options.model_params
    ? JSON.stringify(options.model_params)
    : ''
}

const openGraphConfig = () => {
  fillGraphConfigForm()
  showGraphConfig.value = true
}

const selectExtractorType = (option) => {
  if (isEditingGraphConfig.value || option.disabled) return
  graphConfigForm.extractor_type = option.value
}

const buildExtractorOptions = () => {
  return {
    model_spec: graphConfigForm.model_spec,
    schema: graphConfigForm.schema.trim(),
    concurrency_count: graphConfigForm.concurrency_count || 50,
    timeout_seconds: graphConfigForm.timeout_seconds || DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
    context_window_size: graphConfigForm.context_window_size ?? DEFAULT_CONTEXT_WINDOW_SIZE,
    context_max_chars: graphConfigForm.context_max_chars || DEFAULT_CONTEXT_MAX_CHARS,
    enable_hypothesis_extraction: graphConfigForm.enable_hypothesis_extraction,
    max_hypotheses_per_chunk: graphConfigForm.max_hypotheses_per_chunk,
    model_params: parseModelParams()
  }
}

const configureGraphBuild = async () => {
  try {
    document.activeElement?.blur()
    await nextTick()
    await graphBuildApi.configure(kbId.value, {
      extractor_type: 'llm',
      extractor_options: buildExtractorOptions()
    })
    message.success(isEditingGraphConfig.value ? '图谱抽取配置已更新' : '图谱抽取配置已保存')
    showGraphConfig.value = false
    await loadGraphBuildStatus()
  } catch (e) {
    console.error('Failed to configure graph build:', e)
    message.error(getErrorDetail(e, '配置图谱抽取失败'))
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

const confirmResetGraph = () => {
  Modal.confirm({
    title: '清空并重建图谱',
    content: '将删除该知识库在 Neo4j 中的图谱，重置 Chunk 图谱状态，并清空抽取结果与配置。',
    okText: '确认重置',
    cancelText: '取消',
    onOk: resetGraphBuild
  })
}

const resetGraphBuild = async () => {
  try {
    await graphBuildApi.reset(kbId.value, {
      clear_extraction_result: true,
      clear_config: true
    })
    message.success('图谱构建状态已重置')
    graphLoaded.value = false
    graph.clearGraph()
    await loadGraphBuildStatus()
  } catch (e) {
    console.error('Failed to reset graph build:', e)
    message.error(getErrorDetail(e, '重置图谱构建状态失败'))
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
  showPathDiscovery.value = true
}

const runPathDiscovery = async () => {
  const query = pathQuery.query.trim()
  if (!query) {
    message.warning('请输入研发需求或实体')
    return
  }
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
      max_paths: 10,
      include_combinations: pathQuery.include_combinations
    })
    if (requestSeq === pathDiscoveryRequestSeq && currentDatabaseId === kbId.value) {
      pathDiscoveryResult.paths = response.data?.paths || []
      pathDiscoveryResult.summary = response.data?.summary || {}
    }
  } catch (e) {
    console.error('Failed to discover graph paths:', e)
    if (requestSeq === pathDiscoveryRequestSeq) {
      pathDiscoveryResult.paths = []
      pathDiscoveryResult.summary = {}
      message.error(getErrorDetail(e, '链路发现失败'))
    }
  } finally {
    if (requestSeq === pathDiscoveryRequestSeq) {
      pathDiscoveryLoading.value = false
    }
  }
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
        loadGraphBuildStatus()
      }
      scheduleGraphLoad()
    }
  },
  { immediate: true }
)

watch(kbId, () => {
  graphStatusRequestSeq += 1
  graphLoadRequestSeq += 1
  pathDiscoveryRequestSeq += 1
  pathDiscoveryLoading.value = false
  graphLoaded.value = false
  graph.clearGraph()
  graphBuildStatus.value = null
  pathDiscoveryResult.paths = []
  pathDiscoveryResult.summary = {}
  pathDiscoverySearched.value = false
  showPathDiscovery.value = false
  showFailedChunkSamples.value = false
  failedChunkSamples.value = []
  if (isMilvus.value) {
    loadGraphBuildStatus()
  }
  if (isGraphSupported.value) {
    scheduleGraphLoad(300)
  }
})

watch(isGraphSupported, (supported) => {
  if (!supported) {
    graphLoaded.value = false
    graph.clearGraph()
    graphBuildStatus.value = null
    return
  }
  if (isMilvus.value) {
    loadGraphBuildStatus()
  }
  scheduleGraphLoad(200)
})

onUnmounted(() => {
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

  .graph-search-input {
    flex: 1;
    width: 0;
    min-width: 0;
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
  top: 60px;
  right: 10px;
  width: 300px;
  max-width: calc(100% - 20px);
  max-height: calc(100% - 60px);
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

.path-query-form {
  .path-query-options {
    display: grid;
    grid-template-columns: minmax(220px, 1fr) 120px 140px auto;
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

.path-result-summary {
  margin-bottom: 10px;
  color: var(--gray-600);
  font-size: 12px;
}

.path-card {
  padding: 14px;
  margin-bottom: 12px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
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

.path-card-metrics,
.path-evidence-summary {
  color: var(--gray-600);
  font-size: 12px;
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
  .path-query-form .path-query-options {
    grid-template-columns: 1fr 1fr;
  }

  .path-card-header {
    align-items: flex-start;
    flex-direction: column;
  }
}

.config-warning {
  margin-bottom: 16px;
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
