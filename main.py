# main.py
from docxtpl import DocxTemplate
from datetime import datetime, date
from num2words import num2words
import os

# === Rutas seguras ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLA = os.path.join(
    BASE_DIR, "plantillas", "PERMISO_DOCTOR_ALFREDO_ACTUALIZADO.docx"
)
SALIDA_DOCX = os.path.join(BASE_DIR, "Permiso_Viaje_Generado.docx")

# === Utilidades ===
MESES = {
    1: "ENERO",
    2: "FEBRERO",
    3: "MARZO",
    4: "ABRIL",
    5: "MAYO",
    6: "JUNIO",
    7: "JULIO",
    8: "AGOSTO",
    9: "SEPTIEMBRE",
    10: "OCTUBRE",
    11: "NOVIEMBRE",
    12: "DICIEMBRE",
}


def fecha_iso_a_letras(fecha_iso: str) -> str:
    if not fecha_iso:
        return ""
    dt = datetime.strptime(fecha_iso, "%Y-%m-%d").date()
    return f"{dt.day:02d} DE {MESES[dt.month]} DEL {dt.year}"


def calcular_edad(fecha_nac_iso: str, hoy: date | None = None) -> int:
    if not fecha_nac_iso:
        return 0
    d = datetime.strptime(fecha_nac_iso, "%Y-%m-%d").date()
    hoy = hoy or date.today()
    return hoy.year - d.year - ((hoy.month, hoy.day) < (d.month, d.day))


def edad_en_letras(n: int) -> str:
    return num2words(n, lang="es").upper()


def hoy_en_letras(f: date | None = None):
    f = f or date.today()
    return {
        "DIA_EN_LETRAS": num2words(f.day, lang="es").upper(),  # OCHO
        "MES_EN_LETRAS": MESES[f.month],  # OCTUBRE
        "ANIO_EN_LETRAS": num2words(f.year, lang="es").upper(),  # DOS MIL VEINTICINCO
    }


def genero_menor_vars(sexo_menor: str):
    s = (sexo_menor or "").upper()
    if s == "F":
        return {
            "ART_MENOR": "LA",
            "MENOR_TX": "MENOR",
            "SOLO_A": "SOLA",
            "REC_TX": "RECEPCIONADA",
        }
    return {
        "ART_MENOR": "EL",
        "MENOR_TX": "MENOR",
        "SOLO_A": "SOLO",
        "REC_TX": "RECEPCIONADO",
    }


def viaje_vars(
    fecha_salida_iso: str | None, fecha_retorno_iso: str | None, vias: list[str] | None
):
    es_ida_y_vuelta = False
    via_tx = ""
    if fecha_salida_iso and fecha_retorno_iso:
        fs = datetime.strptime(fecha_salida_iso, "%Y-%m-%d").date()
        fr = datetime.strptime(fecha_retorno_iso, "%Y-%m-%d").date()
        es_ida_y_vuelta = fr >= fs
    if vias:
        via_tx = " Y/O ".join(vias).upper()
    return {"ES_IDA_Y_VUELTA": es_ida_y_vuelta, "VIA_TX": via_tx}


def concordancias_plural(acomp_count: int):
    return {
        "POSESIVO": "SUS" if acomp_count >= 2 else "SU",
        "SUJ_PL": "ES" if acomp_count >= 2 else "",  # QUIEN/QUIENES
        "VERB_PL": "ÁN" if acomp_count >= 2 else "",  # SERÁ/SERÁN
        "SUF_PL": "S" if acomp_count >= 2 else "",  # RESPONSABLE/RESPONSABLES
        "CONJ": "Y",
    }


def preparar_firmas(ctx: dict) -> dict:
    """Reglas: internacional = firman ambos; nacional = firma un padre."""
    tipo = (ctx.get("TIPO_VIAJE") or "").upper()

    if tipo == "INTERNACIONAL":
        return ctx  # La plantilla usa PADRE_* y MADRE_* directamente

    # NACIONAL: un solo firmante (PADRE/MADRE)
    firmante = (ctx.get("QUIEN_FIRMA") or "").upper()
    if firmante == "PADRE" and ctx.get("PADRE_NOMBRE") and ctx.get("PADRE_DNI"):
        ctx["FIRMA_NOMBRE"] = ctx["PADRE_NOMBRE"]
        ctx["FIRMA_DNI"] = ctx["PADRE_DNI"]
    elif firmante == "MADRE" and ctx.get("MADRE_NOMBRE") and ctx.get("MADRE_DNI"):
        ctx["FIRMA_NOMBRE"] = ctx["MADRE_NOMBRE"]
        ctx["FIRMA_DNI"] = ctx["MADRE_DNI"]
    else:
        # fallback por si no eligieron: usa acompañante o el primero disponible
        acomp = (ctx.get("ACOMPANANTE") or "").upper()
        if acomp == "MADRE" and ctx.get("MADRE_NOMBRE") and ctx.get("MADRE_DNI"):
            ctx["FIRMA_NOMBRE"] = ctx["MADRE_NOMBRE"]
            ctx["FIRMA_DNI"] = ctx["MADRE_DNI"]
        elif acomp == "PADRE" and ctx.get("PADRE_NOMBRE") and ctx.get("PADRE_DNI"):
            ctx["FIRMA_NOMBRE"] = ctx["PADRE_NOMBRE"]
            ctx["FIRMA_DNI"] = ctx["PADRE_DNI"]
        else:
            if ctx.get("PADRE_NOMBRE") and ctx.get("PADRE_DNI"):
                ctx["FIRMA_NOMBRE"] = ctx["PADRE_NOMBRE"]
                ctx["FIRMA_DNI"] = ctx["PADRE_DNI"]
            elif ctx.get("MADRE_NOMBRE") and ctx.get("MADRE_DNI"):
                ctx["FIRMA_NOMBRE"] = ctx["MADRE_NOMBRE"]
                ctx["FIRMA_DNI"] = ctx["MADRE_DNI"]
    return ctx


if __name__ == "__main__":
    # ===== Datos de ejemplo (cámbialos o usa formulario.py) =====
    MENOR_FECHA_NAC = "2010-09-14"
    FECHA_SALIDA = "2025-12-10"
    FECHA_RETORNO = "2025-12-20"  # "" si es solo ida
    edad_num = calcular_edad(MENOR_FECHA_NAC)

    ctx = {
        # Cabecera
        "CIUDAD": "CHICLAYO",
        "NOTARIO_NOMBRE": "DR. ALFREDO RIVERA GARCÍA",
        # Comparecientes (padres)
        "PADRE_NOMBRE": "ERLAND PAUL SÁNCHEZ DÍAZ",
        "PADRE_DNI": "03700891",
        "PADRE_ESTADO_CIVIL": "CASADO",
        "PADRE_DIRECCION": "CALLE LA PINTA N° 176",
        "PADRE_DISTRITO": "LA VICTORIA",
        "PADRE_PROVINCIA": "CHICLAYO",
        "PADRE_DEPARTAMENTO": "LAMBAYEQUE",
        "MADRE_NOMBRE": "KATYA MARIELA MERA VILLASÍS",
        "MADRE_DNI": "40443151",
        "MADRE_ESTADO_CIVIL": "CASADA",
        "MADRE_DIRECCION": "CALLE LA PINTA N° 176",
        "MADRE_DISTRITO": "LA VICTORIA",
        "MADRE_PROVINCIA": "CHICLAYO",
        "MADRE_DEPARTAMENTO": "LAMBAYEQUE",
        # Menor
        "MENOR_NOMBRE": "ARIANA SÁNCHEZ MERA",
        "MENOR_DNI": "78234154",
        "MENOR_EDAD_LETRAS": edad_en_letras(edad_num),
        "MENOR_EDAD_NUMERO": edad_num,
        "SEXO_MENOR": "F",
        # Viaje
        "TIPO_VIAJE": "INTERNACIONAL",  # o 'NACIONAL'
        "ORIGEN": "CHICLAYO",
        "DESTINO": "LIMA",
        "VIAS": ["AÉREA"],  # ["TERRESTRE"] o ambas
        "EMPRESA": "LATAM AIRLINES PERU",
        "VIAJA_SOLO": False,
        "FECHA_SALIDA": FECHA_SALIDA,
        "FECHA_RETORNO": FECHA_RETORNO,
        "FECHA_SALIDA_TX": fecha_iso_a_letras(FECHA_SALIDA) if FECHA_SALIDA else "",
        "FECHA_RETORNO_TX": fecha_iso_a_letras(FECHA_RETORNO) if FECHA_RETORNO else "",
        # Observaciones / Acompañantes
        "ACOMPANANTE": "AMBOS",  # 'MADRE'|'PADRE'|'AMBOS'|'TERCERO'|'SOLO'
        "ROL_ACOMPANANTE": "PADRES",  # Texto que sale en OBSERVACIONES
        "ACOMP1_NOMBRE": "ERLAND PAUL SÁNCHEZ DÍAZ",
        "ACOMP1_DNI": "03700891",
        "ACOMP2_NOMBRE": "KATYA MARIELA MERA VILLASÍS",
        "ACOMP2_DNI": "40443151",
        "ACOMP_COUNT": 2,
        "PERSONA_RECEPCION": "",
        "DNI_PERSONA_RECEPCION": "",
        # Motivo / evento
        "MOTIVO_VIAJE": "CONGRESO ESCOLAR CENIT",
        "CIUDAD_EVENTO": "LIMA",
        "FECHA_EVENTO": "",
        "ORGANIZADOR": "",
        # Cabecera/correlativo (dummy)
        "ANIO": date.today().year,
        "CORRELATIVO": 1,
        # Para NACIONAL (si lo usas)
        "QUIEN_FIRMA": "MADRE",
    }

    # Concordancias y fechas en letras para cabecera
    ctx.update(hoy_en_letras())
    ctx.update(genero_menor_vars(ctx.get("SEXO_MENOR")))
    ctx.update(
        viaje_vars(ctx.get("FECHA_SALIDA"), ctx.get("FECHA_RETORNO"), ctx.get("VIAS"))
    )
    ctx.update(concordancias_plural(ctx.get("ACOMP_COUNT", 0)))

    # Render
    if not os.path.exists(PLANTILLA):
        raise FileNotFoundError(f"No se encontró la plantilla: {PLANTILLA}")
    doc = DocxTemplate(PLANTILLA)
    doc.render(ctx)
    doc.save(SALIDA_DOCX)
    print(f"✅ Documento generado: {os.path.abspath(SALIDA_DOCX)}")
