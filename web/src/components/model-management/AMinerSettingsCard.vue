<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { BookOpen } from '@lucide/vue'
import { aminerApi } from '@/apis/system_api'
import { buildAMinerConfigPatch, createAMinerDraft } from '@/utils/aminer'

const option = ref(null)
const draft = reactive(createAMinerDraft())
const loading = ref(true)
const busy = ref('')
const error = ref('')
const notice = ref('')
const testResult = ref(null)
const hasSavedKey = computed(() => !!option.value?.sensitive_configured?.api_key)
const keyPreview = computed(() => option.value?.sensitive_state?.api_key?.preview || '未配置')
const configured = computed(() => !!option.value?.value?.user_id && hasSavedKey.value)
const status = computed(() => {
  if (testResult.value) return testResult.value.status
  if (!configured.value) return 'not_configured'
  return option.value?.value?.enabled ? 'untested' : 'disabled'
})
const statusLabels = {
  not_configured: '未配置',
  disabled: '已停用',
  untested: '已配置，待测试',
  ok: '连接正常',
  auth_failed: '鉴权失败',
  rate_limited: '调用受限',
  unavailable: '服务暂不可用',
  invalid_request: '测试未通过'
}
const canEnable = computed(
  () => !!draft.user_id.trim() && (!!draft.api_key.trim() || hasSavedKey.value)
)
const editable = computed(() => !loading.value && !busy.value && !!option.value)
const applyOption = (value) => {
  option.value = value
  Object.assign(draft, createAMinerDraft(value))
  testResult.value = null
}

watch(
  draft,
  () => {
    testResult.value = null
    notice.value = ''
  },
  { flush: 'sync' }
)

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const result = await aminerApi.getConfig()
    if (!result) throw new Error('AMiner 配置尚未初始化，请完成服务升级')
    applyOption(result)
  } catch (err) {
    error.value = err.message || '加载 AMiner 配置失败'
  } finally {
    loading.value = false
  }
}

const save = async () => {
  busy.value = 'save'
  error.value = ''
  notice.value = ''
  try {
    const result = await aminerApi.saveConfig(buildAMinerConfigPatch(draft))
    applyOption(result.option)
    notice.value = 'AMiner 配置已保存，后续检索使用新配置'
  } catch (err) {
    error.value = err.message || '保存 AMiner 配置失败'
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
    testResult.value = await aminerApi.testConnection({
      user_id: draft.user_id.trim(),
      api_key: draft.api_key.trim() || undefined
    })
  } catch (err) {
    error.value = err.message || '连接测试失败'
  } finally {
    busy.value = ''
  }
}

const clearKey = async () => {
  busy.value = 'clear'
  error.value = ''
  try {
    const result = await aminerApi.saveConfig({ api_key: null, enabled: false })
    applyOption(result.option)
    notice.value = '密钥已清除，AMiner 学术检索已停用'
  } catch (err) {
    error.value = err.message || '清除密钥失败'
  } finally {
    busy.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="aminer-card" aria-labelledby="aminer-heading">
    <header>
      <div class="title">
        <BookOpen :size="20" />
        <div>
          <h2 id="aminer-heading">AMiner 学术检索</h2>
          <p>为智能对话和深研对话补充论文、摘要与参考文献。</p>
        </div>
      </div>
      <span class="status" :class="status" role="status">{{
        loading ? '加载中' : statusLabels[status] || '待检查'
      }}</span>
    </header>
    <p v-if="loading" class="muted">正在读取学术检索配置…</p>
    <form v-else-if="option" @submit.prevent="save">
      <fieldset :disabled="!editable">
        <label class="enable"
          ><input
            v-model="draft.enabled"
            type="checkbox"
            :disabled="!draft.enabled && !canEnable"
          />启用 AMiner 学术检索<span>科研问题自动调用，父子智能体共享单轮预算</span></label
        >
        <div class="fields">
          <label for="aminer-user-id"
            >AMiner 用户 ID<input
              id="aminer-user-id"
              v-model="draft.user_id"
              type="text"
              maxlength="128"
              autocomplete="off"
              placeholder="在 AMiner 控制台账号资料中查看"
          /></label>
          <label for="aminer-api-key"
            >API Key<input
              id="aminer-api-key"
              v-model="draft.api_key"
              type="password"
              autocomplete="new-password"
              placeholder="填写或替换密钥；留空保留已保存密钥"
            /><small>已保存：{{ keyPreview }}。密钥不会回显。</small></label
          >
        </div>
        <details class="advanced">
          <summary>高级设置：单轮预算与调用限额</summary>
          <div class="budget-grid">
            <div v-for="(prefix, index) in ['chat', 'deep']" :key="prefix" class="budget-column">
              <h3>{{ index ? '深研对话' : '智能对话' }}</h3>
              <label :for="`aminer-${prefix}-budget`"
                >费用预算（元）<input
                  :id="`aminer-${prefix}-budget`"
                  v-model.number="draft[`${prefix}_budget_yuan`]"
                  type="number"
                  min="0"
                  :max="index ? 50 : 10"
                  step="0.01"
                  required
              /></label>
              <label :for="`aminer-${prefix}-search`"
                >Pro 搜索次数<input
                  :id="`aminer-${prefix}-search`"
                  v-model.number="draft[`${prefix}_search_limit`]"
                  type="number"
                  min="0"
                  :max="index ? 50 : 20"
                  step="1"
                  required
              /></label>
              <label :for="`aminer-${prefix}-detail`"
                >论文详情次数<input
                  :id="`aminer-${prefix}-detail`"
                  v-model.number="draft[`${prefix}_detail_limit`]"
                  type="number"
                  min="0"
                  :max="index ? 100 : 50"
                  step="1"
                  required
              /></label>
              <label :for="`aminer-${prefix}-reference`"
                >参考文献查询次数<input
                  :id="`aminer-${prefix}-reference`"
                  v-model.number="draft[`${prefix}_reference_limit`]"
                  type="number"
                  min="0"
                  :max="index ? 20 : 10"
                  step="1"
                  required
              /></label>
            </div>
          </div>
          <p class="muted">
            按当前接口单价预占预算，重试计入限额，缓存命中不占付费预算。接口实际费用以 AMiner
            账单为准。
          </p>
        </details>
        <p class="muted">
          连接测试使用免费标题搜索。仅发送公开科研检索词；题录和摘要不等于论文全文。
        </p>
        <div class="actions">
          <button class="primary" type="submit" :disabled="draft.enabled && !canEnable">
            {{ busy === 'save' ? '保存中…' : '保存配置' }}
          </button>
          <button type="button" :disabled="!canEnable" @click="testConnection">
            {{ busy === 'test' ? '测试中…' : '测试连接' }}
          </button>
          <button v-if="hasSavedKey" class="clear" type="button" @click="clearKey">
            {{ busy === 'clear' ? '清除中…' : '清除已保存密钥并停用' }}
          </button>
          <a
            href="https://www.aminer.cn/open/board?tab=doc"
            target="_blank"
            rel="noopener noreferrer"
            >使用说明</a
          >
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
    </p>
    <p v-if="notice" class="feedback success" role="status">{{ notice }}</p>
    <p v-if="error" class="feedback error" role="alert">
      {{ error }} <button v-if="!option && !loading" type="button" @click="load">重新加载</button>
    </p>
  </section>
</template>

<style scoped lang="less">
.aminer-card {
  margin: 16px 24px;
  padding: 20px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
  color: var(--gray-900);
}
header,
.title,
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
header {
  justify-content: space-between;
  align-items: flex-start;
}
.title {
  align-items: flex-start;
}
h2 {
  margin: 0 0 6px;
  font-size: 16px;
}
h3 {
  margin: 0 0 12px;
  font-size: 14px;
}
p {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--gray-600);
}
.status {
  flex-shrink: 0;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 12px;
  background: var(--gray-100);
}
.status.ok,
.success {
  color: var(--color-success-600, #16804a);
}
.status.auth_failed,
.error {
  color: var(--color-error-600, #c53030);
}
fieldset {
  border: 0;
  padding: 0;
  margin: 18px 0 0;
  min-width: 0;
}
.enable {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  flex-wrap: wrap;
}
.enable span {
  color: var(--gray-600);
  font-size: 12px;
}
.fields,
.budget-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  margin: 18px 0;
}
.fields label,
.budget-column label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
}
input:not([type='checkbox']) {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--gray-300);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-900);
  padding: 9px 10px;
  font-size: 13px;
}
input:focus-visible,
button:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 2px;
}
small,
.muted {
  color: var(--gray-600);
  font-size: 12px;
}
.advanced {
  margin: 10px 0 18px;
  padding: 12px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
}
summary {
  font-size: 13px;
  cursor: pointer;
}
.budget-column {
  display: grid;
  gap: 12px;
}
.actions {
  flex-wrap: wrap;
  margin-top: 16px;
}
button {
  padding: 8px 14px;
  border: 1px solid var(--gray-300);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-800);
  cursor: pointer;
  font-size: 13px;
}
button.primary {
  background: var(--main-color);
  border-color: var(--main-color);
  color: white;
}
button:disabled,
fieldset:disabled button {
  cursor: default;
  opacity: 0.55;
}
button.clear {
  color: var(--gray-600);
}
a {
  color: var(--main-color);
  font-size: 12px;
}
.feedback {
  margin-top: 14px;
}
@media (max-width: 680px) {
  .aminer-card {
    margin: 12px;
    padding: 16px;
  }
  .fields,
  .budget-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  header {
    flex-wrap: wrap;
  }
}
</style>
