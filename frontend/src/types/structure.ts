export type ScanStatus = 'complete' | 'partial' | 'failed'
export type ParseStatus = 'success' | 'partial' | 'failed' | 'out_of_scope'
export type ProjectFormat = 'legacy_msbuild' | 'sdk_style' | 'unknown'
export type ProjectLanguage = 'csharp' | 'vb' | 'fsharp' | 'sql' | 'ssis' | 'cpp' | 'shared' | 'unknown'
export type SolutionProjectResolution = 'resolved' | 'unresolved'
export type ProjectReferenceResolution = 'resolved' | 'unresolved' | 'external_repository'
export type PackageDeclarationSource = 'packagereference' | 'packages_config'
export type PackageManagementStyle = 'packagereference' | 'packages_config' | 'mixed' | 'none'
export type RepositoryArtifactCategory =
  | 'build'
  | 'package'
  | 'pipeline'
  | 'container'
  | 'script'
  | 'configuration'
  | 'deployment'
  | 'documentation'

export interface ParseWarning {
  path: string
  warning: string
}

export interface RepositoryStructure {
  repository_id: string
  scan_status: ScanStatus
  solution_count: number | null
  project_file_count: number | null
  projects_referenced_count: number | null
  standalone_project_count: number | null
  shared_project_count: number | null
  unresolved_reference_count: number | null
  out_of_scope_project_count: number | null
  unknown_project_count: number | null
  failed_parse_count: number | null
  legacy_project_count: number | null
  sdk_project_count: number | null
  framework_families: Record<string, number>
  artifact_counts: Record<string, number>
  parse_warnings: ParseWarning[]
  scanned_at: string | null
}

export interface SolutionProjectMember {
  raw_path: string
  project_id: string | null
  relative_path: string | null
  project_guid: string | null
  project_type_guid: string | null
  solution_folder: string | null
  resolution_status: SolutionProjectResolution
}

export interface Solution {
  id: string
  name: string
  relative_path: string
  format_version: string | null
  visual_studio_version: string | null
  minimum_vs_version: string | null
  project_count: number | null
  resolved_project_count: number | null
  missing_project_count: number | null
  solution_folder_count: number | null
  shared_project_count: number | null
  parse_status: ParseStatus
  parse_error: string | null
  projects: SolutionProjectMember[]
}

export interface ProjectSummary {
  id: string
  repository_id: string
  name: string
  relative_path: string
  extension: string
  structural_type: string
  project_format: ProjectFormat
  language: ProjectLanguage
  framework_family: string | null
  framework_version: string | null
  is_multi_targeting: boolean
  solution_membership_count: number
  is_standalone: boolean
  project_reference_count: number
  package_reference_count: number
  package_management_style: PackageManagementStyle
  has_packages_config: boolean
  parse_status: ParseStatus
}

export interface ProjectPackage {
  package_name: string
  version_raw: string | null
  declaration_source: PackageDeclarationSource
  target_framework_raw: string | null
  is_malformed: boolean
}

export interface ProjectReference {
  id: string
  source_project_id: string
  source_relative_path: string
  referenced_project_id: string | null
  referenced_relative_path: string | null
  raw_path: string
  resolution_status: ProjectReferenceResolution
  is_cross_solution: boolean
}

export interface ProjectDetail extends ProjectSummary {
  assembly_name: string | null
  root_namespace: string | null
  output_type: string | null
  target_framework_raw: string | null
  target_frameworks_raw: string[] | null
  parse_warnings: string[]
  packages: ProjectPackage[]
  project_references: ProjectReference[]
  referenced_by: ProjectReference[]
}

export interface RepositoryArtifact {
  id: string
  category: RepositoryArtifactCategory
  relative_path: string
  file_name: string
}

export interface EngagementStructureSummary {
  engagement_id: string
  repositories_scanned: number
  solution_count: number
  project_file_count: number
  standalone_project_count: number
  unresolved_reference_count: number
  legacy_project_count: number
  sdk_project_count: number
  framework_families: Record<string, number>
}
