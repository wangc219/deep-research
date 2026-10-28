<script setup>
import { BrainCircuit, MessageCircle, Sparkles, ArrowUpRight } from '@lucide/vue'

defineProps({
  deep: { type: Boolean, default: false },
  prompts: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false }
})
defineEmits(['prompt'])
</script>

<template>
  <section
    class="conversation-welcome"
    :aria-label="deep ? '深研对话使用指引' : '智能对话使用指引'"
  >
    <nav class="conversation-modes" aria-label="选择对话方式">
      <router-link
        to="/agent"
        :aria-current="!deep ? 'page' : undefined"
        :class="{ active: !deep }"
      >
        <MessageCircle :size="15" />智能对话
      </router-link>
      <router-link
        to="/equipment/deep-thinking"
        :aria-current="deep ? 'page' : undefined"
        :class="{ active: deep }"
      >
        <BrainCircuit :size="15" />深研对话
      </router-link>
    </nav>
    <span class="welcome-icon" aria-hidden="true"><Sparkles :size="24" /></span>
    <h1>{{ deep ? '一个问题，开始深入研究' : '有什么想一起探索？' }}</h1>
    <p>
      {{
        deep
          ? '描述研究目标，助手将按需查找资料、交叉核验，逐步形成有依据的结论。'
          : '提问、梳理资料或比较方案，直接说出你的需求。'
      }}
    </p>
    <div
      v-if="prompts.length"
      class="welcome-prompts"
      :class="{ 'two-prompts': prompts.length === 2 }"
      :aria-label="deep ? '选择研究入口' : '试试这些问题'"
    >
      <button
        v-for="item in prompts"
        :key="item.title"
        type="button"
        :disabled="disabled"
        @click="$emit('prompt', item)"
      >
        <span
          ><b>{{ item.title }}</b
          ><small>{{ item.hint }}</small></span
        >
        <ArrowUpRight :size="15" aria-hidden="true" />
      </button>
    </div>
  </section>
</template>

<style scoped>
.conversation-welcome {
  width: min(720px, 100%);
  margin: 0 auto;
  text-align: center;
}
.conversation-modes {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 24px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-25);
}
.conversation-modes a {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 14px;
  border-radius: 8px;
  color: var(--gray-600);
  text-decoration: none;
  font-size: 13px;
}
.conversation-modes a.active {
  background: var(--gray-0);
  color: var(--main-color);
  box-shadow: 0 1px 4px var(--shadow-0);
  font-weight: 600;
}
.welcome-icon {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  margin: 0 auto 16px;
  border-radius: 16px;
  background: var(--main-50);
  color: var(--main-color);
}
h1 {
  margin: 0 0 10px;
  font-size: clamp(22px, 3vw, 30px);
  letter-spacing: -0.03em;
  color: var(--gray-900);
}
p {
  margin: 0 auto;
  max-width: 560px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--gray-600);
}
.welcome-prompts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 24px;
}
.welcome-prompts.two-prompts {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.welcome-prompts button {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: flex-start;
  min-width: 0;
  padding: 14px;
  text-align: left;
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  color: var(--gray-700);
  cursor: pointer;
}
.welcome-prompts button:hover {
  border-color: var(--main-color);
  background: var(--main-50);
}
.welcome-prompts button:disabled {
  opacity: 0.6;
  cursor: wait;
}
.welcome-prompts span {
  display: grid;
  gap: 6px;
}
.welcome-prompts b {
  font-size: 13px;
  font-weight: 600;
}
.welcome-prompts small {
  font-size: 12px;
  line-height: 1.5;
  color: var(--gray-500);
}
.welcome-prompts svg {
  flex-shrink: 0;
  color: var(--gray-500);
}
button:focus-visible,
a:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 3px;
}
@media (max-width: 640px) {
  .conversation-modes {
    margin-bottom: 18px;
  }
  .welcome-prompts {
    display: flex;
    gap: 8px;
    margin-top: 18px;
    overflow-x: auto;
    padding-bottom: 4px;
    scroll-snap-type: x proximity;
  }
  .welcome-prompts button {
    flex: 0 0 184px;
    padding: 11px 13px;
    scroll-snap-align: start;
  }
  .welcome-prompts span {
    gap: 3px;
  }
}
</style>
