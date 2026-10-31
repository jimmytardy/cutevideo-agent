"""subscription tts_allowed_engines : elevenlabs sur tous les plans (payé avec la clé de l'utilisateur)

Revision ID: 029
Revises: 028
Create Date: 2026-10-31
"""

from __future__ import annotations

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ajout en fin de liste : `tts_allowed_engines[0]` reste le moteur de rétrogradation du plan.
    op.execute(
        """
        UPDATE subscription_plans
        SET limits = jsonb_set(
            limits, '{tts_allowed_engines}',
            COALESCE(limits->'tts_allowed_engines', '["edge"]'::jsonb) || '"elevenlabs"'::jsonb
        )
        WHERE NOT COALESCE(limits->'tts_allowed_engines', '[]'::jsonb) ? 'elevenlabs'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE subscription_plans
        SET limits = jsonb_set(limits, '{tts_allowed_engines}', (limits->'tts_allowed_engines') - 'elevenlabs')
        WHERE limits ? 'tts_allowed_engines'
        """
    )
