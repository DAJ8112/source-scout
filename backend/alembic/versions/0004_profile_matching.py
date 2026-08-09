"""search profile and match results

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("resume_text", sa.Text(), nullable=False),
        sa.Column("resume_filename", sa.String(300)),
        sa.Column("target_roles", sa.JSON(), nullable=False),
        sa.Column("adjacent_roles", sa.JSON(), nullable=False),
        sa.Column("preferred_locations", sa.JSON(), nullable=False),
        sa.Column("remote_preference", sa.String(30), nullable=False),
        sa.Column("employment_types", sa.JSON(), nullable=False),
        sa.Column("required_terms", sa.JSON(), nullable=False),
        sa.Column("excluded_terms", sa.JSON(), nullable=False),
        sa.Column("preference_notes", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "match_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "profile_id",
            sa.String(36),
            sa.ForeignKey("search_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("job_content_fingerprint", sa.String(64), nullable=False),
        sa.Column("matcher_version", sa.String(50), nullable=False),
        sa.Column("classification", sa.String(20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("role_score", sa.Integer(), nullable=False),
        sa.Column("resume_score", sa.Integer(), nullable=False),
        sa.Column("hard_constraint_pass", sa.Boolean(), nullable=False),
        sa.Column("hard_constraint_reasons", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_status", sa.String(30), nullable=False),
        sa.Column("model", sa.String(100)),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("request_id", sa.String(200)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "job_id",
            "profile_id",
            "profile_version",
            "job_content_fingerprint",
            "matcher_version",
            name="uq_match_cache_key",
        ),
    )
    op.create_index(
        "ix_match_profile_class",
        "match_results",
        ["profile_id", "profile_version", "classification"],
    )
    op.create_index("ix_match_job", "match_results", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_match_job", table_name="match_results")
    op.drop_index("ix_match_profile_class", table_name="match_results")
    op.drop_table("match_results")
    op.drop_table("search_profiles")
