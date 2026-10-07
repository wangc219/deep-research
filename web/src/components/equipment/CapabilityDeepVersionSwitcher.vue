<script setup>
import { ref } from 'vue'
import { ChevronDown, Eye, GitCompare } from '@lucide/vue'
import { capabilityTitle, capabilityVersionMeta } from '@/utils/equipmentCapabilities'

defineProps({
  versions: { type: Array, default: () => [] }
})

defineEmits(['select'])

const open = ref(false)
</script>

<template>
  <section v-if="versions.length" class="capability-deep-version-switcher">
    <button
      type="button"
      class="capability-deep-version-toggle"
      :aria-expanded="open"
      @click="open = !open"
    >
      <span><GitCompare :size="14" /><b>深研卡片</b><em>{{ versions.length }}</em></span>
      <small>正式原卡保持不变，展开查看由深研对话新增的独立版本</small>
      <ChevronDown :size="15" :class="{ rotated: open }" />
    </button>
    <div v-if="open" class="capability-deep-version-list">
      <article v-for="item in versions" :key="item.version_id || item.id">
        <span>
          <b>{{ capabilityTitle(item) }}</b>
          <small>
            v{{ capabilityVersionMeta(item).version || '?' }} ·
            {{ capabilityVersionMeta(item).statusLabel }}
            <template v-if="item.created_at"> · {{ new Date(item.created_at).toLocaleString('zh-CN', { hour12: false }) }}</template>
          </small>
        </span>
        <button type="button" @click="$emit('select', item)"><Eye :size="13" />查看深研卡片</button>
      </article>
    </div>
  </section>
</template>

<style scoped>
.capability-deep-version-switcher {
  display: grid;
  margin: 0 20px 16px;
  border: 1px solid #cde5d7;
  border-radius: 9px;
  background: #f7fcf9;
  overflow: hidden;
}

.capability-deep-version-toggle {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 10px 12px;
  border: 0;
  background: transparent;
  color: #2f8060;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.capability-deep-version-toggle > span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.capability-deep-version-toggle b { font-size: 11px; }
.capability-deep-version-toggle em {
  display: inline-grid;
  place-items: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: #dff3e8;
  font-size: 9px;
  font-style: normal;
  font-weight: 800;
}
.capability-deep-version-toggle small { color: #6f8a7c; font-size: 10px; }
.capability-deep-version-toggle svg { transition: transform .18s ease; }
.capability-deep-version-toggle svg.rotated { transform: rotate(180deg); }

.capability-deep-version-list {
  display: grid;
  gap: 7px;
  padding: 0 10px 10px;
}

.capability-deep-version-list article {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 10px;
  border: 1px solid #dbece2;
  border-radius: 7px;
  background: #fff;
}

.capability-deep-version-list article > span { display: grid; gap: 3px; min-width: 0; }
.capability-deep-version-list article b { color: #315f49; font-size: 11px; }
.capability-deep-version-list article small { color: #7b9186; font-size: 9px; }
.capability-deep-version-list article button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  border: 1px solid #b9d8cc;
  border-radius: 5px;
  background: #f2fbf6;
  color: #2f8060;
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}

@media (max-width: 700px) {
  .capability-deep-version-switcher { margin: 0 12px 14px; }
  .capability-deep-version-toggle { grid-template-columns: minmax(0, 1fr) auto; }
  .capability-deep-version-toggle small { grid-column: 1 / -1; }
  .capability-deep-version-list article { align-items: flex-start; flex-direction: column; }
}
</style>
