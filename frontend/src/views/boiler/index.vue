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
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="showCreate" class="modal-mask" @click.self="closeCreate">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3 class="modal-title">登记锅炉设备</h3>
        <p v-if="ruleHint" class="modal-hint">{{ ruleHint }}</p>
        <label v-for="field in createFields" :key="field.name" class="modal-item">
          <span>{{ field.label }}<em v-if="field.required" class="required-mark">*</em></span>
          <input
            v-model="createForm[field.name]"
            :type="field.type ?? 'text'"
            :placeholder="field.placeholder ?? `请输入${field.label}`"
          />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '确认登记' }}
          </button>
          <button class="btn ghost" type="button" :disabled="submitting" @click="closeCreate">取消</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/boiler'
const columns = ["设备编号", "设备名称", "额定蒸发量", "工作压力", "使用场所", "投用日期", "下次检验日", "设备状态"]
const actions = ["办理投用", "安排检修", "报废设备"]
const statuses = ["待投用", "在用运行", "停炉检修", "已报废"]
const stats = [{"label": "在用锅炉", "value": 0}, {"label": "停炉检修", "value": 0}, {"label": "临近检验", "value": 0}]

type CreateField = {
  name: string
  label: string
  required: boolean
  type?: string
  placeholder?: string
}

const createFields: CreateField[] = [
  { name: '设备编号', label: '设备编号', required: true, placeholder: '如 BOIL-0004' },
  { name: '设备名称', label: '设备名称', required: true },
  { name: '额定蒸发量', label: '额定蒸发量', required: true, placeholder: '单位 t/h，如 2' },
  { name: '工作压力', label: '工作压力', required: true, placeholder: '单位 MPa，如 1.25' },
  { name: '使用场所', label: '使用场所', required: false },
  { name: '投用日期', label: '投用日期', required: false, type: 'date' },
  { name: '下次检验日', label: '下次检验日', required: false, type: 'date' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const showCreate = ref(false)
const submitting = ref(false)
const createError = ref('')
const ruleHint = ref('')
const createForm = reactive<Record<string, string>>({})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openCreate() {
  createError.value = ''
  for (const field of createFields) {
    createForm[field.name] = ''
  }
  showCreate.value = true
  if (!ruleHint.value) {
    try {
      const response = await request(`${ENDPOINT}/rule`)
      if (response.ok) {
        const rule = await response.json()
        ruleHint.value = `现行校验口径 ${rule.version}：工作压力不得超过 ${rule.max_pressure_mpa} MPa，设备编号全台账唯一`
      }
    } catch {
      ruleHint.value = ''
    }
  }
}

function closeCreate() {
  showCreate.value = false
  createError.value = ''
}

async function submitCreate() {
  if (submitting.value) {
    return
  }
  submitting.value = true
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createError.value = payload.message ?? '锅炉设备登记未通过，请核对后重试'
      return
    }
    closeCreate()
    noticeMessage.value = payload.message ?? '锅炉设备已登记'
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '锅炉设备登记失败'
  } finally {
    submitting.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '锅炉设备动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '锅炉设备操作失败'
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

onMounted(reload)
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 420px;
  max-width: calc(100vw - 32px);
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.modal-title {
  margin: 0;
  font-size: 16px;
}
.modal-hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted);
}
.modal-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 2px;
}
.modal-item input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.required-mark {
  color: #b42318;
  font-style: normal;
  margin-left: 2px;
}
.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.notice-text {
  color: #067647;
}
</style>
