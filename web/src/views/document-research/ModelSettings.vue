<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
const props = defineProps({ api: { type: Object, required: true } })
const emit = defineEmits(['saved'])
const fields = reactive({ base_url: '', model: '', api_key: '', clear_api_key: false, reasoning_effort: '' })
const loading = ref(true)
const saving = ref(false)
const allowed = ref(false)
const hasKey = ref(false)
const error = ref('')
const message = ref('')
let alive = true
onUnmounted(() => { alive = false; fields.api_key = '' })
onMounted(async () => {
  try {
    const data = await props.api.modelSettings()
    if (!alive) return
    Object.assign(fields, { base_url: data.base_url, model: data.model, reasoning_effort: data.reasoning_effort })
    hasKey.value = data.has_api_key
    allowed.value = true
  } catch (cause) { if (alive) error.value = cause.status === 403 ? '此账号无模型配置权限，请联系独立服务管理员。' : cause.message }
  finally { if (alive) loading.value = false }
})
async function save() {
  if (saving.value) return
  saving.value = true; error.value = ''; message.value = ''
  try {
    const data = await props.api.saveModelSettings({ ...fields, api_key: fields.clear_api_key ? '' : fields.api_key })
    if (!alive) return
    fields.api_key = ''; fields.clear_api_key = false
    hasKey.value = data.has_api_key
    message.value = data.model_configured ? '模型配置已保存，可开始研究。' : '配置已保存；需要设置密钥后才能生成报告。'
    emit('saved')
  } catch (cause) { if (alive) error.value = cause.message }
  finally { if (alive) saving.value = false }
}
</script>
<template>
  <section class="model-settings" aria-label="文档研究模型设置">
    <h2>模型设置</h2>
    <p>支持 OpenAI 兼容接口；API 地址需包含服务的版本路径（例如 https://open.bigmodel.cn/api/paas/v4）。设置仅用于文档研究。</p>
    <p v-if="loading" role="status">正在读取配置…</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <form v-if="allowed" @submit.prevent="save">
      <label>API 地址<input v-model="fields.base_url" required maxlength="2000" :disabled="saving" placeholder="https://api.example.com/v1" /></label>
      <label>模型名称<input v-model="fields.model" required maxlength="200" :disabled="saving" placeholder="glm-4.7" /></label>
      <label>API 密钥<input v-model="fields.api_key" type="password" autocomplete="new-password" maxlength="4096" :disabled="saving || fields.clear_api_key" :placeholder="hasKey ? '已保存；留空保留现有密钥' : '请输入 API 密钥'" /></label>
      <label class="check"><input v-model="fields.clear_api_key" type="checkbox" :disabled="saving" />清除已保存密钥</label>
      <label>思考强度<select v-model="fields.reasoning_effort" :disabled="saving"><option value="">提供商默认</option><option value="low">low</option><option value="high">high</option><option value="max">max</option></select></label>
      <p>保存会更新此独立服务所有任务使用的模型；不会发送测试请求。密钥不回显，也不保存到浏览器存储。</p>
      <button type="submit" :disabled="saving">{{ saving ? '正在保存…' : '保存模型设置' }}</button>
      <p v-if="message" role="status">{{ message }}</p>
    </form>
  </section>
</template>
<style scoped>
.model-settings { margin-bottom: 24px; padding: 24px; background: var(--gray-0); border: 1px solid var(--gray-200); border-radius: 14px; }
h2 { font-size: 18px; } p { color: var(--gray-600); } label { display: block; margin: 12px 0; } input:not([type='checkbox']), select { display: block; width: 100%; padding: 10px; margin-top: 5px; border: 1px solid var(--gray-300); border-radius: 8px; background: var(--gray-0); color: var(--gray-900); } .check { display: flex; gap: 8px; } button { padding: 10px 16px; background: var(--main-color); color: white; border: 0; border-radius: 8px; cursor: pointer; } button:disabled { opacity: .5; } [role='alert'] { color: var(--color-error-700); }
</style>
