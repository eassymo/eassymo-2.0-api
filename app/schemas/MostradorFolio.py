from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import List, Optional
from bson import ObjectId
from datetime import datetime
from zoneinfo import ZoneInfo
from enum import Enum


class FolioStatus(str, Enum):
    DRAFT = "draft"            # seller still capturing / quoting
    SHARED = "shared"          # shared with customer and/or other shops
    CONFIRMED = "confirmed"    # at least one piece confirmed -> Orders created
    CLOSED = "closed"          # fully resolved / archived
    CANCELED = "canceled"


class FolioSource(str, Enum):
    COUNTER = "counter"            # seller "Solicitud + -> Nueva"
    SHARE = "share"
    ASSISTED_ORDER = "assisted_order"
    ORDER = "order"
    OFFER_CREATOR = "offer_creator"
    QR_LOAD = "qr_load"


class PieceStatus(str, Enum):
    PENDIENTE = "pendiente"
    COTIZANDO = "cotizando"
    COTIZADA = "cotizada"
    AGOTADA = "agotada"
    NO_MANEJO = "no_manejo"


class AvailabilityStatus(str, Enum):
    DISPONIBLE = ""
    AGOTADA = "agotada"
    NO_MANEJO = "no_manejo"


class DeliveryMode(str, Enum):
    TIENDA = "tienda"
    DOMICILIO = "domicilio"
    PICKUP = "pickup"


class CustomerType(str, Enum):
    GUEST = "guest"
    EASSYMO = "eassymo"


class MostradorVehicle(BaseModel):
    """Embedded vehicle snapshot (mirrors GroupVehicle shape)."""
    model_config = ConfigDict(populate_by_name=True)

    year: Optional[str] = Field(None)
    maker: Optional[str] = Field(None)
    model: Optional[str] = Field(None)
    version: Optional[str] = Field(None, description="trim/subModel label")
    engine: Optional[str] = Field(None)
    vin: Optional[str] = Field(None)
    license_plate: Optional[str] = Field(None, alias="licensePlate")
    service_order: Optional[str] = Field(None, alias="serviceOrder")
    group_vehicle_id: Optional[str] = Field(None, description="ref to GroupCars when picked from existing")


class MostradorOption(BaseModel):
    """A shop's offer line for a piece. Embedded Offer subset + multi-shop tags."""
    brand: Optional[str] = Field(None)
    code: Optional[str] = Field(None)
    price: Optional[float] = Field(None)
    guarantee: Optional[str] = Field(None)
    unit_of_measure: Optional[str] = Field(None)
    delivery_time: Optional[str] = Field(None)
    photos: Optional[List[str]] = Field(default_factory=list)
    note: Optional[str] = Field(None)
    ready: bool = Field(False, description="brand + price present -> orderable")
    availability_status: AvailabilityStatus = Field(AvailabilityStatus.DISPONIBLE)
    # multi-shop tagging
    source_shop_id: Optional[str] = Field(None)
    source_shop_name: Optional[str] = Field(None)
    # buyer-proxy capture
    captured_by_buyer: bool = Field(False)
    source_confirmation: Optional[str] = Field(
        None, description="e.g. not_confirmed_by_shop when captured by buyer")


class MostradorPieceOrder(BaseModel):
    """Embedded PRO order for a piece (mirrors prototype proOrder*)."""
    option_index: int = Field(..., description="index into piece.options of the chosen offer")
    delivery_mode: DeliveryMode = Field(DeliveryMode.TIENDA)
    shop_id: Optional[str] = Field(None)
    shop_name: Optional[str] = Field(None)
    status: str = Field("ordenada")
    ordered_at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo('UTC')))
    order_doc_id: Optional[str] = Field(None, description="set after confirm -> real Order id")


class MostradorPiece(BaseModel):
    """A line item. Catalog identity by id ref (CarPart/PartRequest.partList shape)."""
    piece_id: str = Field(..., description="stable client-generated id within the folio")
    tipoParteId: Optional[str] = Field(None)
    tipoParteDescripcion: Optional[str] = Field(None)
    categoriaId: Optional[int] = Field(None)
    subCategoriaId: Optional[int] = Field(None)
    name: Optional[str] = Field(None, description="display name when no catalog match")
    qty: int = Field(1)
    unitOfMeasure: Optional[str] = Field("Pieza")
    position: Optional[str] = Field("No aplica")
    comments: Optional[str] = Field(None)
    note: bool = Field(False)
    sample: bool = Field(False)
    status: PieceStatus = Field(PieceStatus.PENDIENTE)
    options: List[MostradorOption] = Field(default_factory=list)
    order: Optional[MostradorPieceOrder] = Field(None)
    # piece-level shop attribution
    added_by_shop_id: Optional[str] = Field(None)
    added_by_shop_name: Optional[str] = Field(None)


class ParticipantShop(BaseModel):
    group_id: Optional[str] = Field(None, description="null for a temp shop without account")
    name: Optional[str] = Field(None)
    eassymo: bool = Field(True, description="false = temp shop / invitado")
    tube_token: Optional[str] = Field(None, description="token for a temp shop restricted tube")


class MostradorCustomer(BaseModel):
    type: CustomerType = Field(CustomerType.GUEST)
    name: Optional[str] = Field(None)
    phone: Optional[str] = Field(None)
    user_uid: Optional[str] = Field(None, description="set when an existing Eassymo user")
    group_id: Optional[str] = Field(None, description="customer taller group when existing")


class MostradorFolio(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    folio_code: Optional[str] = Field(None, description="short human code (Capturar Folio)")
    share_token: Optional[str] = Field(None, description="UUID for public/customer view")
    source: FolioSource = Field(FolioSource.COUNTER)
    status: FolioStatus = Field(FolioStatus.DRAFT)
    origin_group_id: Optional[str] = Field(None, description="seller group that opened it")
    creator_user: Optional[str] = Field(None, description="creator uid")
    vehicle: Optional[MostradorVehicle] = Field(None)
    participant_shops: List[ParticipantShop] = Field(default_factory=list)
    pieces: List[MostradorPiece] = Field(default_factory=list)
    visibility: Optional[dict] = Field(
        default_factory=dict,
        description="map of shop_id/tube_token -> list of visible piece_ids (tube scoping)")
    customer: Optional[MostradorCustomer] = Field(None)
    specific_order_uid: Optional[str] = Field(None, description="groups created Orders")
    order_ids: List[str] = Field(default_factory=list)
    part_request_ids: List[str] = Field(
        default_factory=list, description="real PartRequest ids materialized for buyer group")
    assignment_with_options: Optional[bool] = Field(
        None, description="whether initial assignment included seller offers snapshot")
    created_at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo('UTC')))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(ZoneInfo('UTC')))

    @model_validator(mode="before")
    @classmethod
    def convert_objectId(cls, values):
        if isinstance(values, dict) and '_id' in values and isinstance(values['_id'], ObjectId):
            values['_id'] = str(values['_id'])
        return values

    def toJson(self):
        data = self.model_dump(by_alias=True, mode='json')
        if self.source is not None:
            data['source'] = self.source.value if isinstance(self.source, Enum) else self.source
        if self.status is not None:
            data['status'] = self.status.value if isinstance(self.status, Enum) else self.status
        return data
