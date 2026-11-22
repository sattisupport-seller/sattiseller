"""Журнал чувствительных действий (audit_events). Пишет только действие, результат и идентификаторы — без персональных данных."""

from sqlalchemy.orm import Session as DbSession

from .models import AuditEvent


def record(db: DbSession, action: str, entity: str, *, actor_id: str | None = None,
           shop_id: str | None = None, result: str = "ok") -> None:
    """Сохраняет запись сразу (отдельным коммитом): запись журнала не должна теряться из-за ошибки в основном действии."""
    db.add(AuditEvent(action=action[:64], entity=entity[:64], result=result[:16],
                      actor_id=actor_id, shop_id=shop_id))
    db.commit()
