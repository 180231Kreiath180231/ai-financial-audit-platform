import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusMark } from './StatusMark'

describe('StatusMark', () => {
  it('shows a textual status instead of relying on color', () => {
    render(<StatusMark status="failed" />)
    expect(screen.getByText('处理失败')).toBeVisible()
  })

  it('announces the paused state as visible text', () => {
    render(<StatusMark status="paused" />)
    expect(screen.getByText('已暂停')).toBeVisible()
  })
})
