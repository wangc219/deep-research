<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Archive,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Circle,
  Eye,
  MoreHorizontal,
  Plus,
  Star,
  Download,
  FileText,
  Film,
  FolderOpen,
  ListChecks,
  RefreshCw,
  Search,
  Settings2,
  Square,
  Trash2
} from '@lucide/vue'
import { message, Modal } from 'ant-design-vue'
import { wxchannelsApi } from '@/apis/wxchannels_api'
import CollectionArtifactsPanel from '@/components/knowledge/CollectionArtifactsPanel.vue'
import { formatDateTime, formatRelative } from '@/utils/time'
import WechatConnectionStatus from '@/components/knowledge/WechatConnectionStatus.vue'
import WorkspaceFileDrawer from '@/components/workspace/WorkspaceFileDrawer.vue'

const router = useRouter()
const workspacePreviewPath = ref('')
const historyBusyId = ref('')
const page = ref('channels')
const artifactCount = ref(0)
const videoFilter = ref('')
const navigation = [
  {
    id: 'channels',
    title: '视频号管理',
    icon: FolderOpen,
    description: '搜索并收藏视频号，先看最新视频，再按需加载历史。'
  },
  { id: 'videos', title: '视频转录', icon: Film, description: '选择视频号，浏览并转录视频。' },
  {
    id: 'tasks',
    title: '转录任务',
    icon: ListChecks,
    description: '查看后台进度、历史任务和生成的文字稿。'
  },
  {
    id: 'artifacts',
    title: '沙盒成果与入库',
    icon: Archive,
    description: '预览沙盒中的成果，批量下载或选择知识库入库。'
  }
]
const currentPage = computed(
  () =>
    navigation.find((item) => item.id === page.value) || {
      title: '微信连接',
      description: cloudCollectorManaged.value
        ? '查看云端微信连接状态，或查找需要转录的视频。'
        : '连接本机微信，或快速查找需要转录的视频。'
    }
)
const collectionMode = ref('central')
const deviceId = ref()
const connectionSection = ref(null)
const sourceAvailable = ref(false)
const conversionReady = ref(false)
const cloudCollectorManaged = ref(false)
const account = ref('')
const videoRange = ref(20)
const maxVideos = computed(() => (videoRange.value === 'all' ? null : videoRange.value))
const rangeLabel = computed(() =>
  maxVideos.value === null ? '全部未转录视频' : `最新 ${maxVideos.value} 条未转录视频`
)
const rangeOptions = [5, 10, 15, 20, 30, 40, 50, 100, 150]
  .map((value) => ({ value, label: `最新 ${value} 条` }))
  .concat({ value: 'all', label: '全部' })
const channels = ref([])
const channelsLoading = ref(false)
const channelsError = ref('')
const channelHistory = ref(null)
const channelHistoryLoading = ref(false)
const channelHistoryError = ref('')
const channelOffset = ref(0)
const channelPageSize = 20
const libraryQuery = ref('')
const channelFilter = ref('')
const historyKeyword = ref('')
const historyDates = ref(null)
const historyFilters = ref({})
const historySelection = ref([])
const historyMode = ref('single')
const libraryPreview = ref(null)
const filteredChannels = computed(() =>
  channels.value.filter((channel) =>
    `${channel.account} ${channel.username}`
      .toLowerCase()
      .includes(channelFilter.value.trim().toLowerCase())
  )
)
const libraryCanStart = computed(
  () =>
    sourceReady.value &&
    !activeTask.value &&
    !submitting.value &&
    !searching.value &&
    !pollError.value
)
const selectableHistory = computed(() =>
  (channelHistory.value?.videos || []).filter((video) => !video.completed)
)
const historyAllSelected = computed(
  () =>
    !!selectableHistory.value.length &&
    selectableHistory.value.every((video) => historySelection.value.includes(video.oid))
)
const historySomeSelected = computed(() =>
  selectableHistory.value.some((video) => historySelection.value.includes(video.oid))
)
let channelHistoryVersion = 0
const language = ref('zh')
const loading = ref(true)
const searching = ref(false)
const searchTaskId = ref(null)
const searchMessage = ref('')
const submitting = ref(false)
const error = ref('')
const pollError = ref('')
const discovery = ref(null)
const discoveredAccount = ref('')
const selectedOids = ref([])
const tasks = ref([])
const historyAccount = ref('')
const historyAccounts = computed(() => [...new Set(tasks.value.map((task) => task.account))])
const historyTasks = computed(() =>
  tasks.value.filter((task) => !historyAccount.value || task.account === historyAccount.value)
)
const historyGroups = computed(() => {
  const groups = new Map()
  const ordered = [...historyTasks.value].sort((a, b) =>
    formatDateTime(b.created_at, 'YYYY-MM-DD HH:mm:ss').localeCompare(
      formatDateTime(a.created_at, 'YYYY-MM-DD HH:mm:ss')
    )
  )
  for (const task of ordered) {
    const date = formatDateTime(task.created_at, 'YYYY年M月D日')
    if (!groups.has(date)) groups.set(date, [])
    groups.get(date).push(task)
  }
  return [...groups].map(([date, records]) => ({ date, tasks: records }))
})
const historyTitle = (task) => task.result?.items?.[0]?.title || `${task.account} · 视频转录`
const historySummary = (task) => {
  if (task.status === 'failed') return task.error || task.message || '转录失败，可查看详情后重试。'
  const transcript = task.result?.items?.find((item) => item.status === 'completed' && item.text)
  const text = transcript?.text?.replace(/\s+/g, ' ').trim() || task.message || '等待生成文字稿…'
  return text.length > 160 ? `${text.slice(0, 160)}…` : text
}
const selectedTaskId = ref('')
const taskDetails = ref(null)
const previewItem = ref(null)
const previewDescription = computed(
  () =>
    previewItem.value?.description_paragraphs ||
    (previewItem.value?.title ? [previewItem.value.title] : [])
)
const previewTranscript = computed(
  () =>
    previewItem.value?.transcript_paragraphs ||
    (previewItem.value?.text ? [previewItem.value.text] : [])
)
const previewCharacterCount = computed(() =>
  (previewItem.value?.text || '').replace(/\s/g, '').length.toLocaleString('zh-CN')
)
const downloading = ref(false)
const stopping = ref(false)
let timer
let disposed = false

const activeTask = computed(() =>
  tasks.value.find((task) => ['pending', 'running'].includes(task.status))
)
const currentTask = computed(
  () =>
    tasks.value.find((task) => task.id === selectedTaskId.value) ||
    activeTask.value ||
    tasks.value[0]
)
watch(historyAccount, () => {
  if (
    historyTasks.value.length &&
    !historyTasks.value.some((task) => task.id === currentTask.value?.id)
  )
    selectedTaskId.value = historyTasks.value[0].id
})
const items = computed(() => currentTask.value?.result?.items || [])
const completedItems = computed(() => items.value.filter((item) => item.status === 'completed'))
const pendingVideos = computed(
  () =>
    discovery.value?.videos?.filter(
      (video) =>
        !tasks.value.some((task) =>
          task.result?.items?.some((item) => item.oid === video.oid && item.status === 'completed')
        )
    ) || []
)
const discoveryMatches = computed(
  () => discovery.value && discoveredAccount.value === account.value.trim()
)
const filteredVideos = computed(() =>
  pendingVideos.value.filter((video) =>
    `${video.title || ''} ${video.oid}`
      .toLowerCase()
      .includes(videoFilter.value.trim().toLowerCase())
  )
)
const selectableVideos = computed(() => filteredVideos.value.slice(0, 100))
const allSelected = computed(
  () =>
    !!selectableVideos.value.length &&
    selectableVideos.value.every((video) => selectedOids.value.includes(video.oid))
)
const someSelected = computed(() =>
  selectableVideos.value.some((video) => selectedOids.value.includes(video.oid))
)
const validSettings = computed(() =>
  rangeOptions.some((option) => option.value === videoRange.value)
)
const canSearch = computed(
  () => !!account.value.trim() && sourceAvailable.value && validSettings.value && !searching.value
)
const sourceReady = computed(() => conversionReady.value)
const canStart = computed(
  () =>
    sourceReady.value &&
    account.value.trim() &&
    !activeTask.value &&
    !submitting.value &&
    !pollError.value &&
    validSettings.value &&
    !searching.value
)
const labels = {
  pending: '等待执行',
  running: '处理中',
  success: '已完成',
  failed: '失败',
  cancelled: '已停止',
  extracting: '提取音频',
  transcribing: '语音转写',
  completed: '已完成'
}
const label = (status) => labels[status] || status
const languageOptions = [
  { value: 'zh', label: '中文' },
  { value: 'auto', label: '自动检测' },
  { value: 'yue', label: '粤语' },
  { value: 'en', label: '英语' },
  { value: 'ja', label: '日语' },
  { value: 'ko', label: '韩语' }
]
let searchVersion = 0
watch([collectionMode, deviceId, videoRange], () => {
  searchVersion++
  discovery.value = null
  selectedOids.value = []
  error.value = ''
})
const connectionChanged = (state) => {
  cloudCollectorManaged.value = state.managedCloud === true
  collectionMode.value = state.mode
  deviceId.value = state.deviceId
  sourceAvailable.value = state.sourceReady
  conversionReady.value = state.ready
}
const openConnection = async () => {
  page.value = 'source'
  await nextTick()
  connectionSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const refreshTasks = async () => {
  try {
    const payload = await wxchannelsApi.tasks()
    if (disposed) return
    tasks.value = payload.tasks || []
    pollError.value = ''
    if (!selectedTaskId.value)
      selectedTaskId.value = activeTask.value?.id || tasks.value[0]?.id || ''
  } catch (cause) {
    if (!disposed) pollError.value = cause.message || '任务更新中断'
  } finally {
    loading.value = false
  }
}

const schedule = () => {
  clearTimeout(timer)
  if (disposed) return
  timer = setTimeout(
    async () => {
      await refreshTasks()
      schedule()
    },
    activeTask.value ? 2500 : 10000
  )
}

const search = async (fullRefresh = false, loadMore = false) => {
  if (!canSearch.value) return
  searching.value = true
  searchMessage.value = loadMore
    ? '正在从上次位置加载历史，跳过已保存视频…'
    : '正在添加视频号并加载指定范围的最新视频…'
  error.value = ''
  try {
    const query = account.value.trim()
    const version = ++searchVersion
    let result = await wxchannelsApi.videos({
      account: query,
      max_pages:
        fullRefresh === true
          ? null
          : loadMore
            ? 2
            : Math.max(2, Math.ceil((maxVideos.value || 20) / 15)),
      max_videos: maxVideos.value,
      load_more: loadMore === true,
      full_refresh: fullRefresh === true,
      collection_mode: collectionMode.value,
      device_id: deviceId.value
    })
    if (result.task_id) {
      searchTaskId.value = result.task_id
      const deadline = Date.now() + (fullRefresh ? 900000 : 180000)
      while (!disposed && version === searchVersion && Date.now() < deadline) {
        const task = await wxchannelsApi.task(result.task_id)
        searchMessage.value =
          task.status === 'pending'
            ? '云端采集正在排队，可停止等待后稍后重试。'
            : task.message || '正在获取最新视频…'
        if (task.status === 'success') {
          result = task.result
          break
        }
        if (['failed', 'cancelled'].includes(task.status))
          throw new Error(
            task.status === 'cancelled'
              ? '本次获取已停止，已保存的列表可继续查看'
              : task.error || '获取视频失败，请检查微信连接后重试'
          )
        await new Promise((resolve) => setTimeout(resolve, 1500))
      }
      if (disposed || version !== searchVersion) return
      if (result.task_id) {
        await wxchannelsApi.cancel(result.task_id)
        throw new Error('获取视频超时，已停止本次请求。请确认云端微信在线后重试。')
      }
    }
    if (disposed || version !== searchVersion) return
    if (result.error) throw new Error(result.error)
    discovery.value = result
    discoveredAccount.value = query
    videoFilter.value = ''
    selectedOids.value = []
    await refreshChannels()
    message.success(`视频号已保存，本次新增 ${result.new_count || 0} 条；更多历史可按需加载`)
    return result
  } catch (cause) {
    error.value = cause.message || '获取视频失败'
  } finally {
    searching.value = false
    searchTaskId.value = null
    searchMessage.value = ''
  }
}

const stopSearch = async () => {
  if (searchTaskId.value) await wxchannelsApi.cancel(searchTaskId.value)
}
const loadMoreHistory = async (channel) => {
  account.value = channel.username
  const result = await search(false, true)
  if (result)
    await viewChannelHistory(channels.value.find((item) => item.id === channel.id) || channel)
}

const refreshChannels = async () => {
  channelsLoading.value = true
  channelsError.value = ''
  try {
    const result = await wxchannelsApi.channels()
    if (!disposed) {
      channels.value = result.items || []
      if (!channelHistory.value && channels.value.length)
        await viewChannelHistory(channels.value[0])
    }
  } catch (cause) {
    if (!disposed) channelsError.value = cause.message || '视频号目录加载失败'
  } finally {
    channelsLoading.value = false
  }
}
const viewChannelHistory = async (channel, offset = 0) => {
  const version = ++channelHistoryVersion
  if (channelHistory.value?.id !== channel.id) {
    historyKeyword.value = ''
    historyDates.value = null
    historyFilters.value = {}
    historySelection.value = []
  }
  channelHistory.value = {
    ...channel,
    videos: [],
    total_count: channel.video_count || channel.total_count || 0
  }
  channelOffset.value = offset
  channelHistoryLoading.value = true
  channelHistoryError.value = ''
  try {
    const result = await wxchannelsApi.channelVideos(channel.id, offset, historyFilters.value)
    if (!disposed && version === channelHistoryVersion) channelHistory.value = result
  } catch (cause) {
    if (version === channelHistoryVersion)
      channelHistoryError.value = cause.message || '历史列表加载失败'
  } finally {
    if (version === channelHistoryVersion) channelHistoryLoading.value = false
  }
}
const openChannelVideos = async (channel) => {
  page.value = 'videos'
  await viewChannelHistory(channel)
}
const useSingleMode = () => {
  historyMode.value = 'single'
  historySelection.value = []
}
const clearHistoryDates = () => {
  historyDates.value = null
  applyHistoryFilters()
}

const addChannel = async () => {
  const query = libraryQuery.value.trim()
  if (!query || searching.value) return
  account.value = query
  if (!sourceAvailable.value) {
    await openConnection()
    message.info('请先连接微信，连接后可获取并保存这个视频号')
    return
  }
  const result = await search()
  if (result) {
    libraryQuery.value = ''
    const channel = channels.value.find((item) => item.id === result.channel_id)
    if (channel) await viewChannelHistory(channel)
  }
}
const updateChannel = async (channel, fullRefresh = false) => {
  account.value = channel.username
  if (!sourceAvailable.value) {
    await openConnection()
    message.info('请连接微信后更新列表，已保存的历史仍可浏览')
    return
  }
  const result = await search(fullRefresh)
  if (result) {
    await viewChannelHistory(channels.value.find((item) => item.id === channel.id) || channel)
  }
}
const applyHistoryFilters = () => {
  historySelection.value = []
  historyFilters.value = {
    keyword: historyKeyword.value.trim(),
    published_after: historyDates.value?.[0]?.startOf('day').unix(),
    published_before: historyDates.value?.[1]?.endOf('day').unix()
  }
  if (channelHistory.value) viewChannelHistory(channelHistory.value)
}
const clearHistoryFilters = () => {
  historyKeyword.value = ''
  historyDates.value = null
  applyHistoryFilters()
}
const toggleHistoryVideo = (oid, checked) => {
  if (checked && historySelection.value.length >= 100) {
    message.info('每批最多选择 100 条视频')
    return
  }
  historySelection.value = checked
    ? [...new Set([...historySelection.value, oid])]
    : historySelection.value.filter((value) => value !== oid)
}
const selectHistoryPage = (checked) => {
  const current = new Set(selectableHistory.value.map((video) => video.oid))
  historySelection.value = checked
    ? [...new Set([...historySelection.value, ...current])].slice(0, 100)
    : historySelection.value.filter((oid) => !current.has(oid))
}
const transcribeHistory = async (oids = []) => {
  if (!channelHistory.value || !libraryCanStart.value) return
  account.value = channelHistory.value.username
  await start(oids)
}

const transcribePreview = async () => {
  const video = libraryPreview.value
  if (!video) return
  libraryPreview.value = null
  await transcribeHistory([video.oid])
}
watch(
  () =>
    tasks.value
      .map((task) => `${task.id}:${task.status}:${task.result?.completed_count || 0}`)
      .join('|'),
  async (value, previous) => {
    if (!previous || value === previous) return
    await refreshChannels()
    if (page.value === 'videos' && channelHistory.value)
      await viewChannelHistory(channelHistory.value, channelOffset.value)
  }
)

const removeChannel = (channel) => {
  Modal.confirm({
    title: `移除“${channel.account}”？`,
    content: '移除保存的视频号及历史视频列表。已生成的文字稿和 Word 成果会保留。',
    okText: '移除',
    cancelText: '取消',
    okType: 'danger',
    async onOk() {
      try {
        await wxchannelsApi.deleteChannel(channel.id)
        if (channelHistory.value?.id === channel.id) {
          channelHistory.value = null
          channelHistoryVersion++
          historySelection.value = []
        }
        await refreshChannels()
        message.success('已移除保存的列表')
      } catch (cause) {
        message.error(cause.message || '移除失败')
        throw cause
      }
    }
  })
}

const start = async (oids = []) => {
  if (!canStart.value) return
  submitting.value = true
  error.value = ''
  try {
    const result = await wxchannelsApi.transcribe({
      account: account.value.trim(),
      max_pages: null,
      max_videos: oids.length || maxVideos.value,
      language: language.value,
      video_oids: oids,
      collection_mode: collectionMode.value,
      device_id: deviceId.value
    })
    if (!result.submitted) throw new Error(result.error || '任务提交失败')
    selectedTaskId.value = result.task_id
    await refreshTasks()
    schedule()
    page.value = 'tasks'
    message.success(result.created ? '转换任务已提交' : '已恢复正在执行的任务')
  } catch (cause) {
    error.value = cause.message || '任务提交失败'
  } finally {
    submitting.value = false
  }
}

const cancel = async () => {
  if (!activeTask.value || stopping.value) return
  stopping.value = true
  try {
    await wxchannelsApi.cancel(activeTask.value.id)
    await refreshTasks()
  } catch (cause) {
    error.value = cause.message || '停止任务失败'
  } finally {
    stopping.value = false
  }
}

const toggleOid = (oid, checked) => {
  if (checked && selectedOids.value.length >= 100) {
    message.info('每批最多选择 100 条视频')
    return
  }
  selectedOids.value = checked
    ? [...selectedOids.value, oid]
    : selectedOids.value.filter((id) => id !== oid)
}
const selectBatch = (checked) => {
  if (!checked) {
    const visible = new Set(selectableVideos.value.map((video) => video.oid))
    selectedOids.value = selectedOids.value.filter((id) => !visible.has(id))
    return
  }
  const merged = [
    ...new Set([...selectedOids.value, ...selectableVideos.value.map((video) => video.oid)])
  ]
  if (merged.length > 100) message.info('每批最多选择 100 条视频')
  selectedOids.value = merged.slice(0, 100)
}
const chooseTask = async (task) => {
  selectedTaskId.value = task.id
  page.value = 'tasks'
  await nextTick()
  taskDetails.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
const retry = (task) => {
  page.value = 'source'
  account.value = task.account
  selectedOids.value = []
  discovery.value = null
  message.info('已填入视频号，点击自动转录即可重试；已完成视频会自动跳过')
}

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
const historyCompletedItems = (task) =>
  (task.result?.items || []).filter((item) => item.status === 'completed')
const historyWorkspacePath = (task) =>
  historyCompletedItems(task).find((item) => item.workspace_path)?.workspace_path || ''
const historyFolder = (task) => historyWorkspacePath(task).replace(/\/[^/]+$/, '')
const openHistoryMarkdown = (task) => {
  workspacePreviewPath.value = historyWorkspacePath(task).replace(/\.docx$/i, '.md')
}
const previewHistory = (task) => {
  const completed = historyCompletedItems(task)
  if (!completed.length) {
    chooseTask(task)
    return
  }
  selectedTaskId.value = task.id
  previewItem.value = completed[0]
}
const downloadHistory = async (task) => {
  if (historyBusyId.value) return
  historyBusyId.value = task.id
  try {
    const completed = historyCompletedItems(task)
    const single = completed.length === 1 ? completed[0] : null
    const blob = single
      ? await wxchannelsApi.download(task.id, single.index)
      : await wxchannelsApi.archive(task.id)
    saveBlob(blob, single?.filename || `${task.account}文字稿.zip`)
  } catch (cause) {
    message.error(cause.message || '下载失败，请重试')
  } finally {
    historyBusyId.value = ''
  }
}
const deleteHistory = (task) => {
  Modal.confirm({
    title: '删除这条转录历史？',
    content:
      '仅删除这条任务记录，已保存到沙盒工作区的 Word、MD 文件和知识库内容会保留。删除后无法恢复此记录。',
    okText: '删除记录',
    cancelText: '取消',
    okButtonProps: { danger: true },
    async onOk() {
      try {
        await wxchannelsApi.deleteHistory(task.id)
        if (selectedTaskId.value === task.id) selectedTaskId.value = ''
        await refreshTasks()
        message.success('历史记录已删除')
      } catch (cause) {
        message.error(cause.message || '删除失败，请刷新后重试')
        throw cause
      }
    }
  })
}
const download = async (item) => {
  downloading.value = true
  try {
    const id = currentTask.value.id
    const blob = item
      ? await wxchannelsApi.download(id, item.index)
      : await wxchannelsApi.archive(id)
    saveBlob(blob, item?.filename || '视频号文字稿.zip')
  } catch (cause) {
    error.value = cause.message || '下载失败'
  } finally {
    downloading.value = false
  }
}
onMounted(async () => {
  await Promise.all([refreshTasks(), refreshChannels()])
  schedule()
})
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(timer)
})
</script>

<template>
  <a-config-provider :auto-insert-space-in-button="false">
    <div class="video-workspace">
      <aside class="video-sidebar">
        <div class="video-brand">
          <span class="video-symbol"><Film :size="20" /></span>
          <div>
            <h2>视频号转 DOCX</h2>
            <small>采集 · 转录 · 知识沉淀</small>
          </div>
        </div>
        <nav class="video-nav" aria-label="视频号功能">
          <p class="video-nav-label">内容采集</p>
          <template v-for="entry in navigation" :key="entry.id">
            <button
              :class="{ active: page === entry.id }"
              :aria-current="page === entry.id ? 'page' : undefined"
              @click="page = entry.id"
            >
              <component :is="entry.icon" :size="17" /><span>{{ entry.title }}</span
              ><span
                v-if="entry.id === 'tasks' && activeTask"
                class="video-nav-dot"
                aria-label="任务执行中"
              /><small v-if="entry.id === 'artifacts' && artifactCount">{{ artifactCount }}</small>
            </button>
          </template>
        </nav>
        <button class="video-connection-shortcut" @click="openConnection">
          <CheckCircle2 v-if="sourceAvailable" :size="15" /><Circle v-else :size="15" /><span>{{
            sourceAvailable ? (conversionReady ? '微信已连接' : '转录服务待就绪') : '等待微信连接'
          }}</span
          ><ArrowRight :size="14" />
        </button>
      </aside>

      <main class="video-main">
        <div class="video-content">
          <header class="video-heading">
            <div>
              <h2>{{ currentPage.title }}</h2>
              <p>{{ currentPage.description }}</p>
            </div>
            <a-button v-if="page !== 'source'" class="video-icon-button" @click="openConnection"
              ><span class="video-status-dot" :class="{ ready: conversionReady }" />{{
                conversionReady ? '连接正常' : '检查连接'
              }}</a-button
            >
          </header>
          <a-alert
            v-if="error"
            type="error"
            :message="error"
            show-icon
            closable
            class="video-notice"
            @close="error = ''"
          />
          <a-alert
            v-if="pollError"
            type="warning"
            :message="`${pollError}，请刷新任务恢复状态。`"
            show-icon
            class="video-notice"
            ><template #action
              ><a-button size="small" @click="refreshTasks">刷新任务</a-button></template
            ></a-alert
          >

          <div v-show="page === 'channels'" class="video-page-stack video-library">
            <section class="video-card video-library-search" aria-label="搜索并添加视频号">
              <div class="video-section-heading">
                <h3><Search :size="20" />搜索并添加视频号</h3>
                <a-button type="text" size="small" @click="openConnection"
                  ><Circle v-if="!sourceAvailable" :size="13" /><CheckCircle2 v-else :size="13" />{{
                    sourceAvailable
                      ? cloudCollectorManaged
                        ? '云端微信已连接'
                        : '微信已连接'
                      : cloudCollectorManaged
                        ? '检查云端连接'
                        : '连接微信'
                  }}</a-button
                >
              </div>
              <div class="video-library-add-row">
                <a-input
                  v-model:value="libraryQuery"
                  size="large"
                  allow-clear
                  placeholder="输入视频号名称或 @finder 账号 ID"
                  aria-label="搜索并添加视频号"
                  :maxlength="200"
                  @press-enter="addChannel"
                  ><template #prefix><Search :size="18" /></template
                ></a-input>
                <a-button
                  type="primary"
                  size="large"
                  :loading="searching"
                  :disabled="!libraryQuery.trim() || searching"
                  @click="addChannel"
                  ><Plus :size="17" />获取并添加</a-button
                >
              </div>
              <p class="video-hint">
                先保存视频号并默认加载最新两页，更多历史由你按需加载，已保存视频自动去重。你的收藏和转录记录仅自己可见。
              </p>
              <a-alert v-if="searching" :message="searchMessage" type="info" show-icon>
                <template #action
                  ><a-button v-if="searchTaskId" size="small" @click="stopSearch"
                    >停止获取</a-button
                  ></template
                >
              </a-alert>
            </section>
            <section class="video-card video-library-saved" aria-label="已保存的视频号">
              <div class="video-section-heading">
                <h3>
                  <Star :size="20" />已保存的视频号<span class="video-library-count"
                    >{{ channels.length }} 个</span
                  >
                </h3>
                <a-button
                  type="text"
                  size="small"
                  aria-label="刷新视频号目录"
                  :loading="channelsLoading"
                  @click="refreshChannels"
                  ><RefreshCw :size="16"
                /></a-button>
              </div>
              <a-input
                v-if="channels.length > 4"
                v-model:value="channelFilter"
                allow-clear
                placeholder="查找已保存的视频号"
                aria-label="查找已保存的视频号"
                class="video-filter"
              />
              <a-alert v-if="channelsError" :message="channelsError" type="error" show-icon />
              <a-spin :spinning="channelsLoading">
                <div class="video-library-channel-list">
                  <article
                    v-for="channel in filteredChannels"
                    :key="channel.id"
                    class="video-library-channel"
                  >
                    <button
                      class="video-library-channel-identity"
                      @click="openChannelVideos(channel)"
                      :aria-label="`查看${channel.account}的视频`"
                    >
                      <span class="video-library-avatar"
                        >{{ (channel.account || '视').slice(0, 1) }}<Film :size="14"
                      /></span>
                      <span class="video-library-channel-copy"
                        ><strong>{{ channel.account }}</strong
                        ><small :title="channel.username">{{
                          channel.username.length > 28
                            ? `${channel.username.slice(0, 24)}…`
                            : channel.username
                        }}</small
                        ><span
                          >{{ channel.video_count }} 条视频 <span class="video-library-dot">·</span>
                          {{ formatRelative(channel.updated_at) }}更新</span
                        ></span
                      >
                    </button>
                    <div class="video-library-channel-actions">
                      <a-button type="primary" @click="openChannelVideos(channel)"
                        ><Film :size="15" />视频</a-button
                      >
                      <a-button
                        :loading="searching && account === channel.username"
                        :disabled="searching"
                        @click="updateChannel(channel)"
                        ><RefreshCw :size="14" />更新最新</a-button
                      >
                      <a-dropdown :trigger="['click']"
                        ><a-button
                          class="video-library-more"
                          :aria-label="`${channel.account}更多操作`"
                          ><MoreHorizontal :size="18" /></a-button
                        ><template #overlay
                          ><a-menu
                            ><a-menu-item
                              v-if="!channel.history_complete"
                              :disabled="searching"
                              @click="loadMoreHistory(channel)"
                            >
                              <Plus :size="14" />加载更多历史 </a-menu-item
                            ><a-menu-item
                              :disabled="searching"
                              @click="updateChannel(channel, true)"
                              ><RefreshCw :size="14" />完整同步历史</a-menu-item
                            ><a-menu-divider /><a-menu-item
                              danger
                              :disabled="searching"
                              @click="removeChannel(channel)"
                              ><Trash2 :size="14" />移除保存的列表</a-menu-item
                            ></a-menu
                          ></template
                        ></a-dropdown
                      >
                    </div>
                  </article>
                </div>
                <a-empty
                  v-if="!filteredChannels.length && !channelsLoading"
                  :description="
                    channelFilter
                      ? '没有找到匹配的视频号'
                      : '添加第一个视频号，建立你的专属视频资料库。'
                  "
                />
              </a-spin>
            </section>
          </div>
          <div
            v-show="page === 'videos'"
            class="video-page-stack video-library video-library-browse"
          >
            <section class="video-card video-library-selector" aria-label="选择视频号">
              <div class="video-section-heading">
                <h3><FolderOpen :size="16" />选择视频号</h3>
                <a-button type="text" size="small" @click="page = 'channels'"
                  ><Plus :size="14" />管理视频号</a-button
                >
              </div>
              <div class="video-library-tabs" aria-label="按视频号切换">
                <button
                  v-for="channel in channels"
                  :key="channel.id"
                  :class="{ active: channelHistory?.id === channel.id }"
                  @click="viewChannelHistory(channel)"
                >
                  {{ channel.account }}
                </button>
              </div>
              <a-empty
                v-if="!channels.length && !channelsLoading"
                description="先添加视频号，即可浏览已保存的视频列表。"
                ><a-button type="primary" @click="page = 'channels'">添加视频号</a-button></a-empty
              >
            </section>
            <template v-if="channelHistory">
              <div class="video-library-toolbar">
                <div class="video-library-filter-row">
                  <a-input
                    v-model:value="historyKeyword"
                    allow-clear
                    placeholder="搜索视频标题…"
                    aria-label="搜索历史视频标题"
                    :maxlength="200"
                    @press-enter="applyHistoryFilters"
                    ><template #prefix><Search :size="16" /></template></a-input
                  ><a-button @click="applyHistoryFilters">搜索</a-button
                  ><a-button @click="clearHistoryFilters">清除</a-button>
                  <div class="video-library-mode-switch">
                    <a-button
                      :type="historyMode === 'single' ? 'primary' : 'default'"
                      @click="useSingleMode"
                      >单条</a-button
                    ><a-button
                      :type="historyMode === 'multi' ? 'primary' : 'default'"
                      @click="historyMode = 'multi'"
                      >多选</a-button
                    >
                  </div>
                </div>
                <div class="video-library-filter-row video-library-date-row">
                  <span class="video-library-date-label">时间范围</span
                  ><a-range-picker
                    v-model:value="historyDates"
                    aria-label="视频发布时间范围"
                    :placeholder="['开始日期', '结束日期']"
                    @change="applyHistoryFilters"
                  /><a-button @click="clearHistoryDates">重置</a-button>
                </div>
                <div class="video-library-batch-row">
                  <a-checkbox
                    v-if="historyMode === 'multi'"
                    :disabled="!selectableHistory.length"
                    :checked="historyAllSelected"
                    :indeterminate="historySomeSelected && !historyAllSelected"
                    @change="selectHistoryPage($event.target.checked)"
                    >选择本页</a-checkbox
                  ><span v-if="historySelection.length" class="video-library-selected-count"
                    >已选 {{ historySelection.length }} 条<a-button
                      type="link"
                      size="small"
                      @click="historySelection = []"
                      >取消</a-button
                    ></span
                  >
                  <span v-if="historyMode === 'single'" class="video-library-result-count"
                    >已加载 {{ channelHistory.total_count }} 条 ·
                    {{
                      channelHistory.history_complete ? '历史已全部加载' : '可继续加载历史'
                    }}</span
                  >
                  <a-button
                    v-if="!channelHistory.history_complete"
                    :loading="searching"
                    :disabled="searching || !sourceAvailable"
                    @click="loadMoreHistory(channelHistory)"
                    ><Plus :size="14" />加载更多历史</a-button
                  >
                  <div class="video-library-batch-actions">
                    <span class="video-library-range-label">转录范围</span>
                    <a-select
                      v-model:value="videoRange"
                      :options="rangeOptions"
                      aria-label="历史视频转录范围"
                    /><a-button
                      v-if="historySelection.length"
                      type="primary"
                      :disabled="!libraryCanStart"
                      :loading="submitting"
                      @click="transcribeHistory(historySelection)"
                      >转录所选 {{ historySelection.length }} 条</a-button
                    ><a-button
                      v-else
                      type="primary"
                      :disabled="!libraryCanStart"
                      :loading="submitting"
                      @click="transcribeHistory()"
                      >{{
                        maxVideos === null ? '转录全部未完成' : `转录最新 ${maxVideos} 条`
                      }}</a-button
                    >
                  </div>
                </div>
              </div>
              <a-alert
                v-if="channelHistoryError"
                :message="channelHistoryError"
                type="error"
                show-icon
                ><template #action
                  ><a-button size="small" @click="viewChannelHistory(channelHistory, channelOffset)"
                    >重试</a-button
                  ></template
                ></a-alert
              >
              <a-spin :spinning="channelHistoryLoading">
                <div class="video-library-entries">
                  <article
                    v-for="video in channelHistory.videos || []"
                    :key="video.oid"
                    class="video-library-entry"
                    :class="{ selected: historySelection.includes(video.oid) }"
                  >
                    <a-checkbox
                      v-if="historyMode === 'multi'"
                      :disabled="video.completed"
                      :checked="historySelection.includes(video.oid)"
                      :aria-label="`选择历史视频：${(video.title || '未提供简介').slice(0, 80)}`"
                      @change="toggleHistoryVideo(video.oid, $event.target.checked)"
                    />
                    <button
                      class="video-library-video-icon"
                      @click="libraryPreview = video"
                      :aria-label="`预览简介：${(video.title || '未提供简介').slice(0, 80)}`"
                    >
                      <Film :size="26" />
                    </button>
                    <div class="video-library-entry-copy">
                      <button class="video-library-entry-title" @click="libraryPreview = video">
                        {{ video.title || '未提供简介' }}
                      </button>
                      <div class="video-library-entry-meta">
                        <span>{{
                          video.published_at
                            ? formatDateTime(video.published_at * 1000, 'YYYY/MM/DD')
                            : '发布时间未知'
                        }}</span
                        ><span
                          class="video-library-status"
                          :class="{ completed: video.completed }"
                          >{{ video.completed ? '已转录' : '待转录' }}</span
                        >
                      </div>
                    </div>
                    <div class="video-library-entry-actions">
                      <a-button @click="libraryPreview = video"
                        ><Eye :size="14" /><span class="video-library-preview-label"
                          >预览</span
                        ></a-button
                      ><a-button
                        type="primary"
                        :disabled="video.completed || !libraryCanStart"
                        :loading="submitting"
                        @click="transcribeHistory([video.oid])"
                        >{{ video.completed ? '已转录' : '转录' }}</a-button
                      >
                    </div>
                  </article>
                </div>
                <a-empty
                  v-if="!channelHistoryLoading && !channelHistory.videos?.length"
                  :description="
                    historyFilters.keyword || historyDates
                      ? '没有符合筛选条件的视频，试试其他关键词或日期。'
                      : '暂无保存的视频，点击更新最新获取内容。'
                  "
                />
                <div
                  v-if="channelHistory.total_count > channelPageSize"
                  class="video-channel-pagination"
                >
                  <a-button
                    :disabled="channelHistoryLoading || channelOffset === 0"
                    @click="viewChannelHistory(channelHistory, channelOffset - channelPageSize)"
                    >上一页</a-button
                  ><span
                    >{{ Math.floor(channelOffset / channelPageSize) + 1 }} /
                    {{ Math.ceil(channelHistory.total_count / channelPageSize) }}</span
                  ><a-button
                    :disabled="
                      channelHistoryLoading ||
                      channelOffset + channelPageSize >= channelHistory.total_count
                    "
                    @click="viewChannelHistory(channelHistory, channelOffset + channelPageSize)"
                    >下一页</a-button
                  >
                </div>
              </a-spin>
              <a-alert v-if="searching" :message="searchMessage" type="info" show-icon>
                <template #action
                  ><a-button v-if="searchTaskId" size="small" @click="stopSearch"
                    >停止获取</a-button
                  ></template
                >
              </a-alert>
              <p v-if="!sourceAvailable" class="video-hint">
                历史列表可随时浏览。<a-button type="link" size="small" @click="openConnection"
                  >连接微信后转录或更新</a-button
                >
              </p>
            </template>
          </div>
          <a-modal
            :open="!!libraryPreview"
            title="视频简介"
            :footer="null"
            width="680px"
            @cancel="libraryPreview = null"
            ><p class="video-library-preview-meta">
              {{ channelHistory?.account }} ·
              {{
                libraryPreview?.published_at
                  ? formatDateTime(libraryPreview.published_at * 1000)
                  : '发布时间未知'
              }}
            </p>
            <div class="video-library-description">{{ libraryPreview?.title || '未提供简介' }}</div>
            <div class="video-library-preview-actions">
              <a-button @click="libraryPreview = null">关闭</a-button
              ><a-button
                type="primary"
                :disabled="libraryPreview?.completed || !libraryCanStart"
                @click="transcribePreview"
                >转录此视频</a-button
              >
            </div></a-modal
          >
          <div v-show="page === 'source'" class="video-page-stack">
            <a-button class="video-source-back" @click="page = 'videos'">返回视频转录</a-button>
            <div ref="connectionSection" class="video-inline-connection" aria-label="微信连接">
              <WechatConnectionStatus
                :busy="searching || submitting || !!activeTask"
                @change="connectionChanged"
              />
            </div>
            <div class="video-workflow">
              <span class="current"><span>1</span>选择视频</span><ArrowRight :size="14" /><span
                ><span>2</span>后台转录</span
              ><ArrowRight :size="14" /><span><span>3</span>沙盒预览与入库</span>
            </div>
            <section class="video-card">
              <div class="video-section-heading">
                <h3><Search :size="18" />查找视频号</h3>
              </div>
              <label for="video-account">视频号昵称或账号 ID</label>
              <div class="video-search-row">
                <a-input
                  id="video-account"
                  v-model:value="account"
                  allow-clear
                  placeholder="输入完整昵称或以 @finder 结尾的账号 ID"
                  :maxlength="200"
                  @press-enter="search"
                /><a-button
                  type="primary"
                  :loading="searching"
                  :disabled="!canSearch"
                  class="video-icon-button"
                  @click="search"
                  ><Search :size="15" />获取视频</a-button
                >
              </div>
              <p v-if="!sourceAvailable" class="video-hint" role="status">
                请先在上方完成微信连接，连接成功后即可获取视频和开始转录。
              </p>
              <section class="video-inline-settings" aria-label="转录设置">
                <h3><Settings2 :size="16" />转录设置</h3>
                <div class="video-settings">
                  <label
                    >获取范围<a-select
                      v-model:value="videoRange"
                      :options="rangeOptions"
                      aria-label="获取范围"
                    /><small
                      >按发布时间排序，跳过已转录视频后选取；全部表示已加载的未转录视频。</small
                    ></label
                  >
                  <label
                    >语音语言<a-select
                      v-model:value="language"
                      :options="languageOptions"
                      aria-label="语音语言"
                    /><small>选择内容语言，或自动检测。</small></label
                  >
                </div>
                <a-alert
                  v-if="!validSettings"
                  type="warning"
                  message="请选择最新 5、10、15、20 条或全部。"
                  show-icon
                />
                <p class="video-hint">
                  已转录视频自动跳过，不占本次名额；失败视频可重试。手动勾选时只转录所选视频（最多
                  100 条）。
                </p>
              </section>
              <div class="video-search-meta">
                <span
                  >{{ rangeLabel }} ·
                  {{ languageOptions.find((option) => option.value === language)?.label }}</span
                ><a-button
                  size="small"
                  :loading="submitting"
                  :disabled="!canStart"
                  @click="start()"
                  >{{ activeTask ? '已有任务执行中' : `转录${rangeLabel}` }}</a-button
                >
              </div>
              <a-alert v-if="searching" :message="searchMessage" type="info" show-icon>
                <template #action
                  ><a-button v-if="searchTaskId" size="small" @click="stopSearch"
                    >停止获取</a-button
                  ></template
                >
              </a-alert>
              <a-button
                v-if="discoveryMatches && discovery.has_more && !searching"
                @click="loadMoreHistory({ id: discovery.channel_id, username: discovery.username })"
                ><Plus :size="14" />加载更多历史</a-button
              >
              <p v-if="!sourceAvailable" class="video-hint">
                等待微信连接后可获取视频。你也可以先查看历史转录任务和沙盒成果。
              </p>
              <p v-else class="video-hint">
                默认只加载最新两页并保存视频号，不等待全部历史。可点击“加载更多历史”，或在管理菜单中完整同步。转录范围只针对已加载视频。
              </p>
            </section>
            <section class="video-card video-candidate-card" aria-label="待转录视频">
              <div class="video-section-heading">
                <h3>
                  <Film :size="18" />视频列表<span v-if="discoveryMatches" class="video-count">{{
                    pendingVideos.length
                  }}</span>
                </h3>
                <span v-if="discoveryMatches"
                  >已保存 {{ discovery.total_count }} 条 · 新增 {{ discovery.new_count || 0 }} 条 ·
                  已跳过 {{ discovery.completed_count }} 条 · 最新在前</span
                >
              </div>
              <template v-if="discoveryMatches">
                <a-input
                  v-model:value="videoFilter"
                  allow-clear
                  placeholder="筛选视频标题或 OID"
                  aria-label="筛选视频"
                  class="video-filter"
                  ><template #prefix><Search :size="14" /></template
                ></a-input>
                <div class="video-selection-bar">
                  <a-checkbox
                    :disabled="!selectableVideos.length"
                    :checked="allSelected"
                    :indeterminate="someSelected && !allSelected"
                    @change="selectBatch($event.target.checked)"
                    >选择本批</a-checkbox
                  ><span>已选 {{ selectedOids.length }} / 100</span
                  ><a-button
                    v-if="selectedOids.length"
                    type="text"
                    size="small"
                    @click="selectedOids = []"
                    >清空</a-button
                  ><a-button
                    type="primary"
                    :disabled="!canStart || !selectedOids.length"
                    :loading="submitting"
                    @click="start(selectedOids)"
                    >转录所选视频{{
                      selectedOids.length ? `（${selectedOids.length}）` : ''
                    }}</a-button
                  >
                </div>
                <div v-if="filteredVideos.length" class="video-candidates">
                  <div
                    v-for="video in filteredVideos"
                    :key="video.oid"
                    class="video-candidate"
                    :class="{ selected: selectedOids.includes(video.oid) }"
                  >
                    <a-checkbox
                      :checked="selectedOids.includes(video.oid)"
                      :aria-label="`选择视频：${video.title || video.oid}`"
                      @change="toggleOid(video.oid, $event.target.checked)"
                    /><span class="video-file-icon"><Film :size="18" /></span
                    ><span class="video-candidate-copy"
                      ><strong :title="video.title">{{ video.title || '未提供简介' }}</strong
                      ><small
                        >{{
                          video.published_at
                            ? formatDateTime(video.published_at * 1000)
                            : '发布时间未知'
                        }}
                        · {{ video.oid }}</small
                      ></span
                    >
                  </div>
                </div>
                <div v-else class="video-empty">
                  <CheckCircle2 :size="32" />
                  <h3>{{ videoFilter ? '没有匹配的视频' : '暂无待转录视频' }}</h3>
                  <p>
                    {{
                      videoFilter
                        ? '试试其他关键词，或清空筛选。'
                        : '本次获取的视频均已转换，或账号暂无视频。'
                    }}
                  </p>
                </div>
              </template>
              <div v-else class="video-empty" role="status">
                <Film :size="36" />
                <h3>{{ searching ? '正在获取视频…' : '从一个视频号开始' }}</h3>
                <p>
                  {{
                    searching
                      ? '获取结果后即可批量勾选，请稍候。'
                      : '输入视频号并获取列表，勾选你需要的内容。'
                  }}
                </p>
              </div>
            </section>
            <button v-if="activeTask" class="video-active-banner" @click="chooseTask(activeTask)">
              <ListChecks :size="18" /><span
                >{{ activeTask.account }} · {{ activeTask.message || '正在后台转录' }}</span
              ><strong>查看进度</strong><ArrowRight :size="15" />
            </button>
          </div>

          <div v-show="page === 'tasks'" class="video-task-layout">
            <section class="video-card video-history" aria-label="转录历史">
              <div class="video-history-header">
                <div class="video-section-heading">
                  <h3>转录历史</h3>
                  <span class="video-history-count">共 {{ historyTasks.length }} 次</span>
                  <a-button
                    type="text"
                    size="small"
                    aria-label="刷新转录任务"
                    :loading="loading"
                    @click="refreshTasks"
                    ><RefreshCw :size="15"
                  /></a-button>
                </div>
                <div class="video-history-filter">
                  <select v-model="historyAccount" aria-label="按视频号筛选转录历史">
                    <option value="">全部视频号</option>
                    <option v-for="name in historyAccounts" :key="name" :value="name">
                      {{ name }}
                    </option>
                  </select>
                  <ChevronDown :size="16" aria-hidden="true" />
                </div>
              </div>
              <a-spin :spinning="loading"
                ><a-empty v-if="!tasks.length" description="还没有转录任务"
                  ><a-button @click="page = 'videos'">选择视频</a-button></a-empty
                >
                <div v-if="tasks.length" class="video-history-list">
                  <a-empty v-if="!historyTasks.length" description="该视频号暂无转录记录" />
                  <section
                    v-for="group in historyGroups"
                    :key="group.date"
                    class="video-history-group"
                  >
                    <h4 class="video-history-date">
                      {{ group.date === '-' ? '日期未知' : group.date }}
                    </h4>
                    <article
                      v-for="task in group.tasks"
                      :key="task.id"
                      class="video-history-item"
                      :class="{ selected: currentTask?.id === task.id }"
                    >
                      <button
                        class="video-history-select"
                        :aria-pressed="currentTask?.id === task.id"
                        :aria-label="`${task.account}，${label(task.status)}，${historyTitle(task).slice(0, 80)}，${historyCompletedItems(task).length ? '预览文字稿' : '查看任务详情'}`"
                        :aria-haspopup="historyCompletedItems(task).length ? 'dialog' : undefined"
                        :title="
                          historyCompletedItems(task).length ? '点击预览文字稿' : '点击查看任务详情'
                        "
                        @click="previewHistory(task)"
                      >
                        <span class="video-history-copy">
                          <span class="video-history-title-row">
                            <strong class="video-history-title">{{ historyTitle(task) }}</strong>
                            <span class="video-history-status" :data-status="task.status">{{
                              label(task.status)
                            }}</span>
                          </span>
                          <span class="video-history-summary">{{ historySummary(task) }}</span>
                          <span class="video-history-meta">
                            <span class="video-history-account">{{ task.account }}</span>
                            <span>{{ task.result?.completed_count || 0 }} 份文字稿</span>
                            <time :title="formatDateTime(task.created_at)">{{
                              formatRelative(task.created_at)
                            }}</time>
                          </span>
                        </span>
                        <span class="video-history-document" aria-hidden="true">
                          <FileText :size="28" :stroke-width="1.5" />
                          <span>{{
                            task.result?.items?.length > 1
                              ? `${task.result.items.length} 条视频`
                              : '视频转录'
                          }}</span>
                        </span>
                      </button>
                      <div class="video-history-actions" :aria-label="`${task.account}任务操作`">
                        <a-button
                          :disabled="!historyCompletedItems(task).length"
                          @click="previewHistory(task)"
                          ><FileText :size="15" />查看文字稿</a-button
                        >
                        <a-button
                          :disabled="!historyWorkspacePath(task)"
                          :title="
                            historyWorkspacePath(task)
                              ? '预览首份 Markdown 文字稿'
                              : '暂无工作区文件，可前往沙盒成果刷新同步'
                          "
                          @click="openHistoryMarkdown(task)"
                          ><FileText :size="15" />打开 MD</a-button
                        >
                        <a-button
                          :disabled="!historyCompletedItems(task).length || !!historyBusyId"
                          :loading="historyBusyId === task.id"
                          @click="downloadHistory(task)"
                          ><Download :size="15" />{{
                            historyCompletedItems(task).length > 1 ? '下载 Word 合集' : '下载 Word'
                          }}</a-button
                        >
                        <a-button
                          :disabled="!historyWorkspacePath(task)"
                          :title="historyFolder(task) || '暂无工作区文件，可前往沙盒成果刷新同步'"
                          @click="
                            router.push({
                              path: '/workspace',
                              query: { open: `${historyFolder(task)}/` }
                            })
                          "
                          ><FolderOpen :size="15" />打开文件夹</a-button
                        >
                        <a-button
                          danger
                          class="video-history-delete"
                          :disabled="['pending', 'running'].includes(task.status)"
                          :title="
                            ['pending', 'running'].includes(task.status)
                              ? '请先停止任务再删除记录'
                              : '删除历史记录，保留成果文件'
                          "
                          @click="deleteHistory(task)"
                          ><Trash2 :size="15" />删除记录</a-button
                        >
                      </div>
                    </article>
                  </section>
                </div></a-spin
              >
            </section>
            <div ref="taskDetails" class="video-page-stack video-task-details">
              <section class="video-card" aria-label="转换进度">
                <div class="video-section-heading">
                  <h3>{{ currentTask?.account || '运行进度' }}</h3>
                  <a-tag
                    :color="
                      currentTask?.status === 'failed'
                        ? 'error'
                        : currentTask?.status === 'success'
                          ? 'success'
                          : 'default'
                    "
                    >{{ currentTask ? label(currentTask.status) : '等待任务' }}</a-tag
                  ><a-button
                    v-if="activeTask && currentTask?.id === activeTask.id"
                    size="small"
                    :loading="stopping"
                    :disabled="activeTask.cancel_requested"
                    class="video-icon-button"
                    @click="cancel"
                    ><Square :size="13" />{{
                      activeTask.cancel_requested ? '正在停止' : '停止任务'
                    }}</a-button
                  >
                </div>
                <p class="video-progress-message" role="status">
                  {{
                    currentTask?.error ||
                    currentTask?.message ||
                    '选择视频后开始转录，页面刷新后仍可恢复进度。'
                  }}
                </p>
                <a-progress
                  v-if="currentTask"
                  :percent="Math.round(currentTask.progress || 0)"
                  :status="
                    currentTask.status === 'failed'
                      ? 'exception'
                      : currentTask.status === 'success'
                        ? 'success'
                        : 'normal'
                  "
                />
                <dl class="video-counters">
                  <div>
                    <dt>已完成</dt>
                    <dd>{{ currentTask?.result?.completed_count || 0 }}</dd>
                  </div>
                  <div>
                    <dt>失败</dt>
                    <dd>{{ currentTask?.result?.failed_count || 0 }}</dd>
                  </div>
                  <div>
                    <dt>已跳过</dt>
                    <dd>{{ currentTask?.result?.skipped_count || 0 }}</dd>
                  </div>
                </dl>
                <p class="video-hint">
                  提取音频 → 语音转写 → 生成 DOCX。任务在后台执行，可离开页面稍后查看。
                </p>
              </section>
              <section class="video-card" aria-label="文字稿结果">
                <div class="video-section-heading">
                  <h3><FileText :size="18" />文字稿结果</h3>
                  <a-button
                    v-if="completedItems.length"
                    size="small"
                    :loading="downloading"
                    class="video-icon-button"
                    @click="download()"
                    ><Download :size="14" />下载本次 Word</a-button
                  >
                </div>
                <a-empty v-if="!items.length" description="转录完成后，文字稿会显示在这里" />
                <div
                  v-for="item in items"
                  :key="`${currentTask.id}-${item.index}`"
                  class="video-result-row"
                >
                  <div class="video-result-copy">
                    <strong :title="item.title">{{ item.title || '视频文字稿' }}</strong
                    ><small
                      >{{ label(item.status)
                      }}<span v-if="item.language"> · {{ item.language }}</span></small
                    >
                    <p v-if="item.error" class="video-result-error">{{ item.error }}</p>
                  </div>
                  <template v-if="item.status === 'completed'"
                    ><a-button size="small" @click="previewItem = item">预览</a-button
                    ><a-button size="small" :loading="downloading" @click="download(item)"
                      >下载</a-button
                    ></template
                  >
                </div>
                <div class="video-actions">
                  <a-button
                    v-if="
                      currentTask && ['success', 'failed', 'cancelled'].includes(currentTask.status)
                    "
                    :disabled="!!activeTask"
                    @click="retry(currentTask)"
                    >重试未完成视频</a-button
                  ><a-button type="primary" class="video-icon-button" @click="page = 'artifacts'"
                    >沙盒预览与入库<ArrowRight :size="15"
                  /></a-button>
                </div>
              </section>
            </div>
          </div>

          <div v-show="page === 'artifacts'">
            <CollectionArtifactsPanel source="wxchannels" @count="artifactCount = $event" />
          </div>
        </div>
      </main>
      <WorkspaceFileDrawer :path="workspacePreviewPath" @close="workspacePreviewPath = ''" />
      <a-drawer
        :open="!!previewItem"
        title="视频简介与文字稿"
        width="min(800px, 100vw)"
        :body-style="{ padding: '0', background: 'var(--gray-25)' }"
        @close="previewItem = null"
      >
        <template #extra
          ><a-button
            size="small"
            class="video-icon-button"
            :loading="downloading"
            @click="download(previewItem)"
            ><Download :size="14" />下载 Word</a-button
          ></template
        >
        <article v-if="previewItem" class="video-preview">
          <div class="video-preview-meta">
            <span>{{ currentTask?.account || '视频号文字稿' }}</span
            ><span>{{ previewCharacterCount }} 字 · 正文 {{ previewTranscript.length }} 段</span>
          </div>
          <details class="video-preview-description" open>
            <summary>
              <span class="video-preview-number">01</span>
              <h3>视频简介</h3>
              <small>点击收起 / 展开</small>
            </summary>
            <div class="video-preview-paragraphs">
              <p v-for="(paragraph, index) in previewDescription" :key="index">{{ paragraph }}</p>
              <p v-if="!previewDescription.length" class="video-hint">暂无简介</p>
            </div>
          </details>
          <section class="video-preview-transcript" aria-label="分段文字稿">
            <header>
              <span class="video-preview-number">02</span>
              <h3>文字稿</h3>
              <small>{{ previewTranscript.length }} 段</small>
            </header>
            <div class="video-preview-paragraphs">
              <p v-for="(paragraph, index) in previewTranscript" :key="index">{{ paragraph }}</p>
              <p v-if="!previewTranscript.length" class="video-hint">暂无文字稿</p>
            </div>
          </section>
        </article>
      </a-drawer>
    </div>
  </a-config-provider>
</template>

<style scoped>
/* 与公众号文章 platform-theme.css / style.css 共用尺寸与色彩规则。 */
.video-library {
  font-family:
    'HarmonyOS Sans SC',
    Inter,
    -apple-system,
    'PingFang SC',
    sans-serif;
  font-size: 13px;
  gap: 24px;
}
.video-library .video-card {
  padding: 24px;
  border-radius: 12px;
  border-color: var(--gray-200);
}
.video-library .video-section-heading {
  margin-bottom: 24px;
}
.video-library .video-section-heading h3 {
  font-size: 14px;
  gap: 8px;
  font-weight: 600;
}
.video-library .video-section-heading h3 > svg {
  color: var(--main-color);
  width: 16px;
  height: 16px;
}
.video-library-add-row {
  display: flex;
  gap: 8px;
}
.video-library-add-row > .ant-input-affix-wrapper {
  flex: 1;
  min-width: 0;
  border-color: var(--gray-300);
  border-radius: 8px;
}
.video-library-add-row > .ant-btn {
  height: 38px;
}
.video-library .video-hint {
  font-size: 12px;
  margin-top: 16px;
  color: var(--gray-600);
}
.video-library :deep(.ant-btn) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 12px;
  min-height: 32px;
  height: auto;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 400;
  box-shadow: none;
}
.video-library :deep(.ant-btn-default) {
  border-color: var(--gray-300);
  color: var(--gray-700);
  background: var(--gray-0);
}
.video-library :deep(.ant-btn-primary) {
  background: var(--main-color);
  color: #fff;
  border-color: var(--main-color);
}
.video-library :deep(.ant-btn-primary:disabled) {
  background: var(--gray-100);
  border-color: var(--gray-200);
  color: var(--gray-500);
}
.video-library :deep(.ant-input),
.video-library :deep(.ant-select),
.video-library :deep(.ant-picker) {
  font-size: 13px;
}
.video-library :deep(.ant-input-affix-wrapper),
.video-library :deep(.ant-select-selector),
.video-library :deep(.ant-picker) {
  border-color: var(--gray-300);
  border-radius: 8px;
}
.video-library-count {
  margin-left: auto;
  padding: 3px 10px;
  border-radius: 9999px;
  color: var(--main-color);
  background: var(--main-50);
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.video-library .video-section-heading h3 {
  flex: 1;
}
.video-library-channel-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.video-library-channel {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-50);
  transition:
    background 0.15s,
    border-color 0.15s;
}
.video-library-channel:hover {
  background: var(--gray-100);
  border-color: var(--gray-300);
}
.video-library-channel-identity {
  display: flex;
  gap: 16px;
  flex: 1;
  align-items: center;
  min-width: 0;
  border: 0;
  background: transparent;
  padding: 0;
  text-align: left;
  color: inherit;
  cursor: pointer;
}
.video-library-avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  border-radius: 8px;
  font-size: 20px;
  font-weight: 600;
  color: #fff;
  background: var(--main-color);
}
.video-library-channel-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.video-library-channel-copy strong {
  font-size: 14px;
  font-weight: 600;
  color: var(--gray-1000);
}
.video-library-channel-copy small,
.video-library-channel-copy > span {
  font-size: 11px;
  color: var(--gray-600);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.video-library-dot {
  margin: 0 4px;
}
.video-library-channel-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.video-library-channel-actions > .ant-btn:nth-child(2) {
  color: var(--main-color);
  border-color: var(--main-200);
  background: var(--main-50);
}
.video-library-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.video-library-tabs button {
  border: 1px solid var(--gray-300);
  padding: 8px 14px;
  border-radius: 6px;
  background: var(--gray-0);
  font: inherit;
  color: var(--gray-700);
  cursor: pointer;
}
.video-library-tabs button.active {
  color: #fff;
  background: var(--main-color);
  border-color: var(--main-color);
}
.video-library-selector > .video-section-heading {
  margin-bottom: 16px;
}
.video-library-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-0);
}
.video-library-filter-row,
.video-library-batch-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.video-library-filter-row > .ant-input-affix-wrapper {
  flex: 1;
  min-width: 160px;
  max-width: 440px;
}
.video-library-mode-switch {
  display: flex;
  gap: 4px;
  margin-left: auto;
}
.video-library-date-row :deep(.ant-picker) {
  flex: 1;
  max-width: 360px;
  min-width: 180px;
}
.video-library-date-label,
.video-library-range-label {
  color: var(--gray-700);
  font-size: 12px;
}
.video-library-batch-row {
  padding-top: 8px;
}
.video-library-result-count,
.video-library-selected-count {
  color: var(--gray-600);
  font-size: 12px;
}
.video-library-batch-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}
.video-library-batch-actions .ant-select {
  min-width: 104px;
}
.video-library-entries {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.video-library-entry {
  display: flex;
  gap: 16px;
  align-items: center;
  padding: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-50);
  transition:
    background 0.15s,
    border-color 0.15s;
}
.video-library-entry:hover {
  background: var(--gray-100);
  border-color: var(--gray-300);
}
.video-library-entry.selected {
  border-color: var(--main-color);
  background: var(--main-50);
}
.video-library-video-icon {
  width: 100px;
  height: 70px;
  flex-shrink: 0;
  border: 1px solid var(--gray-200);
  border-radius: 6px;
  display: grid;
  place-items: center;
  color: var(--gray-500);
  background: var(--gray-100);
  cursor: pointer;
}
.video-library-entry-copy {
  flex: 1;
  min-width: 0;
}
.video-library-entry-title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  border: 0;
  padding: 0;
  margin-bottom: 8px;
  background: transparent;
  color: var(--gray-1000);
  font: inherit;
  font-size: 14px;
  line-height: 1.55;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  overflow-wrap: anywhere;
}
.video-library-entry-title:hover {
  color: var(--main-color);
}
.video-library-entry-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  font-size: 11px;
  color: var(--gray-600);
}
.video-library-status {
  padding: 2px 8px;
  border-radius: 9999px;
  color: var(--main-color);
  background: var(--main-50);
  font-size: 11px;
}
.video-library-status.completed {
  color: var(--color-success-700);
  background: var(--color-success-50);
}
.video-library-entry-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}
.video-channel-pagination {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: center;
  margin-top: 20px;
  color: var(--gray-600);
  font-size: 12px;
}
.video-library-description {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.9;
  max-height: 55vh;
  overflow: auto;
  font-size: 15px;
  color: var(--gray-800);
}
.video-library-preview-meta {
  color: var(--gray-600);
  font-size: 12px;
  margin-bottom: 16px;
}
.video-library-preview-actions {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.video-source-back {
  align-self: flex-start;
}
@media (max-width: 768px) {
  .video-library .video-card {
    padding: 24px;
  }
  .video-library-preview-label {
    display: none;
  }
  .video-library-entry-actions {
    gap: 6px;
  }
  .video-library-video-icon {
    width: 80px;
    height: 66px;
  }
  .video-library-entry {
    gap: 12px;
  }
}
@media (max-width: 520px) {
  .video-library .video-card {
    padding: 18px;
  }
  .video-library-channel {
    flex-wrap: wrap;
    gap: 12px;
  }
  .video-library-channel-identity {
    flex-basis: 100%;
  }
  .video-library-channel-actions {
    margin-left: 64px;
  }
  .video-library-add-row {
    flex-wrap: wrap;
  }
  .video-library-add-row > .ant-input-affix-wrapper {
    flex-basis: 100%;
  }
  .video-library-add-row > .ant-btn {
    width: 100%;
  }
  .video-library-mode-switch {
    margin-left: 0;
  }
  .video-library-date-label {
    flex-basis: 100%;
  }
  .video-library-batch-actions {
    width: 100%;
    margin-left: 0;
  }
  .video-library-entry {
    padding: 12px;
    gap: 10px;
    flex-wrap: wrap;
  }
  .video-library-video-icon {
    width: 56px;
    height: 56px;
  }
  .video-library-entry-actions {
    flex-basis: 100%;
    justify-content: flex-end;
  }
}
.video-workspace {
  display: flex;
  min-height: 680px;
  height: 100%;
  color: var(--gray-800);
  background: var(--gray-25);
}
.video-sidebar {
  width: 210px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--gray-200);
  background: var(--gray-0);
}
.video-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 22px 18px;
  border-bottom: 1px solid var(--gray-200);
}
.video-brand h2 {
  font-size: 16px;
  margin: 0 0 4px;
  font-weight: 600;
}
.video-brand small {
  font-size: 11px;
  color: var(--gray-600);
}
.video-symbol {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 8px;
  background: var(--main-50);
  color: var(--main-color);
}
.video-nav {
  padding: 16px 12px;
}
.video-nav-label {
  margin: 4px 12px 10px;
  font-size: 11px;
  color: var(--gray-600);
}
.video-nav button {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 10px 12px;
  margin-bottom: 4px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--gray-700);
  cursor: pointer;
  text-align: left;
  font-size: 13px;
}
.video-nav button:hover {
  background: var(--gray-50);
}
.video-nav button.active {
  background: var(--main-50);
  color: var(--main-800);
  font-weight: 500;
}
.video-nav button small {
  margin-left: auto;
  font-size: 11px;
}
.video-nav-dot,
.video-status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--gray-400);
  flex-shrink: 0;
}
.video-nav-dot {
  margin-left: auto;
  background: var(--main-color);
}
.video-status-dot.ready {
  background: var(--color-success-500);
}
.video-connection-shortcut {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: auto 12px 16px;
  padding: 12px 8px;
  border: 0;
  border-top: 1px solid var(--gray-200);
  background: transparent;
  color: var(--gray-600);
  font-size: 12px;
  cursor: pointer;
}
.video-connection-shortcut span {
  flex: 1;
  text-align: left;
}
.video-main {
  flex: 1;
  min-width: 0;
  padding: 24px 28px 40px;
  overflow: auto;
}
.video-content {
  max-width: 1120px;
  margin: 0 auto;
}
.video-heading,
.video-section-heading,
.video-actions,
.video-search-row,
.video-search-meta,
.video-selection-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.video-heading {
  justify-content: space-between;
  margin-bottom: 24px;
}
.video-heading h2 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 600;
}
.video-heading p {
  margin: 0;
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.8;
}
.video-heading > button {
  flex-shrink: 0;
}
.video-page-stack {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}
.video-inline-connection {
  scroll-margin-top: 20px;
}
.video-inline-connection :deep(.wechat-connection) {
  margin-bottom: 0;
}
.video-card {
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 22px;
  background: var(--gray-0);
  min-width: 0;
}
.video-card h3 {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 14px;
  margin: 0 0 20px;
  font-weight: 600;
}
.video-card h3 > svg {
  color: var(--main-color);
  flex-shrink: 0;
}
.video-card > label {
  display: block;
  font-size: 13px;
  margin-bottom: 8px;
}
.video-section-heading {
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.video-section-heading h3 {
  margin: 0;
  margin-right: auto;
  min-width: 0;
  overflow-wrap: anywhere;
}
.video-section-heading > span,
.video-search-meta {
  color: var(--gray-600);
  font-size: 12px;
}
.video-search-row > .ant-input-affix-wrapper {
  flex: 1;
  min-width: 0;
}
.video-search-meta {
  justify-content: space-between;
  flex-wrap: wrap;
  margin-top: 14px;
}
.video-hint {
  font-size: 12px;
  line-height: 1.8;
  color: var(--gray-600);
  margin: 12px 0 0;
}
.video-icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.video-workflow {
  display: flex;
  align-items: center;
  gap: 18px;
  color: var(--gray-500);
  font-size: 12px;
  flex-wrap: wrap;
}
.video-workflow > span {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.video-workflow > span > span {
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--gray-100);
  width: 22px;
  height: 22px;
  font-size: 11px;
}
.video-workflow .current {
  color: var(--main-color);
}
.video-workflow .current > span {
  background: var(--main-50);
}
.video-count {
  display: inline-block;
  padding: 2px 7px;
  border-radius: 5px;
  background: var(--gray-50);
  color: var(--gray-600);
  font-size: 11px;
  font-weight: 400;
}
.video-filter {
  max-width: 360px;
  margin-bottom: 16px;
}
.video-selection-bar {
  flex-wrap: wrap;
  padding: 12px;
  background: var(--gray-50);
  border-radius: 8px;
  font-size: 12px;
}
.video-selection-bar > span {
  color: var(--gray-600);
  margin-right: auto;
}
.video-candidates {
  max-height: 480px;
  overflow: auto;
  margin-top: 12px;
}
.video-candidate {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 10px;
  border-bottom: 1px solid var(--gray-100);
  cursor: pointer;
}
.video-candidate:hover {
  background: var(--gray-50);
}
.video-candidate.selected {
  background: var(--main-50);
}
.video-file-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 40px;
  background: var(--gray-50);
  border-radius: 6px;
  color: var(--main-color);
  flex-shrink: 0;
}
.video-candidate-copy,
.video-result-copy {
  min-width: 0;
  flex: 1;
}
.video-candidate-copy strong,
.video-result-copy strong {
  font-size: 13px;
  font-weight: 500;
  line-height: 1.7;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}
.video-candidate-copy small,
.video-result-copy small {
  display: block;
  color: var(--gray-600);
  font-size: 11px;
  margin-top: 4px;
  overflow-wrap: anywhere;
}
.video-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 50px 20px;
  color: var(--gray-500);
  border: 1px dashed var(--gray-200);
  border-radius: 8px;
  margin-top: 4px;
}
.video-empty h3 {
  font-size: 15px;
  font-weight: 500;
  color: var(--gray-700);
  margin: 16px 0 8px;
}
.video-empty p {
  font-size: 13px;
  margin: 0;
  line-height: 1.8;
}
.video-active-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  background: var(--main-50);
  color: var(--main-800);
  cursor: pointer;
  font-size: 13px;
  text-align: left;
}
.video-active-banner span {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.video-active-banner strong {
  font-weight: 500;
  flex-shrink: 0;
}
.video-task-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
  gap: 20px;
}
.video-task-details {
  scroll-margin-top: 20px;
}
.video-history {
  padding: 0;
  overflow: hidden;
  background: var(--gray-25);
}
.video-history-header {
  padding: 22px;
  border-bottom: 1px solid var(--gray-200);
}
.video-history .video-section-heading {
  margin-bottom: 18px;
}
.video-history .video-section-heading h3 {
  font-size: 18px;
}
.video-history .video-history-count {
  padding: 4px 10px;
  border-radius: 20px;
  color: var(--main-color);
  background: var(--main-50);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.video-history-filter {
  position: relative;
}
.video-history-filter select {
  appearance: none;
  width: 100%;
  padding: 11px 40px 11px 16px;
  border: 1px solid var(--gray-200);
  border-radius: 9px;
  background: var(--gray-0);
  color: var(--gray-900);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
  text-overflow: ellipsis;
}
.video-history-filter select:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 2px;
}
.video-history-filter > svg {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  color: var(--gray-700);
}
.video-history-list {
  padding: 6px 22px 22px;
}
.video-history-date {
  margin: 26px 0 12px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--gray-300);
  color: var(--gray-600);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.video-history-item {
  width: 100%;
  margin-top: 12px;
  text-align: left;
  border: 1px solid var(--gray-200);
  background: var(--gray-0);
  color: inherit;
  font: inherit;
  border-radius: 10px;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.video-history-select {
  display: flex;
  align-items: center;
  gap: 20px;
  width: 100%;
  padding: 18px;
  border: 0;
  border-radius: 10px 10px 0 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.video-history-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 14px 18px;
  border-top: 1px solid var(--gray-200);
}
.video-history-actions :deep(.ant-btn) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border-radius: 7px;
  font-size: 12px;
  box-shadow: none;
}
.video-history-delete {
  margin-left: auto;
}
.video-history-item:hover {
  border-color: var(--main-300);
  background: var(--main-10);
}
.video-history-item.selected {
  border-color: var(--main-300);
  background: var(--main-10);
  box-shadow: inset 3px 0 0 var(--main-color);
}
.video-history-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 10px;
}
.video-history-title-row {
  display: flex;
  align-items: start;
  gap: 12px;
}
.video-history-title {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  flex: 1;
  min-width: 0;
  color: var(--gray-900);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.video-history-status {
  flex-shrink: 0;
  padding: 2px 7px;
  margin-top: 3px;
  border-radius: 5px;
  color: var(--gray-600);
  background: var(--gray-100);
  font-size: 11px;
  line-height: 1.6;
}
.video-history-status[data-status='success'] {
  color: var(--color-success-700);
  background: var(--color-success-50);
}
.video-history-status[data-status='failed'] {
  color: var(--color-error-700);
  background: var(--color-error-50);
}
.video-history-status[data-status='running'],
.video-history-status[data-status='pending'] {
  color: var(--main-800);
  background: var(--main-50);
}
.video-history-summary {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  overflow-wrap: anywhere;
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.8;
}
.video-history-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  margin-top: 2px;
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.6;
}
.video-history-account {
  font-weight: 500;
  overflow-wrap: anywhere;
}
.video-history-meta time {
  margin-left: auto;
}
.video-history-document {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  width: 88px;
  height: 94px;
  flex-shrink: 0;
  border: 1px solid var(--main-100);
  border-radius: 9px;
  background: var(--main-50);
  color: var(--main-color);
  font-size: 11px;
}
.video-progress-message {
  line-height: 1.8;
  font-size: 13px;
  color: var(--gray-600);
  overflow-wrap: anywhere;
}
.video-counters {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 20px 0;
  padding: 16px;
  background: var(--gray-50);
  border-radius: 8px;
}
.video-counters dt {
  font-size: 12px;
  color: var(--gray-600);
}
.video-counters dd {
  margin: 5px 0 0;
  font-size: 24px;
  font-weight: 600;
}
.video-result-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 17px 0;
  border-bottom: 1px solid var(--gray-100);
}
.video-result-error {
  color: var(--error-color, #c34b4b);
  font-size: 12px;
}
.video-actions {
  justify-content: flex-end;
  margin-top: 20px;
  flex-wrap: wrap;
}
.video-inline-settings {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--gray-100);
}
.video-inline-settings h3 {
  margin-bottom: 16px;
}
.video-settings {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
  margin-bottom: 20px;
}
.video-settings label {
  display: grid;
  gap: 10px;
  font-size: 13px;
}
.video-settings small {
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.6;
}
.video-settings :deep(.ant-input-number),
.video-settings :deep(.ant-select) {
  width: 100%;
}
.video-notice {
  margin-bottom: 18px;
}
.video-preview {
  max-width: 760px;
  margin: 0 auto;
  padding: 24px 28px 40px;
  color: var(--gray-800);
}
.video-preview-meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 20px;
  color: var(--gray-600);
  font-size: 12px;
}
.video-preview-description,
.video-preview-transcript {
  padding: 22px 24px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-0);
}
.video-preview-description {
  margin-bottom: 20px;
}
.video-preview-description summary,
.video-preview-transcript header {
  display: flex;
  align-items: center;
  gap: 10px;
  list-style: none;
}
.video-preview-description summary {
  cursor: pointer;
}
.video-preview-description summary::-webkit-details-marker {
  display: none;
}
.video-preview h3 {
  margin: 0;
  font-size: 17px;
  font-weight: 600;
}
.video-preview summary small,
.video-preview header small {
  margin-left: auto;
  color: var(--gray-500);
  font-size: 11px;
}
.video-preview-number {
  color: var(--main-color);
  background: var(--main-50);
  padding: 4px 6px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 600;
}
.video-preview-paragraphs {
  margin-top: 20px;
}
.video-preview-paragraphs p {
  margin: 0 0 18px;
  font-size: 15px;
  line-height: 1.95;
  text-indent: 2em;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.video-preview-paragraphs p:last-child {
  margin-bottom: 0;
}
@media (max-width: 600px) {
  .video-preview {
    padding: 16px 12px 28px;
  }
  .video-preview-description,
  .video-preview-transcript {
    padding: 18px 16px;
  }
  .video-preview-paragraphs p {
    font-size: 14px;
    line-height: 1.9;
  }
}
button:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 2px;
}
@media (prefers-reduced-motion: reduce) {
  .video-history-item {
    transition: none;
  }
}
@media (max-width: 480px) {
  .video-history-document {
    display: none;
  }
}
@media (max-width: 1100px) {
  .video-task-layout {
    grid-template-columns: 1fr;
  }
  .video-settings {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 768px) {
  .video-history-header {
    padding: 18px;
  }
  .video-history-list {
    padding: 0 18px 18px;
  }
  .video-history-select {
    gap: 14px;
    padding: 14px;
  }
  .video-history-actions {
    padding: 12px 14px;
  }
  .video-history-document {
    width: 70px;
    height: 82px;
  }
  .video-workspace {
    flex-direction: column;
    height: auto;
    min-height: 580px;
  }
  .video-sidebar {
    width: 100%;
    border-right: 0;
    border-bottom: 1px solid var(--gray-200);
  }
  .video-brand,
  .video-nav-label,
  .video-connection-shortcut {
    display: none;
  }
  .video-nav {
    display: flex;
    overflow: auto;
    padding: 8px;
    gap: 4px;
  }
  .video-nav button {
    width: auto;
    flex-shrink: 0;
    margin: 0;
    white-space: nowrap;
  }
  .video-main {
    padding: 20px 16px;
    overflow: visible;
  }
  .video-heading {
    flex-wrap: wrap;
    gap: 12px;
  }
  .video-heading h2 {
    font-size: 20px;
  }
  .video-card {
    padding: 16px;
  }
  .video-workflow {
    gap: 8px;
    font-size: 11px;
  }
  .video-result-row {
    flex-wrap: wrap;
  }
  .video-result-copy {
    min-width: 100%;
  }
}
@media (max-width: 480px) {
  .video-search-row {
    flex-wrap: wrap;
  }
  .video-search-row > .ant-input-affix-wrapper {
    flex-basis: 100%;
  }
  .video-selection-bar > .ant-btn-primary {
    width: 100%;
  }
  .video-workflow > svg {
    display: none;
  }
}
</style>
