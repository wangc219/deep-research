<script setup>
import { RouterLink } from 'vue-router'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'

defineProps({
  modelSpec: { type: String, default: '' },
  label: { type: String, default: '执行模型' },
  placeholder: { type: String, default: '使用系统默认聊天模型' },
  hasDefaultModel: { type: Boolean, default: true }
})

const emit = defineEmits(['update:modelSpec'])
</script>

<template>
  <a-form-item :label="label">
    <ModelSelectorComponent
      :model_spec="modelSpec"
      :placeholder="placeholder"
      size="middle"
      clearable
      @select-model="(spec) => emit('update:modelSpec', spec || '')"
    />
    <p class="muted">
      模型、接口地址和 API Key 在
      <RouterLink to="/models">模型设置</RouterLink>
      中配置，不再使用 env 文件。未选择时使用系统默认聊天模型。
    </p>
    <p v-if="!hasDefaultModel" class="muted">
      尚未指定系统默认模型，请先到
      <RouterLink to="/models">模型设置</RouterLink>
      启用聊天模型并指定默认模型。
    </p>
  </a-form-item>
</template>
