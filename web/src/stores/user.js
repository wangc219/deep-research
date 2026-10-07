import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/apis/auth_api'
import { useAgentStore } from './agent'
import { useProjectsStore } from './projects'
import { useEquipmentStore } from './equipment'

export const useUserStore = defineStore('user', () => {
  // 状态
  const token = ref(localStorage.getItem('user_token') || '')
  const userId = ref(null)
  const username = ref('')
  const uid = ref('')
  const phoneNumber = ref('')
  const avatar = ref('')
  const userRole = ref('')
  const departmentId = ref(null)
  const departmentName = ref('')

  // 计算属性
  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => userRole.value === 'admin' || userRole.value === 'superadmin')
  const isSuperAdmin = computed(() => userRole.value === 'superadmin')

  // The embedded research workbench is a React island, so it cannot consume
  // the Pinia store directly. Keep one non-secret identity hint for namespaced
  // browser storage; authorization remains entirely server-side.
  function syncEquipmentUserScope(value) {
    const normalized = String(value || '').trim()
    if (normalized) globalThis.__EQUIPMENT_USER_ID__ = normalized
    else delete globalThis.__EQUIPMENT_USER_ID__
  }

  // 动作
  function applySession(data) {
    // 账号切换后，智能体可见范围必须按新身份重新向服务端计算。
    // 只清项目与研究缓存会让 agentStore 保留上一账号的已初始化列表，
    // 从而出现共享智能体缺失（或越权残留）的假象。
    useAgentStore().reset()
    useProjectsStore().reset()
    useEquipmentStore().reset()
    token.value = data.access_token
    userId.value = data.user_id
    username.value = data.username
    uid.value = data.uid
    syncEquipmentUserScope(data.uid)
    phoneNumber.value = data.phone_number || ''
    avatar.value = data.avatar || ''
    userRole.value = data.role
    departmentId.value = data.department_id || null
    departmentName.value = data.department_name || ''
    localStorage.setItem('user_token', data.access_token)
  }

  async function login(credentials) {
    try {
      const data = await authApi.login(credentials)
      applySession(data)
      return true
    } catch (error) {
      console.error('登录错误:', error)
      throw error
    }
  }

  async function register(userData) {
    try {
      const data = await authApi.register(userData)
      applySession(data)
      return true
    } catch (error) {
      console.error('注册错误:', error)
      throw error
    }
  }

  function logout() {
    // 清除状态
    token.value = ''
    userId.value = null
    username.value = ''
    uid.value = ''
    syncEquipmentUserScope('')
    phoneNumber.value = ''
    avatar.value = ''
    userRole.value = ''
    departmentId.value = null
    departmentName.value = ''

    // 清除 agentStore 状态，确保重新登录时能正确加载数据
    const agentStore = useAgentStore()
    agentStore.reset()
    useProjectsStore().reset()
    useEquipmentStore().reset()

    // 只清除 token
    localStorage.removeItem('user_token')
  }

  async function initialize(admin) {
    try {
      const data = await authApi.initialize(admin)
      applySession(data)
      return true
    } catch (error) {
      console.error('初始化管理员错误:', error)
      throw error
    }
  }

  async function checkFirstRun() {
    try {
      const data = await authApi.checkFirstRun()
      return data.first_run
    } catch (error) {
      console.error('检查首次运行状态错误:', error)
      return false
    }
  }

  // 用于API请求的授权头
  function getAuthHeaders() {
    return {
      Authorization: `Bearer ${token.value}`
    }
  }

  // 用户管理功能
  async function getUsers({ pageSize = 100 } = {}) {
    try {
      const users = []
      let skip = 0

      while (true) {
        const batch = await authApi.getUsers({ skip, limit: pageSize })
        users.push(...batch)

        if (batch.length < pageSize) {
          break
        }

        skip += pageSize
      }

      return users
    } catch (error) {
      console.error('获取用户列表错误:', error)
      throw error
    }
  }

  async function createUser(userData) {
    try {
      return await authApi.createUser(userData)
    } catch (error) {
      console.error('创建用户错误:', error)
      throw error
    }
  }

  async function updateUser(userId, userData) {
    try {
      return await authApi.updateUser(userId, userData)
    } catch (error) {
      console.error('更新用户错误:', error)
      throw error
    }
  }

  async function deleteUser(userId) {
    try {
      return await authApi.deleteUser(userId)
    } catch (error) {
      console.error('删除用户错误:', error)
      throw error
    }
  }

  // 验证用户名并生成uid
  async function validateUsernameAndGenerateUid(username) {
    try {
      return await authApi.validateUsername(username)
    } catch (error) {
      console.error('用户名验证错误:', error)
      throw error
    }
  }

  // 上传头像
  async function uploadAvatar(file) {
    try {
      const data = await authApi.uploadAvatar(file)

      // 更新本地头像状态
      avatar.value = data.avatar_url

      return data
    } catch (error) {
      console.error('头像上传错误:', error)
      throw error
    }
  }

  // 获取当前用户信息
  async function getCurrentUser() {
    try {
      const userData = await authApi.getCurrentUser()
      const previousRole = userRole.value

      // 更新本地状态
      userId.value = userData.id
      username.value = userData.username
      uid.value = userData.uid
      syncEquipmentUserScope(userData.uid)
      phoneNumber.value = userData.phone_number || ''
      avatar.value = userData.avatar || ''
      userRole.value = userData.role
      departmentId.value = userData.department_id || null
      departmentName.value = userData.department_name || ''

      // 角色由服务端逐请求判定。升权或降权后清空个人作用域缓存，避免前端继续
      // 展示旧角色下的智能体、项目和研究资源；当前 token 无需重新签发。
      if (previousRole && previousRole !== userData.role) {
        useAgentStore().reset()
        useProjectsStore().reset()
        useEquipmentStore().reset()
      }

      return userData
    } catch (error) {
      console.error('获取用户信息错误:', error)
      throw error
    }
  }

  // 更新个人资料
  async function updateProfile(profileData) {
    try {
      const userData = await authApi.updateProfile(profileData)

      // 更新本地状态
      if (typeof userData.username === 'string') {
        username.value = userData.username
      }
      if (typeof userData.phone_number !== 'undefined') {
        phoneNumber.value = userData.phone_number || ''
      }

      return userData
    } catch (error) {
      console.error('更新个人资料错误:', error)
      throw error
    }
  }

  return {
    // 状态
    token,
    userId,
    username,
    uid,
    phoneNumber,
    avatar,
    userRole,
    departmentId,
    departmentName,

    // 计算属性
    isLoggedIn,
    isAdmin,
    isSuperAdmin,

    // 方法
    login,
    register,
    logout,
    initialize,
    checkFirstRun,
    getAuthHeaders,
    getUsers,
    createUser,
    updateUser,
    deleteUser,
    validateUsernameAndGenerateUid,
    uploadAvatar,
    getCurrentUser,
    updateProfile
  }
})

// 检查当前用户是否有管理员权限
export const checkAdminPermission = () => {
  const userStore = useUserStore()
  if (!userStore.isAdmin) {
    throw new Error('需要管理员权限')
  }
  return true
}

// 检查当前用户是否有超级管理员权限
export const checkSuperAdminPermission = () => {
  const userStore = useUserStore()
  return userStore.isSuperAdmin
}
