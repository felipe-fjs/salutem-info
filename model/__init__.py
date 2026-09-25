from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_as_dataclass, mapped_column, registry

from datetime import date

table_registry = registry()

@mapped_as_dataclass(table_registry)
class Cidadao:
    __tablename__ = "tb_cidadao"

    co_seq_cidadao: Mapped[int] = mapped_column(init=False)
    st_fora_area: Mapped[bool]  = mapped_column(init=False)
    st_ativo: Mapped[bool] = mapped_column(init=False)
    nu_cpf: Mapped[str] = mapped_column(String(11))
    nu_cpf: Mapped[str] = mapped_column(String(11))
    no_cidadao: Mapped[str] = mapped_column(String(500)) 
    no_social: Mapped[str] = mapped_column(String(255))
    dt_nascimento: Mapped[date] = mapped_column(init=False)
    no_mae: Mapped[str] = mapped_column(String(500))
    no_pai: Mapped[str] = mapped_column(String(500))
    nu_numero: Mapped[int] = mapped_column(init=False)
    st_sem_numero: Mapped[bool] = mapped_column(init=False)
