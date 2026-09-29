<template>
  <section class="page" data-module="boiler">
    <header class="page-head">
      <div>
        <h2>锅炉设备管理</h2>
        <p class="page-desc">维护锅炉设备，围绕设备编号、设备名称、额定蒸发量、工作压力做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记锅炉设备</button>
        <button class="btn" type="button" @click="exportRows">导出锅炉设备清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无锅炉设备数据，可先登记锅炉设备</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条锅炉设备记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="showCreate" class="modal-mask" @click.self="closeCreate">
      <div class="modal">
        <header class="modal-head">
          <h3>登记锅炉设备</h3>
          <button class="link" type="button" @click="closeCreate">关闭</button>
        </header>
        <p class="modal-hint">
          当前登记口径 <strong>{{ rule.version || '加载中…' }}</strong>
          ：工作压力不得超过 {{ rule.pressure_max_mpa ?? '…' }} MPa，额定蒸发量不低于
          {{ rule.evaporation_min_tph ?? '…' }} t/h，设备编号重复将不予登记。
        </p>
        <div class="form-grid">
          <label v-for="field in formFields" :key="field" class="form-item">
            <span>{{ field }}<em v-if="requiredFields.includes(field)" class="required"> *</em></span>
            <input
              v-model="form[field]"
              :type="field.includes('日期') ? 'date' : isNumericField(field) ? 'number' : 'text'"
              :step="isNumericField(field) ? '0.01' : undefined"
              :placeholder="numericPlaceholder(field)"
            />
          </label>
        </div>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <footer class="modal-foot">
          <button class="btn ghost" type="button" :disabled="submitting" @click="closeCreate">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">
            {{ submitting ? '提交中…' : '提交登记' }}
          </button>
        </footer>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type Rule = {
  version?: string
  pressure_max_mpa?: number
  evaporation_min_tph?: number
  required_fields?: string[]
}

const ENDPOINT = '/api/boiler'
const columns = ["设备编号", "设备名称", "额定蒸发量", "工作压力", "使用场所", "投用日期", "下次检验日", "设备状态"]
const actions = ["办理投用", "安排检修", "报废设备"]
const statuses = ["待投用", "在用运行", "停炉检修", "已报废"]
const formFields = ["设备编号", "设备名称", "额定蒸发量", "工作压力", "使用场所", "投用日期", "下次检验日"]
const requiredFields = ["设备编号", "设备名称", "额定蒸发量", "工作压力"]
const emptyForm = (): Record<string, string> => Object.fromEntries(formFields.map((field) => [field, '']))

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const rule = ref<Rule>({})
const showCreate = ref(false)
const submitting = ref(false)
const formError = ref('')
const form = ref<Record<string, string>>(emptyForm())

const stats = computed(() => [
  { label: "在用锅炉", value: rows.value.filter((row) => row.status === '在用运行').length },
  { label: "停炉检修", value: rows.value.filter((row) => row.status === '停炉检修').length },
  { label: "临近检验", value: rows.value.filter((row) => isNearInspection(row)).length },
])

function isNumericField(field: string): boolean {
  return field === '额定蒸发量' || field === '工作压力'
}

function numericPlaceholder(field: string): string {
  if (field === '工作压力' && rule.value.pressure_max_mpa != null) {
    return `不超过 ${rule.value.pressure_max_mpa} MPa`
  }
  if (field === '额定蒸发量' && rule.value.evaporation_min_tph != null) {
    return `不低于 ${rule.value.evaporation_min_tph} t/h`
  }
  return ''
}

function isNearInspection(row: Row): boolean {
  const raw = row.下次检验日
  if (typeof raw !== 'string' || !raw.trim()) return false
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return false
  return (date.getTime() - Date.now()) / 86400000 <= 30
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  form.value = emptyForm()
  formError.value = ''
  showCreate.value = true
}

function closeCreate() {
  if (submitting.value) return
  showCreate.value = false
}

async function submitCreate() {
  formError.value = ''
  const missing = requiredFields.filter((field) => !form.value[field]?.trim())
  if (missing.length) {
    formError.value = `必填字段缺失：${missing.join('、')}`
    return
  }
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...form.value } }),
    })
    const payload = (await response.json().catch(() => null)) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload?.ok) {
      formError.value = payload?.message || '锅炉设备登记未生效，请稍后重试'
      return
    }
    showCreate.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '锅炉设备登记失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('锅炉设备动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '锅炉设备操作失败'
  }
}

async function loadRule() {
  try {
    rule.value = await fetchJson<Rule>(`${ENDPOINT}/validation-rule`)
  } catch {
    // 阈值提示非关键，加载失败时表单仍可提交
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('锅炉设备列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '锅炉设备列表读取失败'
  }
}

onMounted(() => {
  void loadRule()
  void reload()
})
</script>
