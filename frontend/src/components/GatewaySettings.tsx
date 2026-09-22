import { useState, type FormEvent } from 'react'
import {
  CheckCircle,
  Cpu,
  Key,
  LockKey,
  PencilSimple,
  Plus,
  ShieldCheck,
  TestTube,
  Warning,
} from '@phosphor-icons/react'
import { api } from '../api'
import type {
  GatewayOverview,
  ModelCapability,
  ModelProfile,
  ModelProfilePayload,
  ModelProvider,
  ModelProviderPayload,
  Project,
} from '../types'

const capabilityLabels: Record<ModelCapability, string> = {
  text: '文本',
  vision: '视觉',
  json_schema: 'JSON Schema',
  tools: '工具调用',
  embedding: 'Embedding',
  file_upload: '文件上传',
}

interface GatewaySettingsProps {
  overview: GatewayOverview | null
  project: Project | null
  onOverviewChange: (overview: GatewayOverview) => void
  onProjectChange: (project: Project) => void
}

const initialProvider: ModelProviderPayload = {
  provider_kind: 'openai_compatible',
  display_name: '',
  base_url: 'https://',
  api_key: '',
  timeout_seconds: 60,
  max_retries: 1,
  enabled: true,
}

const initialModel: ModelProfilePayload = {
  provider_id: '',
  display_name: '',
  model_name: '',
  capabilities: ['text'],
  context_window: 32768,
  max_output_tokens: 4096,
  input_cost_per_million: '0',
  output_cost_per_million: '0',
  is_fallback: false,
  enabled: true,
}

export function GatewaySettings({
  overview,
  project,
  onOverviewChange,
  onProjectChange,
}: GatewaySettingsProps) {
  const [providerForm, setProviderForm] = useState(initialProvider)
  const [modelForm, setModelForm] = useState(initialModel)
  const [busy, setBusy] = useState<string | null>(null)
  const [showSecret, setShowSecret] = useState(false)
  const [clearSecret, setClearSecret] = useState(false)
  const [editingProviderId, setEditingProviderId] = useState<string | null>(null)
  const [editingProviderHasSecret, setEditingProviderHasSecret] = useState(false)
  const [editingModelId, setEditingModelId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function refresh() {
    const next = await api.gatewayOverview()
    onOverviewChange(next)
    return next
  }

  async function runOperation(key: string, operation: () => Promise<void>) {
    setBusy(key)
    setError(null)
    setNotice(null)
    try {
      await operation()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '设置保存失败')
    } finally {
      setBusy(null)
    }
  }

  function toggleCapability(capability: ModelCapability) {
    setModelForm((current) => ({
      ...current,
      capabilities: current.capabilities.includes(capability)
        ? current.capabilities.filter((item) => item !== capability)
        : [...current.capabilities, capability],
    }))
  }

  function submitProvider(event: FormEvent) {
    event.preventDefault()
    void runOperation('provider-create', async () => {
      const payload = { ...providerForm }
      if (!payload.api_key) delete payload.api_key
      payload.clear_api_key = clearSecret
      if (editingProviderId) await api.updateModelProvider(editingProviderId, payload)
      else await api.createModelProvider(payload)
      setProviderForm(initialProvider)
      setEditingProviderId(null)
      setEditingProviderHasSecret(false)
      setClearSecret(false)
      setShowSecret(false)
      await refresh()
      setNotice(editingProviderId ? '服务商配置已更新；密钥操作已写入本地审计轨迹。' : '服务商配置已保存在本机；密钥仅以 DPAPI 引用保存。')
    })
  }

  function submitModel(event: FormEvent) {
    event.preventDefault()
    void runOperation('model-create', async () => {
      if (modelForm.capabilities.length === 0) throw new Error('至少选择一项模型能力。')
      if (editingModelId) await api.updateModelProfile(editingModelId, modelForm)
      else await api.createModelProfile(modelForm)
      setModelForm(initialModel)
      setEditingModelId(null)
      await refresh()
      setNotice(editingModelId ? '模型能力档案已更新。' : '模型能力档案已保存。')
    })
  }

  function editProvider(provider: ModelProvider) {
    setEditingProviderId(provider.id)
    setEditingProviderHasSecret(provider.secret_configured)
    setProviderForm({
      provider_kind: 'openai_compatible',
      display_name: provider.display_name,
      base_url: provider.base_url,
      api_key: '',
      timeout_seconds: provider.timeout_seconds,
      max_retries: provider.max_retries,
      enabled: provider.enabled,
    })
    setClearSecret(false)
    setShowSecret(false)
    setError(null)
    setNotice(null)
  }

  function editModel(model: ModelProfile) {
    setEditingModelId(model.id)
    setModelForm({
      provider_id: model.provider_id,
      display_name: model.display_name,
      model_name: model.model_name,
      capabilities: [...model.capabilities],
      context_window: model.context_window,
      max_output_tokens: model.max_output_tokens,
      input_cost_per_million: model.input_cost_per_million,
      output_cost_per_million: model.output_cost_per_million,
      is_fallback: model.is_fallback,
      enabled: model.enabled,
    })
    setError(null)
    setNotice(null)
  }

  if (!overview) {
    return <section className="settings-page" aria-live="polite"><p>正在读取本地模型设置…</p></section>
  }

  const externalProviders = overview.providers.filter((provider) => provider.provider_kind !== 'fake')

  return (
    <section className="settings-page" aria-labelledby="settings-title">
      <header className="settings-head">
        <div>
          <span className="section-kicker">迭代二 · 多模型网关</span>
          <h1 id="settings-title">模型与外发设置</h1>
          <p>配置可以先保存，但真实外部连接尚未启用。当前只运行可审计的 Fake Provider 验收路径。</p>
        </div>
        <span className={`mode-badge ${overview.strict_offline ? 'safe' : 'warning'}`}>
          {overview.strict_offline ? <ShieldCheck aria-hidden="true" /> : <Warning aria-hidden="true" />}
          {overview.strict_offline ? '严格离线' : '外发总开关已打开'}
        </span>
      </header>

      {busy && <div className="notice settings-notice" role="status"><Cpu aria-hidden="true" /><span>正在保存本地设置…</span></div>}
      {error && <div className="notice error settings-notice" role="alert"><Warning aria-hidden="true" /><span>{error}</span></div>}
      {notice && <div className="notice success settings-notice" role="status"><CheckCircle aria-hidden="true" /><span>{notice}</span></div>}

      <div className="settings-grid">
        <section className="settings-section" aria-labelledby="egress-title">
          <div className="settings-section-head">
            <ShieldCheck aria-hidden="true" />
            <div><h2 id="egress-title">双重外发控制</h2><p>全局开关与项目授权必须同时满足；配置密钥本身不会触发请求。</p></div>
          </div>
          <div className="policy-row">
            <div><b>全局严格离线</b><span>拦截模型、视觉、Embedding、Rerank 和远端文件请求。</span></div>
            <button
              className={`button ${overview.strict_offline ? 'danger' : 'primary'}`}
              type="button"
              disabled={busy !== null}
              aria-pressed={overview.strict_offline}
              onClick={() => void runOperation('offline', async () => {
                onOverviewChange(await api.setOfflineMode(!overview.strict_offline))
                setNotice(overview.strict_offline ? '严格离线已关闭；项目仍需单独授权，且真实连接仍未启用。' : '严格离线已开启，所有外发路径已阻断。')
              })}
            >
              {overview.strict_offline ? '关闭严格离线' : '重新开启离线'}
            </button>
          </div>
          <div className="policy-row">
            <div><b>当前项目外发授权</b><span>{project ? project.name : '尚未选择项目'}</span></div>
            <button
              className="button secondary"
              type="button"
              disabled={!project || overview.strict_offline || busy !== null}
              aria-pressed={project?.external_access_enabled ?? false}
              onClick={() => project && void runOperation('project-access', async () => {
                const changed = await api.setProjectExternalAccess(project.id, !project.external_access_enabled)
                onProjectChange(changed)
                setNotice(changed.external_access_enabled ? '项目外发授权已开启；请求仍须通过最小证据审计。' : '项目外发授权已撤销。')
              })}
            >
              {project?.external_access_enabled ? '撤销项目授权' : '授权当前项目'}
            </button>
          </div>
        </section>

        <section className="settings-section" aria-labelledby="probe-title">
          <div className="settings-section-head">
            <TestTube aria-hidden="true" />
            <div><h2 id="probe-title">安全路由自检</h2><p>使用合成提示验证能力路由和调用审计，不产生外部网络请求。</p></div>
          </div>
          <div className="probe-row">
            <dl><div><dt>本地服务商</dt><dd>Fake Provider</dd></div><div><dt>调用记录</dt><dd>{overview.recent_calls.length} 条</dd></div></dl>
            <button
              className="button primary"
              type="button"
              disabled={!project || busy !== null}
              onClick={() => project && void runOperation('probe', async () => {
                const result = await api.probeGateway(project.id)
                await refresh()
                setNotice(`路由自检通过：${result.provider} / ${result.actual_model}；外部请求 0 次。`)
              })}
            ><TestTube aria-hidden="true" />运行本地自检</button>
          </div>
        </section>
      </div>

      <section className="settings-section settings-wide" aria-labelledby="providers-title">
        <div className="settings-section-head">
          <Key aria-hidden="true" />
          <div><h2 id="providers-title">服务商</h2><p>API Key 通过 Windows DPAPI 加密；界面和 API 均不回显完整值。</p></div>
        </div>
        <div className="config-list">
          {overview.providers.map((provider) => (
            <article className="config-row" key={provider.id}>
              <div><b>{provider.display_name}</b><span>{provider.base_url}</span></div>
              <div className="config-meta"><span>{provider.provider_kind === 'fake' ? '本地验收' : provider.secret_configured ? '密钥已配置' : '未配置密钥'}</span><span>{provider.timeout_seconds}s · 重试 {provider.max_retries}</span></div>
              <div className="config-actions">
                <button className="button compact" type="button" disabled={provider.provider_kind === 'fake' || busy !== null} onClick={() => editProvider(provider)}><PencilSimple aria-hidden="true" />编辑</button>
                <button className="button compact" type="button" disabled={provider.provider_kind === 'fake' || busy !== null} onClick={() => void runOperation(`provider-${provider.id}`, async () => { await api.toggleModelProvider(provider.id); await refresh() })}>{provider.enabled ? '停用' : '启用'}</button>
              </div>
            </article>
          ))}
        </div>
        <form className="config-form" onSubmit={submitProvider}>
          <div className="form-title"><Plus aria-hidden="true" /><b>{editingProviderId ? '编辑 OpenAI-compatible 服务商' : '新增 OpenAI-compatible 服务商'}</b></div>
          <label className="field"><span>显示名称</span><input required minLength={2} maxLength={80} value={providerForm.display_name} onChange={(event) => setProviderForm({ ...providerForm, display_name: event.target.value })} /></label>
          <label className="field field-wide"><span>Base URL</span><input required type="url" pattern="https://.*" value={providerForm.base_url} onChange={(event) => setProviderForm({ ...providerForm, base_url: event.target.value })} /><small>仅接受 HTTPS，例如 https://api.example.com/v1</small></label>
          <label className="field field-wide"><span>API Key（可稍后配置）</span><input type={showSecret ? 'text' : 'password'} autoComplete="new-password" disabled={clearSecret} value={providerForm.api_key ?? ''} onChange={(event) => setProviderForm({ ...providerForm, api_key: event.target.value })} /><small>{editingProviderId ? editingProviderHasSecret ? '留空表示保留现有密钥；输入新值将执行轮换。' : '当前未配置密钥；输入新值后将使用 DPAPI 保存。' : '提交后不会再次显示完整值。'}</small></label>
          <label className="secret-visibility field-wide"><input type="checkbox" checked={showSecret} onChange={(event) => setShowSecret(event.target.checked)} />显示本次输入</label>
          {editingProviderId && editingProviderHasSecret && <label className="secret-visibility field-wide danger-choice"><input type="checkbox" checked={clearSecret} onChange={(event) => { setClearSecret(event.target.checked); if (event.target.checked) setProviderForm({ ...providerForm, api_key: '' }) }} />清除已保存的 API Key</label>}
          <label className="field"><span>超时（秒）</span><input required type="number" min={1} max={300} value={providerForm.timeout_seconds} onChange={(event) => setProviderForm({ ...providerForm, timeout_seconds: Number(event.target.value) })} /></label>
          <label className="field"><span>最大重试</span><input required type="number" min={0} max={3} value={providerForm.max_retries} onChange={(event) => setProviderForm({ ...providerForm, max_retries: Number(event.target.value) })} /></label>
          <div className="config-form-actions">
            {editingProviderId && <button className="button secondary" type="button" onClick={() => { setEditingProviderId(null); setEditingProviderHasSecret(false); setProviderForm(initialProvider); setClearSecret(false) }}>取消编辑</button>}
            <button className="button secondary" type="submit" disabled={busy !== null}><LockKey aria-hidden="true" />{editingProviderId ? '保存修改' : '保存服务商'}</button>
          </div>
        </form>
      </section>

      <section className="settings-section settings-wide" aria-labelledby="models-title">
        <div className="settings-section-head">
          <Cpu aria-hidden="true" />
          <div><h2 id="models-title">模型能力档案</h2><p>业务只声明所需能力，运行时记录实际使用的服务商和模型。</p></div>
        </div>
        <div className="config-list">
          {overview.models.map((model) => (
            <article className="config-row model-row" key={model.id}>
              <div><b>{model.display_name}</b><span>{model.model_name}</span></div>
              <div className="capability-list">{model.capabilities.map((item) => <span key={item}>{capabilityLabels[item]}</span>)}</div>
              <div className="config-actions">
                <button className="button compact" type="button" disabled={model.id === 'fake-structured-v1' || busy !== null} onClick={() => editModel(model)}><PencilSimple aria-hidden="true" />编辑</button>
                <button className="button compact" type="button" disabled={model.id === 'fake-structured-v1' || busy !== null} onClick={() => void runOperation(`model-${model.id}`, async () => { await api.toggleModelProfile(model.id); await refresh() })}>{model.enabled ? '停用' : '启用'}</button>
              </div>
            </article>
          ))}
        </div>
        <form className="config-form" onSubmit={submitModel}>
          <div className="form-title"><Plus aria-hidden="true" /><b>{editingModelId ? '编辑模型档案' : '新增模型档案'}</b></div>
          <label className="field"><span>服务商</span><select required value={modelForm.provider_id} onChange={(event) => setModelForm({ ...modelForm, provider_id: event.target.value })}><option value="">请选择</option>{externalProviders.filter((provider) => provider.enabled || provider.id === modelForm.provider_id).map((provider) => <option key={provider.id} value={provider.id}>{provider.display_name}</option>)}</select></label>
          <label className="field"><span>显示名称</span><input required minLength={2} maxLength={80} value={modelForm.display_name} onChange={(event) => setModelForm({ ...modelForm, display_name: event.target.value })} /></label>
          <label className="field field-wide"><span>模型标识</span><input required maxLength={160} value={modelForm.model_name} onChange={(event) => setModelForm({ ...modelForm, model_name: event.target.value })} /></label>
          <fieldset className="capability-field field-wide"><legend>能力</legend><div>{(Object.keys(capabilityLabels) as ModelCapability[]).map((capability) => <label key={capability}><input type="checkbox" checked={modelForm.capabilities.includes(capability)} onChange={() => toggleCapability(capability)} />{capabilityLabels[capability]}</label>)}</div></fieldset>
          <label className="field"><span>上下文长度</span><input required type="number" min={1024} value={modelForm.context_window} onChange={(event) => setModelForm({ ...modelForm, context_window: Number(event.target.value) })} /></label>
          <label className="field"><span>输出上限</span><input required type="number" min={1} value={modelForm.max_output_tokens} onChange={(event) => setModelForm({ ...modelForm, max_output_tokens: Number(event.target.value) })} /></label>
          <div className="config-form-actions">
            {editingModelId && <button className="button secondary" type="button" onClick={() => { setEditingModelId(null); setModelForm(initialModel) }}>取消编辑</button>}
            <button className="button secondary" type="submit" disabled={externalProviders.length === 0 || busy !== null}><Plus aria-hidden="true" />{editingModelId ? '保存修改' : '保存模型档案'}</button>
          </div>
        </form>
      </section>
    </section>
  )
}
