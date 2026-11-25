import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { ToastProvider } from '../../components/Toast'
import { EngagementConventions } from './EngagementConventions'
import { EngagementNote } from './EngagementNote'

const api = vi.hoisted(() => ({
  putResolutionNote: vi.fn(), getConventions: vi.fn(), putConventions: vi.fn(), listResolutionNotes: vi.fn(),
}))
vi.mock('../../api/engagementGuidance', () => api)
vi.mock('../../auth/AuthContext', () => ({ useIsAdmin: () => true }))

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe("an engagement's note on a resolution", () => {
  it('an admin adds one, sent with version 0 when there was none', async () => {
    const onSaved = vi.fn()
    api.putResolutionNote.mockResolvedValue({ resolution_id: 'r', item_id: 'i', note: 'Use the client logger.', version: 1,
      updated_by: 'Admin', updated_at: '' })
    render(<ToastProvider><EngagementNote engagementId="e1" resolutionId="r" note={undefined} isAdmin onSaved={onSaved} /></ToastProvider>)
    expect(screen.getByTestId('engagement-note').textContent).toContain('conversions use the master guidance alone')
    fireEvent.click(screen.getByRole('button', { name: 'Add note' }))
    fireEvent.change(screen.getByLabelText('Engagement note'), { target: { value: '  Use the client logger.  ' } })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save note' })) })
    expect(api.putResolutionNote).toHaveBeenCalledWith('e1', 'r', 'Use the client logger.', 0)
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ version: 1 }))
  })

  it('a refused note shows the field error, and a developer cannot edit', async () => {
    api.putResolutionNote.mockRejectedValue(new ApiError(422, 'refused', [{ field: 'note', message: 'must be self-contained' }]))
    render(<ToastProvider><EngagementNote engagementId="e1" resolutionId="r" isAdmin onSaved={vi.fn()}
      note={{ resolution_id: 'r', item_id: 'i', note: 'Old.', version: 3, updated_by: null, updated_at: null }} /></ToastProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Edit note' }))
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save note' })) })
    expect(api.putResolutionNote).toHaveBeenCalledWith('e1', 'r', 'Old.', 3)
    expect(screen.getByRole('alert').textContent).toBe('must be self-contained')
    cleanup()
    render(<ToastProvider><EngagementNote engagementId="e1" resolutionId="r" isAdmin={false} onSaved={vi.fn()}
      note={{ resolution_id: 'r', item_id: 'i', note: 'Old.', version: 3, updated_by: null, updated_at: null }} /></ToastProvider>)
    expect(screen.queryByRole('button', { name: 'Edit note' })).toBeNull()
  })
})

describe("an engagement's conventions", () => {
  it('load, and save with the settings version', async () => {
    api.getConventions.mockResolvedValue({ conventions: '- Log to standard output.', version: 4 })
    api.putConventions.mockResolvedValue({ conventions: '- Log to standard output.\n- Problem details.', version: 5 })
    render(<ToastProvider><EngagementConventions engagementId="e1" /></ToastProvider>)
    const box = (await screen.findByLabelText('Conventions')) as HTMLTextAreaElement
    await waitFor(() => expect(box.value).toBe('- Log to standard output.'))
    fireEvent.change(box, { target: { value: '- Log to standard output.\n- Problem details.' } })
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Save conventions' })) })
    expect(api.putConventions).toHaveBeenCalledWith('e1', '- Log to standard output.\n- Problem details.', 4)
  })
})
