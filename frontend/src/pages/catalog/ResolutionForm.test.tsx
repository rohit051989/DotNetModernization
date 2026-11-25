import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/Toast'
import type { ItemResolution } from '../../types/items'
import { ResolutionCard } from './ResolutionCard'
import { ResolutionForm } from './ResolutionForm'

const api = vi.hoisted(() => ({ createResolution: vi.fn(), updateResolution: vi.fn() }))
vi.mock('../../api/items', () => ({ createResolution: api.createResolution, updateResolution: api.updateResolution }))

const REST: ItemResolution = {
  id: 'rest-net10', item_id: 'wcf-service', name: 'REST API on .NET 10', description: null, target_description: null,
  consumer_impact: 'high', effort: 'high', is_default: false, linux_compatible: true, container_ready: true,
  confirm_design: false, notes: null, status: 'active', deleted_at: null, created_at: '', updated_at: '',
}

afterEach(cleanup)

describe('confirm the design before implementing', () => {
  it('an admin sets it on a resolution, sent with the version of the copy edited', async () => {
    api.updateResolution.mockResolvedValue({ ...REST, confirm_design: true })
    render(
      <ToastProvider>
        <ResolutionForm mode="edit" itemId="wcf-service" itemVersion={7} resolution={REST} existingDefault={null}
          onClose={vi.fn()} onSaved={vi.fn()} />
      </ToastProvider>,
    )
    const box = screen.getByLabelText(/Confirm the design before implementing/) as HTMLInputElement
    expect(box.checked).toBe(false)
    fireEvent.click(box)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /save/i }))
    })
    expect(api.updateResolution).toHaveBeenCalledWith('wcf-service', 'rest-net10',
      expect.objectContaining({ confirm_design: true }), 7)
  })

  it('an admin writes the instruction for the conversion engine, and empty sends none', async () => {
    api.updateResolution.mockResolvedValue({ ...REST, engine_guidance: 'Expose each operation as an HTTP endpoint.' })
    render(
      <ToastProvider>
        <ResolutionForm mode="edit" itemId="wcf-service" itemVersion={3} resolution={{ ...REST, engine_guidance: null }}
          existingDefault={null} onClose={vi.fn()} onSaved={vi.fn()} />
      </ToastProvider>,
    )
    const field = screen.getByLabelText(/Instruction for the conversion engine/) as HTMLTextAreaElement
    expect(field.value).toBe('')
    fireEvent.change(field, { target: { value: '  Expose each operation as an HTTP endpoint.  ' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /save/i }))
    })
    expect(api.updateResolution).toHaveBeenLastCalledWith('wcf-service', 'rest-net10',
      expect.objectContaining({ engine_guidance: 'Expose each operation as an HTTP endpoint.' }), 3)
  })

  it('a flagged resolution says so on its card, an unflagged one does not', () => {
    render(<ResolutionCard resolution={{ ...REST, confirm_design: true }} isLowestImpact={false} />)
    expect(screen.getByTestId('confirm-design').textContent).toBe('design confirmed first')
    cleanup()
    render(<ResolutionCard resolution={REST} isLowestImpact={false} />)
    expect(screen.queryByTestId('confirm-design')).toBeNull()
  })
})

describe('the phase of a resolution', () => {
  it('the card names it, or says it is not set', () => {
    render(<ResolutionCard resolution={{ ...REST, phase: 4 }} isLowestImpact={false} />)
    expect(screen.getByTestId('phase').textContent).toBe('phase 4: Retarget and host applications')
    cleanup()
    render(<ResolutionCard resolution={{ ...REST, phase: null }} isLowestImpact={false} />)
    expect(screen.getByTestId('phase').textContent).toBe('no phase')
  })

  it('an admin changes it in the form, and it is sent as a number', async () => {
    api.updateResolution.mockResolvedValue({ ...REST, phase: 2 })
    render(
      <ToastProvider>
        <ResolutionForm mode="edit" itemId="wcf-service" itemVersion={5} resolution={{ ...REST, phase: 4 }}
          existingDefault={null} onClose={vi.fn()} onSaved={vi.fn()} />
      </ToastProvider>,
    )
    const select = screen.getByLabelText('Phase') as HTMLSelectElement
    expect(select.value).toBe('4')
    fireEvent.change(select, { target: { value: '2' } })
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /save/i }))
    })
    expect(api.updateResolution).toHaveBeenLastCalledWith('wcf-service', 'rest-net10',
      expect.objectContaining({ phase: 2 }), 5)
  })
})
