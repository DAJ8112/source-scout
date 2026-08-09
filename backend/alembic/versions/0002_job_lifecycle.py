"""durable jobs and lifecycle metrics

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scan_runs", sa.Column("jobs_created", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "scan_runs", sa.Column("jobs_updated", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "scan_runs", sa.Column("jobs_missing", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("careers_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("identity_key", sa.Text(), nullable=False),
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
        sa.Column("lifecycle_status", sa.String(30), nullable=False),
        sa.Column("consecutive_successful_absences", sa.Integer(), nullable=False),
        sa.Column("initial_import", sa.Boolean(), nullable=False),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "identity_key", name="uq_job_source_identity"),
    )
    op.create_index("ix_job_source_lifecycle", "jobs", ["source_id", "lifecycle_status"])

    with op.batch_alter_table("job_observations") as batch_op:
        batch_op.add_column(sa.Column("job_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_observation_job", "jobs", ["job_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index("ix_observation_job", ["job_id"])


def downgrade() -> None:
    with op.batch_alter_table("job_observations") as batch_op:
        batch_op.drop_index("ix_observation_job")
        batch_op.drop_constraint("fk_observation_job", type_="foreignkey")
        batch_op.drop_column("job_id")
    op.drop_index("ix_job_source_lifecycle", table_name="jobs")
    op.drop_table("jobs")
    op.drop_column("scan_runs", "jobs_missing")
    op.drop_column("scan_runs", "jobs_updated")
    op.drop_column("scan_runs", "jobs_created")
