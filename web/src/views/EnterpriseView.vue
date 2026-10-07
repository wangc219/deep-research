<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { Modal } from 'ant-design-vue'
import {
  Building2,
  Users,
  ShieldCheck,
  Activity,
  RefreshCw,
  Network,
  SquarePen,
  Trash2
} from '@lucide/vue'
import { enterpriseApi } from '@/apis/enterprise_api'
import { useUserStore } from '@/stores/user'
import UserManagementComponent from '@/components/UserManagementComponent.vue'

const user = useUserStore()
const tab = ref('organization')
const org = ref({ tenants: [], departments: [], users: [], rules: [], features: [] })
const monitor = ref(null)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const tenantName = ref('')
const selectedTenant = ref('default')
const tenantEditorOpen = ref(false)
const tenantEdit = reactive({ id: '', name: '' })
const labels = {
  queries: '需求 Query',
  research: '研究任务',
  capabilities: '能力画像',
  reports: '研究报告',
  favorites: '收藏',
  'deep-thinking': '深研对话',
  knowledge: '知识库',
  agents: 'Agent'
}
const department = reactive({
  name: '',
  description: '',
  parent_id: null,
  create_admin: false,
  admin_uid: '',
  admin_password: ''
})
const departmentEditorOpen = ref(false)
const departmentEdit = reactive({
  id: null,
  name: '',
  description: '',
  parent_id: null,
  tenant_id: ''
})
const rule = reactive({
  subject_type: 'tenant',
  subject_id: '',
  feature: 'research',
  can_read: true,
  can_write: true
})
const departments = computed(() =>
  org.value.departments.filter((d) => d.tenant_id === selectedTenant.value)
)
const departmentRows = computed(() => {
  const rows = []
  const seen = new Set()
  const ids = new Set(departments.value.map((d) => d.id))
  const append = (parentId, depth) =>
    departments.value
      .filter((d) => (ids.has(d.parent_id) ? d.parent_id : null) === parentId)
      .forEach((d) => {
        if (seen.has(d.id)) return
        seen.add(d.id)
        rows.push({ department: d, depth })
        append(d.id, depth + 1)
      })
  append(null, 0)
  departments.value
    .filter((d) => !seen.has(d.id))
    .forEach((d) => rows.push({ department: d, depth: 0 }))
  return rows
})
const editingParentOptions = computed(() => departmentOptions(departmentEdit.id))
const subjects = computed(() =>
  rule.subject_type === 'department'
    ? departments.value.map((d) => ({ value: String(d.id), label: d.name }))
    : org.value.users
        .filter((u) => departments.value.some((d) => d.id === u.department_id))
        .map((u) => ({ value: u.uid, label: `${u.username} (${u.uid})` }))
)
const rules = computed(() => org.value.rules.filter((r) => r.tenant_id === selectedTenant.value))
const maxRequests = computed(() =>
  Math.max(1, ...(monitor.value?.hourly || []).map((h) => h.requests))
)
let timer

async function refresh() {
  busy.value = true
  error.value = ''
  try {
    const [organization, metrics] = await Promise.all([
      enterpriseApi.organization(),
      enterpriseApi.monitoring()
    ])
    org.value = organization
    monitor.value = metrics
    if (!organization.tenants.some((t) => t.id === selectedTenant.value))
      selectedTenant.value = organization.tenants[0]?.id || ''
    if (!user.isSuperAdmin && department.parent_id == null) {
      department.parent_id = user.departmentId
    }
  } catch (e) {
    error.value = e.message || '加载失败，请重试'
  } finally {
    busy.value = false
  }
}
async function mutate(action, text) {
  busy.value = true
  notice.value = ''
  error.value = ''
  try {
    await action()
    notice.value = text
    await refresh()
    return true
  } catch (e) {
    error.value = e.message || '保存失败'
    busy.value = false
    return false
  }
}
function addTenant() {
  if (!tenantName.value.trim()) return
  return mutate(async () => {
    const tenant = await enterpriseApi.createTenant({ name: tenantName.value.trim() })
    selectedTenant.value = tenant.id
    tenantName.value = ''
  }, '用户已创建')
}
function selectTenant(tenantId) {
  selectedTenant.value = tenantId
  rule.subject_id = ''
  department.parent_id = null
}
function openTenantEditor(tenant) {
  Object.assign(tenantEdit, { id: tenant.id, name: tenant.name.replaceAll('租户', '用户') })
  tenantEditorOpen.value = true
}
async function saveTenant() {
  if (!tenantEdit.name.trim()) return
  const saved = await mutate(
    () => enterpriseApi.updateTenant(tenantEdit.id, { name: tenantEdit.name.trim() }),
    '企业用户名称已更新'
  )
  if (saved) tenantEditorOpen.value = false
}
function confirmDeleteTenant() {
  Modal.confirm({
    title: `删除“${tenantEdit.name}”？`,
    content: '只能删除没有部门的企业用户。相关的功能权限规则会一并清理，此操作不可撤销。',
    okText: '删除企业用户',
    cancelText: '取消',
    okButtonProps: { danger: true },
    async onOk() {
      const deleted = await mutate(
        () => enterpriseApi.deleteTenant(tenantEdit.id),
        '企业用户已删除'
      )
      if (deleted) tenantEditorOpen.value = false
    }
  })
}
function addDepartment() {
  return mutate(
    async () => {
      const payload = {
        name: department.name.trim(),
        description: department.description.trim(),
        parent_id: department.parent_id ?? (user.isSuperAdmin ? null : user.departmentId),
        tenant_id: selectedTenant.value
      }
      if (department.create_admin) {
        payload.admin_uid = department.admin_uid.trim()
        payload.admin_password = department.admin_password
      }
      await enterpriseApi.createDepartment(payload)
      Object.assign(department, {
        name: '',
        description: '',
        parent_id: user.isSuperAdmin ? null : user.departmentId,
        create_admin: false,
        admin_uid: '',
        admin_password: ''
      })
    },
    department.create_admin ? '部门与管理员已创建' : '部门已创建'
  )
}
function descendantIds(departmentId) {
  const descendants = new Set()
  const visit = (id) =>
    departments.value
      .filter((d) => d.parent_id === id)
      .forEach((d) => {
        if (descendants.has(d.id)) return
        descendants.add(d.id)
        visit(d.id)
      })
  if (departmentId != null) visit(departmentId)
  return descendants
}
function departmentOptions(excludedId = null) {
  const excluded = descendantIds(excludedId)
  if (excludedId != null) excluded.add(excludedId)
  return departmentRows.value
    .filter(({ department: d }) => !excluded.has(d.id))
    .map(({ department: d, depth }) => ({
      value: d.id,
      label: `${'　'.repeat(depth)}${depth ? '↳ ' : ''}${d.name}`
    }))
}
function openDepartmentEditor(d) {
  Object.assign(departmentEdit, {
    id: d.id,
    name: d.name,
    description: d.description || '',
    parent_id: d.parent_id,
    tenant_id: d.tenant_id
  })
  departmentEditorOpen.value = true
}
async function saveDepartment() {
  if (!departmentEdit.name.trim()) return
  const saved = await mutate(
    () =>
      enterpriseApi.setDepartment(departmentEdit.id, {
        tenant_id: departmentEdit.tenant_id,
        parent_id: departmentEdit.parent_id ?? null,
        name: departmentEdit.name.trim(),
        description: departmentEdit.description.trim()
      }),
    '部门信息已更新'
  )
  if (saved) departmentEditorOpen.value = false
}
function confirmDeleteDepartment() {
  Modal.confirm({
    title: `删除“${departmentEdit.name}”？`,
    content: '请先移动其子部门。部门成员是否可迁移取决于当前组织范围，此操作不可撤销。',
    okText: '删除部门',
    cancelText: '取消',
    okButtonProps: { danger: true },
    async onOk() {
      const deleted = await mutate(
        () => enterpriseApi.deleteDepartment(departmentEdit.id),
        '部门已删除'
      )
      if (deleted) departmentEditorOpen.value = false
    }
  })
}
function saveRule() {
  return mutate(
    () =>
      enterpriseApi.saveRule({
        ...rule,
        tenant_id: selectedTenant.value,
        subject_id: rule.subject_type === 'tenant' ? selectedTenant.value : rule.subject_id
      }),
    '功能权限已生效'
  )
}
function subjectName(r) {
  if (r.subject_type === 'tenant') return '全体用户'
  if (r.subject_type === 'department')
    return org.value.departments.find((d) => String(d.id) === r.subject_id)?.name || r.subject_id
  return org.value.users.find((u) => u.uid === r.subject_id)?.username || r.subject_id
}
onMounted(() => {
  void refresh()
  timer = window.setInterval(async () => {
    if (tab.value !== 'monitoring' || document.hidden || busy.value) return
    try {
      monitor.value = await enterpriseApi.monitoring()
      error.value = ''
    } catch (e) {
      error.value = e.message || '监控刷新失败'
    }
  }, 15000)
})
onUnmounted(() => window.clearInterval(timer))
</script>

<template>
  <main class="enterprise-page">
    <header class="enterprise-header">
      <div>
        <p class="eyebrow">企业协作</p>
        <h1>组织与权限管理</h1>
        <p>统一管理成员、组织架构与使用权限，掌握研究平台运行情况。</p>
      </div>
      <a-button :loading="busy" @click="refresh"><RefreshCw :size="15" />刷新</a-button>
    </header>
    <a-alert v-if="error" type="error" show-icon :message="error" class="banner" />
    <a-alert
      v-if="notice"
      type="success"
      show-icon
      :message="notice"
      closable
      class="banner"
      @close="notice = ''"
    />
    <div class="privacy-banner">
      <ShieldCheck :size="19" /><span
        >部门管理员可管理本部门及全部下级部门的组织结构与普通成员；兄弟部门和上级部门仍保持隔离。</span
      >
    </div>
    <a-tabs v-model:active-key="tab">
      <a-tab-pane key="organization"
        ><template #tab><Building2 :size="16" />用户与部门</template>
        <div class="organization-grid">
          <section class="panel">
            <h2>企业用户</h2>
            <div v-for="tenant in org.tenants" :key="tenant.id" class="tenant-row">
              <button
                class="tenant"
                :class="{ selected: selectedTenant === tenant.id }"
                @click="selectTenant(tenant.id)"
              >
                <Building2 :size="17" /><span>{{ tenant.name.replaceAll('租户', '用户') }}</span
                ><small
                  >{{
                    org.departments.filter((d) => d.tenant_id === tenant.id).length
                  }}
                  个部门</small
                >
              </button>
              <a-button
                v-if="user.isSuperAdmin"
                class="tenant-edit"
                type="text"
                :aria-label="`编辑${tenant.name.replaceAll('租户', '用户')}`"
                @click="openTenantEditor(tenant)"
                ><SquarePen :size="14"
              /></a-button>
            </div>
            <a-empty v-if="!busy && !org.tenants.length" description="暂无用户" />
            <form v-if="user.isSuperAdmin" class="inline-form" @submit.prevent="addTenant">
              <a-input
                v-model:value="tenantName"
                placeholder="新用户名称"
                aria-label="新用户名称"
                :maxlength="100"
              /><a-button html-type="submit" :disabled="!tenantName.trim() || busy">创建</a-button>
            </form>
          </section>
          <section class="panel">
            <div class="section-heading department-heading">
              <div>
                <h2>部门组织架构</h2>
                <p class="muted">按层级管理部门、上级部门与成员归属。</p>
              </div>
              <span v-if="departments.length" class="department-count"
                >{{ departments.length }} 个部门</span
              >
            </div>
            <div
              v-for="row in departmentRows"
              :key="row.department.id"
              class="department-row"
              :class="{ nested: row.depth > 0 }"
              :style="{ '--tree-depth': row.depth }"
            >
              <div class="department-identity">
                <span class="department-icon"><Network :size="15" /></span>
                <div>
                  <strong>{{ row.department.name }}</strong
                  ><small
                    >{{
                      org.users.filter((u) => u.department_id === row.department.id).length
                    }}
                    位成员<span v-if="row.department.description">
                      · {{ row.department.description }}</span
                    ></small
                  >
                </div>
              </div>
              <div class="department-actions">
                <span class="parent-label">{{
                  row.department.parent_id
                    ? `上级：${departments.find((p) => p.id === row.department.parent_id)?.name || '未知部门'}`
                    : '顶级部门'
                }}</span>
                <a-button
                  v-if="user.isAdmin"
                  size="small"
                  class="icon-label-button"
                  :aria-label="`编辑${row.department.name}`"
                  @click="openDepartmentEditor(row.department)"
                  ><SquarePen :size="14" />编辑</a-button
                >
              </div>
            </div>
            <a-empty v-if="!busy && !departments.length" description="此用户还没有部门" />
            <form v-if="user.isAdmin" class="department-form" @submit.prevent="addDepartment">
              <h3>新建部门</h3>
              <label
                >部门名称<a-input v-model:value="department.name" required :maxlength="50"
              /></label>
              <label
                >上级部门<a-select
                  v-model:value="department.parent_id"
                  :placeholder="user.isSuperAdmin ? '不选择则为顶级部门' : '请选择上级部门'"
                  :allow-clear="user.isSuperAdmin"
                  :options="departmentOptions()"
              /></label>
              <label class="form-wide"
                >部门说明（可选）<a-input
                  v-model:value="department.description"
                  :maxlength="255"
                  placeholder="例如：负责产品研发与技术交付"
              /></label>
              <label v-if="user.isSuperAdmin" class="form-wide admin-option"
                ><a-checkbox v-model:checked="department.create_admin"
                  >同时创建部门管理员</a-checkbox
                ><small>可稍后在“成员管理”中添加或调整管理员。</small></label
              >
              <template v-if="user.isSuperAdmin && department.create_admin">
                <label
                  >管理员登录 ID<a-input
                    v-model:value="department.admin_uid"
                    required
                    placeholder="3–20 位字母、数字或下划线"
                /></label>
                <label
                  >初始密码<a-input-password
                    v-model:value="department.admin_password"
                    required
                    :minlength="8"
                    autocomplete="new-password"
                /></label>
              </template>
              <a-button
                html-type="submit"
                type="primary"
                :loading="busy"
                :disabled="
                  !department.name.trim() ||
                  (department.create_admin &&
                    (!department.admin_uid.trim() || department.admin_password.length < 8))
                "
                >创建部门</a-button
              >
            </form>
          </section>
        </div>
      </a-tab-pane>
      <a-tab-pane key="members"
        ><template #tab><Users :size="16" />成员管理</template>
        <section class="panel"><UserManagementComponent /></section
      ></a-tab-pane>
      <a-tab-pane key="permissions"
        ><template #tab><ShieldCheck :size="16" />功能权限</template>
        <section class="panel">
          <div class="section-heading">
            <div>
              <h2>功能读写权限</h2>
              <p class="muted">
                指定用户规则优先于部门规则，部门规则优先于企业用户规则。未配置时允许使用；功能授权不会开放他人的研究数据。
              </p>
            </div>
            <a-select
              v-model:value="selectedTenant"
              style="min-width: 180px"
              :options="
                org.tenants.map((t) => ({ value: t.id, label: t.name.replaceAll('租户', '用户') }))
              "
              aria-label="权限用户"
              @change="rule.subject_id = ''"
            />
          </div>
          <form v-if="user.isSuperAdmin" class="permission-form" @submit.prevent="saveRule">
            <label
              >授权范围<a-select
                v-model:value="rule.subject_type"
                :options="[
                  { value: 'tenant', label: '全体用户' },
                  { value: 'department', label: '指定部门' },
                  { value: 'user', label: '指定用户' }
                ]"
                @change="rule.subject_id = ''"
            /></label>
            <label v-if="rule.subject_type !== 'tenant'"
              >授权对象<a-select
                v-model:value="rule.subject_id"
                :options="subjects"
                show-search
                option-filter-prop="label"
            /></label>
            <label
              >功能<a-select
                v-model:value="rule.feature"
                :options="org.features.map((f) => ({ value: f, label: labels[f] }))"
            /></label>
            <label class="check"
              ><a-checkbox
                v-model:checked="rule.can_read"
                @change="!rule.can_read && (rule.can_write = false)"
                >可读取</a-checkbox
              ></label
            >
            <label class="check"
              ><a-checkbox v-model:checked="rule.can_write" :disabled="!rule.can_read"
                >可写入</a-checkbox
              ></label
            >
            <a-button
              html-type="submit"
              type="primary"
              :loading="busy"
              :disabled="rule.subject_type !== 'tenant' && !rule.subject_id"
              >保存规则</a-button
            >
          </form>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>授权对象</th>
                  <th>功能</th>
                  <th>读取</th>
                  <th>写入</th>
                  <th v-if="user.isSuperAdmin">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in rules" :key="r.id">
                  <td>{{ subjectName(r) }}</td>
                  <td>{{ labels[r.feature] }}</td>
                  <td>{{ r.can_read ? '允许' : '禁止' }}</td>
                  <td>{{ r.can_write ? '允许' : '禁止' }}</td>
                  <td v-if="user.isSuperAdmin">
                    <a-button
                      size="small"
                      @click="mutate(() => enterpriseApi.deleteRule(r.id), '已恢复继承权限')"
                      >恢复继承</a-button
                    >
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <a-empty v-if="!busy && !rules.length" description="暂无覆盖规则，使用默认权限" />
          <p class="muted">知识库与 Agent 的具体资源共享范围，请在对应资源的权限设置中配置。</p>
        </section>
      </a-tab-pane>
      <a-tab-pane key="monitoring"
        ><template #tab><Activity :size="16" />运行监控</template>
        <template v-if="monitor">
          <div class="metric-grid">
            <section class="panel metric">
              <span>24 小时 API 请求</span><strong>{{ monitor.totals.requests }}</strong>
            </section>
            <section class="panel metric">
              <span>失败请求</span><strong>{{ monitor.totals.errors }}</strong>
            </section>
            <section class="panel metric">
              <span>平均响应时间</span
              ><strong>{{ Math.round(monitor.totals.avg_ms) }} <small>ms</small></strong>
            </section>
            <section class="panel metric">
              <span>主机内存使用</span
              ><strong>{{ monitor.resources.memory_percent ?? '不可用' }}<small>%</small></strong>
            </section>
          </div>
          <section class="panel">
            <h2>请求趋势 · 最近 24 小时</h2>
            <p class="muted">每 15 秒刷新，统计研究、Query、深研、知识库及 Agent 的 HTTP 请求。</p>
            <div class="trend">
              <div
                v-for="h in monitor.hourly"
                :key="h.hour"
                class="bar-column"
                :title="`${h.hour}: ${h.requests} 次请求，${h.errors} 次失败`"
              >
                <strong>{{ h.requests }}</strong
                ><i
                  :style="{ height: `${Math.max(3, (h.requests / maxRequests) * 120)}px` }"
                /><small>{{ new Date(h.hour).getHours() }}时</small>
              </div>
            </div>
            <a-empty
              v-if="!monitor.hourly.length"
              description="暂无调用记录，使用平台后将自动统计"
            />
          </section>
          <section class="panel resource-panel">
            <span
              >每核负载 <b>{{ monitor.resources.load_per_cpu }}</b></span
            ><span
              >1 分钟负载 <b>{{ monitor.resources.load_1m.toFixed(2) }}</b></span
            ><span
              >CPU 核数 <b>{{ monitor.resources.cpu_count }}</b></span
            ><router-link to="/models">管理模型与 API Key →</router-link
            ><router-link v-if="user.isAdmin" to="/dashboard"
              >查看模型 Token 与工具调用 →</router-link
            >
          </section>
        </template>
        <a-spin v-else-if="busy" />
      </a-tab-pane>
    </a-tabs>
    <a-modal
      v-model:open="tenantEditorOpen"
      title="编辑企业用户"
      :confirm-loading="busy"
      :mask-closable="false"
    >
      <a-form layout="vertical">
        <a-form-item label="企业用户名称" required>
          <a-input v-model:value="tenantEdit.name" :maxlength="100" @press-enter="saveTenant" />
        </a-form-item>
        <p class="editor-hint">删除前需要先迁移或删除该企业用户下的所有部门。</p>
      </a-form>
      <template #footer>
        <div class="modal-footer">
          <a-button
            v-if="tenantEdit.id !== 'default'"
            danger
            :disabled="busy"
            @click="confirmDeleteTenant"
            ><Trash2 :size="14" />删除企业用户</a-button
          >
          <span />
          <a-button @click="tenantEditorOpen = false">取消</a-button>
          <a-button
            type="primary"
            :loading="busy"
            :disabled="!tenantEdit.name.trim()"
            @click="saveTenant"
            >保存更改</a-button
          >
        </div>
      </template>
    </a-modal>
    <a-modal
      v-model:open="departmentEditorOpen"
      title="编辑部门"
      :confirm-loading="busy"
      ok-text="保存更改"
      cancel-text="取消"
      :mask-closable="false"
      @ok="saveDepartment"
    >
      <a-form layout="vertical" class="department-editor">
        <a-form-item label="部门名称" required
          ><a-input v-model:value="departmentEdit.name" :maxlength="50"
        /></a-form-item>
        <a-form-item label="上级部门"
          ><a-select
            v-model:value="departmentEdit.parent_id"
            placeholder="不选择则为顶级部门"
            :allow-clear="user.isSuperAdmin"
            :disabled="!user.isSuperAdmin && departmentEdit.id === user.departmentId"
            :options="editingParentOptions"
        /></a-form-item>
        <a-form-item label="部门说明"
          ><a-textarea
            v-model:value="departmentEdit.description"
            :maxlength="255"
            :rows="3"
            show-count
            placeholder="说明该部门的职责或范围（可选）"
        /></a-form-item>
        <p class="editor-hint">不能选择当前部门或它的下级部门，避免形成循环组织关系。</p>
      </a-form>
      <template #footer>
        <div class="modal-footer">
          <a-button
            v-if="
              departmentEdit.id !== 1 &&
              (user.isSuperAdmin || departmentEdit.id !== user.departmentId)
            "
            danger
            :disabled="busy"
            @click="confirmDeleteDepartment"
            ><Trash2 :size="14" />删除部门</a-button
          >
          <span />
          <a-button @click="departmentEditorOpen = false">取消</a-button>
          <a-button
            type="primary"
            :loading="busy"
            :disabled="!departmentEdit.name.trim()"
            @click="saveDepartment"
            >保存更改</a-button
          >
        </div>
      </template>
    </a-modal>
  </main>
</template>

<style scoped>
.enterprise-page {
  padding: 30px;
  max-width: 1440px;
  margin: 0 auto;
  color: var(--gray-900);
  overflow: auto;
  height: 100%;
}
.enterprise-header,
.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
  margin-bottom: 22px;
}
h1 {
  font-size: 25px;
  margin: 4px 0 10px;
}
h2 {
  font-size: 17px;
  margin: 0 0 14px;
}
h3 {
  font-size: 14px;
}
p,
.muted,
small {
  color: var(--gray-600);
}
.eyebrow {
  color: var(--main-color);
  font-size: 12px;
  margin: 0;
}
.banner {
  margin-bottom: 14px;
}
.privacy-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--gray-50);
  padding: 14px 18px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  margin-bottom: 18px;
  font-size: 13px;
}
.panel {
  background: var(--gray-0);
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  padding: 22px;
  margin-bottom: 20px;
}
.organization-grid {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 20px;
}
.tenant {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  padding: 14px 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}
.tenant-row {
  position: relative;
  display: flex;
  align-items: center;
}
.tenant-row .tenant {
  padding-right: 42px;
}
.tenant-edit {
  position: absolute;
  right: 6px;
}
.tenant span {
  flex: 1;
}
.tenant.selected {
  background: var(--gray-50);
  border-color: var(--main-color);
}
.inline-form,
.department-row,
.resource-panel {
  display: flex;
  gap: 12px;
  align-items: center;
}
.inline-form {
  margin-top: 20px;
}
.department-heading {
  margin-bottom: 8px;
}
.department-heading h2,
.department-heading p {
  margin-bottom: 4px;
}
.department-count {
  color: var(--gray-600);
  font-size: 12px;
  white-space: nowrap;
}
.department-row {
  justify-content: space-between;
  min-height: 64px;
  margin-left: calc(var(--tree-depth) * 24px);
  padding: 10px 0;
  border-bottom: 1px solid var(--gray-200);
}
.department-row.nested {
  border-left: 1px solid var(--gray-200);
  padding-left: 12px;
}
.department-identity,
.department-actions,
.icon-label-button {
  display: flex;
  align-items: center;
  gap: 9px;
}
.department-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: var(--main-color);
  background: var(--gray-50);
}
.department-row small {
  display: block;
  margin-top: 4px;
}
.parent-label {
  color: var(--gray-600);
  font-size: 12px;
}
.icon-label-button {
  justify-content: center;
}
.department-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 25px;
}
.department-form h3,
.department-form .form-wide {
  grid-column: 1 / -1;
}
.department-form h3 {
  margin: 0;
}
.admin-option small {
  margin-left: 24px;
}
.department-form label,
.permission-form label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  font-size: 13px;
}
.permission-form {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: 15px;
  margin: 20px 0;
}
.permission-form label {
  min-width: 130px;
}
.permission-form .check {
  min-width: auto;
  padding-bottom: 6px;
}
.editor-hint {
  margin: -4px 0 0;
  font-size: 12px;
}
.modal-footer {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  align-items: center;
  gap: 8px;
}
.table-scroll {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th,
td {
  padding: 14px;
  text-align: left;
  border-bottom: 1px solid var(--gray-200);
}
th {
  background: var(--gray-50);
  font-weight: 500;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 18px;
}
.metric strong {
  display: block;
  font-size: 30px;
  margin-top: 15px;
}
.metric span {
  color: var(--gray-600);
  font-size: 13px;
}
.metric strong small {
  font-size: 14px;
  font-weight: 400;
}
.trend {
  display: flex;
  align-items: end;
  gap: 12px;
  overflow-x: auto;
}
.bar-column {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  min-width: 35px;
  flex: 1;
  font-size: 12px;
}
.bar-column i {
  display: block;
  width: 75%;
  background: var(--main-color);
  border-radius: 4px 4px 0 0;
}
.resource-panel {
  flex-wrap: wrap;
  justify-content: space-between;
  font-size: 13px;
}
:deep(.ant-tabs-tab-btn) {
  display: flex;
  align-items: center;
  gap: 7px;
}
@media (max-width: 900px) {
  .organization-grid {
    grid-template-columns: 1fr;
  }
  .metric-grid {
    grid-template-columns: 1fr 1fr;
  }
  .enterprise-page {
    padding: 16px;
  }
  .section-heading {
    align-items: start;
    flex-direction: column;
  }
}
@media (max-width: 560px) {
  .department-form {
    grid-template-columns: 1fr;
  }
  .department-form .form-wide {
    grid-column: auto;
  }
  .department-row {
    align-items: flex-start;
    margin-left: calc(var(--tree-depth) * 12px);
  }
  .department-actions {
    align-items: flex-end;
    flex-direction: column;
  }
  .parent-label {
    display: none;
  }
  .enterprise-header {
    align-items: start;
  }
  .metric-grid {
    gap: 8px;
  }
  .panel {
    padding: 16px;
  }
}
</style>
