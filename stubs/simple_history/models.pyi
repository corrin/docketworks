from collections.abc import Sequence
from typing import Any

class HistoricalRecords:
    def __init__(
        self,
        verbose_name: str | None = None,
        verbose_name_plural: str | None = None,
        bases: Sequence[type] = ...,
        user_related_name: str = ...,
        table_name: str | None = None,
        inherit: bool = False,
        excluded_fields: Sequence[str] | None = None,
        history_id_field: Any | None = None,
        history_change_reason_field: Any | None = None,
        user_model: Any | None = None,
        get_user: Any | None = None,
        cascade_delete_history: bool = False,
        custom_model_name: str | None = None,
        app: str | None = None,
        history_user_id_field: Any | None = None,
        history_user_getter: Any | None = None,
        history_user_setter: Any | None = None,
        related_name: str | None = None,
        use_base_model_db: bool = False,
        user_db_constraint: bool = True,
        no_db_index: Sequence[str] | str = ...,
        excluded_field_kwargs: dict[str, Any] | None = None,
        m2m_fields: Sequence[Any] = ...,
        m2m_fields_model_field_name: str = ...,
        m2m_bases: Sequence[type] = ...,
    ) -> None: ...
    def __get__(self, instance: Any, owner: type) -> Any: ...
    def __set_name__(self, owner: type, name: str) -> None: ...

class HistoricalChanges:
    def diff_against(
        self,
        old_history: HistoricalChanges,
        excluded_fields: Sequence[str] | None = None,
        included_fields: Sequence[str] | None = None,
        *,
        foreign_keys_are_objs: bool = False,
    ) -> Any: ...
