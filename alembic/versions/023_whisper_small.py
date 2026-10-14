"""Whisper : large-v3 remplacé par small dans les forfaits

Whisper ne sert qu'au calage mot à mot sur une voix de synthèse dont le texte
est connu : small suffit, large-v3 coûtait ~3 Go de disque et de RAM.

Revision ID: 023
Revises: 022
"""
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE subscription_plans
        SET limits = jsonb_set(limits::jsonb, '{whisper_model}', '"small"')
        WHERE limits->>'whisper_model' = 'large-v3'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE subscription_plans
        SET limits = jsonb_set(limits::jsonb, '{whisper_model}', '"large-v3"')
        WHERE name IN ('Starter', 'Pro', 'Enterprise')
          AND limits->>'whisper_model' = 'small'
        """
    )
