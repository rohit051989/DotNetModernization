"""step 6 item detection; drop the classification model

Revision ID: e8b3c61f0a94
Revises: d4e9b6a17f58
Create Date: 2026-09-30 16:00:00.000000

28-ITEM-AND-CONVERSION-MODEL.md Parts G and Q, and 17-LIFECYCLE-STEPS.md step 6.

item_occurrences, for item-detection:
- `value`: the occurrence's value for a `group_by: source_path_and_value`
  item, where one file yields several occurrences (one per connection string,
  one per sensitive key). The located unique index becomes
  (project_id, item_id, file_path, value), NULLS NOT DISTINCT.
- file_path CHECK relaxed from "iff found occurrence-scope" to "only on a
  found occurrence-scope row": an occurrence-scope item can be found with no
  location (system-drawing-common matched on the package alone), recorded as
  one project-level row.

Drops the pattern classification model it replaces (Part Q): step 4's
project_classifications, classification_matches and catalog_coverage_reports;
step 5's pattern_candidate_clusters, pattern_candidate_members and
pattern_discovery_runs. validation_queue is kept: it is generic gate
infrastructure (steps 17, 24, 34).

The downgrade recreates the six tables' exact schema (taken from pg_dump of
the live database before the drop) but not their rows: classification
results are derived data, reproducible only by the deleted step code.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e8b3c61f0a94'
down_revision: Union[str, None] = 'd4e9b6a17f58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DROPPED = [
    # Members before clusters: the only foreign key among them.
    "pattern_candidate_members",
    "pattern_candidate_clusters",
    "pattern_discovery_runs",
    "classification_matches",
    "project_classifications",
    "catalog_coverage_reports",
]

# pg_dump --schema-only of the six tables immediately before this migration.
_OLD_TABLES_DDL = r"""
CREATE TABLE public.catalog_coverage_reports (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    repository_id uuid NOT NULL,
    catalog_version text NOT NULL,
    catalog_revision bigint NOT NULL,
    signal_registry_version text,
    registered_signal_count integer NOT NULL,
    referenced_signal_count integer NOT NULL,
    unreferenced_signal_count integer NOT NULL,
    active_pattern_count integer NOT NULL,
    evaluated_pattern_count integer NOT NULL,
    matched_pattern_count integer NOT NULL,
    never_matched_pattern_ids jsonb,
    patterns_awaiting_signals_by_extractor jsonb,
    most_frequent_unmatched_signal_combinations jsonb,
    step_execution_id uuid,
    generated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.classification_matches (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    repository_id uuid NOT NULL,
    pattern_id text NOT NULL,
    pattern_version integer NOT NULL,
    matched boolean NOT NULL,
    classification_role text NOT NULL,
    match_score integer NOT NULL,
    confidence numeric(3,2) NOT NULL,
    confidence_level text NOT NULL,
    is_primary_selected boolean DEFAULT false NOT NULL,
    rejection_reason text,
    engagement_scope_status text,
    matched_rules jsonb,
    failed_rules jsonb,
    missing_preferred jsonb,
    negative_triggered jsonb,
    explanation text,
    relationship_source text,
    CONSTRAINT ck_classification_matches_engagement_scope_status CHECK (((engagement_scope_status IS NULL) OR (engagement_scope_status = ANY (ARRAY['active'::text, 'deferred'::text, 'deleted'::text])))),
    CONSTRAINT ck_classification_matches_relationship_source CHECK (((relationship_source IS NULL) OR (relationship_source = ANY (ARRAY['declared'::text, 'defaulted'::text])))),
    CONSTRAINT ck_classification_matches_role CHECK ((classification_role = ANY (ARRAY['PRIMARY'::text, 'SECONDARY'::text, 'PROJECT_ROLE'::text])))
);

CREATE TABLE public.pattern_candidate_clusters (
    cluster_id text NOT NULL,
    engagement_id text NOT NULL,
    cluster_method text NOT NULL,
    canonical_signature jsonb NOT NULL,
    signal_count integer NOT NULL,
    member_count integer NOT NULL,
    repository_count integer NOT NULL,
    repository_distribution jsonb NOT NULL,
    cohesion numeric(4,3),
    is_singleton boolean DEFAULT false NOT NULL,
    similar_patterns jsonb,
    status text DEFAULT 'candidate'::text NOT NULL,
    resolved_pattern_id text,
    resolution_note text,
    decided_at_coverage numeric(4,3),
    decided_at_member_count integer,
    needs_rereview boolean DEFAULT false NOT NULL,
    rereview_reason text,
    is_stale boolean DEFAULT false NOT NULL,
    first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT now() NOT NULL,
    step_execution_id uuid,
    suggested_name text,
    suggested_description text,
    suggested_pattern_id text,
    narration_confidence text,
    naming_source text DEFAULT 'none'::text NOT NULL,
    narration_model_version text,
    narrated_at timestamp with time zone,
    CONSTRAINT ck_pattern_candidate_clusters_decision_context CHECK (((status = 'candidate'::text) OR (decided_at_member_count IS NOT NULL))),
    CONSTRAINT ck_pattern_candidate_clusters_method CHECK ((cluster_method = ANY (ARRAY['exact'::text, 'similarity'::text]))),
    CONSTRAINT ck_pattern_candidate_clusters_naming_source CHECK ((naming_source = ANY (ARRAY['claude-code'::text, 'human'::text, 'none'::text]))),
    CONSTRAINT ck_pattern_candidate_clusters_status CHECK ((status = ANY (ARRAY['candidate'::text, 'validated_new'::text, 'merged'::text, 'rejected'::text])))
);

CREATE TABLE public.pattern_candidate_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    cluster_id text NOT NULL,
    project_id uuid NOT NULL,
    repository_id uuid NOT NULL,
    classification_status text NOT NULL,
    similarity_to_signature numeric(4,3),
    signal_count integer NOT NULL,
    classification_step_execution_id uuid
);

CREATE TABLE public.pattern_discovery_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    engagement_id text NOT NULL,
    step_execution_id uuid,
    cluster_count integer DEFAULT 0 NOT NULL,
    narrated_cluster_count integer DEFAULT 0 NOT NULL,
    coverage_ratio numeric(4,3),
    partial_estate boolean DEFAULT false NOT NULL,
    narration_status text NOT NULL,
    narration_reason text,
    output_dir text,
    run_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_pattern_discovery_runs_narration_status CHECK ((narration_status = ANY (ARRAY['succeeded'::text, 'partial'::text, 'failed'::text, 'disabled'::text]))),
    CONSTRAINT ck_pattern_discovery_runs_reason_required CHECK (((narration_status = 'succeeded'::text) OR (narration_reason IS NOT NULL)))
);

CREATE TABLE public.project_classifications (
    project_id uuid NOT NULL,
    repository_id uuid NOT NULL,
    classification_status text NOT NULL,
    project_role text,
    project_role_confidence numeric(3,2),
    catalog_revision bigint NOT NULL,
    signal_registry_version text,
    config_version text NOT NULL,
    evaluated_pattern_count integer DEFAULT 0 NOT NULL,
    primary_pattern_id text,
    warnings jsonb,
    step_execution_id uuid,
    classified_at timestamp with time zone DEFAULT now() NOT NULL,
    framework_family text,
    framework_version text,
    CONSTRAINT ck_project_classifications_status CHECK ((classification_status = ANY (ARRAY['SKIPPED'::text, 'NOT_ELIGIBLE'::text, 'INSUFFICIENT_FINGERPRINT'::text, 'AMBIGUOUS'::text, 'MULTIPLE_MATCHES'::text, 'MATCHED'::text, 'NO_PATTERN_MATCHED'::text, 'CLASSIFICATION_FAILED'::text])))
);

ALTER TABLE ONLY public.catalog_coverage_reports
    ADD CONSTRAINT catalog_coverage_reports_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.classification_matches
    ADD CONSTRAINT classification_matches_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.pattern_candidate_clusters
    ADD CONSTRAINT pattern_candidate_clusters_pkey PRIMARY KEY (cluster_id);

ALTER TABLE ONLY public.pattern_candidate_members
    ADD CONSTRAINT pattern_candidate_members_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.pattern_discovery_runs
    ADD CONSTRAINT pattern_discovery_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.project_classifications
    ADD CONSTRAINT project_classifications_pkey PRIMARY KEY (project_id);

ALTER TABLE ONLY public.classification_matches
    ADD CONSTRAINT uq_classification_matches_project_pattern UNIQUE (project_id, pattern_id);

ALTER TABLE ONLY public.pattern_candidate_members
    ADD CONSTRAINT uq_pattern_candidate_members_cluster_project UNIQUE (cluster_id, project_id);

CREATE INDEX ix_catalog_coverage_reports_repository_id ON public.catalog_coverage_reports USING btree (repository_id);

CREATE INDEX ix_classification_matches_repository_matched ON public.classification_matches USING btree (repository_id, matched);

CREATE INDEX ix_classification_matches_repository_pattern ON public.classification_matches USING btree (repository_id, pattern_id);

CREATE INDEX ix_pattern_candidate_clusters_engagement ON public.pattern_candidate_clusters USING btree (engagement_id);

CREATE INDEX ix_pattern_candidate_clusters_queue ON public.pattern_candidate_clusters USING btree (engagement_id, status, needs_rereview);

CREATE INDEX ix_pattern_candidate_members_cluster ON public.pattern_candidate_members USING btree (cluster_id);

CREATE INDEX ix_pattern_candidate_members_project ON public.pattern_candidate_members USING btree (project_id);

CREATE INDEX ix_pattern_discovery_runs_engagement ON public.pattern_discovery_runs USING btree (engagement_id, run_at);

CREATE INDEX ix_project_classifications_repository_id ON public.project_classifications USING btree (repository_id);

ALTER TABLE ONLY public.catalog_coverage_reports
    ADD CONSTRAINT catalog_coverage_reports_repository_id_fkey FOREIGN KEY (repository_id) REFERENCES public.repositories(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.classification_matches
    ADD CONSTRAINT classification_matches_pattern_id_fkey FOREIGN KEY (pattern_id) REFERENCES public.patterns(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.classification_matches
    ADD CONSTRAINT classification_matches_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.classification_matches
    ADD CONSTRAINT classification_matches_repository_id_fkey FOREIGN KEY (repository_id) REFERENCES public.repositories(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.pattern_candidate_clusters
    ADD CONSTRAINT pattern_candidate_clusters_engagement_id_fkey FOREIGN KEY (engagement_id) REFERENCES public.engagements(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.pattern_candidate_clusters
    ADD CONSTRAINT pattern_candidate_clusters_resolved_pattern_id_fkey FOREIGN KEY (resolved_pattern_id) REFERENCES public.patterns(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.pattern_candidate_members
    ADD CONSTRAINT pattern_candidate_members_cluster_id_fkey FOREIGN KEY (cluster_id) REFERENCES public.pattern_candidate_clusters(cluster_id) ON DELETE CASCADE;

ALTER TABLE ONLY public.pattern_candidate_members
    ADD CONSTRAINT pattern_candidate_members_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.pattern_candidate_members
    ADD CONSTRAINT pattern_candidate_members_repository_id_fkey FOREIGN KEY (repository_id) REFERENCES public.repositories(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.pattern_discovery_runs
    ADD CONSTRAINT pattern_discovery_runs_engagement_id_fkey FOREIGN KEY (engagement_id) REFERENCES public.engagements(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.project_classifications
    ADD CONSTRAINT project_classifications_primary_pattern_id_fkey FOREIGN KEY (primary_pattern_id) REFERENCES public.patterns(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.project_classifications
    ADD CONSTRAINT project_classifications_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.project_classifications
    ADD CONSTRAINT project_classifications_repository_id_fkey FOREIGN KEY (repository_id) REFERENCES public.repositories(id) ON DELETE CASCADE;
"""


def upgrade() -> None:
    op.add_column("item_occurrences", sa.Column("value", sa.Text(), nullable=True))
    op.drop_constraint("ck_item_occurrences_file_path", "item_occurrences", type_="check")
    op.create_check_constraint(
        "ck_item_occurrences_file_path",
        "item_occurrences",
        "file_path IS NULL OR (scope = 'occurrence' AND detection_state = 'found')",
    )
    op.drop_index("uq_item_occurrences_located", table_name="item_occurrences")
    op.create_index(
        "uq_item_occurrences_located",
        "item_occurrences",
        ["project_id", "item_id", "file_path", "value"],
        unique=True,
        postgresql_where=sa.text("file_path IS NOT NULL"),
        postgresql_nulls_not_distinct=True,
    )

    for table in _DROPPED:
        op.drop_table(table)


def downgrade() -> None:
    op.execute(_OLD_TABLES_DDL)

    op.execute("DELETE FROM item_occurrences WHERE value IS NOT NULL OR (file_path IS NULL AND detection_state = 'found' AND scope = 'occurrence')")
    op.drop_index("uq_item_occurrences_located", table_name="item_occurrences")
    op.create_index(
        "uq_item_occurrences_located",
        "item_occurrences",
        ["project_id", "item_id", "file_path"],
        unique=True,
        postgresql_where=sa.text("file_path IS NOT NULL"),
    )
    op.drop_constraint("ck_item_occurrences_file_path", "item_occurrences", type_="check")
    op.create_check_constraint(
        "ck_item_occurrences_file_path",
        "item_occurrences",
        "(file_path IS NOT NULL) = (scope = 'occurrence' AND detection_state = 'found')",
    )
    op.drop_column("item_occurrences", "value")
