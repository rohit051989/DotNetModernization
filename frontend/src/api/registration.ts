import { api } from './client'
import type { StepRegistration, ViewpointCoverage } from '../types/registration'

/** Every registered lifecycle step — read-only, build-time registration is
 * API-only (23-WORKFLOW-ADMINISTRATION.md Part C1). */
export function listSteps() {
  return api.get<StepRegistration[]>('/api/workflow/steps')
}

/** 25-STANDARDS-AND-VIEWPOINTS.md Part A2. */
export function getViewpointCoverage(engagementId: string) {
  return api.get<ViewpointCoverage>(`/api/engagements/${encodeURIComponent(engagementId)}/viewpoint-coverage`)
}
