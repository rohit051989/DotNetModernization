import { api, apiUrl } from './client'
import type { EndpointAnnotation, EndpointAnnotationInput, EstateSettings, EstateView } from '../types/estate'

export function getEstate(engagementId: string) {
  return api.get<EstateView>(`/api/engagements/${encodeURIComponent(engagementId)}/estate`)
}

export function putEndpointAnnotation(engagementId: string, host: string, annotation: EndpointAnnotationInput) {
  return api.put<EndpointAnnotation>(
    `/api/engagements/${encodeURIComponent(engagementId)}/estate/annotations/${encodeURIComponent(host)}`,
    annotation,
  )
}

/** Only the fields given are changed. */
export function putEstateSettings(
  engagementId: string,
  settings: { production_environment?: string | null; deploy_parameter_globs?: string[] | null; target_wcf_client_version?: string | null },
  version?: number,
) {
  return api.put<EstateSettings>(`/api/engagements/${encodeURIComponent(engagementId)}/estate/settings`, settings, { version })
}

/** The SOAP backend compatibility report as CSV — named -DRAFT while any matrix entry it rests on is unconfirmed. */
export function soapCompatibilityCsvUrl(engagementId: string) {
  return apiUrl(`/api/engagements/${encodeURIComponent(engagementId)}/estate/soap-compatibility.csv`)
}
