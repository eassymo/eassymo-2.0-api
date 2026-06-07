from typing import List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_

from models import (
    Vehiculos,
    Vehiculomotores,
    Posiciones,
    Tiposparte,
    t_tiposparteposicion,
)


class VehiculoSensibilidadesRepository:

    @staticmethod
    def find_distinct_motors_by_vehicle(
        mysql_db: Session,
        fabricante: str,
        modelo: str,
        ano: int,
        version: Optional[str] = None,
    ) -> List[Tuple[int, Optional[str]]]:
        q = (
            mysql_db.query(
                Vehiculomotores.VehiculoMotorId,
                Vehiculomotores.VehiculoMotorDescripcion,
            )
            .join(Vehiculos, Vehiculos.VehiculoMotorId == Vehiculomotores.VehiculoMotorId)
            .filter(
                Vehiculos.VehiculoFabricante == fabricante,
                Vehiculos.VehiculoModelo == modelo,
                Vehiculos.VehiculoAno == ano,
            )
        )
        if version:
            q = q.filter(Vehiculos.VehiculoSubModelo == version)
        rows = q.distinct().all()
        return [(r.VehiculoMotorId, r.VehiculoMotorDescripcion) for r in rows]

    @staticmethod
    def find_posiciones_by_tipo_parte(
        mysql_db: Session, tipo_parte_id: int
    ) -> List[Posiciones]:
        return (
            mysql_db.query(Posiciones)
            .join(t_tiposparteposicion, Posiciones.PosicionId == t_tiposparteposicion.c.PosicionId)
            .filter(t_tiposparteposicion.c.TipoParteId == tipo_parte_id)
            .distinct()
            .all()
        )

    @staticmethod
    def find_all_posiciones(mysql_db: Session) -> List[Posiciones]:
        return mysql_db.query(Posiciones).all()

    @staticmethod
    def find_all_versiones(
        mysql_db: Session,
        fabricante: str,
        modelo: str,
        ano: int,
        country_id: int,
    ) -> List[Tuple]:
        return (
            mysql_db.query(
                Vehiculos.VehiculoSubModelo,
                Vehiculos.VehiculoMotorId,
            )
            .filter(
                Vehiculos.VehiculoFabricante == fabricante,
                Vehiculos.VehiculoModelo == modelo,
                Vehiculos.VehiculoAno == ano,
                or_(Vehiculos.PaisId == country_id, Vehiculos.PaisId == None),
            )
            .group_by(Vehiculos.VehiculoSubModelo)
            .all()
        )

    @staticmethod
    def find_all_motor_desc(
        mysql_db: Session,
        fabricante: str,
        modelo: str,
        ano: int,
        country_id: int,
    ) -> List[Tuple]:
        return (
            mysql_db.query(
                Vehiculomotores.VehiculoMotorId,
                Vehiculomotores.VehiculoMotorDescripcion,
            )
            .join(Vehiculos, Vehiculos.VehiculoMotorId == Vehiculomotores.VehiculoMotorId)
            .filter(
                Vehiculos.VehiculoFabricante == fabricante,
                Vehiculos.VehiculoModelo == modelo,
                Vehiculos.VehiculoAno == ano,
                or_(Vehiculos.PaisId == country_id, Vehiculos.PaisId == None),
            )
            .group_by(Vehiculomotores.VehiculoMotorDescripcion)
            .all()
        )
