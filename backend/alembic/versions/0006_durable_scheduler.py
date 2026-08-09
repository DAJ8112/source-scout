"""durable scan scheduling

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-09
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "careers_sources",
        sa.Column("monitoring_status", sa.String(20), nullable=False, server_default="active"),
    )
    op.add_column("careers_sources", sa.Column("next_scan_at", sa.DateTime(timezone=True)))
    op.add_column(
        "careers_sources", sa.Column("last_scan_attempt_at", sa.DateTime(timezone=True))
    )
    op.add_column(
        "careers_sources", sa.Column("last_successful_scan_at", sa.DateTime(timezone=True))
    )
    op.execute(sa.text("UPDATE careers_sources SET next_scan_at = CURRENT_TIMESTAMP"))
    with op.batch_alter_table("careers_sources") as batch_op:
        batch_op.alter_column("next_scan_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.create_index(
        "ix_source_monitoring_due",
        "careers_sources",
        ["monitoring_status", "next_scan_at"],
    )
    op.create_index(
        "uq_scan_source_unfinished",
        "scan_runs",
        ["source_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_scan_source_unfinished", table_name="scan_runs")
    op.drop_index("ix_source_monitoring_due", table_name="careers_sources")
    with op.batch_alter_table("careers_sources") as batch_op:
        batch_op.drop_column("last_successful_scan_at")
        batch_op.drop_column("last_scan_attempt_at")
        batch_op.drop_column("next_scan_at")
        batch_op.drop_column("monitoring_status")
