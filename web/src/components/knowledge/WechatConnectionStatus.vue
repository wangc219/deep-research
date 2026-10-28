<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CheckCircle2, Circle, Plug, RefreshCw } from '@lucide/vue'
import { wxchannelsApi } from '@/apis/wxchannels_api'
import { selectWechatConnection } from '@/utils/wechatConnection'

const props = defineProps({ busy: Boolean })
const emit = defineEmits(['change'])
const checking = ref(false)
const state = ref(null)
const error = ref('')
const downloading = ref(false)
const downloaded = ref(false)
const disconnecting = ref(false)
const platform = navigator.userAgent.includes('Windows') ? 'windows' : 'macos'
let enrollment = null
const managedCloud = computed(() => state.value?.managedCloud === true)
const description = computed(() => {
  if (error.value) return error.value
  if (managedCloud.value) {
    if (!state.value?.sourceReady)
      return '云端微信暂未就绪，请等待管理员完成登录。你无需下载或运行采集程序，已保存的列表和成果仍可查看。'
    return state.value.ready
      ? '已连接平台统一维护的云端微信，可直接获取视频并转录。无需安装本机程序。'
      : '云端微信已连接，可先浏览视频；转录服务正在准备中。'
  }
  if (!state.value?.sourceReady)
    return downloaded.value
      ? '连接程序已下载。请解压并双击“连接我的微信”，保持窗口运行，页面会自动确认连接。'
      : '点击“连接本机微信”，在这台电脑上运行下载的连接程序。只点击“重新检测”不会启动本机微信连接。'
  if (!state.value.ready) return '微信已连接，可先获取视频列表；转录服务就绪后即可开始转录。'
  return state.value.mode === 'personal'
    ? '已连接你的微信电脑，可获取视频并转录。请保持微信和连接窗口运行。'
    : '已连接微信采集端，可在下方输入视频号获取内容并转录。'
})
let timer
let disposed = false
let lastConnectAttempt = 0

const refresh = async () => {
  if (checking.value) return
  checking.value = true
  try {
    let video = await wxchannelsApi.status('central')
    if (disposed) return
    let connectionError = ''
    if (
      video?.api_available &&
      (!video.mcp_available || video.proxy_ready === false) &&
      Date.now() - lastConnectAttempt > 30000
    ) {
      lastConnectAttempt = Date.now()
      try {
        video = await wxchannelsApi.connect()
      } catch (cause) {
        connectionError = cause.message || '微信采集通道连接失败，请重新检测'
      }
    }
    if (disposed) return
    state.value = selectWechatConnection(video)
    error.value = state.value.sourceReady ? '' : connectionError
    emit('change', state.value)
  } catch (cause) {
    if (disposed) return
    state.value = selectWechatConnection(managedCloud.value ? { central_managed: true } : null)
    error.value = cause.message || '连接检测暂不可用，请稍后重试'
    emit('change', state.value)
  } finally {
    if (!disposed) checking.value = false
  }
}
const schedule = () => {
  timer = setTimeout(
    async () => {
      if (!props.busy) await refresh()
      if (!disposed) schedule()
    },
    state.value?.sourceReady ? 15000 : 3000
  )
}
defineExpose({ refresh })
const reconnect = () => {
  lastConnectAttempt = 0
  return refresh()
}
const connect = async (target = platform) => {
  if (props.busy || downloading.value) return
  downloading.value = true
  error.value = ''
  try {
    if (!enrollment || enrollment.platform !== target) {
      const bytes = crypto.getRandomValues(new Uint8Array(32))
      enrollment = {
        device_id: `wxd_${crypto.randomUUID().replaceAll('-', '')}`,
        token: Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join(''),
        name: target === 'macos' ? '本机微信 · Mac' : '本机微信 · Windows',
        platform: target
      }
    }
    const blob = await wxchannelsApi.collectorPackage({
      ...enrollment,
      platform_url: window.location.origin
    })
    if (disposed) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '连接我的微信.zip'
    link.hidden = true
    document.body.appendChild(link)
    link.click()
    setTimeout(() => {
      link.remove()
      URL.revokeObjectURL(url)
    }, 60000)
    downloaded.value = true
    await reconnect()
  } catch (cause) {
    if (!disposed) error.value = cause.message || '连接程序下载失败，请重试'
  } finally {
    if (!disposed) downloading.value = false
  }
}
const disconnect = async () => {
  if (props.busy || disconnecting.value || !state.value?.deviceId) return
  disconnecting.value = true
  try {
    await wxchannelsApi.revokeCollector(state.value.deviceId)
    enrollment = null
    downloaded.value = false
    await refresh()
  } catch (cause) {
    if (!disposed) error.value = cause.message || '断开失败，请重试'
  } finally {
    if (!disposed) disconnecting.value = false
  }
}
onMounted(async () => {
  await refresh()
  if (!disposed) schedule()
})
onBeforeUnmount(() => {
  disposed = true
  clearTimeout(timer)
  enrollment = null
})
</script>

<template>
  <section class="wechat-connection" aria-label="微信自动连接">
    <div class="connection-line" :class="{ ready: state?.contentReady }">
      <CheckCircle2 v-if="state?.contentReady" :size="17" /><Circle v-else :size="17" />
      <strong role="status">{{
        managedCloud
          ? state?.contentReady
            ? '云端微信已连接'
            : checking
              ? '正在检测云端微信…'
              : '等待云端微信连接'
          : state?.contentReady
            ? '微信已连接'
            : checking
              ? '正在连接微信…'
              : '等待微信连接'
      }}</strong>
      <a-dropdown-button
        v-if="!checking && !error && !state?.sourceReady && !managedCloud"
        type="primary"
        :loading="downloading"
        :disabled="busy"
        @click="connect()"
      >
        <Plug :size="14" />连接本机微信
        <template #overlay
          ><a-menu @click="({ key }) => connect(key)"
            ><a-menu-item key="macos">下载 macOS 连接程序</a-menu-item
            ><a-menu-item key="windows">下载 Windows 连接程序</a-menu-item></a-menu
          ></template
        >
      </a-dropdown-button>
      <a-button size="small" type="text" :loading="checking" @click="reconnect"
        ><RefreshCw :size="13" />重新检测</a-button
      >
      <a-popconfirm
        v-if="state?.mode === 'personal' && state.sourceReady"
        title="断开这台电脑与当前账号的连接？正在运行的采集任务会停止。"
        ok-text="断开"
        cancel-text="取消"
        :disabled="busy"
        @confirm="disconnect"
        ><a-button size="small" type="text" :disabled="busy" :loading="disconnecting"
          >断开连接</a-button
        ></a-popconfirm
      >
    </div>
    <p>{{ description }}</p>
    <p v-if="state?.sourceReady && !state.ready" class="engine-error" role="status">
      {{
        state.video?.ffmpeg_available === false
          ? '服务器音频处理服务尚未就绪，请联系管理员。'
          : !state.video?.asr_available
            ? '服务器语音识别服务尚未就绪，请联系管理员。'
            : '微信电脑的音频处理程序尚未就绪，请检查连接窗口中的提示。'
      }}
    </p>
    <div v-if="managedCloud" class="connection-instructions" aria-label="云端微信连接说明">
      <h4>云端共享采集</h4>
      <p>
        微信由管理员统一登录和维护。普通用户直接添加视频号、更新列表、选择转录即可；收藏、转录记录、Word
        和知识库成果仍按各自账号隔离。
      </p>
      <p>登录失效时请联系管理员重新登录，网站会自动检测恢复。</p>
    </div>
    <div v-else class="connection-instructions" aria-label="微信连接操作说明">
      <h4>连接操作</h4>
      <ol>
        <li><strong>打开电脑微信：</strong>登录微信，进入视频号页面。</li>
        <li>
          <strong>启动连接程序：</strong
          >点击上方“连接本机微信”，解压下载的文件，双击“连接我的微信”。首次运行按系统提示完成授权；已有采集程序会自动复用。
        </li>
        <li>
          <strong>确认后开始：</strong
          >保持微信和连接窗口运行，点击“重新检测”。显示“微信已连接”后，在下方输入视频号，获取视频并选择转录。
        </li>
      </ol>
      <p class="connection-cloud-note">
        连接包在登录微信的电脑上运行，云服务器无需登录微信。转录完成后可在本站预览、下载 Word
        或保存到知识库。
      </p>
    </div>
  </section>
</template>

<style scoped>
.wechat-connection {
  padding: 16px 18px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  background: var(--gray-50);
  margin-bottom: 20px;
}
.connection-line {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--gray-600);
  font-size: 13px;
  flex-wrap: wrap;
}
.connection-line strong {
  margin-right: auto;
}
.connection-line :deep(button) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.connection-line.ready {
  color: var(--main-color);
}
p {
  font-size: 12px;
  line-height: 1.8;
  color: var(--gray-600);
  margin: 8px 0 0;
}
.connection-instructions {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--gray-200);
}
.connection-instructions h4 {
  margin: 0 0 8px;
  font-size: 13px;
  color: var(--gray-800);
}
.connection-instructions ol {
  margin: 0;
  padding-left: 20px;
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.9;
}
.connection-instructions li + li {
  margin-top: 6px;
}
.connection-instructions strong {
  color: var(--gray-700);
  font-weight: 500;
}
.connection-cloud-note {
  color: var(--gray-600);
}
.engine-error {
  color: var(--color-error-700);
}
</style>
