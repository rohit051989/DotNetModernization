import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CatalogExportStatus } from '../../types/items'
import { CatalogExportPanel } from './CatalogExportPanel'

const api = vi.hoisted(() => ({ status: null as unknown as CatalogExportStatus }))
vi.mock('../../api/items', () => ({ getCatalogExportStatus: () => Promise.resolve(api.status) }))

const EDITED = { item_id: 'serilog-file-sink', item_name: 'Serilog file sink', change: 'edited' as const }

function status(overrides: Partial<CatalogExportStatus>): CatalogExportStatus {
  return { last_export: null, current_hash: 'h', is_current: true, changed: 0, changes: [], installation: false, command: 'python -m app.items.catalog_export export', ...overrides }
}

async function renderPanel() {
  render(<CatalogExportPanel refreshToken={0} onSelectItem={() => {}} />)
  await act(async () => {})
}

afterEach(cleanup)

describe('CatalogExportPanel', () => {
  it('in our repository, offers to export into the repository and commit', async () => {
    api.status = status({ is_current: false, changed: 1, changes: [EDITED] })
    await renderPanel()
    expect(screen.getByText('1 item differs from the exported files')).toBeTruthy()
    expect(screen.getByText(/Export into the repository and commit/)).toBeTruthy()
  })

  it('on an installation matching its catalog files, says so', async () => {
    api.status = status({ installation: true })
    await renderPanel()
    expect(screen.getByText('Matches the platform’s catalog files')).toBeTruthy()
  })

  it('on an installation with local edits, lists them and never offers to export into the repository or commit', async () => {
    api.status = status({
      installation: true, is_current: false, changed: 1, changes: [EDITED],
      command: 'python -m app.items.catalog_export export --changed --out "C:\\MP\\runs\\catalog-edits"',
    })
    await renderPanel()
    expect(screen.getByText('1 item edited on this installation')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'serilog-file-sink' })).toBeTruthy()
    expect(screen.queryByText(/commit/i)).toBeNull()
    expect(screen.getByRole('link', { name: 'Download the edited items' }).getAttribute('href')).toMatch(/\/api\/catalog\/export\/items\?changed_only=true$/)
    expect(screen.getByText(/--changed --out/)).toBeTruthy()
  })
})
