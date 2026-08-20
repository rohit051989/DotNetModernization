import { api } from './client'
import type { StepRegistration } from '../types/registration'

/** Every registered lifecycle step — read-only, build-time registration is
 * API-only (23-WORKFLOW-ADMINISTRATION.md Part C1). */
export function listSteps() {
  return api.get<StepRegistration[]>('/api/workflow/steps')
}
