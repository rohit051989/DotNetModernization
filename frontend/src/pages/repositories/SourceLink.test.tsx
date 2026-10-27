import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Editor } from '../../api/editors'
import { ToastProvider } from '../../components/Toast'
import { fullPath, resetEditorChoiceForTests } from './editorChoice'
import { RepositoryFiles, SourceLink } from './SourceLink'
import type { RepositoryDetail } from '../../types/repositories'

const api = vi.hoisted(() => ({ installed: [] as Editor[], openInVisualStudio: vi.fn(), recordRepositoryClone: vi.fn(), forgetRepositoryClone: vi.fn() }))
vi.mock('../../api/editors', () => ({
  listEditors: () => Promise.resolve({ editors: api.installed }),
  openInVisualStudio: api.openInVisualStudio,
}))
vi.mock('../../api/repositories', () => ({
  recordRepositoryClone: api.recordRepositoryClone,
  forgetRepositoryClone: api.forgetRepositoryClone,
}))

const VSCODE: Editor = { id: 'vscode', kind: 'vscode', label: 'VS Code', opens_at_line: true }
const VISUAL_STUDIO: Editor = {
  id: 'visual_studio:vs2022', kind: 'visual_studio', label: 'Visual Studio Professional 2022', opens_at_line: true, installation: 'vs2022', version: '17.14.37516.0',
}
const VISUAL_STUDIO_2026: Editor = {
  id: 'visual_studio:vs2026', kind: 'visual_studio', label: 'Visual Studio Enterprise 2026', opens_at_line: true, installation: 'vs2026', version: '18.0.11205.157',
}

function renderLink() {
  return render(
    <ToastProvider>
      <SourceLink localPath="D:\repos\shop" filePath="src/Web/Order Service.cs" line={42}>
        OrderService
      </SourceLink>
    </ToastProvider>,
  )
}

/** Lets the editors request settle, then opens the menu beside the link. */
async function openMenu() {
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: /More ways to open/ }))
}

beforeEach(() => {
  window.localStorage.clear()
  resetEditorChoiceForTests()
  api.openInVisualStudio.mockReset()
  Object.assign(navigator, { clipboard: { writeText: vi.fn(() => Promise.resolve()) } })
})
afterEach(cleanup)

describe('SourceLink', () => {
  it('opens VS Code through its vscode:// link, at the file and line, when VS Code is the choice', async () => {
    api.installed = [VSCODE, VISUAL_STUDIO]
    renderLink()
    await act(async () => {})
    expect(screen.getByRole('link', { name: 'OrderService' }).getAttribute('href')).toBe('vscode://file/D:/repos/shop/src/Web/Order%20Service.cs:42')
  })

  it('offers only the editors found on the machine, and always copying', async () => {
    api.installed = [VISUAL_STUDIO]
    renderLink()
    await openMenu()
    expect(screen.queryByRole('menuitem', { name: 'Open in VS Code' })).toBeNull()
    expect(screen.getByRole('menuitem', { name: 'Open in Visual Studio Professional 2022' })).toBeTruthy()
    expect(screen.getByRole('menuitem', { name: 'Copy path and line' })).toBeTruthy()
    expect(screen.getAllByRole('radio').map((r) => r.parentElement?.textContent)).toEqual(['Visual Studio Professional 2022', 'Copy only'])
    expect(screen.getByText(/VS Code was not found on this/)).toBeTruthy()
  })

  it('with neither editor installed, the link copies the path and line', async () => {
    api.installed = []
    renderLink()
    await act(async () => {})
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'OrderService' }))
    })
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('D:\\repos\\shop\\src\\Web\\Order Service.cs:42')
    expect(screen.getByRole('status').textContent).toBe('Copied D:\\repos\\shop\\src\\Web\\Order Service.cs:42')
  })

  it('remembers the choice in the browser, and the link then asks the backend to open Visual Studio', async () => {
    api.installed = [VSCODE, VISUAL_STUDIO]
    api.openInVisualStudio.mockResolvedValue({ opened: true, at_line: true, message: 'Opened Order Service.cs at line 42 in Visual Studio.' })
    renderLink()
    await openMenu()
    fireEvent.click(screen.getByRole('radio', { name: 'Visual Studio Professional 2022' }))
    expect(window.localStorage.getItem('file-links:editor')).toBe('visual_studio:vs2022')

    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'OrderService' }))
    })
    expect(api.openInVisualStudio).toHaveBeenCalledWith('D:\\repos\\shop\\src\\Web\\Order Service.cs', 42, 'vs2022')
    expect(screen.getAllByRole('status').map((s) => s.textContent)).toContain('Opened Order Service.cs at line 42 in Visual Studio.')
  })

  it('a remembered editor that is not on this machine falls back to the first one that is', async () => {
    window.localStorage.setItem('file-links:editor', 'visual_studio:vs2022')
    api.installed = [VSCODE]
    renderLink()
    await act(async () => {})
    expect(screen.getByRole('link', { name: 'OrderService' }).getAttribute('href')).toMatch(/^vscode:\/\//)
  })

  it('says plainly when the backend refuses the path', async () => {
    api.installed = [VISUAL_STUDIO]
    api.openInVisualStudio.mockRejectedValue(new Error('D:\\elsewhere\\x.cs is outside every registered repository, conversion worktree and RUNS_DIR: not opened'))
    renderLink()
    await openMenu()
    await act(async () => {
      fireEvent.click(screen.getByRole('menuitem', { name: 'Open in Visual Studio Professional 2022' }))
    })
    expect(screen.getAllByRole('status').map((s) => s.textContent)).toContain(
      'D:\\elsewhere\\x.cs is outside every registered repository, conversion worktree and RUNS_DIR: not opened',
    )
  })

  it('lists each Visual Studio installation by its full name, newest first, and opens the one chosen', async () => {
    api.installed = [VSCODE, VISUAL_STUDIO_2026, VISUAL_STUDIO]
    api.openInVisualStudio.mockResolvedValue({ opened: true, at_line: true, message: 'Opened.' })
    renderLink()
    await openMenu()
    expect(screen.getAllByRole('menuitem').map((m) => m.textContent)).toEqual([
      'Open in VS Code',
      'Open in Visual Studio Enterprise 2026',
      'Open in Visual Studio Professional 2022',
      'Copy path and line',
    ])
    expect(screen.queryByText(/was not found/)).toBeNull()
    fireEvent.click(screen.getByRole('radio', { name: 'Visual Studio Professional 2022' }))
    expect(window.localStorage.getItem('file-links:editor')).toBe('visual_studio:vs2022')
    await act(async () => {
      fireEvent.click(screen.getByRole('link', { name: 'OrderService' }))
    })
    expect(api.openInVisualStudio).toHaveBeenLastCalledWith('D:\\repos\\shop\\src\\Web\\Order Service.cs', 42, 'vs2022')
  })

  it('a Visual Studio remembered before installations were told apart, or no longer installed, becomes the newest', async () => {
    api.installed = [VSCODE, VISUAL_STUDIO_2026, VISUAL_STUDIO]
    api.openInVisualStudio.mockResolvedValue({ opened: true, at_line: true, message: 'Opened.' })
    for (const remembered of ['visual_studio', 'visual_studio:removed-install']) {
      cleanup()
      resetEditorChoiceForTests()
      window.localStorage.setItem('file-links:editor', remembered)
      renderLink()
      await act(async () => {})
      await act(async () => {
        fireEvent.click(screen.getByRole('link', { name: 'OrderService' }))
      })
      expect(api.openInVisualStudio).toHaveBeenLastCalledWith('D:\\repos\\shop\\src\\Web\\Order Service.cs', 42, 'vs2026')
    }
  })

  it('with no local path, shows the text without a link or menu', () => {
    render(
      <SourceLink localPath={null} filePath="src/X.cs" line={3}>
        X
      </SourceLink>,
    )
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('SourceLink inside a repository: each person opens files from their own clone', () => {
  const SHOP = { id: 'r', name: 'Shop', clone_command: 'git clone -c core.longpaths=true https://git.client-a.example/team/Shop.git "C:\\MP\\repos\\Shop"' }

  function renderIn(clonePath: string | null, onRecorded = vi.fn()) {
    render(
      <ToastProvider>
        <RepositoryFiles repository={{ ...SHOP, my_clone_path: clonePath }} onRecorded={onRecorded}>
          <SourceLink localPath="D:\owners\shop" filePath="src/Web/Orders.cs" line={7}>
            Orders
          </SourceLink>
        </RepositoryFiles>
      </ToastProvider>,
    )
    return onRecorded
  }

  it("opens from the viewer's own clone, not the owner's folder", async () => {
    api.installed = [VSCODE]
    renderIn('E:\\ben\\Shop')
    await act(async () => {})
    expect(screen.getByRole('link', { name: 'Orders' }).getAttribute('href')).toBe('vscode://file/E:/ben/Shop/src/Web/Orders.cs:7')
  })

  it('with no clone recorded, offers to record one, with the git clone command, or to copy the relative path', async () => {
    api.installed = [VSCODE]
    const onRecorded = renderIn(null)
    await act(async () => {})
    expect(screen.queryByRole('link')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Orders' }))
    await act(async () => {
      fireEvent.click(screen.getByRole('menuitem', { name: /Copy the relative path/ }))
    })
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('src/Web/Orders.cs:7')

    fireEvent.click(screen.getByRole('button', { name: 'Orders' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Record your clone…' }))
    const dialog = screen.getByRole('dialog', { name: 'Your clone of Shop' })
    expect(dialog.textContent).toContain(SHOP.clone_command)
    // The folder the command clones into is the default answer.
    expect((screen.getByLabelText("Your clone's folder") as HTMLInputElement).value).toBe('C:\\MP\\repos\\Shop')

    const recorded = { ...SHOP, my_clone_path: 'C:\\MP\\repos\\Shop' } as RepositoryDetail
    api.recordRepositoryClone.mockResolvedValue(recorded)
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    })
    expect(api.recordRepositoryClone).toHaveBeenCalledWith('r', 'C:\\MP\\repos\\Shop')
    expect(onRecorded).toHaveBeenCalledWith(recorded)
  })

  it("says plainly why a folder is refused: a clone of another repository", async () => {
    renderIn(null)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: 'Orders' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Record your clone…' }))
    api.recordRepositoryClone.mockRejectedValue(new Error('E:\\other is a clone of https://git.client-a.example/team/other, not of Shop: not recorded.'))
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Record' }))
    })
    expect(screen.getByRole('alert').textContent).toContain('not of Shop: not recorded.')
  })
})

describe('fullPath', () => {
  it("follows the repository path's own separators", () => {
    expect(fullPath('D:\\repos\\shop\\', 'src/Web/X.cs')).toBe('D:\\repos\\shop\\src\\Web\\X.cs')
    expect(fullPath('/home/me/shop', 'src/Web/X.cs')).toBe('/home/me/shop/src/Web/X.cs')
  })
})
