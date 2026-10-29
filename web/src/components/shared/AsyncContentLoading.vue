<template>
  <div class="async-content-loading" role="status" aria-live="polite">
    <span class="async-content-spinner" aria-hidden="true"></span>
    <span>正在加载内容…</span>
  </div>
</template>
<style scoped>
.async-content-loading { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 96px; color: var(--gray-600); font-size: 13px; }
.async-content-spinner { width: 16px; height: 16px; border: 2px solid var(--gray-200); border-top-color: var(--main-500); border-radius: 50%; animation: async-content-spin 0.8s linear infinite; }
@keyframes async-content-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .async-content-spinner { animation: none; } }
</style>
