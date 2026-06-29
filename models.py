from typing import Optional
import datetime
import decimal

from sqlalchemy import BigInteger, CHAR, Column, DECIMAL, Date, ForeignKeyConstraint, Index, Integer, SmallInteger, String, Table, Text
from sqlalchemy.dialects.mysql import DATETIME, LONGBLOB, LONGTEXT, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class Atributos(Base):
    __tablename__ = 'atributos'
    __table_args__ = (
        Index('UATRIBUTOS', 'AtrNombre'),
    )

    AtributoId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    AtrNombre: Mapped[str] = mapped_column(CHAR(120), nullable=False)
    AtrTipoValor: Mapped[str] = mapped_column(CHAR(40), nullable=False)

    tiposparte: Mapped[list['Tiposparte']] = relationship('Tiposparte', secondary='cnfatributos', back_populates='atributos')
    partesatributos: Mapped[list['Partesatributos']] = relationship('Partesatributos', back_populates='atributos')


class Categorias(Base):
    __tablename__ = 'categorias'
    __table_args__ = (
        Index('UCATEGORIAS', 'CategoriaDescripcion'),
    )

    CategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    CategoriaDescripcion: Mapped[str] = mapped_column(CHAR(120), nullable=False)
    CategoriaDescripcionEng: Mapped[Optional[str]] = mapped_column(CHAR(120))
    CategoriaFechaCreacion: Mapped[Optional[datetime.date]] = mapped_column(Date)
    CategoriaActivo: Mapped[Optional[int]] = mapped_column(TINYINT(1))

    subcategorias: Mapped[list['Subcategorias']] = relationship('Subcategorias', back_populates='categorias')


class Configuracion(Base):
    __tablename__ = 'configuracion'

    CnfId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    CnfLogo: Mapped[bytes] = mapped_column(LONGBLOB, nullable=False)
    SMTPEnabled: Mapped[int] = mapped_column(TINYINT(1), nullable=False)
    CnfLogo_GXI: Mapped[Optional[str]] = mapped_column(String(2048))
    SMTPPort: Mapped[Optional[int]] = mapped_column(SmallInteger)
    SMTPUser: Mapped[Optional[str]] = mapped_column(CHAR(40))
    SMTPPassword: Mapped[Optional[str]] = mapped_column(CHAR(40))
    SMTPRemitente: Mapped[Optional[str]] = mapped_column(CHAR(40))
    SMTPHost: Mapped[Optional[str]] = mapped_column(CHAR(40))
    WebAppDir: Mapped[Optional[str]] = mapped_column(CHAR(120))
    WebAppHost: Mapped[Optional[str]] = mapped_column(CHAR(120))
    GoogleAPIKey: Mapped[Optional[str]] = mapped_column(CHAR(50))


class Ensambladoras(Base):
    __tablename__ = 'ensambladoras'

    EnsambladoraId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    EnsambladoraNombre: Mapped[str] = mapped_column(CHAR(100), nullable=False)
    EnsambladoraDescr: Mapped[Optional[str]] = mapped_column(CHAR(40))
    EnsambladoraContacto: Mapped[Optional[str]] = mapped_column(CHAR(100))
    EnsambladoraCorreo: Mapped[Optional[str]] = mapped_column(String(100))
    EnsambladoraTelefono: Mapped[Optional[str]] = mapped_column(CHAR(20))
    EnsambladoraImagen_GXI: Mapped[Optional[str]] = mapped_column(String(2048))
    EnsambladoraImagen: Mapped[Optional[bytes]] = mapped_column(LONGBLOB)


class Fabricantes(Base):
    __tablename__ = 'fabricantes'
    __table_args__ = (
        Index('UFABRICANTES', 'FabricanteNombre'),
    )

    FabricanteId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FabricanteNombre: Mapped[str] = mapped_column(CHAR(120), nullable=False)
    FabricantePaginaWeb: Mapped[Optional[str]] = mapped_column(String(1000))
    FabricanteImagen_GXI: Mapped[Optional[str]] = mapped_column(String(2048))
    FabricanteImagen: Mapped[Optional[bytes]] = mapped_column(LONGBLOB)
    FabricanteAddress: Mapped[Optional[str]] = mapped_column(String(1024))
    FabricanteEmail: Mapped[Optional[str]] = mapped_column(String(100))
    FabricanteTel: Mapped[Optional[str]] = mapped_column(CHAR(20))
    FabricantePuesto: Mapped[Optional[str]] = mapped_column(CHAR(100))
    FabricanteContacto: Mapped[Optional[str]] = mapped_column(CHAR(100))
    FabricanteApp: Mapped[Optional[int]] = mapped_column(TINYINT(1))

    tipopartefabricante: Mapped[list['Tipopartefabricante']] = relationship('Tipopartefabricante', back_populates='fabricantes')
    partefabricante: Mapped[list['Partefabricante']] = relationship('Partefabricante', back_populates='fabricantes')


class Menu(Base):
    __tablename__ = 'menu'
    __table_args__ = (
        Index('UMENU', 'MenuNombre'),
    )

    MenuId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    MenuNombre: Mapped[str] = mapped_column(CHAR(100), nullable=False)

    menuopciones: Mapped[list['Menuopciones']] = relationship('Menuopciones', back_populates='menu')
    users: Mapped[list['Users']] = relationship('Users', back_populates='menu')


class Paises(Base):
    __tablename__ = 'paises'
    __table_args__ = (
        Index('UPAISES', 'Pais'),
    )

    PaisId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    PaisISO2: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    PaisISO3: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    Pais: Mapped[str] = mapped_column(CHAR(40), nullable=False)

    vehiculos: Mapped[list['Vehiculos']] = relationship('Vehiculos', back_populates='paises')


class Posiciones(Base):
    __tablename__ = 'posiciones'

    PosicionId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    PosicionNombre: Mapped[str] = mapped_column(CHAR(100), nullable=False)
    clavei18n: Mapped[Optional[str]] = mapped_column(String(100))

    tiposparte: Mapped[list['Tiposparte']] = relationship('Tiposparte', secondary='tiposparteposicion', back_populates='posiciones')


class Refaccionarias(Base):
    __tablename__ = 'refaccionarias'

    IdRefaccionaria: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    RefNombre: Mapped[Optional[str]] = mapped_column(CHAR(100))
    RefDireccion: Mapped[Optional[str]] = mapped_column(String(1024))
    RefTel1: Mapped[Optional[str]] = mapped_column(CHAR(20))
    RefTel2: Mapped[Optional[str]] = mapped_column(CHAR(20))
    RefTel3: Mapped[Optional[str]] = mapped_column(CHAR(20))
    RefEnsambladora: Mapped[Optional[str]] = mapped_column(CHAR(100))
    RefMarcas: Mapped[Optional[str]] = mapped_column(CHAR(100))
    RefSistema1: Mapped[Optional[str]] = mapped_column(CHAR(100))
    RefSistema2: Mapped[Optional[str]] = mapped_column(CHAR(100))
    RefSistema3: Mapped[Optional[str]] = mapped_column(CHAR(100))
    RefContacto: Mapped[Optional[str]] = mapped_column(CHAR(100))
    RefEmail: Mapped[Optional[str]] = mapped_column(String(100))
    RefPagina: Mapped[Optional[str]] = mapped_column(String(1000))
    RefServDomicilio: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    RefCta: Mapped[Optional[str]] = mapped_column(CHAR(100))
    RefRating: Mapped[Optional[int]] = mapped_column(SmallInteger)


class Sysdiagrams(Base):
    __tablename__ = 'sysdiagrams'
    __table_args__ = (
        Index('UK_principal_name', 'principal_id', 'name', unique=True),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    principal_id: Mapped[int] = mapped_column(Integer, nullable=False)
    diagram_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[Optional[int]] = mapped_column(Integer)
    definition: Mapped[Optional[bytes]] = mapped_column(LONGBLOB)


class Unidadmedida(Base):
    __tablename__ = 'unidadmedida'

    UnidadMedidaId: Mapped[int] = mapped_column(Integer, primary_key=True)
    etiquetadefecto: Mapped[str] = mapped_column(Text, nullable=False)
    clavei18n: Mapped[Optional[str]] = mapped_column(String(100))

    tiposparte: Mapped[list['Tiposparte']] = relationship('Tiposparte', secondary='tiposparteunidadmedida', back_populates='unidadmedida')


class Vehiculomotores(Base):
    __tablename__ = 'vehiculomotores'
    __table_args__ = (
        Index('UVEHICULOMOTORES', 'VehiculoMotorDescripcion'),
        Index('UVEHICULOMOTORES1', 'VehiculoMotorBlock'),
        Index('UVEHICULOMOTORES3', 'VehiculoMotorDescripcion')
    )

    VehiculoMotorId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoMotorLitros: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))
    VehiculoMotorCC: Mapped[Optional[int]] = mapped_column(SmallInteger)
    VehiculoMotorCID: Mapped[Optional[int]] = mapped_column(SmallInteger)
    VehiculoMotorCyl: Mapped[Optional[int]] = mapped_column(SmallInteger)
    VehiculoMotorBlock: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoMotorCylInches: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))
    VehiculoMotorCylMetric: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))
    VehiculoMotorStrInches: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))
    VehiculoMotorStrMetric: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))
    VehiculoMotorDescripcion: Mapped[Optional[str]] = mapped_column(CHAR(100))
    VehiculoGasTipo: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoGasSubtipo: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoGasControl: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoGasDiseno: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoMft: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoVIN: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoValvulas: Mapped[Optional[int]] = mapped_column(SmallInteger)
    VehiculoCylHead: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoDesignacion: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoVersion: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoCombustible: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoAspiracion: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoIgnicion: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoHP: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculokW: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoMotorUsuarioAlta: Mapped[Optional[str]] = mapped_column(String(100))
    VehiculoMotorFechaModificacion: Mapped[Optional[datetime.datetime]] = mapped_column(DATETIME(fsp=6))
    VehiculoMotorFechaAlta: Mapped[Optional[datetime.datetime]] = mapped_column(DATETIME(fsp=6))

    vehiculos: Mapped[list['Vehiculos']] = relationship('Vehiculos', back_populates='vehiculomotores')


class Menuopciones(Base):
    __tablename__ = 'menuopciones'
    __table_args__ = (
        ForeignKeyConstraint(['MenuId'], ['menu.MenuId'], name='IMENUMENUOPCIONES1'),
    )

    MenuId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    MenuOptionId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    MenuOptionName: Mapped[str] = mapped_column(CHAR(100), nullable=False)
    MenuOpcionUrl: Mapped[str] = mapped_column(String(1000), nullable=False)
    MenuOpicionHasSB: Mapped[int] = mapped_column(TINYINT(1), nullable=False)

    menu: Mapped['Menu'] = relationship('Menu', back_populates='menuopciones')


class Subcategorias(Base):
    __tablename__ = 'subcategorias'
    __table_args__ = (
        ForeignKeyConstraint(['CategoriaId'], ['categorias.CategoriaId'], name='ISUBCATEGORIAS1'),
        Index('ISUBCATEGORIAS1', 'CategoriaId'),
        Index('USUBCATEGORIAS', 'SubCategoriaDescripcion')
    )

    SubCategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    CategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    SubCategoriaDescripcion: Mapped[str] = mapped_column(CHAR(120), nullable=False)
    SubCategoriaDescripcionEng: Mapped[Optional[str]] = mapped_column(CHAR(120))
    SubCategoriaFechaCreacion: Mapped[Optional[datetime.date]] = mapped_column(Date)
    SubCategoriaActivo: Mapped[Optional[int]] = mapped_column(TINYINT(1))

    categorias: Mapped['Categorias'] = relationship('Categorias', back_populates='subcategorias')
    tiposparte: Mapped[list['Tiposparte']] = relationship('Tiposparte', back_populates='subcategorias')
    partes: Mapped[list['Partes']] = relationship('Partes', back_populates='subcategorias')


class Users(Base):
    __tablename__ = 'users'
    __table_args__ = (
        ForeignKeyConstraint(['MenuId'], ['menu.MenuId'], name='IUSERS1'),
        Index('IUSERS1', 'MenuId')
    )

    GAMUserIdentification: Mapped[str] = mapped_column(String(100), primary_key=True)
    MenuId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    UserPicture: Mapped[Optional[bytes]] = mapped_column(LONGBLOB)
    UserPicture_GXI: Mapped[Optional[str]] = mapped_column(String(2048))
    Nombres: Mapped[Optional[str]] = mapped_column(CHAR(100))

    menu: Mapped['Menu'] = relationship('Menu', back_populates='users')
    logregistros: Mapped[list['Logregistros']] = relationship('Logregistros', back_populates='users')
    userssavecontext: Mapped[list['Userssavecontext']] = relationship('Userssavecontext', back_populates='users')


class Vehiculos(Base):
    __tablename__ = 'vehiculos'
    __table_args__ = (
        ForeignKeyConstraint(['PaisId'], ['paises.PaisId'], name='IVEHICULOS1'),
        ForeignKeyConstraint(['VehiculoMotorId'], ['vehiculomotores.VehiculoMotorId'], name='IVEHICULOS2'),
        Index('IVEHICULOS1', 'PaisId'),
        Index('IVEHICULOS2', 'VehiculoMotorId'),
        Index('UVEHICULOS', 'VehiculoDescripcion'),
        Index('UVEHICULOS1', 'VehiculoAno', 'VehiculoFabricante', 'VehiculoModelo', 'VehiculoSubModelo'),
        Index('UVEHICULOS4', 'VehiculoFabricante', 'VehiculoModelo', 'VehiculoSubModelo')
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehicleId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    BaseId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    VehiculoTipo: Mapped[str] = mapped_column(CHAR(20), nullable=False)
    VehiculoFabricante: Mapped[str] = mapped_column(CHAR(40), nullable=False)
    VehiculoModelo: Mapped[str] = mapped_column(CHAR(40), nullable=False)
    VehiculoAno: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    VehiculoSubModelo: Mapped[str] = mapped_column(CHAR(40), nullable=False)
    PaisId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    VehiculoStatus: Mapped[int] = mapped_column(TINYINT(1), nullable=False)
    VehiculoUser: Mapped[str] = mapped_column(String(100), nullable=False)
    VehiculoFechaAlta: Mapped[datetime.datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    VehiculoFechaMod: Mapped[datetime.datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    VehiculoMotorId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    VehiculoDescripcion: Mapped[Optional[str]] = mapped_column(CHAR(120))
    VehiculoComentarios: Mapped[Optional[str]] = mapped_column(CHAR(120))
    VehiculoStep: Mapped[Optional[int]] = mapped_column(SmallInteger)

    paises: Mapped['Paises'] = relationship('Paises', back_populates='vehiculos')
    vehiculomotores: Mapped['Vehiculomotores'] = relationship('Vehiculomotores', back_populates='vehiculos')
    vehiculoscodigocuerpo: Mapped[list['Vehiculoscodigocuerpo']] = relationship('Vehiculoscodigocuerpo', back_populates='vehiculos')
    vehiculosdistanciaejes: Mapped[list['Vehiculosdistanciaejes']] = relationship('Vehiculosdistanciaejes', back_populates='vehiculos')
    vehiculostipocaja: Mapped[list['Vehiculostipocaja']] = relationship('Vehiculostipocaja', back_populates='vehiculos')
    vehiculostipocuerpo: Mapped[list['Vehiculostipocuerpo']] = relationship('Vehiculostipocuerpo', back_populates='vehiculos')
    vehiculostipodireccion: Mapped[list['Vehiculostipodireccion']] = relationship('Vehiculostipodireccion', back_populates='vehiculos')
    vehiculostipofreno: Mapped[list['Vehiculostipofreno']] = relationship('Vehiculostipofreno', back_populates='vehiculos')
    vehiculostiposuspencion: Mapped[list['Vehiculostiposuspencion']] = relationship('Vehiculostiposuspencion', back_populates='vehiculos')
    vehiculostraccion: Mapped[list['Vehiculostraccion']] = relationship('Vehiculostraccion', back_populates='vehiculos')
    vehiculostransmision: Mapped[list['Vehiculostransmision']] = relationship('Vehiculostransmision', back_populates='vehiculos')
    partevehiculo: Mapped[list['Partevehiculo']] = relationship('Partevehiculo', back_populates='vehiculos')


class Logregistros(Base):
    __tablename__ = 'logregistros'
    __table_args__ = (
        ForeignKeyConstraint(['GAMUserIdentification'], ['users.GAMUserIdentification'], name='ILOGREGISTROS1'),
        Index('ULOGREGISTROS', 'OpId')
    )

    GAMUserIdentification: Mapped[str] = mapped_column(String(100), primary_key=True)
    OpId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    OpFecha: Mapped[datetime.datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    OpTipo: Mapped[str] = mapped_column(CHAR(40), nullable=False)
    VehicleIdOp: Mapped[Optional[int]] = mapped_column(BigInteger)
    ParteInternalIdOp: Mapped[Optional[int]] = mapped_column(BigInteger)

    users: Mapped['Users'] = relationship('Users', back_populates='logregistros')


class Tiposparte(Base):
    __tablename__ = 'tiposparte'
    __table_args__ = (
        ForeignKeyConstraint(['SubCategoriaId', 'CategoriaId'], ['subcategorias.SubCategoriaId', 'subcategorias.CategoriaId'], name='ITIPOSPARTE1'),
        Index('ITIPOSPARTE1', 'SubCategoriaId', 'CategoriaId'),
        Index('UTIPOSPARTE', 'TipoParteDescripcion'),
        Index('UTIPOSPARTE1', 'TipoParteId'),
        Index('UTIPOSPARTE2', 'TipoParteId')
    )

    CategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    SubCategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    TipoParteId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    TipoParteDescripcion: Mapped[str] = mapped_column(CHAR(120), nullable=False)
    TipoParteSensibleMotor: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    Referencia: Mapped[Optional[str]] = mapped_column(CHAR(20))
    TipoParteDescripcionIng: Mapped[Optional[str]] = mapped_column(CHAR(120))
    TopRank: Mapped[Optional[str]] = mapped_column(CHAR(1))
    TipoParteImagen_GXI: Mapped[Optional[str]] = mapped_column(String(2048))
    TipoParteImagen: Mapped[Optional[bytes]] = mapped_column(LONGBLOB)
    TipoParteSensiblePosicion: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    TipoParteSensibleRin: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    TipoSensibleAnillosMotor: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    TipoParteFechaCreacion: Mapped[Optional[datetime.date]] = mapped_column(Date)
    TipoParteActivo: Mapped[Optional[int]] = mapped_column(TINYINT(1))
    TipoParteTags: Mapped[Optional[str]] = mapped_column(CHAR(100))
    claveProdServ: Mapped[Optional[str]] = mapped_column(String(100))

    atributos: Mapped[list['Atributos']] = relationship('Atributos', secondary='cnfatributos', back_populates='tiposparte')
    subcategorias: Mapped['Subcategorias'] = relationship('Subcategorias', back_populates='tiposparte')
    posiciones: Mapped[list['Posiciones']] = relationship('Posiciones', secondary='tiposparteposicion', back_populates='tiposparte')
    unidadmedida: Mapped[list['Unidadmedida']] = relationship('Unidadmedida', secondary='tiposparteunidadmedida', back_populates='tiposparte')
    partes: Mapped[list['Partes']] = relationship('Partes', back_populates='tiposparte')
    tipopartefabricante: Mapped[list['Tipopartefabricante']] = relationship('Tipopartefabricante', back_populates='tiposparte')
    tipospartetag: Mapped[list['Tipospartetag']] = relationship('Tipospartetag', back_populates='tiposparte')


class Userssavecontext(Base):
    __tablename__ = 'userssavecontext'
    __table_args__ = (
        ForeignKeyConstraint(['GAMUserIdentification'], ['users.GAMUserIdentification'], name='IUSERSSAVECONTEXT1'),
    )

    GAMUserIdentification: Mapped[str] = mapped_column(String(100), primary_key=True)
    PgmName: Mapped[str] = mapped_column(CHAR(100), primary_key=True)
    UserGridState: Mapped[Optional[str]] = mapped_column(LONGTEXT)

    users: Mapped['Users'] = relationship('Users', back_populates='userssavecontext')


class Vehiculoscodigocuerpo(Base):
    __tablename__ = 'vehiculoscodigocuerpo'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSCODIGOCUERPO1'),
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoCodigoCuerpoId: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    VehiculoCodigoCuerpoDesc: Mapped[Optional[str]] = mapped_column(CHAR(40))

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculoscodigocuerpo')


class Vehiculosdistanciaejes(Base):
    __tablename__ = 'vehiculosdistanciaejes'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSDISTANCIAEJES1'),
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoDistEjesId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoDistEjesInch: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))
    VehiculoDistEjesMetric: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculosdistanciaejes')


class Vehiculostipocaja(Base):
    __tablename__ = 'vehiculostipocaja'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSTIPOCAJA1'),
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoCajaId: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    VehiculoTipoCajaDesc: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTipoCajaInches: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))
    VehiculoTipoCajaMetric: Mapped[Optional[decimal.Decimal]] = mapped_column(DECIMAL(10, 4))

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculostipocaja')


class Vehiculostipocuerpo(Base):
    __tablename__ = 'vehiculostipocuerpo'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSTIPOCUERPO1'),
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoCuerpoId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoCuerpoDesc: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTipoCuerpoPuertas: Mapped[Optional[int]] = mapped_column(SmallInteger)

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculostipocuerpo')


class Vehiculostipodireccion(Base):
    __tablename__ = 'vehiculostipodireccion'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSTIPODIRECCION1'),
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoDireccionId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoDireccionTipo: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTipoDireccionSys: Mapped[Optional[str]] = mapped_column(CHAR(40))

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculostipodireccion')


class Vehiculostipofreno(Base):
    __tablename__ = 'vehiculostipofreno'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSVEHICULOTIPOFRENO1'),
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoFrenoId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoFrenoDel: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTipoFrenoTra: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTipoFrenoSys: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTipoFrenoABS: Mapped[Optional[str]] = mapped_column(CHAR(40))

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculostipofreno')


class Vehiculostiposuspencion(Base):
    __tablename__ = 'vehiculostiposuspencion'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSTIPOSUSPENCION1'),
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoSuspencionId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoSuspencionDel: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTipoSuspencionTra: Mapped[Optional[str]] = mapped_column(CHAR(40))

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculostiposuspencion')


class Vehiculostraccion(Base):
    __tablename__ = 'vehiculostraccion'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSTRACCION1'),
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoTraccionId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTipoTraccionDesc: Mapped[Optional[str]] = mapped_column(CHAR(40))

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculostraccion')


class Vehiculostransmision(Base):
    __tablename__ = 'vehiculostransmision'
    __table_args__ = (
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IVEHICULOSTRANSMISION1'),
        Index('UVEHICULOSTRANSMISION', 'VehiculoInternalId', 'VehiculoTransmId')
    )

    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTransmId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoTransmVel: Mapped[Optional[int]] = mapped_column(SmallInteger)
    VehiculoTransmCtl: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTransmTipo: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTransmFab: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTransmCod: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTransmECtrl: Mapped[Optional[str]] = mapped_column(CHAR(40))
    VehiculoTransmision: Mapped[Optional[str]] = mapped_column(CHAR(40))

    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='vehiculostransmision')


t_cnfatributos = Table(
    'cnfatributos', Base.metadata,
    Column('CategoriaId', BigInteger, primary_key=True),
    Column('SubCategoriaId', BigInteger, primary_key=True),
    Column('TipoParteId', BigInteger, primary_key=True),
    Column('AtributoId', BigInteger, primary_key=True),
    ForeignKeyConstraint(['AtributoId'], ['atributos.AtributoId'], name='ICNFATRIBUTOS1'),
    ForeignKeyConstraint(['CategoriaId', 'SubCategoriaId', 'TipoParteId'], ['tiposparte.CategoriaId', 'tiposparte.SubCategoriaId', 'tiposparte.TipoParteId'], name='ICNFATRIBUTOS2'),
    Index('ICNFATRIBUTOS1', 'AtributoId')
)


class Partes(Base):
    __tablename__ = 'partes'
    __table_args__ = (
        ForeignKeyConstraint(['CategoriaId', 'SubCategoriaId', 'TipoParteId'], ['tiposparte.CategoriaId', 'tiposparte.SubCategoriaId', 'tiposparte.TipoParteId'], name='IPARTES1'),
        ForeignKeyConstraint(['SubCategoriaId', 'CategoriaId'], ['subcategorias.SubCategoriaId', 'subcategorias.CategoriaId'], name='GX_0007000J000M'),
        Index('GX_0007000J000M', 'SubCategoriaId', 'CategoriaId'),
        Index('IPARTES1', 'CategoriaId', 'SubCategoriaId', 'TipoParteId'),
        Index('UPARTES', 'ParteDescripcion'),
        Index('UPARTES1', 'TipoParteId')
    )

    ParteInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ParteDescripcion: Mapped[str] = mapped_column(CHAR(120), nullable=False)
    PartMasterdId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    CategoriaId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    SubCategoriaId: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ParteStatus: Mapped[int] = mapped_column(TINYINT(1), nullable=False)
    ParteUser: Mapped[str] = mapped_column(String(100), nullable=False)
    ParteFechaAlta: Mapped[datetime.datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    ParteFechaMod: Mapped[datetime.datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    TipoParteId: Mapped[Optional[int]] = mapped_column(BigInteger)
    OEMPartId: Mapped[Optional[str]] = mapped_column(CHAR(20))
    CodigosFabricante: Mapped[Optional[str]] = mapped_column(CHAR(200))
    ParteTransmision: Mapped[Optional[str]] = mapped_column(CHAR(40))
    PartePosicion: Mapped[Optional[int]] = mapped_column(BigInteger)
    ParteMotorDesc: Mapped[Optional[str]] = mapped_column(CHAR(40))
    ParteMotorId: Mapped[Optional[int]] = mapped_column(BigInteger)
    ParteRin: Mapped[Optional[int]] = mapped_column(BigInteger)
    ParteAnillo: Mapped[Optional[str]] = mapped_column(CHAR(20))

    tiposparte: Mapped[Optional['Tiposparte']] = relationship('Tiposparte', back_populates='partes')
    subcategorias: Mapped['Subcategorias'] = relationship('Subcategorias', back_populates='partes')
    partefabricante: Mapped[list['Partefabricante']] = relationship('Partefabricante', back_populates='partes')
    partesatributos: Mapped[list['Partesatributos']] = relationship('Partesatributos', back_populates='partes')
    partevehiculo: Mapped[list['Partevehiculo']] = relationship('Partevehiculo', back_populates='partes')


class Tipopartefabricante(Base):
    __tablename__ = 'tipopartefabricante'
    __table_args__ = (
        ForeignKeyConstraint(['CategoriaId', 'SubCategoriaId', 'TipoParteId'], ['tiposparte.CategoriaId', 'tiposparte.SubCategoriaId', 'tiposparte.TipoParteId'], name='ITIPOPARTEFABRICANTE2'),
        ForeignKeyConstraint(['FabricanteId'], ['fabricantes.FabricanteId'], name='ITIPOPARTEFABRICANTE1'),
        Index('ITIPOPARTEFABRICANTE1', 'FabricanteId')
    )

    CategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    SubCategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    TipoParteId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FabricanteId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FechaCreacion: Mapped[datetime.date] = mapped_column(Date, nullable=False)

    tiposparte: Mapped['Tiposparte'] = relationship('Tiposparte', back_populates='tipopartefabricante')
    fabricantes: Mapped['Fabricantes'] = relationship('Fabricantes', back_populates='tipopartefabricante')


t_tiposparteposicion = Table(
    'tiposparteposicion', Base.metadata,
    Column('CategoriaId', BigInteger, primary_key=True),
    Column('SubCategoriaId', BigInteger, primary_key=True),
    Column('TipoParteId', BigInteger, primary_key=True),
    Column('PosicionId', BigInteger, primary_key=True),
    ForeignKeyConstraint(['CategoriaId', 'SubCategoriaId', 'TipoParteId'], ['tiposparte.CategoriaId', 'tiposparte.SubCategoriaId', 'tiposparte.TipoParteId'], name='ITIPOSPARTEPOSICION2'),
    ForeignKeyConstraint(['PosicionId'], ['posiciones.PosicionId'], name='ITIPOSPARTEPOSICION1'),
    Index('ITIPOSPARTEPOSICION1', 'PosicionId')
)


class Tipospartetag(Base):
    __tablename__ = 'tipospartetag'
    __table_args__ = (
        ForeignKeyConstraint(['CategoriaId', 'SubCategoriaId', 'TipoParteId'], ['tiposparte.CategoriaId', 'tiposparte.SubCategoriaId', 'tiposparte.TipoParteId'], name='ITIPOSPARTETAG1'),
    )

    TipoParteId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    TipoParteTagId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    TipoParteTagDescripcion: Mapped[str] = mapped_column(CHAR(100), nullable=False)
    SubCategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    CategoriaId: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    tiposparte: Mapped['Tiposparte'] = relationship('Tiposparte', back_populates='tipospartetag')


t_tiposparteunidadmedida = Table(
    'tiposparteunidadmedida', Base.metadata,
    Column('CategoriaId', BigInteger, primary_key=True),
    Column('SubCategoriaId', BigInteger, primary_key=True),
    Column('TipoParteId', BigInteger, primary_key=True),
    Column('UnidadMedidaId', Integer, primary_key=True),
    ForeignKeyConstraint(['CategoriaId', 'SubCategoriaId', 'TipoParteId'], ['tiposparte.CategoriaId', 'tiposparte.SubCategoriaId', 'tiposparte.TipoParteId'], name='fk_tiposparte_has_unidadmedida_tiposparte1'),
    ForeignKeyConstraint(['UnidadMedidaId'], ['unidadmedida.UnidadMedidaId'], name='fk_tiposparte_has_unidadmedida_unidadmedida1'),
    Index('fk_tiposparte_has_unidadmedida_tiposparte1_idx', 'CategoriaId', 'SubCategoriaId', 'TipoParteId'),
    Index('fk_tiposparte_has_unidadmedida_unidadmedida1_idx', 'UnidadMedidaId')
)


class Partefabricante(Base):
    __tablename__ = 'partefabricante'
    __table_args__ = (
        ForeignKeyConstraint(['FabricanteId'], ['fabricantes.FabricanteId'], name='IPARTEFABRICANTE1'),
        ForeignKeyConstraint(['ParteInternalId'], ['partes.ParteInternalId'], name='IPARTEFABRICANTE2'),
        Index('IPARTEFABRICANTE1', 'FabricanteId')
    )

    ParteInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FabricanteId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ParteFabricanteCodigo: Mapped[Optional[str]] = mapped_column(CHAR(40))
    ParteFabricanteFecha: Mapped[Optional[datetime.datetime]] = mapped_column(DATETIME(fsp=6))
    ParteFabricanteUser: Mapped[Optional[str]] = mapped_column(String(100))
    ParteFabricanteStatus: Mapped[Optional[int]] = mapped_column(TINYINT(1))

    fabricantes: Mapped['Fabricantes'] = relationship('Fabricantes', back_populates='partefabricante')
    partes: Mapped['Partes'] = relationship('Partes', back_populates='partefabricante')


class Partesatributos(Base):
    __tablename__ = 'partesatributos'
    __table_args__ = (
        ForeignKeyConstraint(['AtributoId'], ['atributos.AtributoId'], name='IPARTESATRIBUTOS1'),
        ForeignKeyConstraint(['ParteInternalId'], ['partes.ParteInternalId'], name='IPARTESATRIBUTOS2'),
        Index('IPARTESATRIBUTOS1', 'AtributoId')
    )

    ParteInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    AtributoId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ParteAttValor: Mapped[Optional[str]] = mapped_column(CHAR(40))

    atributos: Mapped['Atributos'] = relationship('Atributos', back_populates='partesatributos')
    partes: Mapped['Partes'] = relationship('Partes', back_populates='partesatributos')


class Partevehiculo(Base):
    __tablename__ = 'partevehiculo'
    __table_args__ = (
        ForeignKeyConstraint(['ParteInternalId'], ['partes.ParteInternalId'], name='IPARTEVEHICULO2'),
        ForeignKeyConstraint(['VehiculoInternalId'], ['vehiculos.VehiculoInternalId'], name='IPARTEVEHICULO1'),
        Index('IPARTEVEHICULO1', 'VehiculoInternalId'),
        Index('UPARTEVEHICULO', 'ParteVehiculoFecha'),
        Index('UPARTEVEHICULO1', 'ParteVehiculoFecha')
    )

    ParteInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    VehiculoInternalId: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ParteVehiculoFecha: Mapped[Optional[datetime.datetime]] = mapped_column(DATETIME(fsp=6))
    ParteVehiculoUser: Mapped[Optional[str]] = mapped_column(String(100))
    ParteVehiculoStatus: Mapped[Optional[int]] = mapped_column(TINYINT(1))

    partes: Mapped['Partes'] = relationship('Partes', back_populates='partevehiculo')
    vehiculos: Mapped['Vehiculos'] = relationship('Vehiculos', back_populates='partevehiculo')
