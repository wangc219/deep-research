<template>
  <div
    class="login-view"
    :class="{
      'has-alert': serverStatus === 'error',
      'has-expanded-form': isFirstRun || authMode === 'register'
    }"
  >
    <img class="hero-art-backdrop" :src="loginBgImage" alt="" aria-hidden="true" />
    <img class="hero-art" :src="loginBgImage" alt="武器装备创新研究场景" />
    <div class="hero-wash" aria-hidden="true"></div>
    <div v-if="serverStatus === 'error'" class="server-status-alert">
      <div class="alert-content">
        <exclamation-circle-icon class="alert-icon" :size="18" />
        <div class="alert-text">
          <strong>服务端连接失败</strong>
          <span>{{ serverError }}</span>
        </div>
        <button
          class="alert-retry"
          type="button"
          :disabled="healthChecking"
          @click="checkServerHealth"
        >
          {{ healthChecking ? '检查中' : '重试' }}
        </button>
      </div>
    </div>

    <header class="login-headline">
      <h1>创新为帆 探索未至之境</h1>
    </header>

    <main class="login-main">
      <section class="auth-panel" aria-label="账户访问">
        <div v-if="!isFirstRun && registrationEnabled" class="auth-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            :aria-selected="authMode === 'login'"
            :class="{ active: authMode === 'login' }"
            @click="switchAuthMode('login')"
          >
            登录
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="authMode === 'register'"
            :class="{ active: authMode === 'register' }"
            @click="switchAuthMode('register')"
          >
            注册
          </button>
        </div>

        <header class="form-header">
          <span class="form-eyebrow">{{ isFirstRun ? 'SYSTEM SETUP' : 'WELCOME' }}</span>
          <h2 v-if="isFirstRun">创建超级管理员</h2>
          <h2 v-else-if="authMode === 'register'">创建研究账户</h2>
          <h2 v-else>欢迎回来</h2>
          <p v-if="isFirstRun">首次启动需要完成组织与超级管理员初始化。</p>
          <p v-else-if="authMode === 'register'">选择所属部门后，以普通用户身份进入平台。</p>
          <p v-else>登录后继续你的深度研究。</p>
        </header>

        <div class="login-content" :class="{ 'is-initializing': isFirstRun }">
          <div v-if="isFirstRun" class="login-form login-form--init">
            <a-form :model="adminForm" @finish="handleInitialize" layout="vertical">
              <a-form-item
                label="UID"
                name="uid"
                :rules="[
                  { required: true, message: '请输入UID' },
                  {
                    pattern: /^[a-zA-Z0-9_]+$/,
                    message: 'UID只能包含字母、数字和下划线'
                  },
                  {
                    min: 3,
                    max: 20,
                    message: 'UID长度必须在3-20个字符之间'
                  }
                ]"
              >
                <a-input
                  v-model:value="adminForm.uid"
                  placeholder="请输入UID（3-20个字符）"
                  :maxlength="20"
                />
              </a-form-item>

              <a-form-item
                label="手机号（可选）"
                name="phone_number"
                :rules="[
                  {
                    validator: async (rule, value) => {
                      if (!value || value.trim() === '') {
                        return // 空值允许
                      }
                      const phoneRegex = /^1[3-9]\d{9}$/
                      if (!phoneRegex.test(value)) {
                        throw new Error('请输入正确的手机号格式')
                      }
                    }
                  }
                ]"
              >
                <a-input
                  v-model:value="adminForm.phone_number"
                  placeholder="可用于登录，可不填写"
                  :max-length="11"
                />
              </a-form-item>

              <a-form-item
                label="密码"
                name="password"
                :rules="[
                  { required: true, message: '请输入密码' },
                  {
                    min: MIN_PASSWORD_LENGTH,
                    message: `密码至少需要 ${MIN_PASSWORD_LENGTH} 个字符`
                  }
                ]"
              >
                <a-input-password
                  v-model:value="adminForm.password"
                  prefix-icon="lock"
                  :minlength="MIN_PASSWORD_LENGTH"
                />
              </a-form-item>

              <a-form-item
                label="确认密码"
                name="confirmPassword"
                :rules="[
                  { required: true, message: '请确认密码' },
                  { validator: validateConfirmPassword }
                ]"
              >
                <a-input-password v-model:value="adminForm.confirmPassword" prefix-icon="lock" />
              </a-form-item>

              <a-form-item v-if="showAgreementConsent" class="agreement-form-item">
                <div class="agreement-row">
                  <a-checkbox v-model:checked="agreementAccepted">
                    登录即代表同意
                    <a
                      class="agreement-link"
                      :href="userAgreementUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      @click.stop
                      >《用户协议》</a
                    >
                    <a
                      class="agreement-link"
                      :href="privacyPolicyUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      @click.stop
                      >《隐私协议》</a
                    >
                  </a-checkbox>
                </div>
              </a-form-item>

              <a-form-item>
                <a-button type="primary" html-type="submit" :loading="loading" block
                  >创建管理员账户</a-button
                >
              </a-form-item>
            </a-form>
          </div>

          <div v-else-if="authMode === 'login'" class="login-form">
            <a-form :model="loginForm" @finish="handleLogin" layout="vertical">
              <a-form-item
                label="登录账号"
                name="loginId"
                :rules="[{ required: true, message: '请输入UID或手机号' }]"
              >
                <a-input v-model:value="loginForm.loginId" placeholder="UID或手机号">
                  <template #prefix>
                    <user-icon size="18" />
                  </template>
                </a-input>
              </a-form-item>

              <a-form-item
                label="密码"
                name="password"
                :rules="[{ required: true, message: '请输入密码' }]"
              >
                <a-input-password v-model:value="loginForm.password">
                  <template #prefix>
                    <lock-icon size="18" />
                  </template>
                </a-input-password>
              </a-form-item>

              <a-form-item v-if="showAgreementConsent" class="agreement-form-item">
                <div class="agreement-row">
                  <a-checkbox v-model:checked="agreementAccepted">
                    登录即代表同意
                    <a
                      class="agreement-link"
                      :href="userAgreementUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      @click.stop
                      >《用户协议》</a
                    >
                    <a
                      class="agreement-link"
                      :href="privacyPolicyUrl"
                      target="_blank"
                      rel="noopener noreferrer"
                      @click.stop
                      >《隐私协议》</a
                    >
                  </a-checkbox>
                </div>
              </a-form-item>

              <a-form-item>
                <a-button
                  type="primary"
                  html-type="submit"
                  :loading="loading"
                  :disabled="isLocked"
                  block
                  size="large"
                >
                  <span v-if="isLocked">账户已锁定 {{ formatTime(lockRemainingTime) }}</span>
                  <span v-else>登录</span>
                </a-button>
              </a-form-item>
            </a-form>

            <div v-if="oidcChecking || oidcEnabled" class="third-party-login">
              <div class="divider"><span>或</span></div>
              <div v-if="oidcChecking" class="login-skeleton">
                <a-skeleton-button block size="large" :active="true" />
              </div>
              <a-button v-else size="large" block :loading="oidcLoading" @click="handleOIDCLogin">
                <template #icon><key-icon :size="18" /></template>
                {{ oidcButtonText }}
              </a-button>
            </div>
          </div>

          <div v-else class="login-form register-form">
            <a-form :model="registerForm" layout="vertical" @finish="handleRegister">
              <a-form-item
                label="用户名"
                name="username"
                :rules="[
                  { required: true, message: '请输入用户名' },
                  { min: 2, max: 20, message: '用户名长度必须在2-20个字符之间' },
                  { pattern: /^[一-龥a-zA-Z0-9_]+$/, message: '仅支持中文、英文、数字和下划线' }
                ]"
              >
                <a-input v-model:value="registerForm.username" placeholder="你的显示名称">
                  <template #prefix><user-icon :size="18" /></template>
                </a-input>
              </a-form-item>
              <a-form-item
                label="所属部门"
                name="department_id"
                :rules="[{ required: true, message: '请选择所属部门' }]"
              >
                <a-select
                  v-model:value="registerForm.department_id"
                  placeholder="请选择所属部门"
                  :options="registrationDepartmentOptions"
                  show-search
                  option-filter-prop="label"
                />
              </a-form-item>
              <a-form-item
                label="手机号（可选）"
                name="phone_number"
                :rules="[{ pattern: /^$|^1[3-9]\d{9}$/, message: '请输入正确的手机号' }]"
              >
                <a-input
                  v-model:value="registerForm.phone_number"
                  :maxlength="11"
                  placeholder="可用于登录"
                />
              </a-form-item>
              <a-form-item
                label="密码"
                name="password"
                :rules="[
                  { required: true, message: '请输入密码' },
                  {
                    min: MIN_PASSWORD_LENGTH,
                    message: `密码至少需要 ${MIN_PASSWORD_LENGTH} 个字符`
                  }
                ]"
              >
                <a-input-password v-model:value="registerForm.password">
                  <template #prefix><lock-icon :size="18" /></template>
                </a-input-password>
              </a-form-item>
              <a-form-item
                label="确认密码"
                name="confirmPassword"
                :rules="[
                  { required: true, message: '请再次输入密码' },
                  { validator: validateRegisterConfirmPassword }
                ]"
              >
                <a-input-password v-model:value="registerForm.confirmPassword">
                  <template #prefix><lock-icon :size="18" /></template>
                </a-input-password>
              </a-form-item>
              <a-form-item v-if="showAgreementConsent" class="agreement-form-item">
                <a-checkbox v-model:checked="agreementAccepted">
                  我已阅读并同意
                  <a
                    class="agreement-link"
                    :href="userAgreementUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    @click.stop
                    >《用户协议》</a
                  >
                  <a
                    class="agreement-link"
                    :href="privacyPolicyUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    @click.stop
                    >《隐私协议》</a
                  >
                </a-checkbox>
              </a-form-item>
              <a-form-item>
                <a-button type="primary" html-type="submit" size="large" block :loading="loading">
                  创建账户并进入
                </a-button>
              </a-form-item>
            </a-form>
          </div>

          <div v-if="errorMessage" class="error-message" role="alert">{{ errorMessage }}</div>
        </div>
        <footer class="auth-footer">
          <shield-check-icon :size="15" />
          <span>统一身份认证 · 部门权限隔离 · 操作全程审计</span>
        </footer>
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useInfoStore } from '@/stores/info'
import { useAgentStore } from '@/stores/agent'
import { message } from 'ant-design-vue'
import { healthApi } from '@/apis/system_api'
import { authApi } from '@/apis/auth_api'
import {
  User as UserIcon,
  Lock as LockIcon,
  Key as KeyIcon,
  AlertCircle as ExclamationCircleIcon,
  ShieldCheck as ShieldCheckIcon
} from '@lucide/vue'
import { tryAutoStartOIDC, sanitizeRedirect } from '@/utils/oidcAutoStart'
import { MIN_PASSWORD_LENGTH } from '@/utils/passwordValidation'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const infoStore = useInfoStore()
const agentStore = useAgentStore()

// 品牌展示数据
const loginBgImage = '/equipment-login-hero.png'
const userAgreementUrl = computed(() => {
  return infoStore.footer?.user_agreement_url?.trim() || ''
})
const privacyPolicyUrl = computed(() => {
  return infoStore.footer?.privacy_policy_url?.trim() || ''
})
const showAgreementConsent = computed(() => {
  return Boolean(userAgreementUrl.value && privacyPolicyUrl.value)
})

// 状态
const isFirstRun = ref(false)
const loading = ref(false)
const errorMessage = ref('')
const agreementAccepted = ref(false)
const serverStatus = ref('loading')
const serverError = ref('')
const healthChecking = ref(false)
const authMode = ref('login')
const registrationEnabled = ref(false)
const registrationDepartments = ref([])

// OIDC 相关状态
const oidcEnabled = ref(false)
const oidcLoading = ref(false)
const oidcChecking = ref(true)
const oidcButtonText = ref('OIDC 登录')

// 登录锁定相关状态
const isLocked = ref(false)
const lockRemainingTime = ref(0)
const lockCountdown = ref(null)

// 登录表单
const loginForm = reactive({
  loginId: '', // 支持uid或phone_number登录
  password: ''
})

const registerForm = reactive({
  username: '',
  department_id: null,
  phone_number: '',
  password: '',
  confirmPassword: ''
})

const registrationDepartmentOptions = computed(() => {
  const byId = new Map(
    registrationDepartments.value.map((department) => [department.id, department])
  )

  return registrationDepartments.value.map((department) => {
    const names = []
    const visited = new Set()
    let current = department
    while (current && !visited.has(current.id)) {
      visited.add(current.id)
      names.unshift(current.name)
      current = current.parent_id == null ? null : byId.get(current.parent_id)
    }
    return { value: department.id, label: names.join(' / ') }
  })
})

// 管理员初始化表单
const adminForm = reactive({
  uid: '', // 改为直接输入uid
  password: '',
  confirmPassword: '',
  phone_number: '' // 手机号字段（可选）
})

// 清理倒计时器
const clearLockCountdown = () => {
  if (lockCountdown.value) {
    clearInterval(lockCountdown.value)
    lockCountdown.value = null
  }
}

// 启动锁定倒计时
const startLockCountdown = (remainingSeconds) => {
  clearLockCountdown()
  isLocked.value = true
  lockRemainingTime.value = remainingSeconds

  lockCountdown.value = setInterval(() => {
    lockRemainingTime.value--
    if (lockRemainingTime.value <= 0) {
      clearLockCountdown()
      isLocked.value = false
      errorMessage.value = ''
    }
  }, 1000)
}

// 格式化时间显示
const formatTime = (seconds) => {
  if (seconds < 60) {
    return `${seconds}秒`
  } else if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}分${remainingSeconds}秒`
  } else if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}小时${minutes}分钟`
  } else {
    const days = Math.floor(seconds / 86400)
    const hours = Math.floor((seconds % 86400) / 3600)
    return `${days}天${hours}小时`
  }
}

// 密码确认验证
const validateConfirmPassword = async (rule, value) => {
  // 空值由 required 规则统一提示，避免两个规则同时生成重复错误。
  if (!value) return
  if (value !== adminForm.password) {
    throw new Error('两次输入的密码不一致')
  }
}

const validateRegisterConfirmPassword = async (rule, value) => {
  // 空值由 required 规则统一提示，当前校验器只负责一致性校验。
  if (!value) return
  if (value !== registerForm.password) throw new Error('两次输入的密码不一致')
}

const switchAuthMode = (mode) => {
  authMode.value = mode
  errorMessage.value = ''
}

const ensureAgreementAccepted = () => {
  if (!showAgreementConsent.value || agreementAccepted.value) {
    return true
  }

  const warningMessage = '请先阅读并同意《用户协议》《隐私协议》'
  message.warning(warningMessage)
  return false
}

// 处理登录
const handleLogin = async () => {
  // 如果当前被锁定，不允许登录
  if (isLocked.value) {
    message.warning(`账户被锁定，请等待 ${formatTime(lockRemainingTime.value)}`)
    return
  }

  if (!ensureAgreementAccepted()) {
    return
  }

  try {
    loading.value = true
    errorMessage.value = ''
    clearLockCountdown()

    await userStore.login({
      loginId: loginForm.loginId,
      password: loginForm.password
    })

    message.success('登录成功')

    // 获取重定向路径
    const redirectPath = sessionStorage.getItem('redirect') || '/knowledge'
    sessionStorage.removeItem('redirect') // 清除重定向信息

    // 根据用户角色决定重定向目标
    if (redirectPath === '/' || redirectPath === '/knowledge') {
      try {
        await agentStore.initialize()
        router.push('/knowledge')
      } catch (error) {
        console.error('获取智能体信息失败:', error)
        router.push('/knowledge')
      }
    } else {
      // 跳转到其他预设的路径
      router.push(redirectPath)
    }
  } catch (error) {
    console.error('登录失败:', error)

    // 检查是否是锁定错误（HTTP 423）
    if (error.status === 423) {
      // 尝试从响应头中获取剩余时间
      let remainingTime = 0
      if (error.headers && error.headers.get) {
        const lockRemainingHeader = error.headers.get('X-Lock-Remaining')
        if (lockRemainingHeader) {
          remainingTime = parseInt(lockRemainingHeader)
        }
      }

      // 如果没有从头中获取到，尝试从错误消息中解析
      if (remainingTime === 0) {
        const lockTimeMatch = error.message.match(/(\d+)\s*秒/)
        if (lockTimeMatch) {
          remainingTime = parseInt(lockTimeMatch[1])
        }
      }

      if (remainingTime > 0) {
        startLockCountdown(remainingTime)
        errorMessage.value = `由于多次登录失败，账户已被锁定 ${formatTime(remainingTime)}`
      } else {
        errorMessage.value = error.message || '账户被锁定，请稍后再试'
      }
    } else {
      errorMessage.value = error.message || '登录失败，请检查用户名和密码'
    }
  } finally {
    loading.value = false
  }
}

const handleRegister = async () => {
  if (!ensureAgreementAccepted()) return

  try {
    loading.value = true
    errorMessage.value = ''
    await userStore.register({
      username: registerForm.username.trim(),
      department_id: registerForm.department_id,
      phone_number: registerForm.phone_number.trim() || null,
      password: registerForm.password
    })
    message.success('注册成功，已为你登录')
    await agentStore.initialize().catch(() => undefined)
    router.push('/knowledge')
  } catch (error) {
    console.error('注册失败:', error)
    errorMessage.value = error.message || '注册失败，请检查填写信息'
  } finally {
    loading.value = false
  }
}

// 处理 OIDC 登录
const handleOIDCLogin = async () => {
  if (!ensureAgreementAccepted()) {
    return
  }

  try {
    oidcLoading.value = true
    errorMessage.value = ''

    // 获取 OIDC 登录 URL
    const response = await authApi.getOIDCLoginUrl()
    if (response.login_url) {
      // 保存当前路径，以便登录后返回
      const redirectPath =
        sessionStorage.getItem('redirect') || router.currentRoute.value.query.redirect || '/'
      sessionStorage.setItem('oidc_redirect', redirectPath)

      // 跳转到 OIDC Provider
      window.location.href = response.login_url
    } else {
      errorMessage.value = '获取 OIDC 登录地址失败'
    }
  } catch (error) {
    console.error('OIDC 登录失败:', error)
    errorMessage.value = error.message || 'OIDC 登录失败，请重试'
  } finally {
    oidcLoading.value = false
  }
}

// 检查 OIDC 配置
const checkOIDCConfig = async () => {
  oidcChecking.value = true
  try {
    const config = await authApi.getOIDCConfig()
    oidcEnabled.value = config.enabled
    if (config.provider_name) {
      oidcButtonText.value = config.provider_name
    }
    return config
  } catch (error) {
    console.error('检查 OIDC 配置失败:', error)
    oidcEnabled.value = false
    return null
  } finally {
    oidcChecking.value = false
  }
}

const checkRegistrationConfig = async () => {
  try {
    const config = await authApi.getRegistrationConfig()
    registrationEnabled.value = config?.enabled === true
    registrationDepartments.value = Array.isArray(config?.departments) ? config.departments : []
  } catch (error) {
    console.error('检查注册配置失败:', error)
    registrationEnabled.value = false
    registrationDepartments.value = []
  }
}

// 处理初始化管理员
const handleInitialize = async () => {
  if (!ensureAgreementAccepted()) {
    return
  }

  try {
    loading.value = true
    errorMessage.value = ''

    if (adminForm.password !== adminForm.confirmPassword) {
      errorMessage.value = '两次输入的密码不一致'
      return
    }

    await userStore.initialize({
      uid: adminForm.uid,
      password: adminForm.password,
      phone_number: adminForm.phone_number || null // 空字符串转为null
    })

    message.success('管理员账户创建成功')
    router.push('/knowledge')
  } catch (error) {
    console.error('初始化失败:', error)
    errorMessage.value = error.message || '初始化失败，请重试'
  } finally {
    loading.value = false
  }
}

// 检查是否是首次运行
const checkFirstRunStatus = async () => {
  try {
    loading.value = true
    const isFirst = await userStore.checkFirstRun()
    isFirstRun.value = isFirst
  } catch (error) {
    console.error('检查首次运行状态失败:', error)
    errorMessage.value = '系统出错，请稍后重试'
  } finally {
    loading.value = false
  }
}

// 检查服务器健康状态
const checkServerHealth = async () => {
  try {
    healthChecking.value = true
    const response = await healthApi.checkHealth()
    if (response.status === 'ok') {
      serverStatus.value = 'ok'
    } else {
      serverStatus.value = 'error'
      serverError.value = response.message || '服务端状态异常'
    }
  } catch (error) {
    console.error('检查服务器健康状态失败:', error)
    serverStatus.value = 'error'
    serverError.value = error.message || '无法连接到服务端，请检查网络连接'
  } finally {
    healthChecking.value = false
  }
}

// 组件挂载时
onMounted(async () => {
  // 如果已登录，按 redirect 参数跳转（不固定跳首页）
  if (userStore.isLoggedIn) {
    router.push(sanitizeRedirect(route.query.redirect))
    return
  }

  // 显示 OIDC 认证失败的错误信息（由后端重定向携带）
  if (route.query.oidc_error) {
    errorMessage.value = String(route.query.oidc_error)
  }

  // 首先检查服务器健康状态
  await checkServerHealth()

  // 检查是否是首次运行
  await checkFirstRunStatus()

  // 如果处于首次运行状态，不需要 OIDC 自动登录
  if (isFirstRun.value) {
    return
  }

  await checkRegistrationConfig()

  // 检查 OIDC 配置完成后，尝试自动触发 OIDC 登录（跨系统跳转场景）
  const config = await checkOIDCConfig()
  if (config && config.enabled) {
    const autoStarted = await tryAutoStartOIDC(async () => await authApi.getOIDCLoginUrl(), config)
    // 如果已发起 OIDC 跳转，页面会被重定向，不需要继续
    if (autoStarted) return
  }
})

// 组件卸载时清理定时器
onUnmounted(() => {
  clearLockCountdown()
})
</script>

<style lang="less" scoped>
.login-view {
  --auth-ink: #17215b;
  --auth-muted: #66709a;
  --auth-accent: #4d55c7;
  position: relative;
  display: block;
  min-height: 100svh;
  overflow: hidden auto;
  color: var(--auth-ink);
  background: #f7f8ff;
  isolation: isolate;

  &.has-alert {
    padding-top: 0;
  }
}

.hero-art-backdrop,
.hero-art,
.hero-wash {
  position: fixed;
  inset: 0;
  width: 100%;
  height: 100%;
}

.hero-art-backdrop {
  z-index: -5;
  object-fit: cover;
  object-position: center;
  filter: blur(18px) saturate(1.04);
  opacity: 0.62;
  transform: scale(1.05);
}

.hero-art {
  z-index: -4;
  object-fit: cover;
  object-position: center;
  filter: saturate(0.98) contrast(1.01);
}

.hero-wash {
  z-index: -3;
  background: rgba(239, 242, 255, 0.08);
}

.login-headline {
  position: absolute;
  top: clamp(32px, 5vh, 52px);
  right: 20px;
  left: 20px;
  z-index: 1;
  text-align: center;
  pointer-events: none;

  h1 {
    margin: 0;
    color: #303978;
    font-size: clamp(25px, 3vw, 42px);
    font-weight: 750;
    line-height: 1.35;
    letter-spacing: 0.07em;
    text-shadow: 0 2px 18px rgba(255, 255, 255, 0.95);
  }
}

.login-view.has-alert .login-headline {
  top: 88px;
}

.login-main {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  min-height: 100svh;
  padding: 24px;
}

.login-view.has-expanded-form .login-main {
  padding-top: 112px;
}

.auth-panel {
  position: relative;
  width: min(100%, 400px);
  padding: 23px 34px 20px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(126, 132, 196, 0.17);
  border-radius: 24px;
  box-shadow:
    0 28px 80px rgba(47, 53, 126, 0.16),
    inset 0 1px rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(28px) saturate(1.12);
}

@media (max-aspect-ratio: 8 / 5) {
  .hero-art {
    object-fit: contain;
  }
}

.auth-tabs {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 5px;
  padding: 4px;
  margin-bottom: 25px;
  background: rgba(232, 234, 248, 0.72);
  border-radius: 12px;

  button {
    padding: 9px 14px;
    color: #7b829f;
    font-weight: 650;
    background: transparent;
    border: 0;
    border-radius: 9px;
    cursor: pointer;
    transition: 160ms ease;

    &.active {
      color: #363e91;
      background: rgba(255, 255, 255, 0.94);
      box-shadow: 0 4px 14px rgba(61, 67, 142, 0.11);
    }
  }
}

.form-header {
  margin-bottom: 23px;
  text-align: left;

  .form-eyebrow {
    display: block;
    margin-bottom: 8px;
    color: #8188c8;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.22em;
  }

  h2 {
    margin: 0;
    color: #222b69;
    font-size: 25px;
    font-weight: 720;
    letter-spacing: -0.025em;
  }

  p {
    margin: 8px 0 0;
    color: #858ba7;
    font-size: 13px;
  }
}

.login-form {
  :deep(.ant-form-item) {
    margin-bottom: 17px;
  }

  :deep(.ant-form-item-label) {
    padding-bottom: 6px;
  }

  :deep(.ant-form-item-label > label) {
    height: auto;
    color: #535b7c;
    font-size: 12px;
    font-weight: 650;
  }

  :deep(.ant-input),
  :deep(.ant-input-affix-wrapper) {
    background: rgba(249, 250, 255, 0.86);
  }

  :deep(.ant-input-affix-wrapper),
  :deep(.ant-input:not(.ant-input-affix-wrapper .ant-input)) {
    min-height: 46px;
    padding: 10px 13px;
    border-color: #e0e2f0;
    border-radius: 11px;
    box-shadow: none;

    &:hover,
    &:focus,
    &.ant-input-affix-wrapper-focused {
      border-color: #7a80dc;
      box-shadow: 0 0 0 3px rgba(101, 108, 211, 0.1);
    }
  }

  :deep(.ant-input-prefix) {
    margin-right: 9px;
    color: #9ba0b9;
  }

  :deep(.ant-btn) {
    height: 46px;
    font-size: 14px;
    font-weight: 650;
    border-radius: 11px;
  }

  :deep(.ant-btn-primary) {
    background: linear-gradient(135deg, #626bd7, #414bb7);
    border: 0;
    box-shadow: 0 10px 24px rgba(66, 76, 184, 0.24);

    &:hover {
      background: linear-gradient(135deg, #6d75df, #4b55c1);
      transform: translateY(-1px);
    }
  }
}

.register-form :deep(.ant-form-item) {
  margin-bottom: 13px;
}

.agreement-form-item {
  margin-bottom: 13px !important;
}

.agreement-row,
.agreement-form-item {
  color: #777f9d;
  font-size: 12px;
  line-height: 1.6;
}

.agreement-link {
  color: #5962c8;
}

.third-party-login {
  margin-top: -2px;

  .divider {
    display: flex;
    gap: 12px;
    align-items: center;
    margin: 17px 0;
    color: #a3a8bc;
    font-size: 11px;

    &::before,
    &::after {
      position: static;
      flex: 1;
      width: auto;
      height: 1px;
      content: '';
      background: #e4e5ef;
    }

    span {
      padding: 0;
      color: inherit;
      background: transparent;
    }
  }

  :deep(.ant-btn) {
    height: 44px;
    color: #555d80;
    background: rgba(255, 255, 255, 0.55);
    border-color: #dfe1ed;
    border-radius: 11px;
  }
}

.login-skeleton :deep(.ant-skeleton-button) {
  width: 100% !important;
  height: 44px;
  border-radius: 11px;
}

.error-message {
  margin-top: 4px;
  padding: 10px 12px;
  color: #a74454;
  font-size: 12px;
  text-align: left;
  background: rgba(255, 239, 242, 0.92);
  border: 1px solid rgba(194, 75, 96, 0.16);
  border-radius: 10px;
}

.auth-footer {
  display: flex;
  gap: 7px;
  align-items: center;
  justify-content: center;
  padding-top: 18px;
  margin-top: 4px;
  color: #9398ae;
  font-size: 10px;
  border-top: 1px solid rgba(111, 119, 172, 0.1);
}

.server-status-alert {
  position: fixed;
  inset: 12px 12px auto;
  z-index: 20;
  padding: 0;
  color: #924152;
  background: rgba(255, 244, 246, 0.94);
  border: 1px solid rgba(187, 74, 94, 0.14);
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(103, 44, 57, 0.1);
  backdrop-filter: blur(16px);

  .alert-content {
    display: flex;
    gap: 10px;
    align-items: center;
    max-width: none;
    padding: 10px 14px;
  }

  .alert-text {
    display: flex;
    flex: 1;
    gap: 8px;
    align-items: center;
    font-size: 12px;

    strong {
      font-size: 12px;
    }
  }
}

.alert-retry {
  padding: 5px 10px;
  color: #8b4050;
  background: #fff;
  border: 1px solid rgba(139, 64, 80, 0.16);
  border-radius: 7px;
  cursor: pointer;
}

@media (max-width: 1024px) {
  .login-view.has-alert .login-main {
    padding-top: 160px;
  }

  .login-main {
    width: 100%;
  }

  .auth-panel {
    width: min(100%, 440px);
    margin: 0 auto;
  }

  .hero-art {
    object-position: 64% center;
  }

  .hero-wash {
    background: rgba(247, 248, 255, 0.14);
  }
}

@media (max-width: 600px) {
  .login-headline {
    top: 27px;
    right: 12px;
    left: 12px;

    h1 {
      font-size: clamp(22px, 6vw, 28px);
      letter-spacing: 0.03em;
    }
  }

  .login-view.has-alert .login-headline {
    top: 78px;
  }

  .login-main {
    width: 100%;
    min-height: 100svh;
    padding: 92px 16px 16px;
  }

  .login-view.has-alert .login-main {
    padding-top: 140px;
  }

  .auth-panel {
    padding: 22px 20px 18px;
    border-radius: 20px;
  }

  .auth-footer span {
    font-size: 9px;
  }

  .server-status-alert .alert-text span {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .login-view *,
  .login-view *::before,
  .login-view *::after {
    scroll-behavior: auto !important;
    transition: none !important;
  }
}
</style>
