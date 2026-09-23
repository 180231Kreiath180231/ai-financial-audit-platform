import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { GatewaySettings } from './GatewaySettings'
import type { GatewayOverview, Project } from '../types'

const overview: GatewayOverview = {
  strict_offline: true,
  cache_enabled: true,
  cache_entry_count: 0,
  providers: [{
    id: 'fake-provider',
    provider_kind: 'fake',
    display_name: 'Fake Provider',
    base_url: 'local://fake',
    secret_configured: false,
    default_headers: {},
    timeout_seconds: 1,
    max_retries: 0,
    enabled: true,
    created_at: '2026-09-22T00:00:00Z',
    updated_at: '2026-09-22T00:00:00Z',
  }],
  models: [{
    id: 'fake-structured-v1',
    provider_id: 'fake-provider',
    display_name: 'Fake Structured Model',
    model_name: 'fake-structured-v1',
    capabilities: ['text', 'vision', 'json_schema'],
    context_window: 32768,
    max_output_tokens: 4096,
    input_cost_per_million: '0',
    output_cost_per_million: '0',
    is_fallback: false,
    enabled: true,
    created_at: '2026-09-22T00:00:00Z',
    updated_at: '2026-09-22T00:00:00Z',
  }],
  recent_calls: [],
}

const project = {
  id: 'synthetic-project',
  name: '合成项目',
  external_access_enabled: false,
} as Project

describe('GatewaySettings', () => {
  it('keeps project consent disabled while strict offline is active', () => {
    render(<GatewaySettings overview={overview} project={project} onOverviewChange={vi.fn()} onProjectChange={vi.fn()} />)

    expect(screen.getByRole('heading', { name: '模型与外发设置' })).toBeVisible()
    expect(screen.getByRole('button', { name: '授权当前项目' })).toBeDisabled()
    expect(screen.getByLabelText(/API Key（可稍后配置）/)).toHaveAttribute('type', 'password')
    expect(screen.getByRole('checkbox', { name: '显示本次输入' })).not.toBeChecked()
  })

  it('shows model capabilities as text rather than color alone', () => {
    render(<GatewaySettings overview={overview} project={project} onOverviewChange={vi.fn()} onProjectChange={vi.fn()} />)

    expect(screen.getByText('文本', { selector: '.capability-list span' })).toBeVisible()
    expect(screen.getByText('视觉', { selector: '.capability-list span' })).toBeVisible()
    expect(screen.getByText('JSON Schema', { selector: '.capability-list span' })).toBeVisible()
  })

  it('locks PaddleOCR configuration to the approved jobs endpoint', async () => {
    const user = userEvent.setup()
    render(<GatewaySettings overview={overview} project={project} onOverviewChange={vi.fn()} onProjectChange={vi.fn()} />)

    await user.selectOptions(screen.getByRole('combobox', { name: /服务商类型/ }), 'paddleocr_aistudio')

    expect(screen.getByRole('textbox', { name: /Base URL/ })).toHaveValue('https://paddleocr.aistudio-app.com/api/v2/ocr/jobs')
    expect(screen.getByRole('textbox', { name: /Base URL/ })).toHaveAttribute('readonly')
    expect(screen.getByLabelText(/Access Token（可稍后配置）/)).toHaveAttribute('type', 'password')
    expect(screen.getByText('固定为已批准的异步 Jobs Endpoint。')).toBeVisible()
  })

  it('enters an explicit credential rotation state without revealing the saved key', async () => {
    const user = userEvent.setup()
    const editable: GatewayOverview = {
      ...overview,
      providers: [...overview.providers, {
        ...overview.providers[0],
        id: 'external-provider',
        provider_kind: 'openai_compatible',
        display_name: 'Synthetic Provider',
        base_url: 'https://models.invalid/v1',
        secret_configured: true,
      }],
    }
    render(<GatewaySettings overview={editable} project={project} onOverviewChange={vi.fn()} onProjectChange={vi.fn()} />)

    await user.click(screen.getAllByRole('button', { name: '编辑' })[1])

    expect(screen.getByText('编辑 OpenAI-compatible 服务商')).toBeVisible()
    expect(screen.getByLabelText(/API Key（可稍后配置）/)).toHaveValue('')
    expect(screen.getByText('留空表示保留现有密钥；输入新值将执行轮换。')).toBeVisible()
    expect(screen.getByRole('checkbox', { name: '清除已保存的 API Key' })).not.toBeChecked()
  })

  it('requires an explicit confirmation before deleting a provider', async () => {
    const user = userEvent.setup()
    const editable: GatewayOverview = {
      ...overview,
      providers: [...overview.providers, {
        ...overview.providers[0],
        id: 'external-provider',
        provider_kind: 'openai_compatible',
        display_name: 'Synthetic Provider',
        base_url: 'https://models.invalid/v1',
      }],
    }
    render(<GatewaySettings overview={editable} project={project} onOverviewChange={vi.fn()} onProjectChange={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: '删除服务商 Synthetic Provider' }))

    expect(screen.getByRole('dialog')).toBeVisible()
    expect(screen.getByRole('heading', { name: '确认删除“Synthetic Provider”' })).toBeVisible()
    expect(screen.getByText(/历史调用审计不会被删除/)).toBeVisible()
    expect(screen.getByRole('button', { name: '取消' })).toHaveFocus()
    await user.click(screen.getByRole('button', { name: '取消' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
