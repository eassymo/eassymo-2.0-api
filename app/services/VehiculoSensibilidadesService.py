from typing import Dict, Any, List

from sqlalchemy.orm import Session

from app.repositories.VehiculoSensibilidadesRepository import (
    VehiculoSensibilidadesRepository,
)
from app.schemas.CheckSensibilidades import CheckSensibilidadesRequest


def _option(label: str, value: Any) -> Dict[str, Any]:
    return {"label": label, "value": value}


def check_sensibilidades(
    mysql_db: Session, payload: CheckSensibilidadesRequest
) -> Dict[str, Any]:
    v = payload.vehiculo
    p = payload.parte
    lst: List[Dict[str, Any]] = []

    # 1. Motor (if parte.tipoParteSensibleMotor)
    if p.tipoParteSensibleMotor:
        motor_or_trim = v.motor or v.trim
        if motor_or_trim:
            lst.append({
                "defaultLabel": "Motor",
                "options": [_option(motor_or_trim, motor_or_trim)],
            })
        else:
            motors = VehiculoSensibilidadesRepository.find_distinct_motors_by_vehicle(
                mysql_db, v.fabricante, v.modelo, v.ano, v.version
            )
            if not motors:
                options = []
            elif len(motors) == 1:
                options = []
            else:
                options = [_option("Seleccione motor...", None)]
                for motor_id, desc in motors:
                    label = desc or str(motor_id)
                    options.append(_option(label, motor_id))
            lst.append({"defaultLabel": "Motor", "options": options})

    # 2. Position (if parte.tipoParteSensiblePosicion)
    if p.tipoParteSensiblePosicion:
        posiciones = VehiculoSensibilidadesRepository.find_posiciones_by_tipo_parte(
            mysql_db, p.tipoParteId
        )
        if not posiciones:
            posiciones = VehiculoSensibilidadesRepository.find_all_posiciones(mysql_db)
        options = [_option("Seleccione posición...", None)]
        for pos in posiciones:
            options.append(_option(pos.PosicionNombre or "", str(pos.PosicionId)))
        lst.append({"defaultLabel": "Posición", "options": options})

    # 3. Special: Disco de Freno (tipoParteId 1736)
    if p.tipoParteId == 1736:
        lst.append({
            "defaultLabel": "Número de Birlos",
            "dataType": "decimal",
            "optional": True,
        })

    # 4. Special: tipoParteId 2476
    if p.tipoParteId == 2476:
        for label in ("Alto", "Ancho", "Largo", "Amperaje"):
            lst.append({
                "defaultLabel": label,
                "dataType": "decimal",
                "optional": True,
            })

    # 5. Rim (if parte.tipoParteSensibleRin)
    if p.tipoParteSensibleRin:
        lst.append({"defaultLabel": "Anchura", "dataType": "decimal"})
        lst.append({"defaultLabel": "Altura", "dataType": "decimal"})
        lst.append({
            "defaultLabel": "Radial",
            "options": [
                _option("Seleccione una opción...", None),
                _option("Rin", "R"),
                _option("Diámetro", "D"),
            ],
        })
        lst.append({"defaultLabel": "Rin/Diámetro", "dataType": "decimal"})
        runflat_item: Dict[str, Any] = {
            "defaultLabel": "Runflat",
            "dataType": "boolean",
        }
        if v.fabricante and v.fabricante.lower() == "mini":
            runflat_item["valueKey"] = True
        else:
            runflat_item["valueKey"] = False
        lst.append(runflat_item)

    # 6. Anillos del Motor (if parte.tipoSensibleAnillosMotor)
    if p.tipoSensibleAnillosMotor:
        lst.append({
            "defaultLabel": "Anillos del Motor",
            "dataType": "decimal",
        })

    return {"success": True, "lstSensibilidades": lst}
