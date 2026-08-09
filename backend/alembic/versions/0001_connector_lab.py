"""connector lab schema

Revision ID: 0001
Revises:
Create Date: 2026-08-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "careers_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company", sa.String(200), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("detected_platform", sa.String(50)),
        sa.Column("connector_type", sa.String(50)),
        sa.Column("connector_config", sa.JSON(), nullable=False),
        sa.Column("detection", sa.JSON(), nullable=False),
        sa.Column("setup_status", sa.String(30), nullable=False),
        sa.Column("health_status", sa.String(30), nullable=False),
        sa.Column("last_validation_at", sa.DateTime(timezone=True)),
        sa.Column("last_validation", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scan_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("careers_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("jobs_found", sa.Integer(), nullable=False),
        sa.Column("jobs_persisted", sa.Integer(), nullable=False),
        sa.Column("pages_visited", sa.Integer(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_diagnostics", sa.JSON(), nullable=False),
    )
    op.create_index("ix_scan_source_status", "scan_runs", ["source_id", "status"])
    op.create_table(
        "job_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scan_run_id", sa.String(36), sa.ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.String(36), sa.ForeignKey("careers_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(300)),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("locations", sa.JSON(), nullable=False),
        sa.Column("employment_type", sa.String(200)),
        sa.Column("posted_date", sa.Date()),
        sa.Column("description_html", sa.Text()),
        sa.Column("description_text", sa.Text()),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("raw_metadata", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scan_run_id", "canonical_url", name="uq_observation_scan_url"),
    )
    op.create_index("ix_observation_scan", "job_observations", ["scan_run_id"])
    op.create_index("ix_observation_source_external", "job_observations", ["source_id", "external_id"])


def downgrade() -> None:
    op.drop_table("job_observations")
    op.drop_table("scan_runs")
    op.drop_table("careers_sources")

