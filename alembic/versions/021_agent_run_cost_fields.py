"""agent run cost and token fields

Revision ID: 021
Revises: 020
Create Date: 2026-06-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def _agent_run_columns() -> set[str]:
    bind = op.get_bind()
    return {col["name"] for col in inspect(bind).get_columns("agent_runs")}


def upgrade() -> None:
    existing = _agent_run_columns()
    if "cost_estimate_usd" not in existing:
        op.add_column("agent_runs", sa.Column("cost_estimate_usd", sa.Numeric(10, 6), nullable=True))
    if "llm_input_tokens" not in existing:
        op.add_column("agent_runs", sa.Column("llm_input_tokens", sa.Integer(), nullable=True))
    if "llm_output_tokens" not in existing:
        op.add_column("agent_runs", sa.Column("llm_output_tokens", sa.Integer(), nullable=True))
    if "llm_model" not in existing:
        op.add_column("agent_runs", sa.Column("llm_model", sa.String(), nullable=True))


def downgrade() -> None:
    existing = _agent_run_columns()
    if "llm_model" in existing:
        op.drop_column("agent_runs", "llm_model")
    if "llm_output_tokens" in existing:
        op.drop_column("agent_runs", "llm_output_tokens")
    if "llm_input_tokens" in existing:
        op.drop_column("agent_runs", "llm_input_tokens")
    if "cost_estimate_usd" in existing:
        op.drop_column("agent_runs", "cost_estimate_usd")
