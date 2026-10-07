import { computed, onMounted, unref, watch } from 'vue'
import { useConfigStore } from '@/stores/config'

export function useEquipmentModelPrefill(target, field = 'model_spec') {
  const configStore = useConfigStore()
  let seeded = false

  const apply = () => {
    const obj = unref(target)
    if (!obj || seeded) return
    const current = String(obj[field] || '').trim()
    if (current) {
      seeded = true
      return
    }
    const spec = String(configStore.config?.default_model || '').trim()
    if (!spec) return
    obj[field] = spec
    seeded = true
  }

  watch(() => [unref(target)?.[field], configStore.config?.default_model], apply, { immediate: true })

  onMounted(() => {
    configStore.refreshConfig().catch(() => {})
  })

  return {
    configStore,
    hasDefaultModel: computed(() => Boolean(String(configStore.config?.default_model || '').trim()))
  }
}
