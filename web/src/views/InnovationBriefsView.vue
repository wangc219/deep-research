<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { RouterLink, useRoute } from 'vue-router'
import { databaseApi } from '@/apis/knowledge_api'
import { innovationBriefApi, knowledgeGovernanceApi } from '@/apis/knowledge_governance_api'
import { findLatestBriefForToday, formatBriefTime } from '@/utils/innovationBriefPush'

const priorityCatalog = [
  ['无人作战系统', '无人机、无人车、无人艇、无人潜航器、无人集群', '自主感知、智能决策、协同控制'],
  ['导弹武器系统', '防空导弹、反舰导弹、巡航导弹、弹道导弹', '制导导航、目标识别、飞行控制'],
  [
    '远程精确打击装备',
    '远程火箭炮、精确制导弹药、远程巡航打击平台',
    '精确定位、导航制导、体系协同'
  ],
  [
    '反无人系统',
    '反无人机雷达、光电探测系统、电子干扰装备、拦截系统',
    '低慢小目标探测、多传感器融合'
  ],
  ['高超声速武器装备', '高超声速滑翔飞行器、高超声速巡航飞行器', '高温材料、高速飞行、热防护'],
  ['定向能武器装备', '激光武器、高功率微波装备', '高能激光、微波技术、能源管理'],
  ['智能弹药与巡飞装备', '智能炮弹、巡飞弹、末制导弹药', '智能感知、自主导航、精确控制'],
  ['智能化空中作战平台', '新一代战斗机、无人僚机、智能空战平台', '人机协同、态势感知、任务规划'],
  ['新型陆战装备', '无人战车、机器人作战平台、智能装甲车辆', '自主驾驶、战场感知、平台协同'],
  [
    '新型海上作战装备',
    '无人水面舰艇、无人潜航器、新型水下探测平台',
    '水下通信、自主航行、海洋感知'
  ],
  ['空天攻防装备', '军用卫星、空间态势感知系统、反卫星装备', '空间探测、轨道监测、卫星防护'],
  ['电子战与电磁攻防装备', '电子侦察、通信干扰、雷达对抗系统', '频谱感知、电磁环境认知'],
  [
    '网络空间作战装备',
    '网络防护平台、网络靶场、网络态势感知系统',
    '网络安全、威胁检测、自动化防御'
  ],
  ['智能防空反导装备', '综合防空系统、反导预警系统、多层拦截体系', '多源探测、目标跟踪、指挥控制'],
  ['新型水下作战装备', '水下机器人、智能水雷探测与处置系统', '水声感知、水下自主控制'],
  [
    '智能指挥与作战支援装备',
    '智能指挥系统、战场信息融合平台、辅助决策系统',
    '多模态融合、知识推理、智能决策'
  ],
  [
    '新型侦察监视装备',
    '高分辨率侦察卫星、合成孔径雷达、分布式传感器',
    '多源遥感、目标识别、信息融合'
  ],
  [
    '新型通信与导航装备',
    '抗干扰通信终端、战术数据链、组合导航系统',
    '安全通信、导航增强、组网协同'
  ],
  ['新概念作战装备', '仿生机器人、可变构型平台、跨域无人系统', '仿生控制、新材料、跨域自主协同']
]
const defaultTopics = priorityCatalog.map(([category]) => category)
const route = useRoute()

const loading = ref(false)
const error = ref('')
const subscriptions = ref([])
const briefs = ref([])
const unreadCount = ref(0)
const selectedBrief = ref(null)
const runs = ref([])
const databases = ref([])
const sources = ref([])
const filter = ref('')
const editOpen = ref(false)
const readerOpen = ref(false)
const editingId = ref(null)
const form = reactive({
  name: '新质创新军事前沿技术观察',
  topicsText: defaultTopics.join('、'),
  keywordsText:
    '自主、集群、制导、探测、电子对抗、定向能、先进推进、低成本精确打击、高超声速、高能激光、高功率微波、巡飞弹、人机协同、空天攻防、水下自主、频谱感知、抗干扰通信、多模态融合、仿生控制',
  knowledge_ids: [],
  source_ids: [],
  languages: ['zh-CN', 'en'],
  timezone: 'Asia/Shanghai',
  daily_enabled: true,
  weekly_enabled: true,
  daily_cron: '0 8 * * *',
  weekly_cron: '0 9 * * 1',
  reminder_sensitivity: 'standard',
  significance_threshold: 70,
  open_discovery_enabled: true,
  research_explorer_enabled: true,
  enabled: true
})

const dbOptions = computed(() =>
  databases.value.map((item) => ({ value: item.kb_id, label: item.name }))
)
const sourceOptions = computed(() =>
  sources.value.map((item) => ({ value: item.id, label: `${item.name} · ${item.source_type}` }))
)
const latestTodayBrief = computed(() => findLatestBriefForToday(briefs.value))
const activeSubscriptionCount = computed(
  () => subscriptions.value.filter((item) => item.enabled !== false).length
)
const readerSections = [
  {
    key: 'confirmed_facts',
    step: '02',
    label: '已证实事实',
    claimLevel: 'Fact',
    tone: 'fact',
    description: '官方一手来源或多源交叉印证，可作为本期研判基线。'
  },
  {
    key: 'cross_validated_inferences',
    step: '03',
    label: '研判推断',
    claimLevel: 'Inference',
    tone: 'inference',
    description: '由现有证据推演出的技术趋势、能力变化与体系影响。'
  },
  {
    key: 'innovation_hypotheses',
    step: '04',
    label: '创新假设',
    claimLevel: 'Hypothesis',
    tone: 'hypothesis',
    description: '面向新质武器装备的机理组合、潜在应用、反制关系与验证思路。'
  }
]

function splitText(value) {
  return String(value || '')
    .split(/[，,、\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [subResult, briefResult, dbResult, runResult] = await Promise.all([
      innovationBriefApi.subscriptions(),
      innovationBriefApi.briefs({ brief_type: filter.value || null, page: 1, page_size: 100 }),
      databaseApi.getDatabases(),
      innovationBriefApi.runs()
    ])
    subscriptions.value = subResult.items || []
    briefs.value = briefResult.items || []
    unreadCount.value = briefResult.unread_count || 0
    databases.value = (dbResult.databases || []).filter((item) => item.effective_permission)
    runs.value = runResult.items || []
    const manageable = (dbResult.databases || []).filter((item) => item.can_manage)
    const sourceResults = await Promise.all(
      manageable.map((item) =>
        knowledgeGovernanceApi.sources(item.kb_id).catch(() => ({ items: [] }))
      )
    )
    sources.value = sourceResults.flatMap((item) => item.items || [])
    const requestedBriefId = typeof route.query.brief === 'string' ? route.query.brief : ''
    if (requestedBriefId && selectedBrief.value?.id !== requestedBriefId) {
      await openBrief({ id: requestedBriefId })
    }
  } catch (cause) {
    error.value = cause.message || '简报中心加载失败'
  } finally {
    loading.value = false
  }
}

async function openBrief(item) {
  selectedBrief.value = await innovationBriefApi.brief(item.id)
  readerOpen.value = true
  if (selectedBrief.value.unread) {
    await innovationBriefApi.markRead(item.id, true)
    selectedBrief.value.unread = false
    const listItem = briefs.value.find((brief) => brief.id === item.id)
    if (listItem) listItem.unread = false
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  }
}

async function run(subscription, type) {
  await innovationBriefApi.run(subscription.id, type)
  message.success(`${type === 'weekly' ? '周报' : '日简报'}任务已提交，可在运行追踪中查看`)
  await load()
}

function editSubscription(item = null) {
  editingId.value = item?.id || null
  Object.assign(form, {
    name: item?.name || '新质创新军事前沿技术观察',
    topicsText: (item?.topics || defaultTopics).join('、'),
    keywordsText: (item?.keywords || []).join('、'),
    knowledge_ids: [...(item?.knowledge_ids || [])],
    source_ids: [...(item?.source_ids || [])],
    languages: [...(item?.languages || ['zh-CN', 'en'])],
    timezone: item?.timezone || 'Asia/Shanghai',
    daily_enabled: item?.daily_enabled ?? true,
    weekly_enabled: item?.weekly_enabled ?? true,
    daily_cron: item?.daily_cron || '0 8 * * *',
    weekly_cron: item?.weekly_cron || '0 9 * * 1',
    reminder_sensitivity: item?.reminder_sensitivity || 'standard',
    significance_threshold: item?.significance_threshold ?? 70,
    open_discovery_enabled: item?.open_discovery_enabled ?? true,
    research_explorer_enabled: item?.research_explorer_enabled ?? true,
    enabled: item?.enabled ?? true
  })
  editOpen.value = true
}

async function saveSubscription() {
  const payload = {
    name: form.name,
    topics: splitText(form.topicsText),
    keywords: splitText(form.keywordsText),
    knowledge_ids: form.knowledge_ids,
    source_ids: form.source_ids,
    languages: form.languages,
    timezone: form.timezone,
    daily_enabled: form.daily_enabled,
    weekly_enabled: form.weekly_enabled,
    daily_cron: form.daily_cron,
    weekly_cron: form.weekly_cron,
    reminder_sensitivity: form.reminder_sensitivity,
    significance_threshold: Number(form.significance_threshold),
    open_discovery_enabled: form.open_discovery_enabled,
    research_explorer_enabled: form.research_explorer_enabled,
    enabled: form.enabled
  }
  if (editingId.value) await innovationBriefApi.updateSubscription(editingId.value, payload)
  else await innovationBriefApi.createSubscription(payload)
  editOpen.value = false
  message.success('订阅已保存')
  await load()
}

function deleteSubscription(item) {
  Modal.confirm({
    title: `删除订阅“${item.name}”？`,
    content: '历史运行、简报和站内投递记录会一起删除。',
    async onOk() {
      await innovationBriefApi.deleteSubscription(item.id)
      if (selectedBrief.value?.subscription_id === item.id) selectedBrief.value = null
      message.success('订阅已删除')
      await load()
    }
  })
}

function scoreColor(score) {
  if (score >= 85) return 'red'
  if (score >= 70) return 'orange'
  return 'blue'
}

function scheduleTime(cron, fallback) {
  const [minute, hour] = String(cron || '')
    .trim()
    .split(/\s+/)
  if (!/^\d+$/.test(hour) || !/^\d+$/.test(minute)) return fallback
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

onMounted(load)
</script>

<template>
  <main class="brief-page">
    <header class="hero">
      <div class="hero-copy">
        <span class="eyebrow">每日前沿情报</span>
        <h2>新质创新军事技术简报</h2>
        <p>调研探索员每天汇集可信证据，突出新技术、新原理、变化信号与待验证假设。</p>
      </div>
      <div class="hero-actions">
        <div class="hero-stat">
          <b>{{ unreadCount }}</b
          ><span>待阅读</span>
        </div>
        <a-button type="primary" @click="editSubscription()">新增推送订阅</a-button>
      </div>
    </header>
    <a-alert v-if="error" type="error" :message="error" show-icon />
    <a-spin :spinning="loading">
      <section v-if="latestTodayBrief" class="today-brief">
        <div class="today-kicker">
          <span>今日简报</span
          ><em>{{ formatBriefTime(latestTodayBrief.published_at || latestTodayBrief.created_at) }} 推送</em>
        </div>
        <div class="today-content">
          <div>
            <h3>{{ latestTodayBrief.title }}</h3>
            <p>{{ latestTodayBrief.summary }}</p>
          </div>
          <div class="today-score">
            <b>{{ Number(latestTodayBrief.max_score || 0).toFixed(1) }}</b
            ><span>最高信号</span>
          </div>
          <a-button type="primary" @click="openBrief(latestTodayBrief)">阅读今日简报</a-button>
        </div>
      </section>

      <section v-else class="today-brief today-empty">
        <div>
          <span class="eyebrow">今日简报</span>
          <h3>今天还没有新的前沿简报</h3>
          <p>系统会提前完成检索与研判，在设定时间准时推送；无显著变化时不会制造未读提醒。</p>
        </div>
        <a-button type="primary" @click="editSubscription()">设置推送订阅</a-button>
      </section>

      <section class="subscriptions-panel panel">
        <div class="panel-heading">
          <div>
            <h3>推送订阅</h3>
            <small
              >{{ activeSubscriptionCount }} 个订阅运行中 · 登录后自动提醒当天最新未读简报</small
            >
          </div>
          <a-button size="small" @click="editSubscription()">新增订阅</a-button>
        </div>
        <a-empty v-if="!subscriptions.length" description="尚未设置简报推送" />
        <article v-for="item in subscriptions" :key="item.id" class="subscription-row">
          <div class="subscription-main">
            <span class="status-dot" :class="{ active: item.enabled !== false }"></span>
            <div>
              <b>{{ item.name }}</b
              ><small
                >{{ item.topics.slice(0, 4).join(' · ')
                }}<template v-if="item.topics.length > 4">
                  等 {{ item.topics.length }} 类方向</template
                ></small
              >
            </div>
          </div>
          <div class="subscription-delivery">
            <span>{{
              item.daily_enabled ? `每日 ${scheduleTime(item.daily_cron, '08:00')}` : '日报关闭'
            }}</span>
            <span>{{
              item.weekly_enabled ? `每周 ${scheduleTime(item.weekly_cron, '09:00')}` : '周报关闭'
            }}</span>
            <span>阈值 {{ item.significance_threshold }}</span>
            <span>提前 {{ item.prepare_ahead_minutes || 45 }} 分钟准备</span>
          </div>
          <a-space wrap>
            <a-button size="small" @click="editSubscription(item)">推送设置</a-button>
            <a-button size="small" type="primary" ghost @click="run(item, 'daily')"
              >立即生成</a-button
            >
            <a-dropdown>
              <a-button size="small">更多</a-button>
              <template #overlay
                ><a-menu
                  ><a-menu-item @click="run(item, 'weekly')">生成周报</a-menu-item
                  ><a-menu-item danger @click="deleteSubscription(item)"
                    >删除订阅</a-menu-item
                  ></a-menu
                ></template
              >
            </a-dropdown>
          </a-space>
        </article>
      </section>

      <section class="brief-layout">
        <article class="feed panel">
          <div class="panel-heading">
            <div>
              <h3>简报记录</h3>
              <small>按时间查看历史推送</small>
            </div>
            <a-select
              v-model:value="filter"
              style="width: 118px"
              :options="[
                { value: '', label: '全部' },
                { value: 'daily', label: '日报' },
                { value: 'weekly', label: '周报' },
                { value: 'collection_update', label: '采集更新' }
              ]"
              @change="load"
            />
          </div>
          <a-empty v-if="!briefs.length" description="暂无简报，运行订阅后将在这里显示" />
          <button
            v-for="item in briefs"
            :key="item.id"
            class="brief-row"
            :class="{ active: selectedBrief?.id === item.id }"
            @click="openBrief(item)"
          >
            <span class="unread" :class="{ visible: item.unread }"></span>
            <span
              ><b>{{ item.title }}</b
              ><small>{{ item.summary }}</small
              ><em>{{ formatBriefTime(item.published_at || item.created_at) }}</em></span
            >
            <a-tag :color="scoreColor(item.max_score)">{{ item.max_score.toFixed(1) }}</a-tag>
          </button>
        </article>
      </section>

      <details class="secondary-panel panel">
        <summary>
          <span><b>关注范围</b><small>19 类重点谱系，持续扫描谱系外的新概念与跨域信号</small></span
          ><em>展开查看</em>
        </summary>
        <div class="scope-tags">
          <span v-for="([category], index) in priorityCatalog" :key="category"
            >{{ index + 1 }}. {{ category }}</span
          >
        </div>
        <div class="scope-table">
          <div class="scope-table-head"><b>一级分类</b><b>典型装备方向</b><b>重点技术领域</b></div>
          <div
            v-for="([category, equipment, technologies], index) in priorityCatalog"
            :key="category"
            class="scope-table-row"
          >
            <b>{{ index + 1 }}. {{ category }}</b
            ><span>{{ equipment }}</span
            ><span>{{ technologies }}</span>
          </div>
        </div>
      </details>

      <details class="secondary-panel panel runs">
        <summary>
          <span><b>运行记录</b><small>查询计划、证据数量与显著性统计</small></span
          ><em>最近 {{ Math.min(runs.length, 20) }} 次</em>
        </summary>
        <div v-for="item in runs.slice(0, 20)" :key="item.id" class="run-row">
          <span>{{ item.brief_type }} · {{ item.status }}</span
          ><span
            >证据 {{ item.stats?.evidence_count || 0 }} · 假设
            {{ item.stats?.hypothesis_count || 0 }} · 最高 {{ item.stats?.max_score || 0 }}</span
          ><small>{{ formatBriefTime(item.created_at) }}</small>
        </div>
      </details>
    </a-spin>

    <a-drawer
      v-model:open="readerOpen"
      placement="right"
      width="min(920px, 100vw)"
      :closable="false"
      root-class-name="innovation-brief-reader"
    >
      <article v-if="selectedBrief" class="reader-document">
        <div class="reader-toolbar">
          <span
            >前沿技术简报 ·
            {{ formatBriefTime(selectedBrief.published_at || selectedBrief.created_at) }}</span
          >
          <a-button size="small" @click="readerOpen = false">关闭阅读</a-button>
        </div>

        <header class="reader-header">
          <div class="reader-kicker">INTELLIGENCE BRIEF</div>
          <h2>{{ selectedBrief.title }}</h2>
          <p>{{ selectedBrief.summary }}</p>
          <div class="reader-meta">
            <span
              ><b>{{ Number(selectedBrief.max_score || 0).toFixed(1) }}</b> 最高信号</span
            >
            <span>{{ selectedBrief.significant ? '显著变化' : '常规观察' }}</span>
            <span>{{ selectedBrief.brief_type === 'weekly' ? '周度汇总' : '每日简报' }}</span>
          </div>
        </header>

        <nav class="reader-flow" aria-label="简报阅读顺序">
          <span><b>01</b>探索摘要</span>
          <span><b>02</b>事实</span>
          <span><b>03</b>推断</span>
          <span><b>04</b>创新假设</span>
        </nav>

        <details class="reader-section reader-section--explorer" open>
          <summary>
            <span class="reader-step">01</span>
            <span class="reader-section-title">
              <b>调研探索员摘要</b>
              <small>先读结论，再下钻关键技术、作用原理与军事价值。</small>
            </span>
            <span class="reader-count">
              {{ selectedBrief.sections?.research_explorer_findings?.length || 0 }} 项
            </span>
            <span class="reader-toggle">展开</span>
          </summary>
          <div class="reader-section-body">
            <p v-if="selectedBrief.sections?.research_explorer_summary" class="reader-lead">
              {{ selectedBrief.sections.research_explorer_summary }}
            </p>
            <p v-else class="reader-empty-copy">本期暂无调研探索员摘要，可继续查看证据分层。</p>
            <section
              v-if="selectedBrief.sections?.research_explorer_outlook"
              class="reader-outlook"
            >
              <strong>新质技术思考与组合方向</strong>
              <p>{{ selectedBrief.sections.research_explorer_outlook }}</p>
            </section>
            <details
              v-for="(item, index) in selectedBrief.sections?.research_explorer_findings || []"
              :key="`explorer-${index}`"
              class="reader-finding"
            >
              <summary>
                <span class="finding-index">{{ String(index + 1).padStart(2, '0') }}</span>
                <span class="finding-title">
                  <b>{{ item.title }}</b
                  ><small>{{ item.claim_level }} · 展开技术研判</small>
                </span>
                <span class="finding-toggle">展开</span>
              </summary>
              <div class="reader-finding-body">
                <dl class="reader-analysis">
                  <div>
                    <dt>作用原理</dt>
                    <dd>{{ item.principle }}</dd>
                  </div>
                  <div v-if="item.why_it_matters">
                    <dt>装备价值</dt>
                    <dd>{{ item.why_it_matters }}</dd>
                  </div>
                  <div v-if="item.equipment_implication">
                    <dt>装备构型牵引</dt>
                    <dd>{{ item.equipment_implication }}</dd>
                  </div>
                  <div v-if="item.maturity || item.published_at">
                    <dt>阶段与时间</dt>
                    <dd>
                      {{ [item.maturity, item.published_at].filter(Boolean).join(' · ') }}
                    </dd>
                  </div>
                  <div v-if="item.boundaries">
                    <dt>反制与边界</dt>
                    <dd>{{ item.boundaries }}</dd>
                  </div>
                  <div v-if="item.evidence">
                    <dt>证据摘要</dt>
                    <dd>{{ item.evidence }}</dd>
                  </div>
                </dl>
                <div v-if="item.sources?.length" class="reader-links">
                  <a
                    v-for="source in item.sources"
                    :key="source.url"
                    :href="source.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    >{{ source.title }} ↗</a
                  >
                </div>
              </div>
            </details>
          </div>
        </details>

        <details
          v-for="section in readerSections"
          :key="section.key"
          class="reader-section"
          :class="`reader-section--${section.tone}`"
        >
          <summary>
            <span class="reader-step">{{ section.step }}</span>
            <span class="reader-section-title">
              <b>{{ section.label }}</b>
              <small>{{ section.description }}</small>
            </span>
            <span class="reader-count">
              {{ (selectedBrief.sections?.[section.key] || []).length }} 项
            </span>
            <span class="reader-toggle">展开</span>
          </summary>
          <div class="reader-section-body">
            <a-empty
              v-if="!(selectedBrief.sections?.[section.key] || []).length"
              :description="`本期暂无${section.label}`"
            />
            <article
              v-for="(item, index) in selectedBrief.sections?.[section.key] || []"
              :key="item.id || item.hypothesis_id || index"
              class="reader-card"
              :class="`reader-card--${section.tone}`"
            >
              <div class="reader-card-tags">
                <a-tag>{{ item.claim_level || section.claimLevel }}</a-tag>
                <a-tag v-if="item.pending_review" color="orange">待审核</a-tag>
                <a-tag
                  v-if="item.change_signal"
                  :color="
                    item.change_signal === 'conflict'
                      ? 'red'
                      : item.change_signal === 'changed'
                        ? 'orange'
                        : 'blue'
                  "
                  >{{
                    { new: '新增', changed: '变化', conflict: '冲突', known: '已知' }[
                      item.change_signal
                    ] || item.change_signal
                  }}</a-tag
                >
                <a-tag v-if="item.score != null" :color="scoreColor(item.score)">
                  信号 {{ Number(item.score).toFixed(1) }}
                </a-tag>
              </div>

              <h4>{{ item.title || item.mechanism_hypothesis || '待验证技术组合' }}</h4>

              <template v-if="section.key === 'innovation_hypotheses'">
                <p v-if="item.mechanism_hypothesis" class="reader-card-intro">
                  <strong>核心创新假设：</strong>{{ item.mechanism_hypothesis }}
                </p>
                <p v-if="item.feasibility_basis" class="reader-card-intro">
                  <strong>可行性基础：</strong>{{
                    Array.isArray(item.feasibility_basis)
                      ? item.feasibility_basis.join('；')
                      : item.feasibility_basis
                  }}
                </p>
                <dl class="reader-analysis reader-analysis--innovation">
                  <div v-if="item.expected_effects?.length">
                    <dt>潜在能力与应用</dt>
                    <dd>
                      <span v-for="value in item.expected_effects" :key="value">{{ value }}</span>
                    </dd>
                  </div>
                  <div v-if="item.applicable_conditions?.length">
                    <dt>适用条件</dt>
                    <dd>
                      <span v-for="value in item.applicable_conditions" :key="value">{{
                        value
                      }}</span>
                    </dd>
                  </div>
                  <div v-if="item.validation_requirements?.length">
                    <dt>验证与反制观察</dt>
                    <dd>
                      <span v-for="value in item.validation_requirements" :key="value">{{
                        value
                      }}</span>
                    </dd>
                  </div>
                  <div v-if="item.falsification_criteria?.length">
                    <dt>证伪标准</dt>
                    <dd>
                      <span v-for="value in item.falsification_criteria" :key="value">{{
                        value
                      }}</span>
                    </dd>
                  </div>
                </dl>
              </template>
              <template v-else>
                <p class="reader-card-intro">{{ item.excerpt || item.claim_reason }}</p>
                <p v-if="item.claim_reason" class="reader-basis">
                  <strong>判定依据</strong>{{ item.claim_reason }}
                </p>
                <p
                  v-if="section.key === 'cross_validated_inferences' && item.verification_next"
                  class="reader-basis"
                >
                  <strong>后续观察</strong>{{ item.verification_next }}
                </p>
              </template>

              <div class="reader-links">
                <a v-if="item.url" :href="item.url" target="_blank" rel="noopener noreferrer">
                  打开原始证据 ↗
                </a>
                <RouterLink
                  v-if="item.source_item_id"
                  :to="{
                    path: '/extensions',
                    query: {
                      tool: 'knowledge-governance',
                      kb: item.kb_id,
                      staging: item.source_item_id
                    }
                  }"
                  >查看暂存证据 →</RouterLink
                >
              </div>
              <small v-if="item.kb_id" class="reader-source-note">
                知识库 {{ item.kb_id }}
                <template v-if="item.file_id"> · 文件 {{ item.file_id }}</template>
              </small>
            </article>
          </div>
        </details>

        <footer class="reader-footer">
          <b>阅读说明</b>
          <span>事实、推断与创新假设严格分层；创新假设不等同于已验证装备能力。</span>
        </footer>
      </article>
    </a-drawer>

    <a-modal
      v-model:open="editOpen"
      :title="editingId ? '编辑简报订阅' : '新增简报订阅'"
      width="720px"
      ok-text="保存"
      @ok="saveSubscription"
    >
      <a-input v-model:value="form.name" placeholder="订阅名称" />
      <label>高优先级种子方向</label><a-textarea v-model:value="form.topicsText" :rows="4" /><small
        class="field-help"
        >默认覆盖上方 19
        类重点谱系；种子方向用于提高相关性，不是技术范围边界，开放发现会持续扫描其他新兴军事技术。</small
      >
      <label>关键词</label><a-textarea v-model:value="form.keywordsText" :rows="2" />
      <label>检索语言</label
      ><a-select
        v-model:value="form.languages"
        mode="tags"
        :options="[
          { value: 'zh-CN', label: '简体中文' },
          { value: 'en', label: 'English' },
          { value: 'ru', label: 'Русский' },
          { value: 'fr', label: 'Français' }
        ]"
        placeholder="选择或输入语言代码"
        style="width: 100%"
      />
      <label>正式知识库</label
      ><a-select
        v-model:value="form.knowledge_ids"
        mode="multiple"
        :options="dbOptions"
        style="width: 100%"
      />
      <label>启用来源</label
      ><a-select
        v-model:value="form.source_ids"
        mode="multiple"
        :options="sourceOptions"
        style="width: 100%"
      />
      <div class="form-grid">
        <div><label>日报 cron</label><a-input v-model:value="form.daily_cron" /></div>
        <div><label>周报 cron</label><a-input v-model:value="form.weekly_cron" /></div>
        <div><label>IANA 时区</label><a-input v-model:value="form.timezone" /></div>
        <div>
          <label>显著性阈值</label
          ><a-input-number
            v-model:value="form.significance_threshold"
            :min="0"
            :max="100"
            style="width: 100%"
          />
        </div>
      </div>
      <label>提醒敏感度</label
      ><a-select
        v-model:value="form.reminder_sensitivity"
        :options="[
          { value: 'conservative', label: '保守' },
          { value: 'standard', label: '标准' },
          { value: 'sensitive', label: '敏感' }
        ]"
        style="width: 100%"
      />
      <a-space style="margin-top: 14px" wrap
        ><a-checkbox v-model:checked="form.open_discovery_enabled"
          >开放发现（跨域扫描与弱信号）</a-checkbox
        ><a-checkbox v-model:checked="form.research_explorer_enabled"
          >调用调研探索员整理技术与原理</a-checkbox
        ><a-checkbox v-model:checked="form.daily_enabled">每日启用</a-checkbox
        ><a-checkbox v-model:checked="form.weekly_enabled">每周启用</a-checkbox
        ><a-checkbox v-model:checked="form.enabled">订阅启用</a-checkbox></a-space
      >
    </a-modal>
  </main>
</template>

<style scoped>
.brief-page {
  max-width: 1440px;
  margin: auto;
  padding: 20px 24px 42px;
}
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 22px 24px;
  border-radius: 14px;
  background: linear-gradient(135deg, #081a2d, #16445b);
  color: #fff;
}
.hero-copy {
  min-width: 0;
}
.hero h2 {
  margin: 4px 0 6px;
  font-size: 26px;
}
.hero p {
  max-width: 760px;
  margin: 0;
  color: #c9ddea;
  line-height: 1.65;
}
.eyebrow {
  color: #61d8ba;
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.12em;
}
.hero-actions {
  display: flex;
  align-items: center;
  gap: 18px;
  flex: 0 0 auto;
}
.hero-stat {
  min-width: 58px;
  text-align: center;
}
.hero-stat b {
  display: block;
  font-size: 27px;
  line-height: 1;
}
.hero-stat span {
  display: block;
  margin-top: 5px;
  color: #c9ddea;
  font-size: 11px;
}
.panel {
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
  padding: 16px;
}
.panel h3 {
  margin: 0;
}
.today-brief {
  margin: 14px 0;
  padding: 18px 20px;
  border: 1px solid color-mix(in srgb, var(--main-color) 22%, var(--gray-200));
  border-radius: 13px;
  background: linear-gradient(
    135deg,
    color-mix(in srgb, var(--main-20) 80%, var(--gray-0)),
    var(--gray-0)
  );
  box-shadow: 0 8px 24px rgb(45 60 100 / 5%);
}
.today-kicker {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 9px;
}
.today-kicker span {
  color: var(--main-color);
  font-size: 12px;
  font-weight: 800;
}
.today-kicker em {
  color: var(--gray-500);
  font-size: 11px;
  font-style: normal;
}
.today-content {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 22px;
}
.today-content h3,
.today-empty h3 {
  margin: 0;
  font-size: 20px;
}
.today-content p,
.today-empty p {
  margin: 6px 0 0;
  color: var(--gray-600);
  line-height: 1.6;
}
.today-score {
  min-width: 76px;
  text-align: center;
}
.today-score b {
  display: block;
  color: #d97706;
  font-size: 23px;
}
.today-score span {
  color: var(--gray-500);
  font-size: 10px;
}
.today-empty {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.subscriptions-panel {
  margin-bottom: 14px;
}
.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.panel-heading small,
.field-help {
  color: var(--gray-600);
}
.field-help {
  display: block;
  margin-top: 5px;
}
.subscription-row {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto auto;
  align-items: center;
  gap: 18px;
  padding: 13px 0;
  border-top: 1px solid var(--gray-100);
}
.subscription-row:first-of-type {
  margin-top: 12px;
}
.subscription-main {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-width: 0;
}
.subscription-main b,
.subscription-main small {
  display: block;
}
.subscription-main small {
  margin-top: 4px;
  overflow: hidden;
  color: var(--gray-600);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--gray-300);
}
.status-dot.active {
  background: #10b981;
  box-shadow: 0 0 0 3px rgb(16 185 129 / 12%);
}
.subscription-delivery {
  display: flex;
  gap: 7px;
}
.subscription-delivery span {
  padding: 5px 8px;
  border-radius: 6px;
  background: var(--gray-50);
  color: var(--gray-600);
  font-size: 11px;
}
.brief-layout {
  display: block;
}
.feed {
  min-height: 280px;
}
.brief-row {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  align-items: start;
  width: 100%;
  gap: 12px;
  padding: 15px 8px;
  border: 0;
  border-top: 1px solid var(--gray-100);
  background: transparent;
  text-align: left;
  cursor: pointer;
}
.brief-row:hover,
.brief-row.active {
  background: var(--gray-50);
}
.brief-row > span:nth-child(2) {
  min-width: 0;
}
.brief-row b,
.brief-row small,
.brief-row em {
  display: block;
}
.brief-row small {
  display: -webkit-box;
  margin: 5px 0;
  overflow: hidden;
  color: var(--gray-600);
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.brief-row em {
  color: var(--gray-500);
  font-size: 11px;
  font-style: normal;
}
.unread {
  width: 7px;
  height: 7px;
  margin-top: 6px;
  border-radius: 50%;
}
.unread.visible {
  background: #ef4444;
}
.reader-document {
  width: min(100%, 820px);
  margin: 0 auto;
  padding-bottom: 32px;
  color: var(--gray-800);
}
.reader-toolbar {
  position: sticky;
  z-index: 3;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 0;
  background: color-mix(in srgb, var(--gray-0) 94%, transparent);
  color: var(--gray-500);
  font-size: 12px;
  backdrop-filter: blur(10px);
}
.reader-header {
  position: relative;
  overflow: hidden;
  padding: 34px 36px 30px;
  border: 1px solid color-mix(in srgb, #0e7490 25%, var(--gray-200));
  border-radius: 18px;
  background:
    radial-gradient(circle at 90% 10%, rgb(34 211 238 / 18%), transparent 30%),
    linear-gradient(145deg, #071928, #123d51);
  color: #fff;
  box-shadow: 0 20px 46px rgb(15 48 66 / 13%);
}
.reader-kicker {
  color: #67e8d2;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.17em;
}
.reader-header h2 {
  max-width: 680px;
  margin: 9px 0 12px;
  color: #fff;
  font-size: clamp(25px, 4vw, 36px);
  line-height: 1.25;
}
.reader-header > p {
  max-width: 700px;
  margin: 0;
  color: #c8dce6;
  font-size: 14px;
  line-height: 1.8;
}
.reader-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 22px;
}
.reader-meta span {
  padding: 6px 10px;
  border: 1px solid rgb(255 255 255 / 15%);
  border-radius: 999px;
  background: rgb(255 255 255 / 7%);
  color: #dcebf1;
  font-size: 11px;
}
.reader-meta b {
  color: #fbbf24;
  font-size: 13px;
}
.reader-flow {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin: 18px 0;
}
.reader-flow span {
  padding: 10px 12px;
  border: 1px solid var(--gray-200);
  border-radius: 9px;
  background: var(--gray-0);
  color: var(--gray-600);
  font-size: 11px;
}
.reader-flow b {
  margin-right: 5px;
  color: var(--main-color);
}
.reader-section {
  --reader-accent: var(--main-color);
  margin-top: 12px;
  overflow: hidden;
  border: 1px solid var(--gray-200);
  border-radius: 13px;
  background: var(--gray-0);
  box-shadow: 0 5px 18px rgb(15 23 42 / 3%);
}
.reader-section--explorer {
  --reader-accent: #0891b2;
}
.reader-section--fact {
  --reader-accent: #059669;
}
.reader-section--inference {
  --reader-accent: #d97706;
}
.reader-section--hypothesis {
  --reader-accent: #7c3aed;
}
.reader-section > summary {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  padding: 17px 18px;
  cursor: pointer;
  list-style: none;
}
.reader-section > summary::-webkit-details-marker {
  display: none;
}
.reader-step {
  color: var(--reader-accent);
  font-size: 18px;
  font-weight: 850;
  letter-spacing: -0.04em;
}
.reader-section-title b,
.reader-section-title small {
  display: block;
}
.reader-section-title b {
  color: var(--gray-800);
  font-size: 16px;
}
.reader-section-title small {
  margin-top: 4px;
  color: var(--gray-500);
  line-height: 1.45;
}
.reader-count {
  min-width: 46px;
  padding: 4px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--reader-accent) 9%, var(--gray-0));
  color: var(--reader-accent);
  font-size: 11px;
  text-align: center;
}
.reader-toggle {
  color: var(--gray-500);
  font-size: 11px;
}
.reader-section[open] > summary {
  border-bottom: 1px solid var(--gray-100);
  background: color-mix(in srgb, var(--reader-accent) 4%, var(--gray-0));
}
.reader-section[open] .reader-toggle {
  font-size: 0;
}
.reader-section[open] .reader-toggle::after {
  content: '收起';
  font-size: 11px;
}
.reader-section-body {
  padding: 8px 18px 20px;
}
.reader-lead {
  margin: 10px 2px 18px;
  padding: 16px 18px;
  border-left: 3px solid var(--reader-accent);
  border-radius: 0 10px 10px 0;
  background: color-mix(in srgb, var(--reader-accent) 6%, var(--gray-0));
  color: var(--gray-700);
  font-size: 14px;
  line-height: 1.85;
}
.reader-outlook {
  margin: -6px 2px 18px;
  padding: 14px 16px;
  border: 1px solid color-mix(in srgb, var(--reader-accent) 20%, var(--gray-100));
  border-radius: 10px;
  background: color-mix(in srgb, var(--reader-accent) 4%, var(--gray-0));
  color: var(--gray-700);
}
.reader-outlook strong {
  color: var(--reader-accent);
  font-size: 13px;
}
.reader-outlook p {
  margin: 7px 0 0;
  line-height: 1.8;
}
.reader-empty-copy {
  color: var(--gray-500);
  text-align: center;
}
.reader-finding {
  margin-top: 8px;
  overflow: hidden;
  border: 1px solid var(--gray-150, var(--gray-100));
  border-radius: 9px;
  background: var(--gray-0);
}
.reader-finding > summary {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  cursor: pointer;
  list-style: none;
}
.reader-finding > summary::-webkit-details-marker {
  display: none;
}
.finding-index {
  color: var(--reader-accent);
  font-size: 12px;
  font-weight: 850;
}
.finding-title b,
.finding-title small {
  display: block;
}
.finding-title b {
  color: var(--gray-750, var(--gray-700));
  line-height: 1.55;
}
.finding-title small {
  margin-top: 3px;
  color: var(--gray-500);
  font-size: 10px;
}
.finding-toggle {
  color: var(--reader-accent);
  font-size: 11px;
}
.reader-finding[open] > summary {
  background: color-mix(in srgb, var(--reader-accent) 4%, var(--gray-0));
}
.reader-finding[open] .finding-toggle {
  font-size: 0;
}
.reader-finding[open] .finding-toggle::after {
  content: '收起';
  font-size: 11px;
}
.reader-finding-body {
  padding: 0 14px 14px;
  border-top: 1px solid var(--gray-100);
}
.reader-card {
  position: relative;
  margin-top: 12px;
  padding: 18px 20px;
  border: 1px solid var(--gray-150, var(--gray-100));
  border-left: 3px solid var(--reader-accent);
  border-radius: 10px;
  background: var(--gray-0);
}
.reader-card h4 {
  margin: 10px 0 8px;
  color: var(--gray-800);
  font-size: 16px;
  line-height: 1.55;
}
.reader-card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}
.reader-card-intro {
  margin: 8px 0;
  color: var(--gray-650, var(--gray-600));
  line-height: 1.8;
  white-space: pre-wrap;
}
.reader-analysis {
  margin: 12px 0 0;
}
.reader-analysis > div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 12px;
  padding: 10px 0;
  border-top: 1px dashed var(--gray-200);
}
.reader-analysis dt {
  color: var(--reader-accent);
  font-size: 12px;
  font-weight: 750;
}
.reader-analysis dd {
  margin: 0;
  color: var(--gray-650, var(--gray-600));
  line-height: 1.75;
}
.reader-analysis--innovation dd span {
  display: block;
  position: relative;
  padding-left: 13px;
}
.reader-analysis--innovation dd span::before {
  position: absolute;
  top: 0;
  left: 0;
  color: var(--reader-accent);
  content: '·';
  font-weight: 900;
}
.reader-basis {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 10px;
  margin: 10px 0 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--gray-50);
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.65;
}
.reader-basis strong {
  color: var(--gray-700);
}
.reader-links {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}
.reader-links a {
  color: var(--main-color);
  font-size: 12px;
  font-weight: 650;
}
.reader-source-note {
  display: block;
  margin-top: 10px;
  color: var(--gray-500);
}
.reader-footer {
  display: flex;
  gap: 12px;
  margin-top: 18px;
  padding: 14px 16px;
  border-radius: 10px;
  background: var(--gray-50);
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.65;
}
.reader-footer b {
  flex: 0 0 auto;
  color: var(--gray-700);
}
:global(.innovation-brief-reader .ant-drawer-body) {
  padding: 0 28px;
  background: color-mix(in srgb, var(--gray-50) 72%, var(--gray-0));
}
.secondary-panel {
  margin-top: 12px;
}
.secondary-panel summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  cursor: pointer;
  list-style: none;
}
.secondary-panel summary::-webkit-details-marker {
  display: none;
}
.secondary-panel summary span b,
.secondary-panel summary span small {
  display: block;
}
.secondary-panel summary span small {
  margin-top: 3px;
  color: var(--gray-600);
}
.secondary-panel summary em {
  color: var(--main-color);
  font-size: 12px;
  font-style: normal;
}
.scope-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 15px;
}
.scope-tags span {
  padding: 5px 8px;
  border: 1px solid var(--gray-200);
  border-radius: 999px;
  background: var(--gray-0);
  font-size: 11px;
}
.scope-table {
  margin-top: 12px;
  overflow: hidden;
  border: 1px solid var(--gray-200);
  border-radius: 9px;
}
.scope-table-head,
.scope-table-row {
  display: grid;
  grid-template-columns: minmax(190px, 0.75fr) minmax(280px, 1.35fr) minmax(240px, 1fr);
  gap: 16px;
  padding: 10px 12px;
}
.scope-table-head {
  background: var(--gray-100);
}
.scope-table-row {
  border-top: 1px solid var(--gray-100);
  background: var(--gray-0);
}
.scope-table-row span {
  color: var(--gray-600);
}
.run-row {
  display: grid;
  grid-template-columns: 180px 1fr auto;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid var(--gray-100);
}
.runs summary {
  margin-bottom: 2px;
}
label {
  display: block;
  margin: 12px 0 6px;
  color: var(--gray-700);
  font-size: 13px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
@media (max-width: 1050px) {
  .subscription-row {
    grid-template-columns: 1fr auto;
  }
  .subscription-delivery {
    grid-column: 1/-1;
    grid-row: 2;
  }
}
@media (max-width: 720px) {
  .brief-page {
    padding: 12px 12px 32px;
  }
  .hero {
    align-items: flex-start;
    flex-direction: column;
    padding: 18px;
  }
  .hero-actions {
    width: 100%;
    justify-content: space-between;
  }
  .today-content {
    grid-template-columns: 1fr;
  }
  .today-score {
    text-align: left;
  }
  .today-empty {
    align-items: flex-start;
    flex-direction: column;
    gap: 14px;
  }
  .subscription-row {
    grid-template-columns: 1fr;
  }
  .subscription-delivery {
    grid-column: auto;
    grid-row: auto;
    flex-wrap: wrap;
  }
  .form-grid {
    grid-template-columns: 1fr;
  }
  .reader-header {
    padding: 26px 22px 24px;
    border-radius: 13px;
  }
  .reader-flow {
    grid-template-columns: repeat(2, 1fr);
  }
  .reader-section > summary {
    grid-template-columns: 36px minmax(0, 1fr) auto;
    gap: 8px;
    padding: 15px 14px;
  }
  .reader-toggle {
    display: none;
  }
  .reader-section-title small {
    display: none;
  }
  .reader-section-body {
    padding: 6px 12px 16px;
  }
  .reader-card {
    padding: 15px;
  }
  .reader-analysis > div,
  .reader-basis {
    grid-template-columns: 1fr;
    gap: 5px;
  }
  :global(.innovation-brief-reader .ant-drawer-body) {
    padding: 0 12px;
  }
  .run-row {
    grid-template-columns: 1fr;
  }
  .scope-table {
    overflow-x: auto;
  }
  .scope-table-head,
  .scope-table-row {
    min-width: 820px;
  }
}
</style>
