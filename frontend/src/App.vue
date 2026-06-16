<template>
  <main class="shell">
    <div v-if="appLoading" class="loading-screen">
      <div class="loader-card">
        <div class="loader-mark"></div>
        <h2>正在连接管道焊接智能体</h2>
        <p>加载会话和必填字段</p>
        <div class="progress-track">
          <span :style="{ width: `${loadingProgress}%` }"></span>
        </div>
      </div>
    </div>

    <div v-if="busy || generating" class="top-progress">
      <span></span>
    </div>

    <section class="workbench">
      <header class="topbar">
        <div>
          <p class="eyebrow">Pipeline Welding</p>
          <h1>管道焊接重问与标准文档生成</h1>
        </div>
        <div class="topbar-actions">
          <div class="mode-switch" aria-label="模式切换">
            <button :class="{ active: mode === 'professional' }" :disabled="busy" @click="switchMode('professional')">
              专业问答模式
            </button>
            <button :class="{ active: mode === 'nonprofessional' }" :disabled="busy" @click="switchMode('nonprofessional')">
              非专业描述模式
            </button>
          </div>
          <button class="secondary" :disabled="busy" @click="resetSession">新建会话</button>
        </div>
      </header>

      <section class="content">
        <div v-if="mode === 'professional'" class="conversation">
          <div class="panel-head">
            <div>
              <h2>重问答交互</h2>
              <p>输入焊接工艺、对象、接头、母材和管径壁厚等信息</p>
            </div>
            <span :class="['status', state?.complete ? 'complete' : 'pending']">
              {{ state?.complete ? '信息完整' : `第 ${state?.round_count ?? 0} 轮` }}
            </span>
          </div>

          <div ref="messageListRef" class="messages">
            <article class="message assistant">
              <div class="bubble">
                请描述当前焊接场景。示例：工艺 GTAW+SMAW，焊接对象是管道，接头对接，母材 ASTM A106 Gr.B，OD 219.1 x 8.2 mm。
              </div>
            </article>
            <article
              v-for="(message, index) in state?.messages ?? []"
              :key="index"
              :class="['message', message.role]"
            >
              <div class="bubble">{{ message.content }}</div>
            </article>
          </div>

          <form class="composer" @submit.prevent="sendMessage">
            <textarea
              v-model="draft"
              rows="3"
              placeholder="请输入本轮补充信息..."
              :disabled="busy || !sessionId || reachedLimit"
            />
            <button class="primary" :disabled="!canSend">
              {{ busy ? '处理中' : '发送' }}
            </button>
          </form>
        </div>

        <div v-else class="conversation natural-panel">
          <div class="panel-head">
            <div>
              <h2>描述你的焊接需求</h2>
              <p>输入一段自然语言描述，系统会自动识别关键字段</p>
            </div>
            <span :class="['status', state?.complete ? 'complete' : 'pending']">
              {{ state?.complete ? '字段完整' : '等待分析' }}
            </span>
          </div>

          <div class="natural-body">
            <textarea
              v-model="naturalDescription"
              rows="8"
              placeholder="例如：我有两块20mm厚的20号钢板，需要帮我生成一个焊接工艺"
              :disabled="busy || generating"
            />
            <div class="natural-actions">
              <button class="secondary" :disabled="!canAnalyzeNatural" @click="analyzeNaturalDescription">
                {{ busy ? '正在分析' : '分析描述' }}
              </button>
              <button class="primary" :disabled="!canGenerate" @click="generateDocument">
                {{ generating ? '正在生成文档' : '生成标准文档' }}
              </button>
            </div>
            <div v-if="naturalAnalyzed" class="analysis-result">
              <h2>自动识别字段</h2>
              <p v-if="state?.complete">字段已完整，可以生成文档。</p>
              <p v-else>仍有字段需要修正或补充。</p>
            </div>
          </div>
        </div>

        <aside class="sidebar">
          <section class="fields">
            <div class="panel-head compact">
              <div>
                <h2>关键字段</h2>
                <p>可直接修正自动提取结果</p>
              </div>
            </div>

            <label v-for="field in requiredFields" :key="field.key" class="field">
              <span>{{ field.label }}</span>
              <select
                v-if="field.key === 'welding_process' || (mode === 'professional' && field.options.length)"
                v-model="editableFields[field.key]"
                :disabled="busy"
                @change="syncFields"
              >
                <option value="">未填写</option>
                <template v-if="field.key === 'welding_process'">
                  <option v-for="option in weldingProcessOptions" :key="option" :value="option">
                    {{ option }}
                  </option>
                </template>
                <option v-for="option in field.options" v-else :key="option" :value="option">
                  {{ option }}
                </option>
              </select>
              <input
                v-else
                v-model="editableFields[field.key]"
                :placeholder="field.examples[0] || field.source_hint"
                :disabled="busy"
                @blur="syncFields"
              />
            </label>
          </section>

          <section class="summary">
            <h2>流程状态</h2>
            <div class="metric">
              <span>缺失字段</span>
              <strong>{{ state?.missing_keys?.length ?? 0 }}</strong>
            </div>
            <div class="metric">
              <span>异常字段</span>
              <strong>{{ state?.invalid_keys?.length ?? 0 }}</strong>
            </div>
            <div class="question-list" v-if="state?.questions?.length">
              <p v-for="question in state.questions" :key="question">{{ question }}</p>
            </div>
          </section>

          <section class="actions">
            <button class="primary wide" :disabled="!canGenerate" @click="generateDocument">
              {{ generating ? '正在生成文档' : '生成标准文档' }}
            </button>
            <div v-if="generating" class="generation-progress">
              <div class="progress-copy">
                <strong>{{ generationStep }}</strong>
                <span>{{ loadingProgress }}%</span>
              </div>
              <div class="progress-track">
                <span :style="{ width: `${loadingProgress}%` }"></span>
              </div>
              <p>标准检索、字段综合和 DOCX 填充可能需要一些时间</p>
            </div>
            <a
              v-if="downloadUrl"
              class="download"
              :href="downloadUrl"
              target="_blank"
              rel="noreferrer"
            >
              下载 {{ documentName }}
            </a>
          </section>
        </aside>
      </section>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
}

type ReaskState = {
  messages: ChatMessage[]
  fields: Record<string, string>
  round_count: number
  complete: boolean
  missing_keys: string[]
  invalid_keys: string[]
  questions: string[]
  assistant_message: string
}

type SessionPayload = {
  session_id: string
  state: ReaskState
  download_url?: string
  document_name?: string
  analysis?: NaturalAnalysisPayload
}

type NaturalAnalysisPayload = {
  fields: Record<string, string>
  complete: boolean
  missing_keys: string[]
  invalid_keys: string[]
  questions: string[]
  rag_evidence: unknown[]
  network_evidence: unknown[]
}

type RequiredField = {
  key: string
  label: string
  source_hint: string
  field_type: string
  options: string[]
  examples: string[]
}

const sessionId = ref('')
const state = ref<ReaskState | null>(null)
const requiredFields = ref<RequiredField[]>([])
const draft = ref('')
const mode = ref<'professional' | 'nonprofessional'>('professional')
const naturalDescription = ref('')
const naturalAnalyzed = ref(false)
const busy = ref(false)
const generating = ref(false)
const appLoading = ref(true)
const loadingProgress = ref(12)
const generationStep = ref('准备生成任务')
let progressTimer: number | undefined
const downloadUrl = ref('')
const documentName = ref('')
const messageListRef = ref<HTMLElement | null>(null)
const editableFields = reactive<Record<string, string>>({})
const weldingProcessOptions = ['SMAW', 'GTAW', 'GMAW', 'FCAW', 'SAW', 'GTAW+SMAW']

const reachedLimit = computed(() => (state.value?.round_count ?? 0) >= 5 && !state.value?.complete)
const canSend = computed(() => Boolean(draft.value.trim() && sessionId.value && !busy.value && !reachedLimit.value))
const canAnalyzeNatural = computed(() => Boolean(naturalDescription.value.trim() && !busy.value && !generating.value))
const canGenerate = computed(() => {
  const hasFields = Object.values(editableFields).some(Boolean)
  if (mode.value === 'nonprofessional') {
    return Boolean(naturalDescription.value.trim() && !generating.value && hasFields)
  }
  return Boolean(sessionId.value && !generating.value && hasFields)
})

onMounted(async () => {
  startProgress('加载前端资源')
  try {
    await Promise.all([loadRequiredFields(), resetSession()])
    loadingProgress.value = 100
  } finally {
    window.setTimeout(() => {
      appLoading.value = false
      stopProgress()
    }, 280)
  }
})

async function loadRequiredFields() {
  const result = await api<{ fields: RequiredField[] }>('/api/required-fields')
  requiredFields.value = result.fields
  for (const field of result.fields) {
    editableFields[field.key] = ''
  }
}

async function resetSession() {
  busy.value = true
  startProgress('创建新会话')
  try {
    const payload = await api<SessionPayload>('/api/sessions', { method: 'POST' })
    applySession(payload)
    draft.value = ''
    naturalAnalyzed.value = false
  } finally {
    busy.value = false
    if (!appLoading.value) stopProgress()
  }
}

function switchMode(nextMode: 'professional' | 'nonprofessional') {
  mode.value = nextMode
  downloadUrl.value = ''
  documentName.value = ''
}

async function sendMessage() {
  if (!canSend.value) return
  busy.value = true
  startProgress('分析用户输入')
  try {
    const payload = await api<SessionPayload>(`/api/sessions/${sessionId.value}/message`, {
      method: 'POST',
      body: JSON.stringify({ message: draft.value.trim() })
    })
    draft.value = ''
    applySession(payload)
  } finally {
    busy.value = false
    stopProgress()
  }
}

async function syncFields() {
  if (!sessionId.value || busy.value) return
  busy.value = true
  startProgress('校验字段完整性')
  try {
    const payload = await api<SessionPayload>(`/api/sessions/${sessionId.value}/fields`, {
      method: 'POST',
      body: JSON.stringify({ fields: editableFields })
    })
    applySession(payload)
  } finally {
    busy.value = false
    stopProgress()
  }
}

async function generateDocument() {
  if (!canGenerate.value) return
  generating.value = true
  startProgress('准备生成任务')
  rotateGenerationSteps()
  try {
    const payload =
      mode.value === 'nonprofessional'
        ? await api<SessionPayload>('/api/nonprofessional/generate', {
            method: 'POST',
            body: JSON.stringify({
              description: naturalDescription.value.trim(),
              fields_override: editableFields
            })
          })
        : await api<SessionPayload>(`/api/sessions/${sessionId.value}/generate`, {
            method: 'POST',
            body: JSON.stringify({ fields: editableFields })
          })
    applySession(payload)
  } finally {
    generating.value = false
    stopProgress()
  }
}

async function analyzeNaturalDescription() {
  if (!canAnalyzeNatural.value) return
  busy.value = true
  startProgress('分析描述')
  try {
    const result = await api<NaturalAnalysisPayload>('/api/nonprofessional/analyze', {
      method: 'POST',
      body: JSON.stringify({ description: naturalDescription.value.trim() })
    })
    naturalAnalyzed.value = true
    applyNaturalAnalysis(result)
  } finally {
    busy.value = false
    stopProgress()
  }
}

function applyNaturalAnalysis(result: NaturalAnalysisPayload) {
  const fields = result.fields || {}
  for (const field of requiredFields.value) {
    editableFields[field.key] = fields[field.key] || editableFields[field.key] || ''
  }
  state.value = {
    messages: [],
    fields: { ...editableFields },
    round_count: 0,
    complete: result.complete,
    missing_keys: result.missing_keys || [],
    invalid_keys: result.invalid_keys || [],
    questions: result.questions || [],
    assistant_message: result.complete ? '字段已自动识别完整。' : '仍有字段需要补充或修正。'
  }
  downloadUrl.value = ''
  documentName.value = ''
}

function applySession(payload: SessionPayload) {
  sessionId.value = payload.session_id
  state.value = payload.state
  downloadUrl.value = payload.download_url || ''
  documentName.value = payload.document_name || '焊接标准文档.docx'
  for (const field of requiredFields.value) {
    editableFields[field.key] = payload.state.fields[field.key] || ''
  }
  nextTick(() => {
    if (messageListRef.value) {
      messageListRef.value.scrollTop = messageListRef.value.scrollHeight
    }
  })
}

async function api<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {})
    },
    ...options
  })
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || response.statusText)
  }
  return response.json() as Promise<T>
}

function startProgress(step: string) {
  window.clearInterval(progressTimer)
  generationStep.value = step
  loadingProgress.value = 12
  progressTimer = window.setInterval(() => {
    const ceiling = generating.value ? 92 : 86
    if (loadingProgress.value < ceiling) {
      loadingProgress.value += loadingProgress.value < 55 ? 7 : 3
    }
  }, 520)
}

function rotateGenerationSteps() {
  const steps = ['读取焊接输入', '检索相似工艺资料', '综合标准字段', '填充 WPS 模板', '整理下载文件']
  let index = 0
  generationStep.value = steps[index]
  window.clearInterval(progressTimer)
  progressTimer = window.setInterval(() => {
    index = Math.min(index + 1, steps.length - 1)
    generationStep.value = steps[index]
    if (loadingProgress.value < 92) {
      loadingProgress.value += index < 2 ? 10 : 5
    }
  }, 2400)
}

function stopProgress() {
  window.clearInterval(progressTimer)
  loadingProgress.value = 100
  window.setTimeout(() => {
    if (!busy.value && !generating.value && !appLoading.value) {
      loadingProgress.value = 12
      generationStep.value = '准备生成任务'
    }
  }, 360)
}
</script>
