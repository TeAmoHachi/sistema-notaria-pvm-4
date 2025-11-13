# formulario.py
from docxtpl import DocxTemplate
from datetime import datetime, date
from num2words import num2words
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLANTILLA = os.path.join(
    BASE_DIR, "plantillas", "PERMISO_DOCTOR_ALFREDO_ACTUALIZADO.docx"
)
SALIDA_DOCX = os.path.join(BASE_DIR, "Permiso_Viaje_Generado.docx")

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
        "DIA_EN_LETRAS": num2words(f.day, lang="es").upper(),
        "MES_EN_LETRAS": MESES[f.month],
        "ANIO_EN_LETRAS": num2words(f.year, lang="es").upper(),
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
        "SUJ_PL": "ES" if acomp_count >= 2 else "",
        "VERB_PL": "ÁN" if acomp_count >= 2 else "",
        "SUF_PL": "S" if acomp_count >= 2 else "",
        "CONJ": "Y",
    }


def preparar_firmas(ctx: dict) -> dict:
    tipo = (ctx.get("TIPO_VIAJE") or "").upper()
    if tipo == "INTERNACIONAL":
        return ctx
    firmante = (ctx.get("QUIEN_FIRMA") or "").upper()
    if firmante == "PADRE" and ctx.get("PADRE_NOMBRE") and ctx.get("PADRE_DNI"):
        ctx["FIRMA_NOMBRE"] = ctx["PADRE_NOMBRE"]
        ctx["FIRMA_DNI"] = ctx["PADRE_DNI"]
    elif firmante == "MADRE" and ctx.get("MADRE_NOMBRE") and ctx.get("MADRE_DNI"):
        ctx["FIRMA_NOMBRE"] = ctx["MADRE_NOMBRE"]
        ctx["FIRMA_DNI"] = ctx["MADRE_DNI"]
    else:
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


# ==== Inputs de consola ====
def input_opcion(msg, opciones):
    print(msg, f"({', '.join(opciones)})")
    while True:
        r = input("> ").strip().upper()
        if r in [o.upper() for o in opciones]:
            return r
        print("Opción inválida, intenta otra vez.")


def input_fecha(msg, obligatorio=True):
    print(msg, "(formato YYYY-MM-DD)")
    while True:
        r = input("> ").strip()
        if not r and not obligatorio:
            return ""
        try:
            datetime.strptime(r, "%Y-%m-%d")
            return r
        except ValueError:
            print("Fecha inválida. Ejemplo: 2025-12-10")


def input_texto(msg, obligatorio=True):
    print(msg)
    while True:
        r = input("> ").strip()
        if r or not obligatorio:
            return r
        print("Este campo es obligatorio.")


def input_si_no(msg):
    print(msg, "(S/N)")
    while True:
        r = input("> ").strip().upper()
        if r in ("S", "N"):
            return r == "S"
        print("Responde S o N.")


def run_formulario():
    print("=== IA Notarial – Permiso de Viaje de Menores ===")

    # Cabecera
    ciudad = input_texto("Ciudad (para cabecera):")
    notario = input_texto("Nombre del NOTARIO:")
    tipo_viaje = input_opcion("Tipo de viaje", ["NACIONAL", "INTERNACIONAL"])

    # Padres
    padre_nombre = input_texto("Nombre del PADRE (tal cual DNI):")
    padre_dni = input_texto("DNI del PADRE (respetar ceros):")
    padre_ec = input_texto("Estado civil del PADRE (SOLTERO/CASADO/etc.):")
    padre_dir = input_texto("Dirección del PADRE:")
    padre_dist = input_texto("Distrito del PADRE:")
    padre_prov = input_texto("Provincia del PADRE:")
    padre_dep = input_texto("Departamento del PADRE:")

    madre_nombre = input_texto("Nombre de la MADRE (tal cual DNI):")
    madre_dni = input_texto("DNI de la MADRE (respetar ceros):")
    madre_ec = input_texto("Estado civil de la MADRE (SOLTERA/CASADA/etc.):")
    madre_dir = input_texto("Dirección de la MADRE:")
    madre_dist = input_texto("Distrito de la MADRE:")
    madre_prov = input_texto("Provincia de la MADRE:")
    madre_dep = input_texto("Departamento de la MADRE:")

    # Menor
    menor_nombre = input_texto("Nombre del MENOR (tal cual DNI):")
    menor_dni = input_texto("DNI del MENOR:")
    sexo_menor = input_opcion("Sexo del menor", ["M", "F"])
    fnac = input_fecha("Fecha de nacimiento del menor")
    edad_num = calcular_edad(fnac)

    # Viaje
    origen = input_texto("Ciudad de ORIGEN:")
    destino = input_texto("Ciudad de DESTINO:")
    vias = []
    if input_si_no("¿Viaje TERRESTRE?"):
        vias.append("TERRESTRE")
    if input_si_no("¿Viaje AÉREO?"):
        vias.append("AÉREA")
    empresa = input_texto(
        "Empresa (opcional, ej. LATAM AIRLINES PERU):", obligatorio=False
    )

    fecha_salida = input_fecha("Fecha de SALIDA")
    tiene_retorno = input_si_no("¿Tiene fecha de RETORNO?")
    fecha_retorno = (
        input_fecha("Fecha de RETORNO", obligatorio=False) if tiene_retorno else ""
    )

    # Acompañante
    acomp = input_opcion(
        "¿Quién acompaña? (si viaja solo, elige 'SOLO')",
        ["PADRE", "MADRE", "AMBOS", "TERCERO", "SOLO"],
    )
    rol_acompanante = ""
    acomp1_nombre = ""
    acomp1_dni = ""
    acomp_count = 0
    viaja_solo = False

    if acomp == "SOLO":
        viaja_solo = True
    elif acomp == "PADRE":
        acomp_count = 1
        rol_acompanante = "PADRE"
        acomp1_nombre = padre_nombre
        acomp1_dni = padre_dni
    elif acomp == "MADRE":
        acomp_count = 1
        rol_acompanante = "MADRE"
        acomp1_nombre = madre_nombre
        acomp1_dni = madre_dni
    elif acomp == "AMBOS":
        acomp_count = 2
        rol_acompanante = "PADRES"
    elif acomp == "TERCERO":
        acomp_count = 1
        rol_acompanante = input_texto(
            "Parentesco del tercero (TUTOR/TUTORA/TÍA/TÍO/ABUELO/ABUELA/HERMANO/HERMANA):"
        )
        acomp1_nombre = input_texto("Nombre del tercero:")
        acomp1_dni = input_texto("DNI del tercero:")

    # Motivo / evento
    motivo = input_texto("Motivo del viaje (ej. Congreso Escolar CENIT):")
    ciudad_evento = input_texto("Ciudad del evento (opcional):", obligatorio=False)
    fecha_evento = input_texto(
        "Fecha del evento (opcional, ej. 10/12/2025):", obligatorio=False
    )
    organizador = input_texto("Organizador (opcional):", obligatorio=False)

    # Firma para NACIONAL
    quien_firma = ""
    if tipo_viaje == "NACIONAL":
        quien_firma = input_opcion(
            "¿Quién firmará el permiso? (PADRE/MADRE)", ["PADRE", "MADRE"]
        )

    # Contexto
    ctx = {
        # Cabecera
        "CIUDAD": ciudad.upper(),
        "NOTARIO_NOMBRE": notario.upper(),
        **hoy_en_letras(),
        # Comparecientes
        "PADRE_NOMBRE": padre_nombre.upper(),
        "PADRE_DNI": padre_dni,
        "PADRE_ESTADO_CIVIL": padre_ec.upper(),
        "PADRE_DIRECCION": padre_dir.upper(),
        "PADRE_DISTRITO": padre_dist.upper(),
        "PADRE_PROVINCIA": padre_prov.upper(),
        "PADRE_DEPARTAMENTO": padre_dep.upper(),
        "MADRE_NOMBRE": madre_nombre.upper(),
        "MADRE_DNI": madre_dni,
        "MADRE_ESTADO_CIVIL": madre_ec.upper(),
        "MADRE_DIRECCION": madre_dir.upper(),
        "MADRE_DISTRITO": madre_dist.upper(),
        "MADRE_PROVINCIA": madre_prov.upper(),
        "MADRE_DEPARTAMENTO": madre_dep.upper(),
        # Menor
        "MENOR_NOMBRE": menor_nombre.upper(),
        "MENOR_DNI": menor_dni,
        "MENOR_EDAD_LETRAS": edad_en_letras(edad_num),
        "MENOR_EDAD_NUMERO": edad_num,
        "SEXO_MENOR": sexo_menor,
        # Viaje
        "TIPO_VIAJE": tipo_viaje,
        "ORIGEN": origen.upper(),
        "DESTINO": destino.upper(),
        "VIAS": [v.upper() for v in vias],
        "EMPRESA": empresa.upper() if empresa else "",
        "VIAJA_SOLO": viaja_solo,
        "FECHA_SALIDA": fecha_salida,
        "FECHA_RETORNO": fecha_retorno,
        "FECHA_SALIDA_TX": fecha_iso_a_letras(fecha_salida) if fecha_salida else "",
        "FECHA_RETORNO_TX": fecha_iso_a_letras(fecha_retorno) if fecha_retorno else "",
        # Observaciones / Acompañantes
        "ACOMPANANTE": acomp,  # 'MADRE'|'PADRE'|'AMBOS'|'TERCERO'|'SOLO'
        "ROL_ACOMPANANTE": (rol_acompanante or "").upper(),
        "ACOMP1_NOMBRE": acomp1_nombre.upper(),
        "ACOMP1_DNI": acomp1_dni,
        "ACOMP_COUNT": (
            2
            if acomp == "AMBOS"
            else (1 if acomp in ["PADRE", "MADRE", "TERCERO"] else 0)
        ),
        "PERSONA_RECEPCION": "",
        "DNI_PERSONA_RECEPCION": "",
        # Motivo / evento
        "MOTIVO_VIAJE": motivo,
        "CIUDAD_EVENTO": ciudad_evento.upper() if ciudad_evento else "",
        "FECHA_EVENTO": fecha_evento,
        "ORGANIZADOR": organizador.upper() if organizador else "",
        # Correlativo dummy
        "ANIO": date.today().year,
        "CORRELATIVO": 1,
        "QUIEN_FIRMA": quien_firma,
    }

    # Concordancias, género, viaje y firmas
    ctx.update(concordancias_plural(ctx.get("ACOMP_COUNT", 0)))
    ctx.update(genero_menor_vars(ctx.get("SEXO_MENOR")))
    ctx.update(
        viaje_vars(ctx.get("FECHA_SALIDA"), ctx.get("FECHA_RETORNO"), ctx.get("VIAS"))
    )
    ctx = preparar_firmas(ctx)

    # Validaciones clave
    if tipo_viaje == "INTERNACIONAL":
        faltan = [
            k
            for k in ["PADRE_NOMBRE", "PADRE_DNI", "MADRE_NOMBRE", "MADRE_DNI"]
            if not ctx.get(k)
        ]
        if faltan:
            print("❌ Internacional requiere ambos padres con DNI. Faltan:", faltan)
            return
    else:
        if not ctx.get("FIRMA_NOMBRE") or not ctx.get("FIRMA_DNI"):
            print("❌ Nacional requiere un firmante (PADRE o MADRE) con DNI.")
            return

    if not os.path.exists(PLANTILLA):
        print("❌ No se encontró la plantilla:", PLANTILLA)
        return

    # Render
    doc = DocxTemplate(PLANTILLA)
    doc.render(ctx)
    doc.save(SALIDA_DOCX)
    print(f"✅ Documento generado: {os.path.abspath(SALIDA_DOCX)}")


if __name__ == "__main__":
    run_formulario()
