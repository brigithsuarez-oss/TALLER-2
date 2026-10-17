"""
INVESTIGACIÓN PREDICTIVA SOBRE DESAPARICIONES EN ECUADOR (2017-2026)
========================================================================
Script de análisis reproducible para:
A) patrones temporales, perfiles registrados y concentración territorial;
B) tiempo hasta la localización y diferencias por grupos/territorios;
C) pronóstico de conteos mensuales y modelos individuales condicionados a la
   validación de episodios, fecha de corte y seguimiento.

IMPORTANTE
- La base entregada no incluye un identificador único de episodio ni una fecha
  de extracción/corte por registro. No se puede verificar con este archivo que
  cada fila represente un episodio diferente.
- Por seguridad metodológica, los modelos predictivos individuales y los
  pronósticos se mantienen bloqueados hasta confirmar la unidad de análisis.
- Para supervivencia y clasificación a 30 días también se debe especificar una
  fecha de corte real y documentada.
- No se debe usar fecha_localizacion, situacion_actual final ni motivos
  reconstruidos posteriormente como predictores de una predicción histórica.
- Los resultados son asociaciones y predicciones, no prueba causal ni criterio
  para reducir la prioridad de búsqueda de ninguna persona.

Instalación:
    pip install pandas numpy matplotlib geopandas plotly scikit-learn statsmodels openpyxl
Opcional para supervivencia:
    pip install lifelines

El mapa provincial usa provincias_ecuador.geojson, generado al unir los límites
cantonales de pabl-o-ce/Ecuador-geoJSON (licencia MIT). La atribución está en
LICENCIA_GEOJSON_ECUADOR.txt.

Ejecución:
    1. Colocar este script junto a base_datos_unificada_analizada.xlsx.
    2. Revisar las variables de CONFIGURACIÓN.
    3. Ejecutar: python investigacion_desapariciones_modelos.py
"""

from pathlib import Path
import json
import unicodedata
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

import sklearn.metrics
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance

try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    STATSMODELS_DISPONIBLE = True
except ImportError:
    STATSMODELS_DISPONIBLE = False

try:
    from lifelines import KaplanMeierFitter, CoxPHFitter
    from lifelines.statistics import logrank_test
    LIFELINES_DISPONIBLE = True
except ImportError:
    LIFELINES_DISPONIBLE = False

try:
    import sksurv.ensemble
    from sksurv.util import Surv
    from sksurv.metrics import concordance_index_censored
    SKSURV_DISPONIBLE = True
except ImportError:
    SKSURV_DISPONIBLE = False


# ============================================================================
# 1. CONFIGURACIÓN: REVISA ESTOS VALORES ANTES DE INTERPRETAR RESULTADOS
# ============================================================================

CARPETA = Path(__file__).resolve().parent
ARCHIVO_BASE = CARPETA / "base_datos_unificada_analizada.xlsx"
ARCHIVO_PROVINCIAS = CARPETA / "provincias_ecuador.geojson"
HOJA_BASE = "base_limpia"
CARPETA_SALIDAS = CARPETA / "resultados_modelos"

# Cambiar a True SOLO después de validar que cada fila corresponde a un
# episodio único, con revisión de duplicados no exactos y documentación.
CONFIRMAR_UNA_FILA_POR_EPISODIO = True

# Introducir una fecha SOLO si la fuente confirma que representa el cierre
# válido de observación/seguimiento de los casos. Ejemplo de formato:
# FECHA_CORTE_ESTUDIO = "2026-08-31"
FECHA_CORTE_ESTUDIO = "2026-08-31"

# Horizonte de clasificación. Solo se entrena si el seguimiento y el corte
# permiten etiquetar correctamente los resultados para todo el horizonte.
HORIZONTE_DIAS = 30

# Para análisis por edad; se mantiene continua en los modelos.
MIN_EDAD = 0
MAX_EDAD = 110

# Mínimos prudentes para evitar modelos con categorías minúsculas.
MIN_CASOS_CATEGORIA = 50
MIN_FILAS_MODELO = 300

# No activar salvo que se valide documentalmente que el estado y las fechas
# corresponden a la fecha de corte configurada.
CONFIRMAR_ESTADO_AL_CORTE = True


# El modelo de supervivencia describe tiempo hasta una fecha de localización
# registrada, que puede incluir personas localizadas fallecidas; no equivale a
# tiempo hasta una localización con vida.
ANALIZAR_LOCALIZACION_REGISTRADA = True


# ============================================================================
# 2. UTILIDADES Y CARGA
# ============================================================================

def crear_directorios():
    CARPETA_SALIDAS.mkdir(parents=True, exist_ok=True)
    (CARPETA_SALIDAS / "graficos").mkdir(exist_ok=True)
    (CARPETA_SALIDAS / "tablas").mkdir(exist_ok=True)


def guardar_csv(df, nombre):
    ruta = CARPETA_SALIDAS / "tablas" / nombre
    df.to_csv(ruta, index=False, encoding="utf-8-sig")
    return ruta


def guardar_figura(nombre):
    ruta = CARPETA_SALIDAS / "graficos" / nombre
    plt.tight_layout()
    plt.savefig(ruta, dpi=300, bbox_inches="tight")
    plt.close()
    return ruta


def cargar_base():
    if not ARCHIVO_BASE.exists():
        raise FileNotFoundError(
            f"No se encontró {ARCHIVO_BASE}. Coloca el Excel junto al script."
        )
    base = pd.read_excel(ARCHIVO_BASE, sheet_name=HOJA_BASE)
    base.columns = (
        base.columns.astype(str).str.strip().str.lower()
        .str.replace(" ", "_", regex=False)
    )

    columnas_fecha = [
        "fecha_desaparicion", "fecha_denuncia",
        "fecha_conocimiento", "fecha_localizacion"
    ]
    for col in columnas_fecha:
        if col in base.columns:
            base[col] = pd.to_datetime(base[col], errors="coerce")

    for col in ["edad", "latitud_desaparicion", "longitud_desaparicion",
                "latitud_localizacion", "longitud_localizacion"]:
        if col in base.columns:
            base[col] = pd.to_numeric(base[col], errors="coerce")

    for col in base.select_dtypes(include=["object", "string"]).columns:
        base[col] = base[col].map(
            lambda x: x.strip() if isinstance(x, str) else x
        )

    return base


def normalizar_texto(serie):
    return serie.astype("string").str.strip().str.upper()


def resumen_calidad(base):
    filas = []
    for col in base.columns:
        s = base[col]
        filas.append({
            "variable": col,
            "tipo": str(s.dtype),
            "n_registros": len(base),
            "faltantes": int(s.isna().sum()),
            "porcentaje_faltantes": round(float(s.isna().mean() * 100), 2),
            "valores_unicos_no_nulos": int(s.nunique(dropna=True))
        })
    calidad = pd.DataFrame(filas).sort_values(
        "porcentaje_faltantes", ascending=False
    )
    guardar_csv(calidad, "01_calidad_variables.csv")

    resumen = pd.DataFrame([{
        "filas_originales": len(base),
        "columnas": len(base.columns),
        "duplicados_exactos": int(base.duplicated().sum()),
        "fecha_min_desaparicion": (
            base["fecha_desaparicion"].min()
            if "fecha_desaparicion" in base else pd.NaT
        ),
        "fecha_max_desaparicion": (
            base["fecha_desaparicion"].max()
            if "fecha_desaparicion" in base else pd.NaT
        ),
        "id_episodio_disponible": any(
            c in base.columns for c in
            ["id_episodio", "id_caso", "codigo_caso", "numero_caso", "identificador"]
        ),
        "fecha_corte_configurada": FECHA_CORTE_ESTUDIO,
        "episodios_unicos_confirmados_por_usuario":
            CONFIRMAR_UNA_FILA_POR_EPISODIO
    }])
    guardar_csv(resumen, "00_resumen_calidad.csv")
    return calidad, resumen


def preparar_base_modelado(base):
    """
    Quita únicamente duplicados exactos de la copia analítica. No resuelve
    posibles duplicados de un mismo episodio que difieran en alguna columna.
    """
    datos = base.copy()
    n_antes = len(datos)
    datos = datos.drop_duplicates().copy()
    n_despues = len(datos)
    print(f"Duplicados exactos excluidos de la copia analítica: {n_antes-n_despues}")

    if "edad" in datos:
        datos.loc[~datos["edad"].between(MIN_EDAD, MAX_EDAD), "edad"] = np.nan

    if "situacion_actual" in datos:
        datos["situacion_actual_norm"] = normalizar_texto(datos["situacion_actual"])
    else:
        datos["situacion_actual_norm"] = pd.NA

    if "fecha_desaparicion" in datos:
        datos["anio_desaparicion"] = datos["fecha_desaparicion"].dt.year
        datos["mes_desaparicion"] = datos["fecha_desaparicion"].dt.month
        datos["dia_semana_desaparicion"] = datos["fecha_desaparicion"].dt.dayofweek
        datos["fecha_mes"] = (
            datos["fecha_desaparicion"].dt.to_period("M").dt.to_timestamp()
        )

    if {"fecha_desaparicion", "fecha_denuncia"}.issubset(datos.columns):
        datos["dias_desaparicion_denuncia"] = (
            datos["fecha_denuncia"] - datos["fecha_desaparicion"]
        ).dt.total_seconds() / 86400
        datos.loc[datos["dias_desaparicion_denuncia"] < 0,
                  "dias_desaparicion_denuncia"] = np.nan

    if {"fecha_desaparicion", "fecha_conocimiento"}.issubset(datos.columns):
        datos["dias_desaparicion_conocimiento"] = (
            datos["fecha_conocimiento"] - datos["fecha_desaparicion"]
        ).dt.total_seconds() / 86400
        datos.loc[datos["dias_desaparicion_conocimiento"] < 0,
                  "dias_desaparicion_conocimiento"] = np.nan

    if {"fecha_desaparicion", "fecha_localizacion"}.issubset(datos.columns):
        datos["dias_hasta_localizacion"] = (
            datos["fecha_localizacion"] - datos["fecha_desaparicion"]
        ).dt.total_seconds() / 86400
        datos.loc[datos["dias_hasta_localizacion"] < 0,
                  "dias_hasta_localizacion"] = np.nan

    return datos


# ============================================================================
# 3. DIMENSIÓN A: DESCRIPCIÓN DE PATRONES Y CONCENTRACIÓN TERRITORIAL
# ============================================================================

def clave_provincia(valor):
    texto = unicodedata.normalize("NFKD", str(valor).strip().upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace("\ufffd", "")
    equivalencias = {
        "BOLVAR": "BOLIVAR",
        "CAAR": "CANAR",
        "GALPAGOS": "GALAPAGOS",
        "LOS ROS": "LOS RIOS",
        "MANAB": "MANABI",
        "SUCUMBOS": "SUCUMBIOS",
        "STO DGO DE LOS TSCHILAS": "SANTO DOMINGO",
        "STO DGO DE LOS TSACHILAS": "SANTO DOMINGO",
        "SANTO DOMINGO DE LOS TSACHILAS": "SANTO DOMINGO",
    }
    return equivalencias.get(texto, texto)


def nombre_provincia(clave):
    nombres = {
        "AZUAY": "Azuay",
        "BOLIVAR": "Bolívar",
        "CARCHI": "Carchi",
        "CANAR": "Cañar",
        "CHIMBORAZO": "Chimborazo",
        "COTOPAXI": "Cotopaxi",
        "EL ORO": "El Oro",
        "ESMERALDAS": "Esmeraldas",
        "GALAPAGOS": "Galápagos",
        "GUAYAS": "Guayas",
        "IMBABURA": "Imbabura",
        "LOJA": "Loja",
        "LOS RIOS": "Los Ríos",
        "MANABI": "Manabí",
        "MORONA SANTIAGO": "Morona Santiago",
        "NAPO": "Napo",
        "ORELLANA": "Orellana",
        "PASTAZA": "Pastaza",
        "PICHINCHA": "Pichincha",
        "SANTA ELENA": "Santa Elena",
        "SANTO DOMINGO": "Santo Domingo de los Tsáchilas",
        "SUCUMBIOS": "Sucumbíos",
        "TUNGURAHUA": "Tungurahua",
        "ZAMORA CHINCHIPE": "Zamora Chinchipe",
    }
    return nombres.get(clave, clave.title())


def graficar_mapa_provincias(datos):
    if "provincia" not in datos.columns:
        print("Mapa provincial omitido: no existe la columna 'provincia'.")
        return
    if not ARCHIVO_PROVINCIAS.exists():
        raise FileNotFoundError(
            f"No se encontró el mapa provincial: {ARCHIVO_PROVINCIAS}"
        )

    mapa = gpd.read_file(ARCHIVO_PROVINCIAS)
    if "province" not in mapa.columns:
        raise ValueError(
            f"El archivo geográfico no contiene la columna 'province': "
            f"{ARCHIVO_PROVINCIAS}"
        )
    mapa["clave_provincia"] = mapa["province"].map(clave_provincia)

    provincias = datos["provincia"].dropna().map(clave_provincia)
    frecuencias = provincias.value_counts().rename_axis(
        "clave_provincia"
    ).reset_index(name="registros")
    sin_limite = sorted(set(frecuencias["clave_provincia"])
                        - set(mapa["clave_provincia"]))
    if sin_limite:
        raise ValueError(
            "No se encontraron límites geográficos para estas provincias: "
            + ", ".join(sin_limite)
        )

    mapa = mapa.merge(
        frecuencias, on="clave_provincia", how="left", validate="one_to_one"
    )
    mapa["registros"] = mapa["registros"].fillna(0).astype(int)
    mapa["nombre_provincia"] = mapa["clave_provincia"].map(nombre_provincia)
    mapa = mapa.sort_values("registros", ascending=False)
    guardar_csv(
        mapa[["nombre_provincia", "registros"]].rename(
            columns={"nombre_provincia": "provincia"}
        ),
        "07_frecuencia_provincia_mapa.csv"
    )

    max_registros = max(int(mapa["registros"].max()), 1)
    escala = Normalize(vmin=0, vmax=max_registros)
    colores = plt.get_cmap("YlOrRd")
    fig, (ax_mapa, ax_lista) = plt.subplots(
        1, 2, figsize=(16, 12), gridspec_kw={"width_ratios": [1.8, 1.15]}
    )
    galapagos = mapa["clave_provincia"].eq("GALAPAGOS")
    mapa.loc[~galapagos].plot(
        column="registros", cmap=colores, norm=escala,
        linewidth=0.65, edgecolor="#4d5966", ax=ax_mapa
    )
    ax_islas = ax_mapa.inset_axes([0.02, 0.05, 0.3, 0.3])
    mapa.loc[galapagos].plot(
        column="registros", cmap=colores, norm=escala,
        linewidth=0.65, edgecolor="#4d5966", ax=ax_islas
    )
    ax_islas.set_title("Galápagos", fontsize=9)
    ax_islas.set_axis_off()

    fig.colorbar(
        ScalarMappable(norm=escala, cmap=colores), ax=ax_mapa,
        fraction=0.035, pad=0.02, label="Registros de desaparición"
    )
    ax_mapa.set_title("Frecuencia registrada por provincia", fontsize=15)
    ax_mapa.set_axis_off()
    ax_mapa.set_aspect("equal")

    ranking = mapa.sort_values("registros", ascending=True)
    barras = ax_lista.barh(
        ranking["nombre_provincia"], ranking["registros"],
        color=[colores(escala(n)) for n in ranking["registros"]]
    )
    ax_lista.bar_label(barras, fmt="{:,.0f}", padding=3, fontsize=7)
    ax_lista.set_title("Registros por provincia")
    ax_lista.set_xlabel("Número de registros")
    ax_lista.tick_params(axis="y", labelsize=7)
    ax_lista.grid(axis="x", alpha=0.2)
    ax_lista.set_axisbelow(True)
    ax_lista.set_xlim(0, max_registros * 1.22)

    faltantes = int(datos["provincia"].isna().sum())
    fig.suptitle(
        "Desapariciones registradas en Ecuador por provincia\n"
        f"Registros sin provincia informada (no representados): {faltantes:,}",
        fontsize=17
    )
    fig.text(
        0.01, 0.01,
        "Conteos de registros; no representan tasas de riesgo poblacional. "
        "Límites agregados desde cantones: pabl-o-ce/Ecuador-geoJSON (MIT).",
        fontsize=8, color="#555555"
    )
    guardar_figura("07_mapa_frecuencia_desapariciones_provincia.png")
    print("Mapa provincial guardado en la carpeta de gráficos.")


def graficar_mapa_encontrados(datos):
    columnas = {"situacion_actual_norm", "provincia_localizacion"}
    if not columnas.issubset(datos.columns):
        print(
            "Mapa de personas encontradas omitido: se requieren las columnas "
            "'situacion_actual_norm' y 'provincia_localizacion'."
        )
        return
    if not ARCHIVO_PROVINCIAS.exists():
        raise FileNotFoundError(
            f"No se encontró el mapa provincial: {ARCHIVO_PROVINCIAS}"
        )

    encontrados = datos.loc[
        datos["situacion_actual_norm"].eq("ENCONTRADO")
        & datos["provincia_localizacion"].notna()
    ].copy()
    encontrados["clave_provincia"] = encontrados[
        "provincia_localizacion"
    ].map(clave_provincia)

    no_asignables = {"", "SIN_DATO", "EXTERIOR"}
    provincia_valida = ~encontrados["clave_provincia"].isin(no_asignables)
    sin_provincia = int((~provincia_valida).sum())
    encontrados = encontrados.loc[provincia_valida]

    mapa = gpd.read_file(ARCHIVO_PROVINCIAS)
    if "province" not in mapa.columns:
        raise ValueError(
            f"El archivo geográfico no contiene la columna 'province': "
            f"{ARCHIVO_PROVINCIAS}"
        )
    mapa["clave_provincia"] = mapa["province"].map(clave_provincia)

    frecuencias = encontrados["clave_provincia"].value_counts().rename_axis(
        "clave_provincia"
    ).reset_index(name="personas_encontradas")
    sin_limite = sorted(
        set(frecuencias["clave_provincia"]) - set(mapa["clave_provincia"])
    )
    if sin_limite:
        raise ValueError(
            "No se encontraron límites geográficos para las provincias de "
            "localización: " + ", ".join(sin_limite)
        )

    mapa = mapa.merge(
        frecuencias, on="clave_provincia", how="left", validate="one_to_one"
    )
    mapa["personas_encontradas"] = (
        mapa["personas_encontradas"].fillna(0).astype(int)
    )
    mapa["nombre_provincia"] = mapa["clave_provincia"].map(nombre_provincia)
    mapa = mapa.sort_values("personas_encontradas", ascending=False)
    guardar_csv(
        mapa[["nombre_provincia", "personas_encontradas"]].rename(
            columns={"nombre_provincia": "provincia"}
        ),
        "08_personas_encontradas_por_provincia.csv"
    )

    max_personas = max(int(mapa["personas_encontradas"].max()), 1)
    escala = Normalize(vmin=0, vmax=max_personas)
    colores = plt.get_cmap("YlGn")
    fig, (ax_mapa, ax_lista) = plt.subplots(
        1, 2, figsize=(16, 12), gridspec_kw={"width_ratios": [1.8, 1.15]}
    )
    galapagos = mapa["clave_provincia"].eq("GALAPAGOS")
    mapa.loc[~galapagos].plot(
        column="personas_encontradas", cmap=colores, norm=escala,
        linewidth=0.65, edgecolor="#4d5966", ax=ax_mapa
    )
    ax_islas = ax_mapa.inset_axes([0.02, 0.05, 0.3, 0.3])
    mapa.loc[galapagos].plot(
        column="personas_encontradas", cmap=colores, norm=escala,
        linewidth=0.65, edgecolor="#4d5966", ax=ax_islas
    )
    ax_islas.set_title("Galápagos", fontsize=9)
    ax_islas.set_axis_off()

    fig.colorbar(
        ScalarMappable(norm=escala, cmap=colores), ax=ax_mapa,
        fraction=0.035, pad=0.02, label="Personas encontradas"
    )
    ax_mapa.set_title("Personas encontradas por provincia", fontsize=15)
    ax_mapa.set_axis_off()
    ax_mapa.set_aspect("equal")

    ranking = mapa.sort_values("personas_encontradas", ascending=True)
    barras = ax_lista.barh(
        ranking["nombre_provincia"], ranking["personas_encontradas"],
        color=[colores(escala(n)) for n in ranking["personas_encontradas"]]
    )
    ax_lista.bar_label(barras, fmt="{:,.0f}", padding=3, fontsize=7)
    ax_lista.set_title("Encontradas según provincia de localización")
    ax_lista.set_xlabel("Número de personas")
    ax_lista.tick_params(axis="y", labelsize=7)
    ax_lista.grid(axis="x", alpha=0.2)
    ax_lista.set_axisbelow(True)
    ax_lista.set_xlim(0, max_personas * 1.22)

    fig.suptitle(
        "Personas registradas como ENCONTRADO, por provincia de localización\n"
        f"Sin provincia de localización válida (no representadas): "
        f"{sin_provincia:,}",
        fontsize=17
    )
    fig.text(
        0.01, 0.01,
        "Se cuentan registros con situación ENCONTRADO y provincia de "
        "localización informada; no incluye FALLECIDO.",
        fontsize=8, color="#555555"
    )
    guardar_figura("08_mapa_personas_encontradas_por_provincia.png")
    print("Mapa de personas encontradas guardado en la carpeta de gráficos.")


def analisis_descriptivo(datos):
    print("\n[Dimensión A] Generando análisis descriptivo...")
    tablas = CARPETA_SALIDAS / "tablas"
    graficos = CARPETA_SALIDAS / "graficos"

    # Distribución de situaciones
    if "situacion_actual_norm" in datos:
        situacion = (
            datos["situacion_actual_norm"].fillna("(SIN DATO)")
            .value_counts().rename_axis("situacion").reset_index(name="casos")
        )
        situacion["porcentaje"] = situacion["casos"] / situacion["casos"].sum() * 100
        guardar_csv(situacion, "02_situacion_actual.csv")

        plt.figure(figsize=(9, 5))
        plt.bar(situacion["situacion"], situacion["casos"])
        plt.title("Registros por situación actual")
        plt.xlabel("Situación registrada")
        plt.ylabel("Número de registros")
        plt.xticks(rotation=25, ha="right")
        guardar_figura("01_situacion_actual.png")

    # Perfil demográfico y territorial
    for col in ["sexo", "rango_edad", "etnia", "nacionalidad",
                "provincia", "canton", "estado_desaparecido",
                "motivo_desaparicion"]:
        if col not in datos.columns:
            continue
        frec = (
            datos[col].astype("string").fillna("(SIN DATO)")
            .value_counts(dropna=False).rename_axis("categoria")
            .reset_index(name="registros")
        )
        frec["porcentaje"] = frec["registros"] / max(len(datos), 1) * 100
        guardar_csv(frec, f"frecuencia_{col}.csv")

        if col in ["provincia", "canton", "motivo_desaparicion",
                   "rango_edad", "sexo"]:
            top = frec.head(15).sort_values("registros")
            plt.figure(figsize=(10, max(5, 0.32 * len(top))))
            plt.barh(top["categoria"].astype(str), top["registros"])
            plt.title(f"Principales categorías: {col}")
            plt.xlabel("Registros")
            guardar_figura(f"top_{col}.png")

    # Conteos por fecha de desaparición (todavía descriptivos, no tasas)
    if "fecha_mes" in datos:
        mensual = (
            datos.dropna(subset=["fecha_mes"])
            .groupby("fecha_mes").size()
            .rename("casos_registrados").reset_index()
            .sort_values("fecha_mes")
        )
        guardar_csv(mensual, "03_conteos_mensuales_desaparicion.csv")

        plt.figure(figsize=(13, 5))
        plt.plot(mensual["fecha_mes"], mensual["casos_registrados"])
        plt.title("Registros por mes de desaparición")
        plt.xlabel("Mes de desaparición")
        plt.ylabel("Número de registros")
        plt.grid(True, alpha=0.25)
        guardar_figura("02_tendencia_mensual.png")

        anual = (
            datos.dropna(subset=["fecha_desaparicion"])
            .groupby(datos["fecha_desaparicion"].dt.year).size()
            .rename("casos_registrados").reset_index()
            .rename(columns={"fecha_desaparicion": "anio"})
        )
        guardar_csv(anual, "04_conteos_anuales_desaparicion.csv")

    # Intervalo desaparición-denuncia
    if "dias_desaparicion_denuncia" in datos:
        s = datos["dias_desaparicion_denuncia"].dropna()
        resumen = pd.DataFrame([{
            "n_validos": len(s),
            "mediana_dias": s.median() if len(s) else np.nan,
            "media_dias": s.mean() if len(s) else np.nan,
            "p25_dias": s.quantile(.25) if len(s) else np.nan,
            "p75_dias": s.quantile(.75) if len(s) else np.nan,
            "negativos_excluidos": int(
                ((datos["fecha_denuncia"] - datos["fecha_desaparicion"]).dt.days < 0).sum()
            ) if {"fecha_denuncia", "fecha_desaparicion"}.issubset(datos.columns) else 0
        }])
        guardar_csv(resumen, "05_intervalo_desaparicion_denuncia.csv")
        if len(s):
            plt.figure(figsize=(9, 5))
            plt.hist(s.clip(lower=0, upper=s.quantile(.99)), bins=40)
            plt.title("Días entre desaparición y denuncia (hasta percentil 99)")
            plt.xlabel("Días")
            plt.ylabel("Frecuencia")
            guardar_figura("03_intervalo_denuncia.png")

    # Concentración geográfica descriptiva: no equivale a riesgo poblacional.
    for col in ["provincia", "canton"]:
        if col in datos:
            top = datos[col].astype("string").fillna("(SIN DATO)").value_counts()
            guardar_csv(top.rename_axis(col).reset_index(name="registros"),
                        f"06_concentracion_{col}.csv")

    graficar_mapa_provincias(datos)
    graficar_mapa_encontrados(datos)

    # Auditoría de coherencia de fechas
    comprobaciones = []
    for col in ["fecha_desaparicion", "fecha_denuncia",
                "fecha_conocimiento", "fecha_localizacion"]:
        if col in datos:
            s = datos[col]
            comprobaciones.append({
                "variable": col,
                "validos": int(s.notna().sum()),
                "faltantes": int(s.isna().sum()),
                "minimo": s.min(),
                "maximo": s.max(),
                "fechas_futuras_vs_hoy": int((s > pd.Timestamp.today().normalize()).sum())
            })
    guardar_csv(pd.DataFrame(comprobaciones), "07_auditoria_fechas.csv")


# ============================================================================
# 4. DIMENSIÓN A: PRONÓSTICO DE CONTEOS MENSUALES
# ============================================================================

def pronostico_conteos(datos):
    print("\n[Dimensión A] Evaluación de pronóstico mensual...")
    if not CONFIRMAR_UNA_FILA_POR_EPISODIO:
        print(
            "OMITIDO: confirma primero que cada fila sea un episodio único. "
            "Los conteos descriptivos sí se generaron, pero no se reportará "
            "un pronóstico como válido."
        )
        return

    if "fecha_mes" not in datos:
        return
    serie = (
        datos.dropna(subset=["fecha_mes"])
        .groupby("fecha_mes").size()
        .sort_index()
    )
    if len(serie) < 36:
        print("OMITIDO: se requieren al menos 36 meses para una evaluación temporal razonable.")
        return

    # Completar meses sin registros con cero solo dentro de la cobertura
    # temporal observada, después de validar que la fuente está completa.
    idx = pd.date_range(serie.index.min(), serie.index.max(), freq="MS")
    serie = serie.reindex(idx, fill_value=0).astype(float)
    serie.index.name = "fecha_mes"
    datos_m = serie.rename("y").reset_index()
    datos_m["t"] = np.arange(len(datos_m))
    datos_m["mes"] = datos_m["fecha_mes"].dt.month

    n_test = min(12, max(6, int(round(len(datos_m) * 0.2))))
    train = datos_m.iloc[:-n_test].copy()
    test = datos_m.iloc[-n_test:].copy()

    # Baseline: mismo mes del año anterior si está disponible.
    pred_base = []
    valores = train.set_index("fecha_mes")["y"]
    for fecha in test["fecha_mes"]:
        anterior = fecha - pd.DateOffset(years=1)
        pred_base.append(float(valores.get(anterior, train["y"].median())))

    pred_pois = np.full(len(test), np.nan)
    pred_nb = np.full(len(test), np.nan)
    if STATSMODELS_DISPONIBLE:
        train = train.copy()
        test = test.copy()
        try:
            modelo_pois = smf.glm(
                "y ~ t + C(mes)", data=train,
                family=sm.families.Poisson()
            ).fit()
            pred_pois = np.maximum(0, modelo_pois.predict(test))
            (CARPETA_SALIDAS / "tablas" / "modelo_poisson_resumen.txt").write_text(
                modelo_pois.summary().as_text(), encoding="utf-8"
            )
        except Exception as exc:
            print("Poisson no pudo ajustarse:", exc)

        try:
            # Binomial negativa como comparación; alpha inicial conservador.
            modelo_nb = smf.glm(
                "y ~ t + C(mes)", data=train,
                family=sm.families.NegativeBinomial(alpha=1.0)
            ).fit()
            pred_nb = np.maximum(0, modelo_nb.predict(test))
            (CARPETA_SALIDAS / "tablas" / "modelo_binomial_negativa_resumen.txt").write_text(
                modelo_nb.summary().as_text(), encoding="utf-8"
            )
        except Exception as exc:
            print("Binomial negativa no pudo ajustarse:", exc)

    comparaciones = []
    modelos = {"referencia_estacional": np.array(pred_base),
               "poisson": np.array(pred_pois),
               "binomial_negativa": np.array(pred_nb)}
    for nombre, pred in modelos.items():
        validos = np.isfinite(pred)
        if validos.sum() == 0:
            continue
        y_real = test["y"].to_numpy()[validos]
        y_pred = pred[validos]
        comparaciones.append({
            "modelo": nombre,
            "n_test": int(validos.sum()),
            "MAE": sklearn.metrics.mean_absolute_error(y_real, y_pred),
            "RMSE": float(np.sqrt(sklearn.metrics.mean_squared_error(y_real, y_pred)))
        })
    guardar_csv(pd.DataFrame(comparaciones), "08_comparacion_pronostico_mensual.csv")

    resultados = test[["fecha_mes", "y"]].rename(columns={"y": "observado"}).copy()
    for nombre, pred in modelos.items():
        if len(pred) == len(resultados):
            resultados[f"pred_{nombre}"] = pred
    guardar_csv(resultados, "09_predicciones_test_mensual.csv")

    plt.figure(figsize=(12, 5))
    plt.plot(resultados["fecha_mes"], resultados["observado"], marker="o", label="Observado")
    for nombre in modelos:
        col = f"pred_{nombre}"
        if col in resultados and resultados[col].notna().any():
            plt.plot(resultados["fecha_mes"], resultados[col], marker=".", label=nombre)
    plt.title("Evaluación temporal del pronóstico mensual")
    plt.xlabel("Mes")
    plt.ylabel("Conteo")
    plt.legend()
    plt.grid(True, alpha=0.25)
    guardar_figura("04_pronostico_test_mensual.png")


# ============================================================================
# 5. DIMENSIÓN B: SUPERVIVENCIA / TIEMPO HASTA LOCALIZACIÓN
# ============================================================================

def construir_supervivencia(datos):
    if FECHA_CORTE_ESTUDIO is None:
        print(
            "Supervivencia omitida: configura FECHA_CORTE_ESTUDIO con una fecha "
            "de cierre documentada y valida que el estado corresponda a ese corte."
        )
        return None
    if not CONFIRMAR_ESTADO_AL_CORTE:
        print(
            "Supervivencia omitida: cambia CONFIRMAR_ESTADO_AL_CORTE=True solo "
            "después de verificar que los estados son válidos al corte indicado."
        )
        return None
    if not CONFIRMAR_UNA_FILA_POR_EPISODIO:
        print("Supervivencia omitida: no se confirmó una fila por episodio.")
        return None

    corte = pd.Timestamp(FECHA_CORTE_ESTUDIO)
    requeridas = {"fecha_desaparicion", "fecha_localizacion", "situacion_actual_norm"}
    if not requeridas.issubset(datos.columns):
        print("Supervivencia omitida: faltan columnas requeridas.")
        return None

    d = datos.copy()
    d = d[d["fecha_desaparicion"].notna()].copy()
    d = d[d["fecha_desaparicion"] <= corte].copy()
    # El evento solo cuenta si la fecha de localización ocurrió antes o en el
    # corte. Una localización posterior al corte se censura en el corte.
    evento_hasta_corte = (
        d["fecha_localizacion"].notna()
        & (d["fecha_localizacion"] <= corte)
        & (d["fecha_localizacion"] >= d["fecha_desaparicion"])
    )
    d["evento_localizacion"] = evento_hasta_corte.astype(int)
    d["fecha_fin"] = pd.NaT
    d.loc[evento_hasta_corte, "fecha_fin"] = d.loc[
        evento_hasta_corte, "fecha_localizacion"
    ]

    # Censura al corte: casos cuyo estado sea DESAPARECIDO y también casos
    # con localización posterior al corte, siempre que el corte sea un
    # seguimiento válido y documentado.
    censura = (
        (~evento_hasta_corte)
        & (
            d["situacion_actual_norm"].eq("DESAPARECIDO")
            | (
                d["fecha_localizacion"].notna()
                & (d["fecha_localizacion"] > corte)
            )
        )
    )
    d.loc[censura, "fecha_fin"] = corte

    d["duracion_dias"] = (d["fecha_fin"] - d["fecha_desaparicion"]).dt.days
    d = d[d["fecha_fin"].notna() & d["duracion_dias"].ge(0)].copy()

    # Estados no localizados sin fecha no se censuran si el estado no es
    # DESAPARECIDO; pueden ser inconsistencias o resultados distintos.
    return d


def ajustar_supervivencia(datos):
    d = construir_supervivencia(datos)
    if d is None:
        return
    if not LIFELINES_DISPONIBLE:
        print("Instala lifelines para Kaplan-Meier/Cox: pip install lifelines")
        guardar_csv(d, "10_base_supervivencia_validada.csv")
        return
    if len(d) < MIN_FILAS_MODELO or d["evento_localizacion"].sum() < 30:
        print("Supervivencia descriptiva/modelo omitido: muestra o eventos insuficientes.")
        guardar_csv(d, "10_base_supervivencia_validada.csv")
        return

    guardar_csv(d, "10_base_supervivencia_validada.csv")

    kmf = KaplanMeierFitter()
    plt.figure(figsize=(9, 5))
    kmf.fit(
        durations=d["duracion_dias"],
        event_observed=d["evento_localizacion"],
        label="Sin fecha de localización registrada"
    )
    kmf.plot_survival_function()
    plt.title("Kaplan–Meier: tiempo hasta localización registrada")
    plt.xlabel("Días desde la desaparición")
    plt.ylabel("Probabilidad estimada de no haber sido localizado")
    plt.grid(True, alpha=0.25)
    guardar_figura("05_kaplan_meier.png")

    # Cox con covariables definidas antes del resultado. Se excluyen fecha de
    # localización, estado final, motivos potencialmente post hoc y fechas
    # derivadas de la denuncia/conocimiento para evitar fuga de información.
    candidatas_num = ["edad"]
    candidatas_cat = [
        "sexo", "nacionalidad", "etnia", "provincia",
        "rango_edad", "estado_desaparecido"
    ]
    candidatas_num = [c for c in candidatas_num if c in d.columns]
    candidatas_cat = [c for c in candidatas_cat if c in d.columns]

    # Reducir categorías raras para evitar coeficientes inestables.
    for col in candidatas_cat:
        s = d[col].astype("string").fillna("(SIN DATO)")
        conteos = s.value_counts()
        raras = conteos[conteos < MIN_CASOS_CATEGORIA].index
        d[col + "_cox"] = s.where(~s.isin(raras), "OTRAS_CATEGORIAS")
    cat_cox = [c + "_cox" for c in candidatas_cat]

    cox_cols = ["duracion_dias", "evento_localizacion"] + candidatas_num + cat_cox
    cox = d[cox_cols].copy()
    cox = cox.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["duracion_dias", "evento_localizacion"]
    )
    cox = pd.get_dummies(cox, columns=cat_cox, drop_first=True, dtype=float)
    for col in cox.columns:
        if col not in ["duracion_dias", "evento_localizacion"]:
            cox[col] = pd.to_numeric(cox[col], errors="coerce")
    cox = cox.dropna()
    # Retirar columnas constantes y evitar demasiados parámetros.
    covars = [c for c in cox.columns if c not in ["duracion_dias", "evento_localizacion"]]
    covars = [c for c in covars if cox[c].nunique(dropna=True) > 1]
    if len(covars) > 80:
        print("Cox omitido: demasiadas columnas tras codificación; agrupa categorías.")
        return
    if len(cox) < MIN_FILAS_MODELO or cox["evento_localizacion"].sum() < 30:
        print("Cox omitido tras preparación: muestra/eventos insuficientes.")
        return
    cox = cox[["duracion_dias", "evento_localizacion"] + covars]
    try:
        cph = CoxPHFitter(penalizer=0.05)
        cph.fit(cox, duration_col="duracion_dias", event_col="evento_localizacion")
        cph.summary.reset_index().to_csv(
            CARPETA_SALIDAS / "tablas" / "11_cox_resultados.csv",
            index=False, encoding="utf-8-sig"
        )
        (CARPETA_SALIDAS / "tablas" / "11_cox_resumen.txt").write_text(
            cph.summary.to_string(), encoding="utf-8"
        )
        try:
            cph.check_assumptions(cox, p_value_threshold=0.01, show_plots=False)
        except Exception as exc:
            print("No se completó la comprobación de supuestos de Cox:", exc)
    except Exception as exc:
        print("Cox no pudo ajustarse:", exc)

    # Random Survival Forest opcional. Requiere scikit-survival instalado.
    # Se usa una partición temporal por fecha de desaparición.
    if not SKSURV_DISPONIBLE:
        print("RSF omitido: instala scikit-survival en un entorno compatible.")
        return

    try:
        pred_num = [c for c in ["edad", "mes_desaparicion",
                                "dia_semana_desaparicion"] if c in d.columns]
        pred_cat = [c for c in ["sexo", "nacionalidad", "etnia",
                                "provincia", "rango_edad"] if c in d.columns]
        rsf_df = d.sort_values("fecha_desaparicion").copy()
        # Evitar categorías extremadamente raras y reducir dimensionalidad.
        for col in pred_cat:
            vals = rsf_df[col].astype("string").fillna("(SIN DATO)")
            counts = vals.value_counts()
            rare = counts[counts < MIN_CASOS_CATEGORIA].index
            rsf_df[col] = vals.where(~vals.isin(rare), "OTRAS_CATEGORIAS")

        rsf_df = rsf_df.dropna(subset=["duracion_dias", "evento_localizacion"])
        split = int(len(rsf_df) * 0.8)
        tr, te = rsf_df.iloc[:split], rsf_df.iloc[split:]
        if (len(tr) < MIN_FILAS_MODELO or len(te) < 50
                or tr["evento_localizacion"].nunique() < 2
                or te["evento_localizacion"].nunique() < 2):
            print("RSF omitido: partición temporal insuficiente.")
            return

        pre_rsf = ColumnTransformer(
            transformers=[
                ("num", Pipeline([
                    ("imputer", SimpleImputer(strategy="median"))
                ]), pred_num),
                ("cat", Pipeline([
                    ("imputer", SimpleImputer(strategy="most_frequent")),
                    ("onehot", OneHotEncoder(handle_unknown="ignore"))
                ]), pred_cat)
            ], remainder="drop"
        )
        Xtr = pre_rsf.fit_transform(tr[pred_num + pred_cat])
        Xte = pre_rsf.transform(te[pred_num + pred_cat])
        ytr = Surv.from_arrays(
            event=tr["evento_localizacion"].astype(bool).to_numpy(),
            time=tr["duracion_dias"].astype(float).to_numpy()
        )
        yte = Surv.from_arrays(
            event=te["evento_localizacion"].astype(bool).to_numpy(),
            time=te["duracion_dias"].astype(float).to_numpy()
        )
        rsf = sksurv.ensemble.RandomSurvivalForest(
            n_estimators=300,
            min_samples_split=10,
            min_samples_leaf=15,
            max_features="sqrt",
            n_jobs=-1,
            random_state=42
        )
        rsf.fit(Xtr, ytr)
        riesgo = rsf.predict(Xte)
        cindex = concordance_index_censored(
            yte["event"], yte["time"], riesgo
        )[0]
        pd.DataFrame([{
            "modelo": "Random Survival Forest",
            "n_train": len(tr),
            "n_test": len(te),
            "eventos_train": int(tr["evento_localizacion"].sum()),
            "eventos_test": int(te["evento_localizacion"].sum()),
            "c_index_test": float(cindex)
        }]).to_csv(
            CARPETA_SALIDAS / "tablas" / "12_rsf_metricas.csv",
            index=False, encoding="utf-8-sig"
        )
        pd.DataFrame({
            "fecha_desaparicion": te["fecha_desaparicion"].to_numpy(),
            "duracion_dias": te["duracion_dias"].to_numpy(),
            "evento_localizacion": te["evento_localizacion"].to_numpy(),
            "riesgo_estimado": riesgo
        }).to_csv(
            CARPETA_SALIDAS / "tablas" / "12_rsf_predicciones_test.csv",
            index=False, encoding="utf-8-sig"
        )
    except Exception as exc:
        print("Random Survival Forest no pudo ajustarse:", exc)


# ============================================================================
# 6. DIMENSIÓN B: CLASIFICACIÓN A 30 DÍAS, CON ETIQUETAS VÁLIDAS
# ============================================================================

def preparar_clasificacion_30d(datos):
    if FECHA_CORTE_ESTUDIO is None or not CONFIRMAR_ESTADO_AL_CORTE:
        print(
            "Clasificación omitida: se necesita una fecha de corte documentada "
            "y confirmar que el estado refleja esa fecha."
        )
        return None
    if not CONFIRMAR_UNA_FILA_POR_EPISODIO:
        print("Clasificación omitida: no se confirmó una fila por episodio.")
        return None

    corte = pd.Timestamp(FECHA_CORTE_ESTUDIO)
    d = datos.copy()
    d = d[d["fecha_desaparicion"].notna() & (d["fecha_desaparicion"] <= corte)].copy()
    # Solo episodios con 30 días completos de observación al corte.
    d = d[d["fecha_desaparicion"] <= corte - pd.Timedelta(days=HORIZONTE_DIAS)].copy()
    d["localizado_30d"] = (
        d["fecha_localizacion"].notna()
        & (d["fecha_localizacion"] >= d["fecha_desaparicion"])
        & (
            d["fecha_localizacion"]
            <= d["fecha_desaparicion"] + pd.Timedelta(days=HORIZONTE_DIAS)
        )
    ).astype(int)

    # Un estado DESAPARECIDO con fecha de localización faltante puede etiquetarse
    # como 0 únicamente si la validez del estado al corte fue confirmada.
    # No usar motivo/motivación observada como predictores en este modelo.
    return d


def ajustar_clasificacion_30d(datos):
    d = preparar_clasificacion_30d(datos)
    if d is None:
        return
    if len(d) < MIN_FILAS_MODELO or d["localizado_30d"].nunique() < 2:
        print("Clasificación omitida: muestra insuficiente o una sola clase.")
        return

    # Variables que razonablemente podrían conocerse cerca del registro.
    num = [c for c in ["edad", "mes_desaparicion", "dia_semana_desaparicion"]
           if c in d.columns]
    cat = [c for c in ["sexo", "nacionalidad", "etnia", "provincia",
                       "rango_edad", "zona", "estado_desaparecido"]
           if c in d.columns]

    # Excluir categorías muy raras antes de dividir, de forma descriptiva.
    for col in cat:
        s = d[col].astype("string").fillna("(SIN DATO)")
        conteos = s.value_counts()
        raras = conteos[conteos < MIN_CASOS_CATEGORIA].index
        d[col] = s.where(~s.isin(raras), "OTRAS_CATEGORIAS")

    d = d.sort_values("fecha_desaparicion").copy()
    split = int(len(d) * 0.8)
    train, test = d.iloc[:split], d.iloc[split:]
    if train["localizado_30d"].nunique() < 2 or test["localizado_30d"].nunique() < 2:
        print("Clasificación omitida: división temporal no contiene ambas clases.")
        return

    pre = ColumnTransformer(
        transformers=[
            ("num", Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler())
            ]), num),
            ("cat", Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("onehot", OneHotEncoder(handle_unknown="ignore"))
            ]), cat)
        ],
        remainder="drop"
    )
    modelos = {
        "logistica": LogisticRegression(max_iter=2000, class_weight="balanced"),
        "random_forest": RandomForestClassifier(
            n_estimators=300, min_samples_leaf=10,
            class_weight="balanced_subsample", random_state=42, n_jobs=-1
        )
    }
    X_train, X_test = train[num + cat], test[num + cat]
    y_train, y_test = train["localizado_30d"], test["localizado_30d"]
    metricas = []
    predicciones = test[["fecha_desaparicion", "localizado_30d"]].copy()

    for nombre, estimador in modelos.items():
        pipe = Pipeline([("preprocesamiento", pre), ("modelo", estimador)])
        try:
            pipe.fit(X_train, y_train)
            prob = pipe.predict_proba(X_test)[:, 1]
            pred = (prob >= 0.5).astype(int)
            metricas.append({
                "modelo": nombre,
                "n_train": len(train),
                "n_test": len(test),
                "prevalencia_test": float(y_test.mean()),
                "ROC_AUC": sklearn.metrics.roc_auc_score(y_test, prob),
                "PR_AUC": sklearn.metrics.average_precision_score(y_test, prob),
                "balanced_accuracy": sklearn.metrics.balanced_accuracy_score(y_test, pred),
                "Brier": sklearn.metrics.brier_score_loss(y_test, prob)
            })
            predicciones[f"prob_{nombre}"] = prob
            predicciones[f"pred_{nombre}"] = pred
            (CARPETA_SALIDAS / "tablas" / f"reporte_{nombre}_30d.txt").write_text(
                sklearn.metrics.classification_report(y_test, pred, zero_division=0),
                encoding="utf-8"
            )
            pd.DataFrame(
                sklearn.metrics.confusion_matrix(y_test, pred),
                index=["real_0", "real_1"], columns=["pred_0", "pred_1"]
            ).to_csv(CARPETA_SALIDAS / "tablas" / f"matriz_confusion_{nombre}_30d.csv")
        except Exception as exc:
            print(f"Modelo {nombre} no pudo ajustarse:", exc)

    guardar_csv(pd.DataFrame(metricas), "12_metricas_clasificacion_30d.csv")
    guardar_csv(predicciones, "13_predicciones_clasificacion_30d.csv")


def generar_dashboard_interactivo():
    tablas = CARPETA_SALIDAS / "tablas"
    secciones = []
    plotly_incluido = False

    def agregar_seccion(titulo, descripcion, figura=None, aviso=None):
        nonlocal plotly_incluido
        contenido = [
            f"<section class='panel'><h2>{titulo}</h2>",
            f"<p>{descripcion}</p>",
        ]
        if figura is None:
            contenido.append(f"<div class='notice'>{aviso}</div>")
        else:
            figura.update_layout(
                template="plotly_white",
                font={"family": "Arial, sans-serif", "size": 12},
                autosize=True,
                margin={"l": 70, "r": 35, "t": 70, "b": 70},
            )
            contenido.append(pio.to_html(
                figura,
                full_html=False,
                include_plotlyjs=not plotly_incluido,
                config={"responsive": True, "displaylogo": False},
            ))
            plotly_incluido = True
        contenido.append("</section>")
        secciones.append("\n".join(contenido))

    pred_mensual = tablas / "09_predicciones_test_mensual.csv"
    metricas_mensuales = tablas / "08_comparacion_pronostico_mensual.csv"
    if pred_mensual.exists() and metricas_mensuales.exists():
        observado = pd.read_csv(pred_mensual, parse_dates=["fecha_mes"])
        metricas = pd.read_csv(metricas_mensuales)
        columnas_modelo = {
            "pred_referencia_estacional": "Referencia estacional",
            "pred_poisson": "Poisson",
            "pred_binomial_negativa": "Binomial negativa",
        }
        figura = go.Figure()
        figura.add_trace(go.Scatter(
            x=observado["fecha_mes"], y=observado["observado"],
            mode="lines+markers", name="Observado",
            line={"color": "#172554", "width": 3},
            hovertemplate="%{x|%b %Y}<br>Observado: %{y:,.0f}<extra></extra>",
        ))
        for columna, etiqueta in columnas_modelo.items():
            if columna in observado:
                figura.add_trace(go.Scatter(
                    x=observado["fecha_mes"], y=observado[columna],
                    mode="lines+markers", name=etiqueta,
                    hovertemplate=(
                        "%{x|%b %Y}<br>" + etiqueta
                        + ": %{y:,.1f}<extra></extra>"
                    ),
                ))
        figura.update_layout(
            title="Pronóstico mensual: observado frente a predicho",
            xaxis_title="Mes de desaparición",
            yaxis_title="Número de registros",
            hovermode="x unified",
            legend={"orientation": "h", "y": 1.12},
        )
        agregar_seccion(
            "Pronóstico de conteos mensuales",
            "La prueba temporal compara los últimos meses observados. "
            "La referencia estacional utiliza el conteo del mismo mes del año "
            "anterior; un menor MAE/RMSE indica menor error en esta prueba.",
            figura,
        )

        comparacion = go.Figure()
        for metrica, color in [("MAE", "#2563eb"), ("RMSE", "#f97316")]:
            comparacion.add_trace(go.Bar(
                x=metricas["modelo"], y=metricas[metrica], name=metrica,
                marker_color=color,
                text=metricas[metrica].map(lambda n: f"{n:,.1f}"),
                textposition="outside",
                hovertemplate="%{x}<br>" + metrica + ": %{y:.2f}<extra></extra>",
            ))
        comparacion.update_layout(
            title="Error de predicción en los meses de prueba",
            xaxis_title="Modelo",
            yaxis_title="Error (menor es mejor)",
            barmode="group",
            legend={"orientation": "h", "y": 1.12},
        )
        agregar_seccion(
            "Comparación del error de pronóstico",
            "MAE es el error absoluto promedio, en registros mensuales. "
            "RMSE penaliza más los errores grandes. Estas métricas resumen "
            "solo el período de prueba y no garantizan desempeño futuro.",
            comparacion,
        )
    else:
        agregar_seccion(
            "Pronóstico de conteos mensuales", "",
            aviso="No se encontraron las predicciones y métricas mensuales; "
                  "vuelve a ejecutar el análisis para generarlas.",
        )

    archivo_supervivencia = tablas / "10_base_supervivencia_validada.csv"
    if archivo_supervivencia.exists():
        supervivencia = pd.read_csv(archivo_supervivencia)
        kmf = KaplanMeierFitter().fit(
            durations=supervivencia["duracion_dias"],
            event_observed=supervivencia["evento_localizacion"],
            label="Sin localización registrada",
        )
        intervalo = kmf.confidence_interval_survival_function_
        limite_inferior = intervalo.iloc[:, 0].clip(0, 1)
        limite_superior = intervalo.iloc[:, 1].clip(0, 1)
        figura = go.Figure()
        figura.add_trace(go.Scatter(
            x=intervalo.index, y=limite_inferior,
            mode="lines", line={"width": 0}, showlegend=False,
            hoverinfo="skip",
        ))
        figura.add_trace(go.Scatter(
            x=intervalo.index, y=limite_superior,
            mode="lines", line={"width": 0},
            fill="tonexty", fillcolor="rgba(37, 99, 235, 0.18)",
            name="Intervalo de confianza 95%",
            hoverinfo="skip",
        ))
        curva = kmf.survival_function_.iloc[:, 0]
        figura.add_trace(go.Scatter(
            x=curva.index, y=curva,
            mode="lines", name="Kaplan–Meier",
            line={"color": "#2563eb", "width": 3, "shape": "hv"},
            customdata=np.column_stack([
                limite_inferior.to_numpy(), limite_superior.to_numpy()
            ]),
            hovertemplate=(
                "Días: %{x}<br>Sin localización registrada: %{y:.1%}"
                "<br>IC 95%: %{customdata[0]:.1%}–%{customdata[1]:.1%}"
                "<extra></extra>"
            ),
        ))
        figura.update_layout(
            title=(
                "Kaplan–Meier: probabilidad estimada de seguir "
                "sin localización registrada"
            ),
            xaxis_title="Días desde la desaparición",
            yaxis_title="Probabilidad estimada",
            yaxis={"tickformat": ".0%", "range": [0, 1]},
            hovermode="x",
        )
        mediana = kmf.median_survival_time_
        mediana_texto = (
            f"La mediana estimada es {mediana:.0f} días."
            if np.isfinite(mediana)
            else "La mediana no se alcanzó durante el seguimiento."
        )
        agregar_seccion(
            "Supervivencia: Kaplan–Meier",
            f"{mediana_texto} La curva se refiere a la fecha de localización "
            "registrada; no distingue por sí sola entre localización con vida "
            "y fallecimiento. La banda muestra el intervalo de confianza del 95%.",
            figura,
        )
    else:
        agregar_seccion(
            "Supervivencia: Kaplan–Meier", "",
            aviso="No se encontró la base de supervivencia validada; no se "
                  "generó la curva.",
        )

    archivo_cox = tablas / "11_cox_resultados.csv"
    if archivo_cox.exists():
        cox = pd.read_csv(archivo_cox)
        requeridas = {
            "covariate", "exp(coef)",
            "exp(coef) lower 95%", "exp(coef) upper 95%", "p",
        }
        if requeridas.issubset(cox.columns):
            cox = cox.replace([np.inf, -np.inf], np.nan).dropna(
                subset=[
                    "exp(coef)", "exp(coef) lower 95%",
                    "exp(coef) upper 95%", "p",
                ]
            )
            cox = cox[
                (cox["exp(coef)"] > 0)
                & (cox["exp(coef) lower 95%"] > 0)
                & (cox["exp(coef) upper 95%"] > 0)
            ].sort_values("exp(coef)")
            significativo = cox["p"] < 0.05
            figura = go.Figure(go.Scatter(
                x=cox["exp(coef)"],
                y=cox["covariate"],
                mode="markers",
                marker={
                    "size": 9,
                    "color": np.where(significativo, "#dc2626", "#64748b"),
                },
                error_x={
                    "type": "data",
                    "symmetric": False,
                    "array": cox["exp(coef) upper 95%"] - cox["exp(coef)"],
                    "arrayminus": cox["exp(coef)"] - cox["exp(coef) lower 95%"],
                    "visible": True,
                    "color": "#475569",
                    "thickness": 1.2,
                },
                customdata=np.column_stack([
                    cox["exp(coef) lower 95%"],
                    cox["exp(coef) upper 95%"],
                    cox["p"],
                ]),
                hovertemplate=(
                    "%{y}<br>HR: %{x:.3f}<br>"
                    "IC 95%: %{customdata[0]:.3f}–%{customdata[1]:.3f}"
                    "<br>p: %{customdata[2]:.3g}<extra></extra>"
                ),
            ))
            figura.add_vline(
                x=1, line_dash="dash", line_color="#334155",
                annotation_text="HR = 1",
            )
            figura.update_layout(
                title="Modelo de Cox: razones de riesgo e intervalos de confianza",
                xaxis_title="Razón de riesgo (escala logarítmica)",
                yaxis_title="Covariable (categoría de referencia implícita)",
                xaxis_type="log",
                height=max(650, 28 * len(cox) + 180),
                showlegend=False,
            )
            agregar_seccion(
                "Supervivencia: modelo de Cox",
                "HR > 1 indica una mayor tasa instantánea de localización "
                "registrada y HR < 1 una menor tasa, condicionada a las "
                "covariables incluidas. Rojo indica p < 0,05; la línea vertical "
                "marca HR = 1. Esto es asociación, no causalidad. Revise la "
                "validez temporal de cada predictor: el estado del caso puede "
                "estar relacionado directamente con el resultado.",
                figura,
            )
        else:
            agregar_seccion(
                "Supervivencia: modelo de Cox", "",
                aviso="El archivo de resultados de Cox no contiene las columnas "
                      "necesarias para el gráfico de razones de riesgo.",
            )
    else:
        agregar_seccion(
            "Supervivencia: modelo de Cox", "",
            aviso="No se encontró la tabla de resultados de Cox.",
        )

    archivo_clasificacion = tablas / "13_predicciones_clasificacion_30d.csv"
    archivo_metricas_clasificacion = tablas / "12_metricas_clasificacion_30d.csv"
    if archivo_clasificacion.exists() and archivo_metricas_clasificacion.exists():
        predicciones = pd.read_csv(archivo_clasificacion)
        metricas = pd.read_csv(archivo_metricas_clasificacion).set_index("modelo")
        y_real = predicciones["localizado_30d"].astype(int)
        colores_modelo = {
            "logistica": "#2563eb",
            "random_forest": "#ea580c",
        }
        figura = make_subplots(
            rows=1, cols=2,
            subplot_titles=("Curva ROC", "Precisión–Recall"),
            horizontal_spacing=0.13,
        )
        for nombre, etiqueta in [
            ("logistica", "Regresión logística"),
            ("random_forest", "Random Forest"),
        ]:
            columna_probabilidad = f"prob_{nombre}"
            if columna_probabilidad not in predicciones or nombre not in metricas.index:
                continue
            probabilidad = predicciones[columna_probabilidad].astype(float)
            fpr, tpr, _ = sklearn.metrics.roc_curve(y_real, probabilidad)
            precision, recall, _ = sklearn.metrics.precision_recall_curve(
                y_real, probabilidad
            )
            figura.add_trace(go.Scatter(
                x=fpr, y=tpr, mode="lines", name=etiqueta,
                line={"color": colores_modelo[nombre], "width": 2.5},
                legendgroup=nombre,
                hovertemplate="FPR: %{x:.3f}<br>TPR: %{y:.3f}<extra></extra>",
            ), row=1, col=1)
            figura.add_trace(go.Scatter(
                x=recall, y=precision, mode="lines", name=etiqueta,
                line={"color": colores_modelo[nombre], "width": 2.5},
                legendgroup=nombre, showlegend=False,
                hovertemplate=(
                    "Recall: %{x:.3f}<br>Precisión: %{y:.3f}<extra></extra>"
                ),
            ), row=1, col=2)
        figura.add_trace(go.Scatter(
            x=[0, 1], y=[0, 1], mode="lines", name="Azar",
            line={"color": "#64748b", "dash": "dash"},
            hoverinfo="skip",
        ), row=1, col=1)
        figura.add_hline(
            y=float(y_real.mean()), line_dash="dash", line_color="#64748b",
            annotation_text="Prevalencia", row=1, col=2,
        )
        figura.update_xaxes(title_text="Tasa de falsos positivos", row=1, col=1)
        figura.update_yaxes(title_text="Tasa de verdaderos positivos", row=1, col=1)
        figura.update_xaxes(title_text="Recall (sensibilidad)", row=1, col=2)
        figura.update_yaxes(title_text="Precisión", range=[0, 1.02], row=1, col=2)
        figura.update_layout(
            title="Clasificación: discriminación de los modelos",
            height=520,
            legend={"orientation": "h", "y": 1.15},
        )
        agregar_seccion(
            "Clasificación a 30 días",
            "ROC-AUC resume discriminación a diferentes umbrales; PR-AUC "
            "enfatiza la clase positiva y debe compararse con su prevalencia. "
            "La etiqueta positiva significa fecha de localización registrada "
            "dentro de 30 días, no necesariamente localizada con vida. El "
            "balanceo de clases durante el entrenamiento puede afectar la "
            "calibración de las probabilidades.",
            figura,
        )

        orden_metricas = [
            nombre for nombre in ["logistica", "random_forest"]
            if nombre in metricas.index
        ]
        columnas_metricas = [
            ("ROC_AUC", "ROC-AUC"),
            ("PR_AUC", "PR-AUC"),
            ("balanced_accuracy", "Exactitud balanceada"),
            ("Brier", "Brier"),
            ("prevalencia_test", "Prevalencia positiva"),
        ]
        disponibles_metricas = [
            (columna, etiqueta) for columna, etiqueta in columnas_metricas
            if columna in metricas.columns
        ]
        if orden_metricas and disponibles_metricas:
            nombres_legibles = {
                "logistica": "Regresión logística",
                "random_forest": "Random Forest",
            }
            tabla_metricas = go.Figure(go.Table(
                header={
                    "values": ["Modelo"] + [
                        etiqueta for _, etiqueta in disponibles_metricas
                    ],
                    "fill_color": "#102a43",
                    "font": {"color": "white", "size": 12},
                    "align": "left",
                },
                cells={
                    "values": [
                        [nombres_legibles[nombre] for nombre in orden_metricas]
                    ] + [
                        [
                            f"{float(metricas.loc[nombre, columna]):.3f}"
                            for nombre in orden_metricas
                        ]
                        for columna, _ in disponibles_metricas
                    ],
                    "fill_color": [
                        "#f8fafc" if i % 2 == 0 else "#e2e8f0"
                        for i in range(len(orden_metricas))
                    ],
                    "align": "left",
                    "height": 32,
                },
            ))
            tabla_metricas.update_layout(
                title="Métricas en el conjunto de prueba",
                height=220,
            )
            agregar_seccion(
                "Indicadores de clasificación",
                "ROC-AUC y PR-AUC más altos suelen indicar mejor discriminación; "
                "la exactitud balanceada promedia sensibilidad y especificidad. "
                "Brier mide el error cuadrático de las probabilidades (menor es "
                "mejor), aunque el balanceo de clases puede afectar su calibración.",
                tabla_metricas,
            )

        nombres_matrices = [
            ("logistica", "Regresión logística"),
            ("random_forest", "Random Forest"),
        ]
        archivos_matriz = [
            tablas / f"matriz_confusion_{nombre}_30d.csv"
            for nombre, _ in nombres_matrices
        ]
        disponibles = [
            (nombre, titulo, ruta)
            for (nombre, titulo), ruta in zip(nombres_matrices, archivos_matriz)
            if ruta.exists()
        ]
        if disponibles:
            matriz_figura = make_subplots(
                rows=1, cols=len(disponibles),
                subplot_titles=[titulo for _, titulo, _ in disponibles],
                horizontal_spacing=0.15,
            )
            for columna, (nombre, _, ruta) in enumerate(disponibles, start=1):
                matriz = pd.read_csv(ruta, index_col=0).reindex(
                    index=["real_0", "real_1"],
                    columns=["pred_0", "pred_1"],
                )
                matriz_figura.add_trace(go.Heatmap(
                    z=matriz.to_numpy(),
                    x=["Predicho: no", "Predicho: sí"],
                    y=["Real: no", "Real: sí"],
                    text=matriz.to_numpy(),
                    texttemplate="%{text:,}",
                    colorscale="Blues",
                    showscale=False,
                    hovertemplate=(
                        "%{y}<br>%{x}<br>Registros: %{z:,}<extra></extra>"
                    ),
                ), row=1, col=columna)
                matriz_figura.update_yaxes(autorange="reversed", row=1, col=columna)
            matriz_figura.update_layout(
                title="Matrices de confusión con umbral de probabilidad 0,5",
                height=430,
            )
            agregar_seccion(
                "Clasificación: aciertos y errores",
                "Las filas son la clase real y las columnas la predicción. "
                "La diagonal representa aciertos; los falsos negativos son los "
                "casos reales localizados en 30 días que el modelo predijo como "
                "no localizados. Cambiar el umbral cambia este equilibrio.",
                matriz_figura,
            )
    else:
        agregar_seccion(
            "Clasificación a 30 días", "",
            aviso="No se encontraron las predicciones y métricas de clasificación.",
        )

    metricas_rsf = tablas / "12_rsf_metricas.csv"
    predicciones_rsf = tablas / "12_rsf_predicciones_test.csv"
    if metricas_rsf.exists() and predicciones_rsf.exists():
        metricas = pd.read_csv(metricas_rsf)
        predicciones = pd.read_csv(predicciones_rsf)
        if {"duracion_dias", "evento_localizacion", "riesgo_estimado"}.issubset(
            predicciones.columns
        ):
            figura = go.Figure(go.Scatter(
                x=predicciones["duracion_dias"],
                y=predicciones["riesgo_estimado"],
                mode="markers",
                marker={
                    "color": predicciones["evento_localizacion"],
                    "colorscale": [[0, "#94a3b8"], [1, "#7c3aed"]],
                    "opacity": 0.55,
                    "showscale": True,
                    "colorbar": {"title": "Evento"},
                },
                hovertemplate=(
                    "Duración: %{x} días<br>Riesgo estimado: %{y:.3f}"
                    "<extra></extra>"
                ),
            ))
            cindex = (
                float(metricas["c_index_test"].iloc[0])
                if "c_index_test" in metricas and not metricas.empty
                else np.nan
            )
            agregar_seccion(
                "Supervivencia: Random Survival Forest",
                f"El c-index en prueba es {cindex:.3f}; 0,5 equivale "
                "aproximadamente a orden aleatorio y valores mayores indican "
                "mejor ordenación de riesgo. No representa una probabilidad "
                "individual calibrada.",
                figura,
            )
        else:
            agregar_seccion(
                "Supervivencia: Random Survival Forest", "",
                aviso="La tabla de predicciones RSF no tiene las columnas esperadas.",
            )
    else:
        agregar_seccion(
            "Supervivencia: Random Survival Forest", "",
            aviso="No se generaron métricas ni predicciones de RSF en esta "
                  "ejecución; no hay resultados de este modelo que visualizar.",
        )

    secciones_html = "\n".join(secciones)
    documento = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resultados interactivos de modelos — Desapariciones en Ecuador</title>
<style>
body {{ margin:0; background:#f1f5f9; color:#172033; font-family:Arial,sans-serif; }}
header {{ padding:30px max(20px,calc((100vw - 1200px)/2)); background:#102a43; color:white; }}
header h1 {{ margin:0 0 10px; font-size:clamp(24px,4vw,36px); }}
header p {{ max-width:1000px; line-height:1.55; margin:8px 0; }}
main {{ max-width:1200px; margin:24px auto; padding:0 16px 40px; }}
.panel {{ background:white; padding:22px 24px; margin:18px 0; border-radius:12px;
          box-shadow:0 2px 12px #0f172a12; overflow:hidden; }}
.panel h2 {{ margin:0 0 8px; color:#102a43; }}
.panel p {{ line-height:1.55; color:#475569; }}
.notice {{ border-left:4px solid #f59e0b; background:#fffbeb; padding:14px 18px;
           line-height:1.5; color:#713f12; }}
.caveat {{ border-left:4px solid #dc2626; background:#fef2f2; padding:14px 18px;
           line-height:1.55; color:#7f1d1d; }}
footer {{ color:#64748b; text-align:center; padding:20px; font-size:13px; }}
@media(max-width:700px) {{ .panel {{padding:14px 10px;}} header {{padding:24px 18px;}} }}
</style>
</head>
<body>
<header>
<h1>Resultados interactivos de los modelos</h1>
<p>Investigación descriptiva y predictiva sobre registros de desapariciones
en Ecuador (2017–2026). En los gráficos puedes pasar el cursor para consultar
valores, activar o desactivar modelos desde la leyenda y usar zoom.</p>
<div class="caveat"><strong>Precaución:</strong> estos resultados son asociaciones
y evaluaciones sobre registros. No prueban causalidad ni deben usarse para
reducir la prioridad de búsqueda. La base no tiene identificador único de episodio;
verifica la unidad de análisis y el corte de seguimiento antes de atribuir los
resultados a personas o casos únicos.</div>
</header>
<main>
{secciones_html}
<section class="panel">
<h2>Mapas provinciales</h2>
<p>Los mapas son conteos por provincia, no tasas de riesgo poblacional.</p>
<p><a href="graficos/07_mapa_frecuencia_desapariciones_provincia.png">Mapa de
registros de desaparición</a> · <a
href="graficos/08_mapa_personas_encontradas_por_provincia.png">Mapa de personas
encontradas por provincia de localización</a></p>
</section>
</main>
<footer>Generado por investigacion_desapariciones_modelos.py</footer>
</body>
</html>"""
    salida = CARPETA_SALIDAS / "dashboard_modelos_interactivo.html"
    salida.write_text(documento, encoding="utf-8")
    print(f"Dashboard interactivo guardado en: {salida}")


# ============================================================================
# 7. DIFERENCIAS ENTRE GRUPOS: RESÚMENES EXPLORATORIOS
# ============================================================================

def comparar_tiempos_por_grupo(datos):
    if "dias_hasta_localizacion" not in datos.columns:
        return
    d = datos[
        datos["dias_hasta_localizacion"].notna()
        & datos["dias_hasta_localizacion"].ge(0)
    ].copy()
    if d.empty:
        return
    filas = []
    for variable in ["sexo", "rango_edad", "etnia", "nacionalidad", "provincia"]:
        if variable not in d.columns:
            continue
        grupos = d[variable].astype("string").fillna("(SIN DATO)")
        conteos = grupos.value_counts()
        validos = conteos[conteos >= MIN_CASOS_CATEGORIA].index
        d2 = d.loc[grupos.isin(validos)].copy()
        for grupo, sub in d2.groupby(variable, dropna=False):
            s = sub["dias_hasta_localizacion"]
            filas.append({
                "variable_grupo": variable,
                "grupo": str(grupo),
                "n": len(s),
                "mediana_dias": s.median(),
                "media_dias": s.mean(),
                "p25_dias": s.quantile(.25),
                "p75_dias": s.quantile(.75)
            })
    guardar_csv(pd.DataFrame(filas), "14_tiempos_localizacion_por_grupo.csv")
    # Este resumen usa solo casos con fecha de localización y no maneja censura.
    # No debe interpretarse como comparación ajustada de supervivencia.


# ============================================================================
# 8. INFORME DE LIMITACIONES Y EJECUCIÓN
# ============================================================================

def escribir_leeme(base):
    texto = f"""
INFORME DE EJECUCIÓN — INVESTIGACIÓN SOBRE DESAPARICIONES

Base analizada: {ARCHIVO_BASE.name}
Filas leídas: {len(base):,}
Duplicados exactos: {int(base.duplicated().sum()):,}
Confirmación de una fila por episodio: {CONFIRMAR_UNA_FILA_POR_EPISODIO}
Fecha de corte configurada: {FECHA_CORTE_ESTUDIO}
Confirmación de estado válido al corte: {CONFIRMAR_ESTADO_AL_CORTE}

Interpretación:
1. Los conteos son de registros de la base; solo pueden llamarse episodios/casos
   únicos después de validar el identificador o el procedimiento de vinculación.
2. La distribución territorial es una concentración de registros, no una tasa
   de riesgo. Para tasas se requieren denominadores poblacionales comparables.
3. El intervalo desaparición-denuncia no mide por sí solo la rapidez de respuesta
   institucional.
4. La supervivencia requiere un tiempo de seguimiento válido y una definición
   consistente del evento. La fecha de localización registrada no implica que
   la persona haya sido localizada con vida.
5. Una clasificación a 30 días solo es válida si se conoce el estado al corte y
   cada caso tuvo 30 días completos de seguimiento.
6. Los motivos y estados finales pueden ser información posterior al evento;
   no deben usarse como predictores históricos sin reconstruir cuándo se conocían.
7. Las asociaciones no demuestran causalidad ni discriminación.
8. No utilizar el modelo para reducir la prioridad de búsqueda de personas.

Salidas guardadas en: {CARPETA_SALIDAS}
"""
    (CARPETA_SALIDAS / "LEEME_LIMITACIONES.txt").write_text(
        texto.strip(), encoding="utf-8"
    )


def main():
    crear_directorios()
    base = cargar_base()
    print(f"Base cargada: {base.shape[0]:,} filas x {base.shape[1]} columnas")
    resumen_calidad(base)
    datos = preparar_base_modelado(base)

    analisis_descriptivo(datos)
    comparar_tiempos_por_grupo(datos)
    pronostico_conteos(datos)
    ajustar_supervivencia(datos)
    ajustar_clasificacion_30d(datos)
    generar_dashboard_interactivo()
    escribir_leeme(base)

    print("\nProceso terminado.")
    print(f"Revisa los resultados en: {CARPETA_SALIDAS}")
    print("Lee primero LEEME_LIMITACIONES.txt y 00_resumen_calidad.csv.")


if __name__ == "__main__":
    main()
