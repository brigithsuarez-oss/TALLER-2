from contextlib import closing
from datetime import datetime, timezone
import sqlite3
from pathlib import Path

import pandas as pd



CARPETA_DATOS = Path(__file__).resolve().parent
ARCHIVO_2017_2025 = CARPETA_DATOS / "mdi_personasdesaparecidas_pm_2017_2025.xlsx"
ARCHIVO_2026 = CARPETA_DATOS / "mdi_personasdesaparecidas_pm_2026_enero_agosto.xlsx"
ARCHIVO_RESULTADO = CARPETA_DATOS / "base_datos_unificada_analizada.xlsx"
ARCHIVO_SQLITE = CARPETA_DATOS / "base_datos_unificada.db"

# En ambos archivos la primera hoja contiene metadatos y la segunda los registros.
HOJA_REGISTROS = 1

EQUIVALENCIAS_2026 = {
    "latitud": "latitud_desaparicion",
    "longitud": "longitud_desaparicion",
    "motivacion": "motivo_desaparicion",
    "motivacion_observada": "motivacion_desaparicion_observada",
    "status": "estado_desaparecido",
}

COLUMNAS_FECHA = {
    "fecha_desaparicion",
    "fecha_denuncia",
    "fecha_conocimiento",
    "fecha_localizacion",
}

COLUMNAS_COORDENADAS = {
    "latitud_desaparicion": (-90, 90),
    "longitud_desaparicion": (-180, 180),
    "latitud_localizacion": (-90, 90),
    "longitud_localizacion": (-180, 180),
}

PARES_COORDENADAS = {
    "punto_desaparicion_wkt": (
        "longitud_desaparicion",
        "latitud_desaparicion",
    ),
    "punto_localizacion_wkt": (
        "longitud_localizacion",
        "latitud_localizacion",
    ),
}
CRS_COORDENADAS = "EPSG:4326"

DESCRIPCIONES_CAMPOS = {
    "fecha_desaparicion": "Fecha en que ocurrió la desaparición.",
    "fecha_denuncia": "Fecha en que se registró la denuncia.",
    "fecha_conocimiento": "Fecha en que la autoridad tuvo conocimiento del caso.",
    "zona": "Zona operativa donde se registra el caso.",
    "distrito": "Distrito operativo asociado al registro.",
    "circuito": "Circuito operativo asociado al registro.",
    "subcircuito": "Subcircuito operativo asociado al registro.",
    "codigo_provincia": "Código geográfico de la provincia; se conserva como texto.",
    "provincia": "Nombre de la provincia de desaparición.",
    "codigo_canton": "Código geográfico del cantón; se conserva como texto.",
    "canton": "Nombre del cantón de desaparición.",
    "latitud_desaparicion": "Latitud del lugar de desaparición.",
    "longitud_desaparicion": "Longitud del lugar de desaparición.",
    "sexo": "Sexo registrado para la persona desaparecida.",
    "nacionalidad": "Nacionalidad registrada.",
    "edad": "Edad en años al momento de la desaparición.",
    "rango_edad": "Categoría etaria asignada en la fuente.",
    "etnia": "Autoidentificación étnica registrada en la fuente.",
    "fecha_localizacion": "Fecha en que la persona fue localizada, si consta.",
    "latitud_localizacion": "Latitud del lugar de localización, si consta.",
    "longitud_localizacion": "Longitud del lugar de localización, si consta.",
    "provincia_localizacion": "Provincia donde se localizó a la persona, si consta.",
    "situacion_actual": "Situación registrada del caso: encontrado, desaparecido o fallecido.",
    "motivo_desaparicion": "Categoría general del motivo de desaparición.",
    "motivacion_desaparicion_observada": "Motivación observada o específica registrada.",
    "estado_desaparecido": "Clasificación del estado o tipo de desaparición registrada.",
    "estado_fecha_localizacion": "Indica si existe fecha de localización o figura como no encontrada.",
    "punto_desaparicion_wkt": "Punto geográfico de desaparición en WKT, orden longitud-latitud.",
    "punto_localizacion_wkt": "Punto geográfico de localización en WKT, orden longitud-latitud.",
}

UNIDADES_CAMPOS = {
    "fecha_desaparicion": "Fecha (AAAA-MM-DD)",
    "fecha_denuncia": "Fecha (AAAA-MM-DD)",
    "fecha_conocimiento": "Fecha (AAAA-MM-DD)",
    "fecha_localizacion": "Fecha (AAAA-MM-DD)",
    "edad": "Años",
    "latitud_desaparicion": "Grados decimales",
    "longitud_desaparicion": "Grados decimales",
    "latitud_localizacion": "Grados decimales",
    "longitud_localizacion": "Grados decimales",
    "punto_desaparicion_wkt": f"WKT; {CRS_COORDENADAS}",
    "punto_localizacion_wkt": f"WKT; {CRS_COORDENADAS}",
}

SENTINELAS_CAMPOS = {
    "fecha_localizacion": "NO ENCONTRADO (en estado_fecha_localizacion)",
    "motivo_desaparicion": "NO ENCONTRADO",
    "motivacion_desaparicion_observada": "NO ENCONTRADO",
    "estado_fecha_localizacion": "FECHA REGISTRADA | NO ENCONTRADO",
    "nacionalidad": "SIN_DATO (si proviene así de la fuente)",
    "rango_edad": "SIN_DATO (si proviene así de la fuente)",
}

FALTANTES_CON_NA = {
    "fecha_conocimiento",
    "latitud_localizacion",
    "longitud_localizacion",
    "provincia_localizacion",
}

FALTANTES_CON_NO_ENCONTRADO = {
    "fecha_localizacion",
    "motivo_desaparicion",
    "motivacion_desaparicion_observada",
}

ANCHOS_CODIGOS = {
    "codigo_provincia": 2,
    "codigo_canton": 4,
}

MARCADORES_SIN_DATO = {
    "",
    "NO_APLICA",
    "NO APLICA",
    "N/A",
    "NA",
    "NAN",
    "NONE",
    "NULL",
    "SIN DATO",
    "S/D",
}


def cargar_bases_datos() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carga los registros y armoniza los nombres que cambiaron en 2026."""
    personas_2017_2025 = pd.read_excel(
        ARCHIVO_2017_2025,
        sheet_name=HOJA_REGISTROS,
    )
    personas_2026 = pd.read_excel(
        ARCHIVO_2026,
        sheet_name=HOJA_REGISTROS,
    )

    personas_2017_2025.columns = personas_2017_2025.columns.astype(str).str.strip()
    personas_2026.columns = personas_2026.columns.astype(str).str.strip()
    personas_2026 = personas_2026.rename(columns=EQUIVALENCIAS_2026)
    return personas_2017_2025, personas_2026


def unificar_bases_datos() -> pd.DataFrame:
    """Une ambos conjuntos sin eliminar ni modificar registros."""
    personas_2017_2025, personas_2026 = cargar_bases_datos()
    return pd.concat(
        [personas_2017_2025, personas_2026],
        ignore_index=True,
        sort=False,
    )


def contar_marcadores(serie: pd.Series) -> int:
    """Cuenta textos que representan ausencia de dato en el contenido original."""
    return int(
        serie.map(
            lambda valor: isinstance(valor, str)
                and bool(valor.strip())
                and valor.strip().upper() in MARCADORES_SIN_DATO
        ).sum()
    )


def normalizar_faltantes(base: pd.DataFrame) -> pd.DataFrame:
    """Recorta espacios en textos y convierte marcadores de ausencia a NA."""
    resultado = base.copy()
    for columna in resultado.columns:
        resultado[columna] = resultado[columna].map(
            lambda valor: valor.strip() if isinstance(valor, str) else valor
        )
        resultado[columna] = resultado[columna].map(
            lambda valor: pd.NA
            if isinstance(valor, str)
            and valor.strip().upper() in MARCADORES_SIN_DATO
            else valor
        )
    return resultado


def convertir_fecha(serie: pd.Series) -> tuple[pd.Series, int]:
    """Convierte fechas Excel seriales o textuales a datetime."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        fechas = pd.to_datetime(serie, errors="coerce")
        no_convertibles = int((serie.notna() & fechas.isna()).sum())
        return fechas, no_convertibles

    valores_numericos = pd.to_numeric(serie, errors="coerce")
    es_serial_excel = valores_numericos.notna()
    fechas = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")

    fechas.loc[es_serial_excel] = pd.to_datetime(
        valores_numericos.loc[es_serial_excel],
        unit="D",
        origin="1899-12-30",
        errors="coerce",
    )
    es_texto = serie.notna() & ~es_serial_excel
    fechas.loc[es_texto] = pd.to_datetime(
        serie.loc[es_texto],
        errors="coerce",
        dayfirst=False,
    )
    no_convertibles = int((serie.notna() & fechas.isna()).sum())
    return fechas, no_convertibles


def convertir_coordenada(
    serie: pd.Series,
    minimo: int,
    maximo: int,
) -> tuple[pd.Series, int, int]:
    """Convierte coordenadas a números y marca como ausentes las fuera de rango."""
    texto = serie.astype("string").str.strip().str.replace(",", ".", regex=False)
    coordenadas = pd.to_numeric(texto, errors="coerce")
    no_convertibles = int((serie.notna() & coordenadas.isna()).sum())
    fuera_de_rango = coordenadas.notna() & ~coordenadas.between(minimo, maximo)
    cantidad_fuera_de_rango = int(fuera_de_rango.sum())
    coordenadas = coordenadas.mask(fuera_de_rango)
    return coordenadas, no_convertibles, cantidad_fuera_de_rango


def formatear_codigo(valor: object, ancho: int) -> object:
    """Conserva los códigos como texto y recupera ceros iniciales."""
    if pd.isna(valor):
        return pd.NA

    texto = str(valor).strip()
    numero = pd.to_numeric(texto, errors="coerce")
    if pd.notna(numero) and float(numero).is_integer():
        return f"{int(numero):0{ancho}d}"
    return texto


def limpiar_base(
    base: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int], dict[str, int]]:
    """Estandariza faltantes, fechas, coordenadas, edad y códigos."""
    limpia = normalizar_faltantes(base)
    no_convertibles: dict[str, int] = {}
    coordenadas_fuera_rango: dict[str, int] = {}

    for columna in COLUMNAS_FECHA.intersection(limpia.columns):
        limpia[columna], no_convertibles[columna] = convertir_fecha(
            limpia[columna]
        )

    for columna, (minimo, maximo) in COLUMNAS_COORDENADAS.items():
        if columna in limpia.columns:
            (
                limpia[columna],
                no_convertibles[columna],
                coordenadas_fuera_rango[columna],
            ) = convertir_coordenada(limpia[columna], minimo, maximo)

    if "edad" in limpia.columns:
        edad_original = limpia["edad"]
        edad = pd.to_numeric(edad_original, errors="coerce")
        no_convertibles["edad"] = int((edad_original.notna() & edad.isna()).sum())
        if edad.dropna().mod(1).eq(0).all():
            edad = edad.astype("Int64")
        limpia["edad"] = edad

    for columna, ancho in ANCHOS_CODIGOS.items():
        if columna in limpia.columns:
            limpia[columna] = limpia[columna].map(
                lambda valor: formatear_codigo(valor, ancho)
            ).astype("string")

    for columna in FALTANTES_CON_NO_ENCONTRADO.intersection(limpia.columns):
        if columna != "fecha_localizacion":
            limpia[columna] = limpia[columna].fillna("NO ENCONTRADO")

    if "fecha_localizacion" in limpia.columns:
        limpia["estado_fecha_localizacion"] = "FECHA REGISTRADA"
        limpia.loc[
            limpia["fecha_localizacion"].isna(),
            "estado_fecha_localizacion",
        ] = "NO ENCONTRADO"

    return limpia, no_convertibles, coordenadas_fuera_rango


def crear_puntos_geograficos(base: pd.DataFrame) -> pd.DataFrame:
    """Crea geometrías WKT POINT en EPSG:4326, con orden longitud-latitud."""
    resultado = base.copy()
    for nombre, (longitud, latitud) in PARES_COORDENADAS.items():
        puntos = [
            f"POINT ({x:.15g} {y:.15g})"
            if pd.notna(x) and pd.notna(y)
            else pd.NA
            for x, y in zip(resultado[longitud], resultado[latitud])
        ]
        resultado[nombre] = pd.Series(puntos, index=resultado.index, dtype="string")
    return resultado


def clasificar_variable(nombre: str, serie: pd.Series) -> str:
    """Asigna una clasificación estadística conservadora según nombre y tipo."""
    nombre_normalizado = nombre.lower()
    if nombre_normalizado in PARES_COORDENADAS:
        return "Geoespacial (WKT POINT)"
    if nombre_normalizado in COLUMNAS_FECHA or nombre_normalizado.startswith("fecha_"):
        return "Fecha/temporal"
    if nombre_normalizado in COLUMNAS_COORDENADAS:
        return "Cuantitativa continua (coordenada)"
    if nombre_normalizado in ANCHOS_CODIGOS or "codigo" in nombre_normalizado:
        return "Cualitativa nominal (código)"
    if pd.api.types.is_datetime64_any_dtype(serie):
        return "Fecha/temporal"
    if pd.api.types.is_numeric_dtype(serie):
        if pd.api.types.is_integer_dtype(serie):
            return "Cuantitativa discreta"
        return "Cuantitativa continua"
    return "Cualitativa"


def crear_perfil(
    original: pd.DataFrame,
    limpia: pd.DataFrame,
    no_convertibles: dict[str, int],
    coordenadas_fuera_rango: dict[str, int],
) -> pd.DataFrame:
    """Resume faltantes, tipo estadístico, conversiones y alertas por variable."""
    filas = []
    total_filas = len(original)

    for columna in original.columns:
        serie_original = original[columna]
        serie_limpia = limpia[columna]
        espacios = int(
            serie_original.map(
                lambda valor: isinstance(valor, str) and not valor.strip()
            ).sum()
        )
        marcadores = contar_marcadores(serie_original)
        nulos_originales = int(serie_original.isna().sum())
        sin_dato_detectado = nulos_originales + espacios + marcadores
        nulos_finales = int(serie_limpia.isna().sum())
        fallos_conversion = no_convertibles.get(columna, 0)
        fuera_rango = coordenadas_fuera_rango.get(columna, 0)

        if total_filas and sin_dato_detectado == total_filas:
            recomendacion = "Variable completamente vacía; validar antes de conservar."
        elif fallos_conversion or fuera_rango:
            recomendacion = (
                "Revisar valores no convertibles o coordenadas fuera de rango."
            )
        elif sin_dato_detectado:
            recomendacion = (
                "Revisar los faltantes; decidir si se dejan como NA o se imputan."
            )
        else:
            recomendacion = "Sin faltantes detectados; revisar valores y contexto."

        ejemplos = serie_original.dropna().astype(str).drop_duplicates().head(5)
        filas.append(
            {
                "variable": columna,
                "tipo_variable": clasificar_variable(columna, serie_limpia),
                "tipo_dato_original": str(serie_original.dtype),
                "registros": total_filas,
                "nulos_originales": nulos_originales,
                "celdas_en_blanco": espacios,
                "marcadores_sin_dato": marcadores,
                "faltantes_detectados": sin_dato_detectado,
                "porcentaje_faltantes": (
                    round(sin_dato_detectado * 100 / total_filas, 2)
                    if total_filas
                    else 0.0
                ),
                "nulos_despues_limpieza": nulos_finales,
                "valores_unicos_originales": int(serie_original.nunique(dropna=True)),
                "valores_no_convertibles": fallos_conversion,
                "coordenadas_fuera_de_rango": fuera_rango,
                "tratamiento_faltantes": tratamiento_faltantes(columna),
                "referencia_espacial": (
                    f"{CRS_COORDENADAS}; WKT usa POINT (longitud latitud)"
                    if columna in PARES_COORDENADAS
                    else ""
                ),
                "ejemplos_originales": " | ".join(ejemplos.tolist()),
                "recomendacion": recomendacion,
            }
        )

    return pd.DataFrame(filas)


def tratamiento_faltantes(columna: str) -> str:
    """Describe el valor elegido para los faltantes de cada variable."""
    if columna in FALTANTES_CON_NO_ENCONTRADO:
        if columna == "fecha_localizacion":
            return "NO ENCONTRADO en estado_fecha_localizacion; fecha como NaT"
        return "NO ENCONTRADO"
    if columna in FALTANTES_CON_NA:
        return "NA (faltante real; conserva tipo fecha/número)"
    return "NA (faltante real)"


def crear_estadisticas_cuantitativas(base: pd.DataFrame) -> pd.DataFrame:
    """Calcula estadísticos descriptivos de edad y coordenadas numéricas."""
    columnas = [
        columna
        for columna in base.select_dtypes(include="number").columns
        if columna not in ANCHOS_CODIGOS
    ]
    filas = []
    for columna in columnas:
        serie = base[columna].dropna()
        filas.append(
            {
                "variable": columna,
                "n": int(serie.count()),
                "faltantes": int(base[columna].isna().sum()),
                "media": serie.mean() if not serie.empty else pd.NA,
                "desviacion_estandar": serie.std() if len(serie) > 1 else pd.NA,
                "minimo": serie.min() if not serie.empty else pd.NA,
                "percentil_25": serie.quantile(0.25) if not serie.empty else pd.NA,
                "mediana": serie.median() if not serie.empty else pd.NA,
                "percentil_75": serie.quantile(0.75) if not serie.empty else pd.NA,
                "maximo": serie.max() if not serie.empty else pd.NA,
            }
        )
    return pd.DataFrame(filas)


def crear_frecuencias_cualitativas(base: pd.DataFrame) -> pd.DataFrame:
    """Calcula frecuencias y porcentajes para variables categóricas."""
    excluidas = (
        COLUMNAS_FECHA
        | set(COLUMNAS_COORDENADAS)
        | set(PARES_COORDENADAS)
    )
    columnas = [
        columna
        for columna in base.columns
        if columna not in excluidas
        and not pd.api.types.is_numeric_dtype(base[columna])
    ]
    filas = []
    total_registros = len(base)
    for columna in columnas:
        frecuencias = base[columna].astype("string").fillna("(SIN DATO)").value_counts()
        validos = int(base[columna].notna().sum())
        for categoria, frecuencia in frecuencias.items():
            filas.append(
                {
                    "variable": columna,
                    "categoria": categoria,
                    "frecuencia": int(frecuencia),
                    "porcentaje_total": (
                        round(frecuencia * 100 / total_registros, 2)
                        if total_registros
                        else 0.0
                    ),
                    "porcentaje_validos": (
                        round(frecuencia * 100 / validos, 2)
                        if validos and categoria != "(SIN DATO)"
                        else pd.NA
                    ),
                }
            )
    return pd.DataFrame(filas)


def crear_resumen_temporal(base: pd.DataFrame) -> pd.DataFrame:
    """Resume registros por año y mes para cada fecha de interés."""
    filas = []
    for columna in sorted(COLUMNAS_FECHA.intersection(base.columns)):
        fechas = pd.to_datetime(base[columna], errors="coerce").dropna()
        conteos = fechas.groupby([fechas.dt.year, fechas.dt.month]).size()
        for (anio, mes), frecuencia in conteos.items():
            filas.append(
                {
                    "variable_fecha": columna,
                    "anio": int(anio),
                    "mes": int(mes),
                    "frecuencia": int(frecuencia),
                }
            )
    return pd.DataFrame(
        filas,
        columns=["variable_fecha", "anio", "mes", "frecuencia"],
    )


def crear_resumen_general(base: pd.DataFrame) -> pd.DataFrame:
    """Resume tamaño y duplicados exactos de la base analizada."""
    return pd.DataFrame(
        [
            {
                "registros": len(base),
                "variables": len(base.columns),
                "filas_duplicadas_exactas": int(base.duplicated().sum()),
                "celdas_faltantes": int(base.isna().sum().sum()),
            }
        ]
    )


def leer_base_sqlite(nombre_tabla: str = "base_limpia") -> pd.DataFrame:
    """Lee una tabla SQLite como DataFrame y convierte las columnas de fecha."""
    with closing(sqlite3.connect(ARCHIVO_SQLITE)) as conexion:
        tablas = {
            fila[0]
            for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if nombre_tabla not in tablas:
            raise ValueError(
                f"La tabla '{nombre_tabla}' no existe en {ARCHIVO_SQLITE.name}."
            )

        esquema = pd.read_sql_query(
            f'PRAGMA table_info("{nombre_tabla}")',
            conexion,
        )
        columnas_fecha = COLUMNAS_FECHA.intersection(esquema["name"].tolist())
        return pd.read_sql_query(
            f'SELECT * FROM "{nombre_tabla}"',
            conexion,
            parse_dates=sorted(columnas_fecha),
        )


def contar_menores_desaparecidos(base: pd.DataFrame) -> int:
    """Cuenta personas menores de 17 cuya situación actual es desaparecido."""
    columnas_requeridas = {"edad", "situacion_actual"}
    faltantes = columnas_requeridas.difference(base.columns)
    if faltantes:
        raise ValueError(
            f"Faltan columnas requeridas para el conteo: {', '.join(sorted(faltantes))}"
        )

    edades = pd.to_numeric(base["edad"], errors="coerce")
    situaciones = base["situacion_actual"].astype("string").str.strip().str.upper()
    filtro = edades.lt(17) & situaciones.eq("DESAPARECIDO")
    return int(filtro.sum())


def calcular_tiempo_localizacion(base: pd.DataFrame) -> dict[str, float | int]:
    """Resume días entre desaparición y localización en casos encontrados."""
    columnas_requeridas = {
        "situacion_actual",
        "fecha_desaparicion",
        "fecha_localizacion",
    }
    faltantes = columnas_requeridas.difference(base.columns)
    if faltantes:
        raise ValueError(
            "Faltan columnas requeridas para el cálculo: "
            f"{', '.join(sorted(faltantes))}"
        )

    situaciones = base["situacion_actual"].astype("string").str.strip().str.upper()
    encontrados = base.loc[situaciones.eq("ENCONTRADO")].copy()
    fecha_desaparicion = pd.to_datetime(
        encontrados["fecha_desaparicion"],
        errors="coerce",
    )
    fecha_localizacion = pd.to_datetime(
        encontrados["fecha_localizacion"],
        errors="coerce",
    )
    dias = (fecha_localizacion - fecha_desaparicion).dt.total_seconds() / 86400
    fechas_validas = fecha_desaparicion.notna() & fecha_localizacion.notna()
    negativos = fechas_validas & dias.lt(0)
    duraciones_validas = dias.loc[fechas_validas & ~negativos]

    return {
        "casos_encontrados": int(len(encontrados)),
        "casos_con_ambas_fechas": int(fechas_validas.sum()),
        "fechas_invertidas_excluidas": int(negativos.sum()),
        "casos_incluidos_en_promedio": int(duraciones_validas.count()),
        "promedio_dias": (
            float(duraciones_validas.mean())
            if not duraciones_validas.empty
            else float("nan")
        ),
        "mediana_dias": (
            float(duraciones_validas.median())
            if not duraciones_validas.empty
            else float("nan")
        ),
    }


def principales_cantones_menores_desaparecidos(
    base: pd.DataFrame,
    cantidad_cantones: int = 10,
) -> pd.DataFrame:
    """Resume menores desaparecidos por cantón y estado de desaparición."""
    columnas_requeridas = {
        "edad",
        "situacion_actual",
        "canton",
        "estado_desaparecido",
    }
    faltantes = columnas_requeridas.difference(base.columns)
    if faltantes:
        raise ValueError(
            "Faltan columnas requeridas para el resumen: "
            f"{', '.join(sorted(faltantes))}"
        )
    if cantidad_cantones < 1:
        raise ValueError("cantidad_cantones debe ser al menos 1.")

    edades = pd.to_numeric(base["edad"], errors="coerce")
    situaciones = base["situacion_actual"].astype("string").str.strip().str.upper()
    filtro = edades.lt(17) & situaciones.eq("DESAPARECIDO")
    menores = base.loc[
        filtro,
        ["canton", "estado_desaparecido"],
    ].copy()

    if menores.empty:
        return pd.DataFrame(
            columns=["canton", "total_menores_desaparecidos"]
        )

    menores["canton"] = menores["canton"].astype("string").fillna("(SIN DATO)")
    menores["estado_desaparecido"] = (
        menores["estado_desaparecido"]
        .astype("string")
        .fillna("(SIN DATO)")
    )
    resumen = (
        menores.groupby(["canton", "estado_desaparecido"], dropna=False)
        .size()
        .unstack(fill_value=0)
    )
    resumen["total_menores_desaparecidos"] = resumen.sum(axis=1)
    resumen = resumen.sort_values(
        "total_menores_desaparecidos",
        ascending=False,
    ).head(cantidad_cantones)
    return resumen.reset_index()


def crear_catalogo_metadatos(base: pd.DataFrame) -> pd.DataFrame:
    """Genera metadatos descriptivos y de calidad para cada campo."""
    filas = []
    for columna in base.columns:
        serie = base[columna]
        ejemplos = (
            serie.dropna()
            .astype(str)
            .drop_duplicates()
            .head(5)
            .tolist()
        )
        if columna in COLUMNAS_FECHA:
            nivel_medicion = "Temporal"
        elif columna in COLUMNAS_COORDENADAS:
            nivel_medicion = "Cuantitativa continua"
        elif columna in PARES_COORDENADAS:
            nivel_medicion = "Geoespacial"
        elif columna == "edad":
            nivel_medicion = "Cuantitativa discreta"
        elif columna in ANCHOS_CODIGOS or columna.startswith("codigo_"):
            nivel_medicion = "Cualitativa nominal (identificador)"
        else:
            nivel_medicion = "Cualitativa nominal"

        filas.append(
            {
                "campo": columna,
                "descripcion": DESCRIPCIONES_CAMPOS.get(
                    columna,
                    "Campo de la base fuente; confirmar definición con el diccionario oficial.",
                ),
                "tipo_pandas": str(serie.dtype),
                "nivel_medicion": nivel_medicion,
                "unidad_o_formato": UNIDADES_CAMPOS.get(columna, "No aplica"),
                "dominio_observado": (
                    " | ".join(sorted(serie.dropna().astype(str).unique()))
                    if serie.nunique(dropna=True) <= 30
                    else "Dominio amplio; consultar valores_ejemplo"
                ),
                "sistema_referencia_espacial": (
                    CRS_COORDENADAS if columna in COLUMNAS_COORDENADAS or columna in PARES_COORDENADAS else ""
                ),
                "registros": len(base),
                "faltantes": int(serie.isna().sum()),
                "porcentaje_faltantes": (
                    round(float(serie.isna().mean() * 100), 2)
                    if len(base)
                    else 0.0
                ),
                "valores_distintos": int(serie.nunique(dropna=True)),
                "valores_ejemplo": " | ".join(ejemplos),
                "valor_sentinela": SENTINELAS_CAMPOS.get(columna, ""),
                "transformacion_aplicada": (
                    "Fecha convertida desde Excel y almacenada en ISO en SQLite"
                    if columna in COLUMNAS_FECHA
                    else "Coordenada decimal; rango global validado"
                    if columna in COLUMNAS_COORDENADAS
                    else "Código conservado como texto y con ceros iniciales"
                    if columna in ANCHOS_CODIGOS
                    else "Geometría WKT POINT (longitud latitud)"
                    if columna in PARES_COORDENADAS
                    else "Texto recortado; faltantes normalizados"
                ),
                "origen": "Archivos XLSX 2017-2025 y 2026 armonizados",
            }
        )
    return pd.DataFrame(filas)


def crear_metadatos_dataset(base: pd.DataFrame) -> pd.DataFrame:
    """Crea metadatos generales del conjunto de datos procesado."""
    fechas = pd.to_datetime(base["fecha_desaparicion"], errors="coerce")
    pares = [
        columna
        for columna in (
            "latitud_desaparicion",
            "longitud_desaparicion",
        )
        if columna in base.columns
    ]
    valores = [
        ("nombre", "Base unificada de personas desaparecidas"),
        (
            "descripcion",
            "Registros unificados, estandarizados y perfilados para análisis.",
        ),
        (
            "fuentes",
            "mdi_personasdesaparecidas_pm_2017_2025.xlsx; "
            "mdi_personasdesaparecidas_pm_2026_enero_agosto.xlsx",
        ),
        ("tabla_principal", "base_limpia"),
        ("cantidad_registros", str(len(base))),
        ("cantidad_campos", str(len(base.columns))),
        (
            "periodo_fecha_desaparicion",
            f"{fechas.min().date() if fechas.notna().any() else 'Sin dato'} a "
            f"{fechas.max().date() if fechas.notna().any() else 'Sin dato'}",
        ),
        ("sistema_referencia_espacial", CRS_COORDENADAS),
        ("formato_geometria", "WKT POINT (longitud latitud)"),
        (
            "tratamiento_faltantes",
            "NA en campos tipados; NO ENCONTRADO donde se especifica en el catálogo.",
        ),
        (
            "fecha_generacion_utc",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
        (
            "privacidad",
            "Contiene información sensible; limitar acceso y revisar reglas de divulgación.",
        ),
    ]
    if pares and base[pares].notna().any(axis=None):
        valores.append(
            (
                "cobertura_coordenadas_desaparicion",
                f"Latitud {base[pares[0]].min()} a {base[pares[0]].max()}; "
                f"longitud {base[pares[1]].min()} a {base[pares[1]].max()}",
            )
        )
    return pd.DataFrame(valores, columns=["metadato", "valor"])


def guardar_en_sqlite(
    base: pd.DataFrame,
    perfil: pd.DataFrame,
    resumen_general: pd.DataFrame,
    estadisticas_cuantitativas: pd.DataFrame,
    frecuencias_cualitativas: pd.DataFrame,
    resumen_temporal: pd.DataFrame,
    catalogo_metadatos: pd.DataFrame,
    metadatos_dataset: pd.DataFrame,
) -> None:
    """Guarda los datos y el perfil en tablas SQLite; fechas se almacenan ISO."""
    base_sql = base.copy()
    for columna in COLUMNAS_FECHA.intersection(base_sql.columns):
        base_sql[columna] = pd.to_datetime(
            base_sql[columna],
            errors="coerce",
        ).dt.strftime("%Y-%m-%d")

    with closing(sqlite3.connect(ARCHIVO_SQLITE)) as conexion:
        with conexion:
            base_sql.to_sql(
                "base_limpia",
                conexion,
                if_exists="replace",
                index=False,
            )
            perfil.to_sql(
                "perfil_variables",
                conexion,
                if_exists="replace",
                index=False,
            )
            resumen_general.to_sql(
                "resumen_general",
                conexion,
                if_exists="replace",
                index=False,
            )
            estadisticas_cuantitativas.to_sql(
                "estadisticas_cuantitativas",
                conexion,
                if_exists="replace",
                index=False,
            )
            frecuencias_cualitativas.to_sql(
                "frecuencias_cualitativas",
                conexion,
                if_exists="replace",
                index=False,
            )
            resumen_temporal.to_sql(
                "resumen_temporal",
                conexion,
                if_exists="replace",
                index=False,
            )
            catalogo_metadatos.to_sql(
                "catalogo_metadatos",
                conexion,
                if_exists="replace",
                index=False,
            )
            metadatos_dataset.to_sql(
                "metadatos_dataset",
                conexion,
                if_exists="replace",
                index=False,
            )


def generar_base_analizada() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Unifica, limpia y guarda la base junto con su perfil de calidad."""
    base_original = unificar_bases_datos()
    base_limpia, no_convertibles, fuera_rango = limpiar_base(base_original)
    base_limpia = crear_puntos_geograficos(base_limpia)
    for columna in (
        *FALTANTES_CON_NO_ENCONTRADO,
        "estado_fecha_localizacion",
        *PARES_COORDENADAS,
    ):
        if columna in base_limpia.columns and columna not in base_original.columns:
            base_original[columna] = base_limpia[columna]
    perfil = crear_perfil(
        base_original,
        base_limpia,
        no_convertibles,
        fuera_rango,
    )
    resumen_general = crear_resumen_general(base_limpia)
    estadisticas_cuantitativas = crear_estadisticas_cuantitativas(base_limpia)
    frecuencias_cualitativas = crear_frecuencias_cualitativas(base_limpia)
    resumen_temporal = crear_resumen_temporal(base_limpia)
    catalogo_metadatos = crear_catalogo_metadatos(base_limpia)
    metadatos_dataset = crear_metadatos_dataset(base_limpia)

    with pd.ExcelWriter(
        ARCHIVO_RESULTADO,
        date_format="dd/mm/yyyy",
        datetime_format="dd/mm/yyyy",
    ) as escritor:
        base_limpia.to_excel(escritor, sheet_name="base_limpia", index=False)
        perfil.to_excel(escritor, sheet_name="perfil_variables", index=False)
        resumen_general.to_excel(escritor, sheet_name="resumen_general", index=False)
        estadisticas_cuantitativas.to_excel(
            escritor,
            sheet_name="estadisticas_cuantitativas",
            index=False,
        )
        frecuencias_cualitativas.to_excel(
            escritor,
            sheet_name="frecuencias_cualitativas",
            index=False,
        )
        resumen_temporal.to_excel(escritor, sheet_name="resumen_temporal", index=False)
        catalogo_metadatos.to_excel(
            escritor,
            sheet_name="catalogo_metadatos",
            index=False,
        )
        metadatos_dataset.to_excel(
            escritor,
            sheet_name="metadatos_dataset",
            index=False,
        )

        hoja_base = escritor.sheets["base_limpia"]
        columnas = {
            celda.value: celda.column
            for celda in hoja_base[1]
        }
        for nombre_columna in COLUMNAS_FECHA.intersection(columnas):
            numero_columna = columnas[nombre_columna]
            for fila in range(2, hoja_base.max_row + 1):
                hoja_base.cell(
                    row=fila,
                    column=numero_columna,
                ).number_format = "DD/MM/YYYY"

    guardar_en_sqlite(
        base_limpia,
        perfil,
        resumen_general,
        estadisticas_cuantitativas,
        frecuencias_cualitativas,
        resumen_temporal,
        catalogo_metadatos,
        metadatos_dataset,
    )
    return base_limpia, perfil


if __name__ == "__main__":
    base_limpia, perfil = generar_base_analizada()
    print(f"Archivo guardado en: {ARCHIVO_RESULTADO}")
    print(f"Base de datos SQLite guardada en: {ARCHIVO_SQLITE}")
    print(
        "Tablas SQLite: base_limpia, perfil_variables, resumen_general, "
        "estadisticas_cuantitativas, frecuencias_cualitativas, resumen_temporal, "
        "catalogo_metadatos, metadatos_dataset"
    )
    dataframe_sqlite = leer_base_sqlite()
    print(
        "DataFrame leído desde SQLite: "
        f"{dataframe_sqlite.shape[0]:,} filas x {dataframe_sqlite.shape[1]} columnas"
    )
    print("Tipos de datos del DataFrame:")
    print(dataframe_sqlite.dtypes.to_string())
    menores_desaparecidos = contar_menores_desaparecidos(dataframe_sqlite)
    print(
        "Personas menores de 17 años no localizadas "
        f"(situación actual: DESAPARECIDO): {menores_desaparecidos:,}"
    )
    print("\nPrincipales cantones y estado de desaparición:")
    print(
        principales_cantones_menores_desaparecidos(dataframe_sqlite)
        .to_string(index=False)
    )
    tiempo_localizacion = calcular_tiempo_localizacion(dataframe_sqlite)
    print(
        "\nTiempo promedio entre desaparición y localización "
        "para personas encontradas:"
    )
    print(
        f"{tiempo_localizacion['promedio_dias']:.2f} días "
        f"(n={tiempo_localizacion['casos_incluidos_en_promedio']:,}; "
        f"mediana={tiempo_localizacion['mediana_dias']:.2f} días)"
    )
    if tiempo_localizacion["fechas_invertidas_excluidas"]:
        print(
            "Fechas invertidas excluidas del cálculo: "
            f"{tiempo_localizacion['fechas_invertidas_excluidas']:,}"
        )
    print(f"Registros unificados: {len(base_limpia):,}")
    print(f"Variables perfiladas: {len(perfil):,}")
    print(
        "Variables con faltantes: "
        f"{int((perfil['faltantes_detectados'] > 0).sum())}"
    )
    variables_con_problemas = (
        (perfil["valores_no_convertibles"] > 0)
        | (perfil["coordenadas_fuera_de_rango"] > 0)
    )
    print(
        "Variables con problemas de conversión/rango: "
        f"{int(variables_con_problemas.sum())}"
    )
    