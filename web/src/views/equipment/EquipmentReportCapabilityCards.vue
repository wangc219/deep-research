<script setup>
import { useRouter } from 'vue-router'
import { Eye } from '@lucide/vue'
import CapabilityPortraitCard from '@/components/equipment/CapabilityPortraitCard.vue'
import {
  capabilityCardKey,
  capabilityPortraitModules,
  capabilityTitle
} from '@/utils/equipmentCapabilities'
import { publishDeepLaunchCard } from '@/utils/equipmentDeepLaunch.js'

const props = defineProps({
  rows: {
    type: Array,
    default: () => []
  },
  runId: {
    type: String,
    default: ''
  },
  showToolbar: {
    type: Boolean,
    default: true
  }
})

const router = useRouter()

const openCapabilities = (item = null) => {
  const cardKey = item ? capabilityCardKey(item) : ''
  router.push({
    path: '/equipment/capabilities',
    query: {
      ...(props.runId ? { run: props.runId } : {}),
      ...(cardKey ? { cap: cardKey } : {})
    }
  })
}

const openDeepResearch = (item, section = null) => {
  const capabilityKey =
    item.card_binding_id ||
    item.card_key ||
    item.capability_id ||
    item.hypothesis_id ||
    item.id ||
    capabilityTitle(item)
  publishDeepLaunchCard({
    card_key: capabilityKey,
    run_id: item.run_id || props.runId,
    capability_id: item.capability_id || '',
    name: capabilityTitle(item),
    sections: capabilityPortraitModules(item),
    section_label: section?.label || '',
    section_text: section?.text || ''
  })
  router.push({
    path: '/equipment/deep-thinking',
    query: {
      ...(props.runId ? { run: props.runId } : {}),
      ...(capabilityKey ? { cap: String(capabilityKey) } : {}),
      ...(section?.label ? { section: section.label } : {})
    }
  })
}
</script>

<template>
  <section class="capability-view report-early-capability-view">
    <div v-if="showToolbar" class="capability-toolbar">
      <div>
        <b>能力画像成果</b>
        <small>报告正文落盘前，先展示已经持久化的五模块能力画像</small>
      </div>
      <div>
        <button type="button" @click="openCapabilities()">
          <Eye :size="14" />查看完整能力画像
        </button>
      </div>
    </div>

    <div class="report-capability-card-list">
      <CapabilityPortraitCard
        v-for="item in rows"
        :key="capabilityCardKey(item)"
        :item="item"
        surface="report"
        @deep="openDeepResearch"
        @view="openCapabilities"
      />
    </div>
  </section>
</template>

<style scoped>
.report-early-capability-view {
  min-width: 0;
  padding: 16px;
}

.report-capability-card-list {
  display: grid;
  gap: 14px;
}

@media (max-width: 700px) {
  .report-early-capability-view {
    padding: 12px;
  }
}
</style>
