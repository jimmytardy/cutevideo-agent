# Faux positifs de vulture (code mort), lus par .claude/hooks/quality_gate.py.
# N'ajouter ici que du code utilisé hors de portée de l'analyse statique, avec la raison.
from agent.core import database

database.SubscriptionEvent  # noqa: B018 — table ORM : la retirer ferait supprimer la table par alembic autogenerate
