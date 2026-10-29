<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ChevronDown, Search } from '@lucide/vue'
import { webSearchApi } from '@/apis/system_api'

const option = ref(null)
const draft = reactive({})
const loading = ref(true)
const busy = ref('')
const error = ref('')
const notice = ref('')
const testResult = ref(null)

const engineFields = computed(() =>
  (option.value?.params?.fields || []).filter((field) => field.type === 'list[str]')
)
const integerFields = computed(() =>
  (option.value?.params?.fields || []).filter((field) => field.type === 'integer')
)
const status = computed(() => {
  if (testResult.value) return testResult.value.status
  if (!draft.adaptive_fusion_enabled) return 'disabled'
  return draft.searxng_enabled ? 'untested' : 'disabled'
})
const statusLabels = {
  disabled: '已停用',
  untested: '已启用，待测试',
  ok: '连接正常',
  degraded: '容器正常，外网检索异常',
  unavailable: '连接失败',
  not_configured: '未配置'
}

const applyOption = (value) => {
  option.value = value
  for (const field of value?.params?.fields || []) {
    const current = value?.value?.[field.key]
    draft[field.key] = current ?? structuredClone(field.default)
  }
  testResult.value = null
}

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const result = await webSearchApi.getConfig()
    if (!result) throw new Error('融合检索配置尚未初始化，请完成服务升级')
    applyOption(result)
  } catch (err) {
    error.value = err.message || '加载融合检索配置失败'
  } finally {
    loading.value = false
  }
}

const save = async () => {
  busy.value = 'save'
  error.value = ''
  notice.value = ''
  try {
    const payload = Object.fromEntries(
      (option.value?.params?.fields || []).map((field) => [field.key, draft[field.key]])
    )
    const result = await webSearchApi.saveConfig(payload)
    applyOption(result.option)
    notice.value = '融合检索配置已保存，并已热更新到 API 与调研 worker'
  } catch (err) {
    error.value = err.message || '保存融合检索配置失败'
  } finally {
    busy.value = ''
  }
}

const testConnection = async () => {
  busy.value = 'test'
  error.value = ''
  notice.value = ''
  testResult.value = null
  try {
    testResult.value = await webSearchApi.testConnection()
  } catch (err) {
    error.value = err.message || 'SearXNG 连接测试失败'
  } finally {
    busy.value = ''
  }
}

onMounted(load)
</script>

<template>
  <details class="web-search-card" aria-labelledby="web-search-heading">
    <summary class="card-summary">
      <span class="title">
        <Search :size="20" />
        <span>
          <span id="web-search-heading" class="card-heading" role="heading" aria-level="2"
            >Open WebSearch × SearXNG</span
          >
          <span class="card-description"
            >网页查询自适应融合；调研探索员首轮再与 AMiner 三渠道并发发现、去重和排序。</span
          >
        </span>
      </span>
      <span class="card-meta">
        <span class="status" :class="status" role="status">
          {{ loading ? '加载中' : statusLabels[status] || '待检查' }}
        </span>
        <ChevronDown class="card-chevron" :size="18" aria-hidden="true" />
      </span>
    </summary>

    <div class="card-content">
      <p v-if="loading" class="muted">正在读取融合检索配置…</p>
      <form v-else-if="option" @submit.prevent="save">
        <fieldset :disabled="Boolean(busy)">
          <div class="switches">
            <label>
              <input v-model="draft.adaptive_fusion_enabled" type="checkbox" />
              默认启用自适应融合
              <small>关闭后立即恢复现有 Open WebSearch 路径。</small>
            </label>
            <label>
              <input v-model="draft.searxng_enabled" type="checkbox" />
              启用内部 SearXNG
              <small>失败时保留 Open WebSearch 已完成结果。</small>
            </label>
          </div>

          <div class="engine-grid">
            <label v-for="field in engineFields" :key="field.key" :for="`web-search-${field.key}`">
              {{ field.label }}
              <select :id="`web-search-${field.key}`" v-model="draft[field.key]" multiple>
                <option v-for="engine in field.options" :key="engine" :value="engine">
                  {{ engine }}
                </option>
              </select>
            </label>
          </div>

          <details class="advanced">
            <summary>高级设置：质量阈值与超时</summary>
            <div class="integer-grid">
              <label
                v-for="field in integerFields"
                :key="field.key"
                :for="`web-search-${field.key}`"
              >
                {{ field.label }}
                <input
                  :id="`web-search-${field.key}`"
                  v-model.number="draft[field.key]"
                  type="number"
                  :min="field.minimum"
                  :max="field.maximum"
                  step="1"
                  required
                />
              </label>
            </div>
          </details>

          <p class="muted">
            中文、学术、新闻和定向查询会直接双路检索；普通外文查询仅在覆盖不足或超时后补查。
            调研探索员首轮会覆盖普通外文查询的自适应策略，强制 Open WebSearch、SearXNG 与 AMiner
            并发。 内部地址与密钥由部署配置管理，不在页面回显。
          </p>
          <div class="actions">
            <button class="primary" type="submit">
              {{ busy === 'save' ? '保存中…' : '保存配置' }}
            </button>
            <button type="button" @click="testConnection">
              {{ busy === 'test' ? '测试中…' : '测试已保存配置' }}
            </button>
          </div>
        </fieldset>
      </form>

      <p
        v-if="testResult"
        class="feedback"
        :class="testResult.status === 'ok' ? 'success' : 'error'"
        role="status"
      >
        {{ testResult.message }}
        <span v-if="testResult.latency_ms">（{{ testResult.latency_ms }} ms）</span>
      </p>
      <p v-if="notice" class="feedback success" role="status">{{ notice }}</p>
      <p v-if="error" class="feedback error" role="alert">
        {{ error }}
        <button v-if="!option && !loading" type="button" @click="load">重新加载</button>
      </p>
    </div>
  </details>
</template>

<style scoped lang="less">
.web-search-card {
  margin: 16px 24px;
  padding: 20px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
  color: var(--gray-900);
}
.card-summary,
.title,
.card-meta,
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.card-summary {
  justify-content: space-between;
  align-items: flex-start;
  cursor: pointer;
  list-style: none;
}
.card-summary::-webkit-details-marker {
  display: none;
}
.title {
  align-items: flex-start;
}
.card-heading {
  display: block;
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 600;
}
.card-description {
  display: block;
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.55;
}
.card-meta {
  flex: none;
}
.card-chevron {
  color: var(--gray-500);
  transition: transform 160ms ease;
}
.web-search-card[open] > .card-summary .card-chevron {
  transform: rotate(180deg);
}
.card-content {
  padding-top: 18px;
}
p,
small {
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.55;
}
p {
  margin: 0;
}
.status {
  flex: none;
  padding: 4px 10px;
  border-radius: 20px;
  background: var(--gray-100);
  font-size: 12px;
}
.status.ok,
.success {
  color: var(--color-success-600, #16804a);
}
.status.unavailable,
.status.degraded,
.error {
  color: var(--color-error-600, #c53030);
}
fieldset {
  margin: 18px 0 0;
  padding: 0;
  border: 0;
}
.switches,
.engine-grid,
.integer-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
}
.switches label {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: 4px 8px;
  font-size: 14px;
}
.switches small {
  grid-column: 2;
}
.engine-grid {
  margin-top: 18px;
}
.engine-grid label,
.integer-grid label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
select,
input[type='number'] {
  min-height: 36px;
  border: 1px solid var(--gray-250, var(--gray-200));
  border-radius: 8px;
  background: var(--gray-0);
  color: inherit;
}
select {
  min-height: 108px;
  padding: 6px;
}
input[type='number'] {
  padding: 0 10px;
}
.advanced {
  margin: 18px 0;
}
.advanced > summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}
.integer-grid {
  margin-top: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}
.actions {
  margin-top: 14px;
  flex-wrap: wrap;
}
button {
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--gray-250, var(--gray-200));
  border-radius: 8px;
  background: var(--gray-0);
  color: inherit;
  cursor: pointer;
}
button.primary {
  border-color: var(--gray-900);
  background: var(--gray-900);
  color: var(--gray-0);
}
.feedback {
  margin-top: 12px;
}
@media (max-width: 780px) {
  .web-search-card {
    margin: 12px;
  }
  .switches,
  .engine-grid,
  .integer-grid {
    grid-template-columns: 1fr;
  }
  .card-summary {
    gap: 8px;
    flex-wrap: wrap;
  }
  .card-meta {
    width: 100%;
    justify-content: flex-end;
  }
}
</style>
