import { useState } from 'react'
import { StepRegistrySection } from './StepRegistrySection'
import { JobDefinitionsAdminSection } from './JobDefinitionsAdminSection'
import { GlobalPolicySection } from './GlobalPolicySection'
import { PolicyMatrixSection } from './PolicyMatrixSection'
import { ViewpointCoverageSection } from './ViewpointCoverageSection'
import { DetectionCapabilitiesSection } from './DetectionCapabilitiesSection'

type Section = 'registry' | 'viewpoints' | 'capabilities' | 'definitions' | 'policy' | 'matrix'

const SECTIONS: { key: Section; label: string }[] = [
  { key: 'registry', label: 'Step registry' },
  { key: 'viewpoints', label: 'Viewpoint coverage' },
  { key: 'capabilities', label: 'Detection capabilities' },
  { key: 'definitions', label: 'Job definitions' },
  { key: 'policy', label: 'Global policy' },
  { key: 'matrix', label: 'Policy matrix' },
]

/** 23-WORKFLOW-ADMINISTRATION.md Part C — master-scope administration of
 * the step registry, job definitions, and policy at both global and
 * engagement level. Visible only in Master Catalog view; the caller
 * (App.tsx) gates rendering on that, mirroring how engagement-only tabs are
 * gated the other way.
 *
 * Admins only: the tab shows to admins only, and the backend refuses anyone
 * else's changes (app.auth.policy; 04-FRONTEND-SPEC.md, "Sign-in and roles").
 */
export function WorkflowAdministrationPage() {
  const [section, setSection] = useState<Section>('registry')

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-6">
      <div>
        <h1 className="text-lg font-semibold text-neutral-900">Workflow Administration</h1>
        <p className="text-sm text-neutral-500">
          The step registry, job definitions, and policy at both global and engagement level.
        </p>
      </div>

      <nav className="flex gap-1 border-b border-neutral-200">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setSection(s.key)}
            className={`border-b-2 px-3 py-2 text-sm font-medium ${
              section === s.key ? 'border-violet-600 text-neutral-900' : 'border-transparent text-neutral-500 hover:text-neutral-800'
            }`}
          >
            {s.label}
          </button>
        ))}
      </nav>

      {section === 'registry' && <StepRegistrySection />}
      {section === 'viewpoints' && <ViewpointCoverageSection />}
      {section === 'capabilities' && <DetectionCapabilitiesSection />}
      {section === 'definitions' && <JobDefinitionsAdminSection />}
      {section === 'policy' && <GlobalPolicySection />}
      {section === 'matrix' && <PolicyMatrixSection />}
    </div>
  )
}
