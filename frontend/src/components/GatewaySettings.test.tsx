import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GatewaySettings } from './GatewaySettings'
import type { GatewayOverview, Project } from '../types'

const overview: GatewayOverview = {
  strict_offline: true,
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
})
