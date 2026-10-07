<script setup>
defineProps({
  variant: { type: String, default: 'list' }
})
</script>

<template>
  <div class="ews" role="status" aria-live="polite" aria-label="工作台加载中">
    <div class="ews-head">
      <span class="ews-line ews-line-eyebrow" />
      <span class="ews-line ews-line-title" />
      <span class="ews-line ews-line-lead" />
    </div>

    <div class="ews-nav">
      <span class="ews-pill" />
      <span class="ews-pill ews-pill-wide" />
      <span class="ews-pill" />
    </div>

    <div v-if="variant === 'split'" class="ews-split">
      <div class="ews-card ews-rail">
        <span v-for="index in 6" :key="index" class="ews-row" />
      </div>
      <div class="ews-card ews-main">
        <span class="ews-line ews-line-title" />
        <span v-for="index in 8" :key="index" class="ews-row" />
      </div>
    </div>
    <div v-else class="ews-grid">
      <div v-for="index in 6" :key="index" class="ews-card ews-tile">
        <span class="ews-line ews-line-lead" />
        <span class="ews-row" />
        <span class="ews-row ews-row-short" />
      </div>
    </div>

    <span class="ews-sr">正在加载装备研究工作台…</span>
  </div>
</template>

<style scoped>
.ews {
  display: grid;
  gap: 18px;
  padding: 28px 32px 40px;
}

.ews-head {
  display: grid;
  gap: 10px;
  max-width: 620px;
}

.ews-nav {
  display: flex;
  gap: 8px;
}

.ews-split {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.ews-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}

.ews-card {
  display: grid;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--gray-100, #e7eaf2);
  border-radius: 12px;
  background: var(--gray-0, #fff);
}

.ews-rail {
  gap: 14px;
}

.ews-main {
  min-height: 420px;
}

.ews-tile {
  min-height: 132px;
}

.ews-line,
.ews-row,
.ews-pill {
  display: block;
  border-radius: 6px;
  background: linear-gradient(
    100deg,
    var(--gray-75, #eef0f6) 28%,
    var(--gray-50, #f6f7fb) 46%,
    var(--gray-75, #eef0f6) 64%
  );
  background-size: 220% 100%;
  animation: ews-shimmer 1.35s ease-in-out infinite;
}

.ews-line-eyebrow {
  width: 92px;
  height: 10px;
}

.ews-line-title {
  width: 280px;
  height: 22px;
  border-radius: 8px;
}

.ews-line-lead {
  width: 100%;
  max-width: 460px;
  height: 12px;
}

.ews-row {
  width: 100%;
  height: 14px;
}

.ews-row-short {
  width: 62%;
}

.ews-pill {
  width: 96px;
  height: 34px;
  border-radius: 9px;
}

.ews-pill-wide {
  width: 210px;
}

.ews-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

@keyframes ews-shimmer {
  from {
    background-position: 140% 0;
  }
  to {
    background-position: -40% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ews-line,
  .ews-row,
  .ews-pill {
    animation: none;
  }
}

@media (max-width: 900px) {
  .ews {
    padding: 18px 16px 28px;
  }

  .ews-split {
    grid-template-columns: 1fr;
  }
}
</style>
