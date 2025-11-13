# app.py
import html
import requests
from typing import Optional, Dict, List
import os
from dotenv import load_dotenv
import sqlite3
import math
from io import BytesIO
from datetime import datetime, date

import base64
import time
import threading
import streamlit as st
import pandas as pd
import json
from docxtpl import DocxTemplate
from num2words import num2words
from PIL import Image
from pathlib import Path
import shutil

from packages.attr.validators import disabled

# 🆕 Cargar variables de entorno desde .env
load_dotenv()

# ============================================================
# CONFIGURACIÓN INICIAL (DEBE IR PRIMERO)
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import logging
import base64

# Crear carpeta de logs si no existe
logs_dir = os.path.join(BASE_DIR, 'logs')
os.makedirs(logs_dir, exist_ok=True)

# Configurar logging
logging.basicConfig(
    filename=os.path.join(logs_dir, 'app.log'),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== 🔐 DESCIFRAR TOKEN RENIEC ==========
raw_token = os.getenv("RENIEC_TOKEN", "")

if not raw_token:
    RENIEC_TOKEN = ""
    logger.warning("⚠️ RENIEC_TOKEN no configurado - Consultas API limitadas")
else:
    try:
        RENIEC_TOKEN = base64.b64decode(raw_token).decode()
        logger.info("✅ Token RENIEC cargado correctamente (cifrado)")
    except Exception:
        RENIEC_TOKEN = raw_token
        logger.warning("⚠️ Token RENIEC en texto plano - considera cifrarlo por seguridad")

# ==================== FUNCIONES DE API GRATUITAS ====================

def consultar_dni_reniec(dni: str) -> Optional[Dict]:
    """
    Consulta DNI en APIs gratuitas de RENIEC (prueba múltiples proveedores)
    Retorna: {"nombres": "JUAN", "apellidoPaterno": "PEREZ", "apellidoMaterno": "GARCIA"}
    """
    if not dni or len(dni) != 8:
        return None
    
    # Lista de APIs para probar (en orden de prioridad)
    apis = [
        # API 1: dniruc.apisperu.com
        {
            "url": f"https://dniruc.apisperu.com/api/v1/dni/{dni}",
            "headers": {},
            "parser": lambda data: {
                "nombres": data.get("nombres", ""),
                "apellidoPaterno": data.get("apellidoPaterno", ""),
                "apellidoMaterno": data.get("apellidoMaterno", ""),
                "nombre_completo": f"{data.get('nombres', '')} {data.get('apellidoPaterno', '')} {data.get('apellidoMaterno', '')}"
            } if data.get("success") else None
        },
        # API 2: api.decolecta.com (requiere token gratis)
        {
            "url": f"https://api.decolecta.com/v1/reniec/dni?numero={dni}",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {RENIEC_TOKEN}"  # 🔐 Ahora usa la variable de entorno
            },
            "parser": lambda data: {
                "nombres": data.get("first_name", ""),
                "apellidoPaterno": data.get("first_last_name", ""),
                "apellidoMaterno": data.get("second_last_name", ""),
                "nombre_completo": data.get("full_name", "")
            } if data.get("full_name") else None
        },
        # API 3: apiperu.dev (sin token)
        {
            "url": f"https://apiperu.dev/api/dni/{dni}",
            "headers": {},
            "parser": lambda data: {
                "nombres": data.get("data", {}).get("nombres", ""),
                "apellidoPaterno": data.get("data", {}).get("apellido_paterno", ""),
                "apellidoMaterno": data.get("data", {}).get("apellido_materno", ""),
                "nombre_completo": f"{data.get('data', {}).get('nombres', '')} {data.get('data', {}).get('apellido_paterno', '')} {data.get('data', {}).get('apellido_materno', '')}"
            } if data.get("success") else None
        }
    ]
    
    # Probar cada API en orden
    for i, api_config in enumerate(apis, 1):
        try:
            response = requests.get(
                api_config["url"], 
                headers=api_config["headers"],
                timeout=8
            )
            
            if response.status_code == 200:
                data = response.json()
                result = api_config["parser"](data)
                
                if result and result.get("nombre_completo", "").strip():
                    # Éxito: retorna los datos
                    return result
                    
        except Exception as e:
            # Si falla esta API, continúa con la siguiente
            continue
    
    # Si todas las APIs fallaron, retorna None
    return None

def obtener_departamentos() -> List[str]:
    """Obtiene lista de departamentos del Perú"""
    try:
        url = "https://api.apis.net.pe/v1/ubigeo?nivel=departamento"
        
        print(f"🔍 DEBUG: Consultando API UBIGEO: {url}")
        
        response = requests.get(url, timeout=15)
        
        print(f"🔍 DEBUG: Status code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            print(f"🔍 DEBUG: Tipo de respuesta: {type(data)}")
            
            # 🔥 CASO ESPECIAL: Dict con códigos como keys
            if isinstance(data, dict):
                departamentos = []
                
                # Iterar sobre cada código de departamento
                for codigo, info in data.items():
                    if isinstance(info, dict) and "nombre" in info:
                        nombre = info["nombre"].upper()
                        departamentos.append(nombre)
                        print(f"  ✓ Departamento {codigo}: {nombre}")
                
                print(f"✅ DEBUG: Total departamentos extraídos: {len(departamentos)}")
                print(f"✅ DEBUG: Lista: {sorted(departamentos)[:5]}...")
                
                return sorted(departamentos)
            
            # Fallback: si fuera lista (por si cambian la API)
            elif isinstance(data, list):
                departamentos = []
                for item in data:
                    if isinstance(item, dict):
                        nombre = (
                            item.get("nombre_ubigeo") or 
                            item.get("nombre") or 
                            item.get("departamento")
                        )
                        if nombre:
                            departamentos.append(nombre.upper())
                
                return sorted(departamentos)
            
            else:
                print(f"❌ DEBUG: Formato inesperado: {type(data)}")
                return []
        else:
            print(f"❌ DEBUG: API devolvió código {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ DEBUG: Error consultando UBIGEO: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return []

def obtener_provincias(departamento: str) -> List[str]:
    """Obtiene provincias de un departamento"""
    try:
        url = f"https://api.apis.net.pe/v1/ubigeo?nivel=provincia&departamento={departamento}"
        
        print(f"🔍 DEBUG: Consultando provincias de {departamento}")
        
        response = requests.get(url, timeout=15)
        
        print(f"🔍 DEBUG: Status code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # 🔥 CASO 1: Dict con códigos de departamento como primer nivel
            if isinstance(data, dict):
                provincias = []
                
                # Buscar el departamento en el dict
                for dep_codigo, dep_info in data.items():
                    if isinstance(dep_info, dict):
                        # Verificar si el nombre coincide (insensible a mayúsculas)
                        dep_nombre = dep_info.get("nombre", "").upper()
                        
                        if dep_nombre == departamento.upper():
                            # Encontramos el departamento, extraer provincias
                            provincias_dict = dep_info.get("provincias", {})
                            
                            if isinstance(provincias_dict, dict):
                                for prov_codigo, prov_info in provincias_dict.items():
                                    if isinstance(prov_info, dict):
                                        nombre = prov_info.get("nombre", "").upper()
                                        if nombre:
                                            provincias.append(nombre)
                                    elif isinstance(prov_info, str):
                                        provincias.append(prov_info.upper())
                            
                            break
                
                print(f"✅ DEBUG: {len(provincias)} provincias encontradas")
                return sorted(provincias)
            
            # Fallback: si fuera lista
            elif isinstance(data, list):
                provincias = []
                for item in data:
                    if isinstance(item, dict):
                        nombre = (
                            item.get("nombre_ubigeo") or 
                            item.get("nombre") or 
                            item.get("provincia")
                        )
                        if nombre:
                            provincias.append(nombre.upper())
                return sorted(provincias)
            
            return []
        
        return []
    except Exception as e:
        print(f"❌ DEBUG: Error consultando provincias: {e}")
        import traceback
        traceback.print_exc()
        return []


def obtener_distritos(departamento: str, provincia: str) -> List[str]:
    """Obtiene distritos de una provincia"""
    try:
        url = f"https://api.apis.net.pe/v1/ubigeo?nivel=distrito&departamento={departamento}&provincia={provincia}"
        
        print(f"🔍 DEBUG: Consultando distritos de {provincia}, {departamento}")
        
        response = requests.get(url, timeout=10)
        
        print(f"🔍 DEBUG: Status code: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # 🔥 CASO 1: Dict anidado (dep -> prov -> distritos)
            if isinstance(data, dict):
                distritos = []
                
                # Buscar departamento
                for dep_codigo, dep_info in data.items():
                    if isinstance(dep_info, dict):
                        dep_nombre = dep_info.get("nombre", "").upper()
                        
                        if dep_nombre == departamento.upper():
                            # Buscar provincia dentro del departamento
                            provincias_dict = dep_info.get("provincias", {})
                            
                            if isinstance(provincias_dict, dict):
                                for prov_codigo, prov_info in provincias_dict.items():
                                    if isinstance(prov_info, dict):
                                        prov_nombre = prov_info.get("nombre", "").upper()
                                        
                                        if prov_nombre == provincia.upper():
                                            # Encontramos la provincia, extraer distritos
                                            distritos_dict = prov_info.get("distritos", {})
                                            
                                            if isinstance(distritos_dict, dict):
                                                for dist_codigo, dist_nombre in distritos_dict.items():
                                                    if isinstance(dist_nombre, str):
                                                        distritos.append(dist_nombre.upper())
                                                    elif isinstance(dist_nombre, dict):
                                                        nombre = dist_nombre.get("nombre", "").upper()
                                                        if nombre:
                                                            distritos.append(nombre)
                                            
                                            break
                            break
                
                print(f"✅ DEBUG: {len(distritos)} distritos encontrados")
                return sorted(distritos)
            
            # Fallback: si fuera lista
            elif isinstance(data, list):
                distritos = []
                for item in data:
                    if isinstance(item, dict):
                        nombre = (
                            item.get("nombre_ubigeo") or 
                            item.get("nombre") or 
                            item.get("distrito")
                        )
                        if nombre:
                            distritos.append(nombre.upper())
                return sorted(distritos)
            
            return []
        
        return []
    except Exception as e:
        print(f"❌ DEBUG: Error consultando distritos: {e}")
        import traceback
        traceback.print_exc()
        return []

# ====================================================================

def inject_css():
    css_path = Path(__file__).parent / "assets" / "theme.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

    # 🚨 SOLUCIÓN JAVASCRIPT DE EMERGENCIA
    st.markdown("""
    <script>
    function aplicarCeleste() {
        const padre = document.querySelector('input[aria-label="DNI del Padre"]');
        const madre = document.querySelector('input[aria-label="DNI de la Madre"]');
        const menor = document.querySelector('input[aria-label="Doc. MENOR"]');
        
        [padre, madre, menor].forEach(input => {
            if (input) {
                input.style.setProperty('background-color', '#c9e7f5', 'important');
                input.style.setProperty('color', '#002c44', 'important');
                input.style.setProperty('border', '2px solid #9edaff', 'important');
            }
        });
    }
    
    setTimeout(aplicarCeleste, 500);
    setTimeout(aplicarCeleste, 1500);
    
    const observer = new MutationObserver(aplicarCeleste);
    observer.observe(document.body, { childList: true, subtree: true });
    </script>
    """, unsafe_allow_html=True)

inject_css()

# --- PRELOADER ROBUSTO (solo la primera vez en la sesión) ---

if "_preloader_shown" not in st.session_state:
    st.session_state._preloader_shown = False

if not st.session_state._preloader_shown:
    # Opcional: usa tu logo si existe
    logo_path = Path(__file__).parent / "assets" / "logo.png"
    has_logo = logo_path.exists()

    preloader_html = f"""
    <style>
    #preloader {{
      position: fixed;
      inset: 0;
      background: #0e0e0e;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      z-index: 99999;
    }}
    .loader {{
      border: 6px solid #2e2e2e;
      border-top: 6px solid #d4af37;
      border-radius: 50%;
      width: 70px;
      height: 70px;
      animation: spin 1.2s linear infinite;
      margin-bottom: 16px;
    }}
    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}
    #preloader-text {{
      color: #f1c550;
      font-size: 16px;
      letter-spacing: 1px;
      font-family: 'Georgia', serif;
      opacity: 0.9;
      margin-top: 6px;
    }}
    .logo-wrap {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 12px;
      margin-bottom: 18px;
      filter: drop-shadow(0 0 12px rgba(212,175,55,0.25));
    }}
    .logo-wrap img {{
      width: 64px;
      height: 64px;
      object-fit: contain;
    }}
    .brand {{
      color: #e8d9a8;
      font-weight: 600;
      font-size: 18px;
      letter-spacing: 0.5px;
      font-family: 'Georgia', serif;
      text-transform: uppercase;
    }}
    @media (prefers-reduced-motion: reduce) {{
      .loader {{ animation: none; }}
    }}
    </style>

    <div id="preloader">
      {"<div class='logo-wrap'><img src='data:image/png;base64," + __import__("base64").b64encode(logo_path.read_bytes()).decode() + "' /><div class='brand'>Notaría Santa Cruz</div></div>" if has_logo else ""}
      <div class="loader"></div>
      <div id="preloader-text">Espera un momento, cargando…</div>
    </div>
    """

    holder = st.empty()
    holder.markdown(preloader_html, unsafe_allow_html=True)

    # Mantenlo visible un momento para que se note
    time.sleep(1.6)

    # Oculta el preloader quitando el html
    holder.empty()

    # Para que no reaparezca en cada rerun
    st.session_state._preloader_shown = True

def cargar_css():
    css_path = Path(BASE_DIR) / "style.css"
    if css_path.exists():
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


# ============ Config ============
PLANTILLAS_DIR = os.path.join(BASE_DIR, "plantillas")
PLANTILLA_DEFAULT = os.path.join(PLANTILLAS_DIR, "PERMISO_DOCTOR_ALFREDO_ACTUALIZADO.docx")

MESES = {
    1:"ENERO", 2:"FEBRERO", 3:"MARZO", 4:"ABRIL", 5:"MAYO", 6:"JUNIO",
    7:"JULIO", 8:"AGOSTO", 9:"SEPTIEMBRE", 10:"OCTUBRE", 11:"NOVIEMBRE", 12:"DICIEMBRE"
}

# ========= Auth admin (simple por sesión) =========
# ========= Auth admin (simple por sesión) =========
ADMIN_USER = os.getenv("ADMIN_USER")
ADMIN_PASS = os.getenv("ADMIN_PASS")

# 🔒 VALIDACIÓN: Si no hay credenciales en .env, DETENER la app
if not ADMIN_USER or not ADMIN_PASS:
    st.error("⚠️ **ERROR CRÍTICO DE SEGURIDAD**")
    st.error("Las variables ADMIN_USER y ADMIN_PASS no están configuradas en el archivo .env")
    st.info("**Solución:**\n1. Crea/edita el archivo `.env` en la raíz del proyecto\n2. Agrega:\n```\nADMIN_USER=tu_usuario\nADMIN_PASS=tu_contraseña_segura\n```")
    st.stop()  # ← DETIENE la aplicación si faltan credenciales

def init_admin_session():
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False
    if "admin_user" not in st.session_state:
        st.session_state.admin_user = ""

def login_admin(username: str, password: str):
    if username.strip().upper() == ADMIN_USER.upper() and password == ADMIN_PASS:
        st.session_state.is_admin = True
        st.session_state.admin_user = username.strip().upper()
        st.success("✅ Sesión de administrador iniciada.")
    else:
        st.error("Usuario o contraseña incorrectos.")

def logout_admin():
    st.session_state.is_admin = False
    st.session_state.admin_user = ""
    st.info("Sesión finalizada.")

# ========= BD (SQLite) =========
DB_PATH = os.path.join(BASE_DIR, "permisos.db")
os.makedirs(BASE_DIR, exist_ok=True)

import threading
import sqlite3

DB_LOCK = threading.Lock()  # opcional, por si necesitas secciones críticas
_correlativo_lock = threading.Lock()  # ← 🆕 AGREGAR ESTA LÍNEA

def get_conn(timeout_sec: int = 10) -> sqlite3.Connection:
    """
    Abre conexión con PRAGMAs de concurrencia.
    Cada operación abre/cierra su propia conexión.
    """
    conn = sqlite3.connect(DB_PATH, timeout=timeout_sec, isolation_level=None)  # autocommit
    conn.execute("PRAGMA journal_mode=WAL;")   # lecturas y escrituras concurrentes
    conn.execute("PRAGMA synchronous=NORMAL;") # buen balance durabilidad/velocidad
    conn.execute("PRAGMA busy_timeout=5000;")  # espera 5s si hay bloqueo
    conn.execute("PRAGMA foreign_keys=ON;")    # por si usas FK ahora o después
    return conn

def init_db():
    """Crea la BD y tablas si no existen."""
    with get_conn(timeout_sec=10) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS correlativos (
            anio INTEGER NOT NULL PRIMARY KEY,
            numero INTEGER NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS permisos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anio INTEGER NOT NULL,
            numero INTEGER NOT NULL,
            nsc TEXT NOT NULL DEFAULT 'NSC',
            fecha_registro TEXT NOT NULL,

            ciudad TEXT,
            notario TEXT,

            -- Padres
            padre_nombre TEXT,
            padre_dni TEXT,
            padre_estado_civil TEXT,
            padre_direccion TEXT,
            padre_distrito TEXT,
            padre_provincia TEXT,
            padre_departamento TEXT,

            madre_nombre TEXT,
            madre_dni TEXT,
            madre_estado_civil TEXT,
            madre_direccion TEXT,
            madre_distrito TEXT,
            madre_provincia TEXT,
            madre_departamento TEXT,

            -- Menor
            menor_nombre TEXT,
            menor_dni TEXT,
            menor_fnac TEXT,          -- YYYY-MM-DD
            sexo_menor TEXT,          -- F | M

            -- Viaje
            tipo_viaje TEXT,          -- 'NACIONAL' | 'INTERNACIONAL'
            firma_quien TEXT,         -- 'PADRE' | 'MADRE' | 'AMBOS'
            origen TEXT,
            destino TEXT,
            vias TEXT,
            empresa TEXT,
            salida TEXT,              -- 'YYYY-MM-DD'
            retorno TEXT,             -- 'YYYY-MM-DD' o ''

            -- Acompañante
            acompanante TEXT,         -- PADRE/MADRE/AMBOS/TERCERO/SOLO
            tercero_nombre TEXT,
            tercero_dni TEXT,

            -- Motivo / evento
            motivo TEXT,
            ciudad_evento TEXT,
            fecha_evento TEXT,
            organizador TEXT,

            archivo_generado TEXT,

            -- control de cambios
            estado TEXT DEFAULT 'EMITIDO',
            updated_at TEXT,
            version INTEGER DEFAULT 1,

            -- anulación
            anulado_at TEXT,
            anulado_motivo TEXT,
            anulado_por TEXT,

            -- Documento y nacionalidad por persona
            padre_doc_tipo TEXT,      -- 'DNI' | 'PASAPORTE'
            padre_doc_num TEXT,
            padre_nacionalidad TEXT,

            madre_doc_tipo TEXT,      -- 'DNI' | 'PASAPORTE'
            madre_doc_num TEXT,
            madre_nacionalidad TEXT,

            menor_doc_tipo TEXT,      -- 'DNI' | 'PASAPORTE'
            menor_doc_num TEXT,
            menor_nacionalidad TEXT,

            UNIQUE(anio, numero)
        )
        """)
                # Agenda interna
        conn.execute("""
        CREATE TABLE IF NOT EXISTS agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            asunto TEXT NOT NULL,
            nota TEXT,
            vinculo_doc TEXT,   -- opcional: DNI/Pasaporte vinculado
            creado_por TEXT
        )
        """)
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agenda_vinculo_doc ON agenda(vinculo_doc)")
        except Exception:
            pass

            # Índices para búsquedas por documento (evita duplicados si ya existen)
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_padre_doc_num ON permisos(padre_doc_num)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_madre_doc_num ON permisos(madre_doc_num)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_menor_doc_num ON permisos(menor_doc_num)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_padre_dni ON permisos(padre_dni)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_madre_dni ON permisos(madre_dni)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_menor_dni ON permisos(menor_dni)")
        except Exception:
            pass
                # DNI / Pasaportes ocultos (no se precargan)
        conn.execute("""
        
        CREATE TABLE IF NOT EXISTS doc_ocultos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rol TEXT NOT NULL,            -- 'PADRE' | 'MADRE' | 'MENOR'
            doc_num TEXT NOT NULL,        -- DNI/Pasaporte
            motivo TEXT,
            creado_por TEXT,
            creado_at TEXT NOT NULL
        )
        """)
        try:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_ocultos_unique ON doc_ocultos(rol, doc_num)")
        except Exception:
            pass
        
def migrate_db():
    """Agrega columnas nuevas si aún no existen."""
    def add_if_missing(conn, name, type_sql, default_sql=""):
        cur = conn.execute("PRAGMA table_info(permisos)")
        cols = {r[1] for r in cur.fetchall()}
        if name not in cols:
            conn.execute(f"ALTER TABLE permisos ADD COLUMN {name} {type_sql} {default_sql}".strip())

    with get_conn() as conn:
        for c in [
            ("padre_nombre","TEXT"),("padre_dni","TEXT"),("padre_estado_civil","TEXT"),
            ("padre_direccion","TEXT"),("padre_distrito","TEXT"),("padre_provincia","TEXT"),
            ("padre_departamento","TEXT"),
            ("madre_nombre","TEXT"),("madre_dni","TEXT"),("madre_estado_civil","TEXT"),
            ("madre_direccion","TEXT"),("madre_distrito","TEXT"),("madre_provincia","TEXT"),
            ("madre_departamento","TEXT"),
            ("menor_fnac","TEXT"),("sexo_menor","TEXT"),
            ("ciudad_evento","TEXT"),("fecha_evento","TEXT"),("organizador","TEXT"),
            ("estado","TEXT","DEFAULT 'EMITIDO'"),("updated_at","TEXT"),
            ("version","INTEGER","DEFAULT 1"),
            ("anulado_at","TEXT"),("anulado_motivo","TEXT"),("anulado_por","TEXT"),
            ("padre_doc_tipo","TEXT"),("padre_doc_num","TEXT"),("padre_nacionalidad","TEXT"),
            ("madre_doc_tipo","TEXT"),("madre_doc_num","TEXT"),("madre_nacionalidad","TEXT"),
            ("menor_doc_tipo","TEXT"),("menor_doc_num","TEXT"),("menor_nacionalidad","TEXT"),
            ("hermanos_json","TEXT"),
            # 👇 NUEVO: flags y recepción múltiple
            ("viaja_solo","INTEGER","DEFAULT 0"),
            ("recibe_si","TEXT","DEFAULT 'NO'"),
            ("rec_nombre","TEXT"),
            ("rec_doc_tipo","TEXT"),
            ("rec_doc_num","TEXT"),
            ("rec_doc_pais","TEXT"),
            ("rec_list_json","TEXT"),
            ("recibe_si","TEXT"),           # "SI" / "NO"
            ("rec_nombre","TEXT"),          # nombre completo de quien recibe
            ("rec_doc_tipo","TEXT"),        # "DNI PERUANO" | "DNI EXTRANJERO" | "PASAPORTE"
            ("rec_doc_num","TEXT"),         # número de ese doc
            ("rec_doc_pais","TEXT"),        # p.ej. "DEL REINO DE ESPAÑA"
            ("rol_acompanante","TEXT"),
            ("acomp1_nombre","TEXT"),
            ("acomp1_dni","TEXT"),
            ("acomp_count","INTEGER","DEFAULT 0"),
            ("terceros_json", "TEXT"),

        ]:
            if len(c) == 2:
                add_if_missing(conn, c[0], c[1])
            else:
                add_if_missing(conn, c[0], c[1], c[2])
                
        conn.execute("""
            UPDATE permisos
            SET updated_at = COALESCE(updated_at, fecha_registro)
            WHERE updated_at IS NULL OR updated_at = ''          
         """)        
        conn.commit()

def get_next_correlativo(anio: int) -> int:
    """
    Obtiene el siguiente correlativo para un año dado.
    
    🔒 SEGURIDAD:
    - Usa threading.Lock para evitar race conditions
    - Valida que el año sea un entero válido (2000-2100)
    
    Returns:
        int: Número correlativo único para el año
    """
    # 🔒 VALIDACIÓN DE ENTRADA (previene SQL injection y bugs)
    if not isinstance(anio, int):
        raise ValueError(f"El año debe ser un entero, recibido: {type(anio).__name__}")
    
    if not (2000 <= anio <= 2100):
        raise ValueError(f"Año fuera de rango válido (2000-2100): {anio}")
    
    # 🔒 LOCK: Solo 1 proceso puede leer/escribir el correlativo a la vez
    with _correlativo_lock:
        with get_conn(timeout_sec=10) as conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("SELECT numero FROM correlativos WHERE anio = ?", (anio,))
            row = cur.fetchone()
            if row is None:
                numero = 1
                conn.execute("INSERT INTO correlativos(anio, numero) VALUES (?, ?)", (anio, numero))
            else:
                numero = row[0] + 1
                conn.execute("UPDATE correlativos SET numero = ? WHERE anio = ?", (numero, anio))
            conn.commit()
            
            # Log para auditoría
            logger.info(f"✅ Correlativo generado: {numero:04d}-NSC-{anio}")
            return numero

def save_permiso_registro(data: dict) -> None:
    """Inserta un registro de permiso emitido en la BD (columnas=valores 1:1)."""
    cols = [
        "anio","numero","nsc","fecha_registro",
        "ciudad","notario",

        "padre_nombre","padre_dni","padre_estado_civil","padre_direccion","padre_distrito","padre_provincia","padre_departamento",
        "madre_nombre","madre_dni","madre_estado_civil","madre_direccion","madre_distrito","madre_provincia","madre_departamento",

        "menor_nombre","menor_dni","menor_fnac","sexo_menor",

        "tipo_viaje","firma_quien","origen","destino","vias","empresa","salida","retorno",

        "acompanante","tercero_nombre","tercero_dni",
        
        "rol_acompanante", "acomp1_nombre", "acomp1_dni", "acomp_count",
        
        "viaja_solo","recibe_si","rec_nombre","rec_doc_tipo","rec_doc_num","rec_doc_pais","rec_list_json",

        "motivo","ciudad_evento","fecha_evento","organizador",
        
        "hermanos_json","terceros_json",
        
        "recibe_si","rec_nombre","rec_doc_tipo","rec_doc_num","rec_doc_pais",

        "archivo_generado","estado","updated_at","version",

        "anulado_at","anulado_motivo","anulado_por",

        "padre_doc_tipo","padre_doc_num","padre_nacionalidad",
        "madre_doc_tipo","madre_doc_num","madre_nacionalidad",
        "menor_doc_tipo","menor_doc_num","menor_nacionalidad",
    ]
    now = datetime.now().isoformat(timespec="seconds")
    defaults = {
        "nsc": "NSC", "fecha_registro": now, "estado": "EMITIDO", "updated_at": now, "version": 1,
        "anulado_at": "", "anulado_motivo": "", "anulado_por": ""
    }
    values = [data.get(k, defaults.get(k, "")) for k in cols]

    qmarks = ",".join(["?"] * len(cols))
    sql = f"INSERT INTO permisos ({','.join(cols)}) VALUES ({qmarks})"
    with get_conn(timeout_sec=10) as conn:
        conn.execute(sql, values)
        conn.commit()

def fetch_permisos(anio: int | None = None):
    q = ("SELECT id, anio, numero, nsc, fecha_registro, ciudad, notario, "
         "padre_nombre, madre_nombre, menor_nombre, menor_dni, tipo_viaje, firma_quien, "
         "origen, destino, vias, salida, retorno, estado, version, archivo_generado "
         "FROM permisos")
    params = ()
    if anio:
        q += " WHERE anio = ? ORDER BY numero ASC"
        params = (anio,)
    with get_conn() as conn:
        cur = conn.execute(q, params)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return cols, rows

def fetch_permiso_by_id(pid: int) -> dict | None:
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM permisos WHERE id = ?", (pid,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))

def fetch_permiso_by_correlativo(anio: int, numero: int) -> dict | None:
    """Devuelve el permiso por (anio, numero) o None si no existe."""
    with get_conn(timeout_sec=10) as conn:
        cur = conn.execute("SELECT * FROM permisos WHERE anio = ? AND numero = ? LIMIT 1", (anio, numero))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))

def get_id_por_correlativo(anio: int, numero: int) -> int | None:
    """Devuelve el ID del permiso dado un año y su correlativo (numero)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM permisos WHERE anio = ? AND numero = ? LIMIT 1",
            (int(anio), int(numero))
        ).fetchone()
    return int(row[0]) if row else None

def update_permiso(pid: int, data: dict):
    fields = [
        "ciudad","notario",

        "padre_nombre","padre_dni","padre_estado_civil","padre_direccion","padre_distrito","padre_provincia","padre_departamento",
        "madre_nombre","madre_dni","madre_estado_civil","madre_direccion","madre_distrito","madre_provincia","madre_departamento",

        "menor_nombre","menor_dni","menor_fnac","sexo_menor",

        "tipo_viaje","firma_quien","origen","destino","vias","empresa","salida","retorno",
        
        "acompanante","tercero_nombre","tercero_dni",
        
        "rol_acompanante", "acomp1_nombre", "acomp1_dni", "acomp_count",

        "motivo","ciudad_evento","fecha_evento","organizador",
        
        "recibe_si","rec_nombre","rec_doc_tipo","rec_doc_num","rec_doc_pais",

        "archivo_generado","estado","version",
        "anulado_at","anulado_motivo","anulado_por",

        "padre_doc_tipo","padre_doc_num","padre_nacionalidad",
        "madre_doc_tipo","madre_doc_num","madre_nacionalidad",
        "menor_doc_tipo","menor_doc_num","menor_nacionalidad",
        "viaja_solo","recibe_si","rec_nombre","rec_doc_tipo","rec_doc_num","rec_doc_pais","rec_list_json",
        "hermanos_json",
        "terceros_json",
    ]
    set_clause = ", ".join([f"{f}=?" for f in fields]) + ", updated_at=?"
    values = [data.get(f, "") for f in fields]
    values.append(datetime.now().isoformat(timespec="seconds"))
    values.append(pid)
    with get_conn() as conn:
        conn.execute(f"UPDATE permisos SET {set_clause} WHERE id = ?", values)
        conn.commit()
        
        
def _norm_doc(x: str) -> str:
    x = (x or "").strip()
    # Si parece DNI (mayoría dígitos)
    only_digits = "".join(ch for ch in x if ch.isdigit())
    return only_digits if len(only_digits) >= 8 else x

def propagar_cambio_doc(rol: str, old_doc: str, new_doc: str) -> int:
    """Propaga el cambio de documento a todos los permisos históricos del rol indicado."""
    rol = (rol or "").upper()
    old_doc = _norm_doc(old_doc)
    new_doc = _norm_doc(new_doc)
    if not old_doc or not new_doc or old_doc == new_doc:
        return 0  # nada que hacer

    with get_conn(timeout_sec=10) as conn:
        if rol == "PADRE":
            cur = conn.execute("""
                UPDATE permisos
                SET padre_doc_num = ?, padre_dni = ?, updated_at = CURRENT_TIMESTAMP
                WHERE REPLACE(padre_doc_num, ' ', '') = ? OR REPLACE(padre_dni, ' ', '') = ?
            """, (new_doc, new_doc, old_doc, old_doc))
        elif rol == "MADRE":
            cur = conn.execute("""
                UPDATE permisos
                SET madre_doc_num = ?, madre_dni = ?, updated_at = CURRENT_TIMESTAMP
                WHERE REPLACE(madre_doc_num, ' ', '') = ? OR REPLACE(madre_dni, ' ', '') = ?
            """, (new_doc, new_doc, old_doc, old_doc))
        else:  # MENOR
            cur = conn.execute("""
                UPDATE permisos
                SET menor_doc_num = ?, menor_dni = ?, updated_at = CURRENT_TIMESTAMP
                WHERE REPLACE(menor_doc_num, ' ', '') = ? OR REPLACE(menor_dni, ' ', '') = ?
            """, (new_doc, new_doc, old_doc, old_doc))
        conn.commit()
        return cur.rowcount

def _update_hermano_doc_json(old_doc: str, new_doc: str) -> int:
    """
    Recorre todos los permisos con hermanos_json y reemplaza old_doc por new_doc
    en el campo doc_num (o dni) de cada hermano que coincida.
    Devuelve cuántos permisos fueron modificados.
    """
    old_n = _norm_doc(old_doc)
    new_n = _norm_doc(new_doc)
    if not old_n or not new_n or old_n == new_n:
        return 0

    import json
    afectados = 0
    with get_conn(timeout_sec=10) as conn:
        cur = conn.execute("SELECT id, hermanos_json FROM permisos WHERE COALESCE(hermanos_json,'') <> ''")
        rows = cur.fetchall()
        for pid, hjson in rows:
            try:
                arr = json.loads(hjson)
            except Exception:
                continue
            if not isinstance(arr, list):
                continue

            changed = False
            for h in arr:
                doc = (h.get("doc_num") or h.get("dni") or "").strip()
                if _norm_doc(doc) == old_n:
                    # normalizamos siempre en doc_num
                    h["doc_num"] = new_n
                    changed = True

            if changed:
                conn.execute(
                    "UPDATE permisos SET hermanos_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (json.dumps(arr, ensure_ascii=False), int(pid))
                )
                afectados += 1
        conn.commit()
    return afectados

   
def admin_actualizar_doc(rol: str, old_doc: str, new_doc: str, mover_oculto: bool = True) -> tuple[bool, str, int]:
    """
    Admin: actualiza un documento (DNI/Pasaporte) para un ROL en TODOS los permisos históricos.
    - rol: 'PADRE' | 'MADRE' | 'MENOR' | 'HERMANO'
    - old_doc: documento anterior (tal como está guardado)
    - new_doc: documento nuevo (corregido)
    Devuelve: (ok, mensaje, filas_afectadas)
    """
    rol = (rol or "").upper()
    old_doc_n = _norm_doc(old_doc)
    new_doc_n = _norm_doc(new_doc)

    if rol not in ("PADRE", "MADRE", "MENOR", "HERMANO"):
        return False, "ROL inválido.", 0
    if not old_doc_n or not new_doc_n:
        return False, "Faltan documentos (anterior/nuevo).", 0
    if old_doc_n == new_doc_n:
        return False, "El documento nuevo es igual al anterior.", 0

    try:
        filas = 0
        if rol == "PADRE":
            with get_conn(timeout_sec=10) as conn:
                cur = conn.execute("""
                    UPDATE permisos
                    SET padre_doc_num = ?, padre_dni = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE REPLACE(COALESCE(padre_doc_num, ''), ' ', '') = ?
                       OR REPLACE(COALESCE(padre_dni, ''), ' ', '') = ?
                """, (new_doc_n, new_doc_n, old_doc_n, old_doc_n))
                filas = cur.rowcount
                conn.commit()

        elif rol == "MADRE":
            with get_conn(timeout_sec=10) as conn:
                cur = conn.execute("""
                    UPDATE permisos
                    SET madre_doc_num = ?, madre_dni = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE REPLACE(COALESCE(madre_doc_num, ''), ' ', '') = ?
                       OR REPLACE(COALESCE(madre_dni, ''), ' ', '') = ?
                """, (new_doc_n, new_doc_n, old_doc_n, old_doc_n))
                filas = cur.rowcount
                conn.commit()

        elif rol == "MENOR":
            with get_conn(timeout_sec=10) as conn:
                cur = conn.execute("""
                    UPDATE permisos
                    SET menor_doc_num = ?, menor_dni = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE REPLACE(COALESCE(menor_doc_num, ''), ' ', '') = ?
                       OR REPLACE(COALESCE(menor_dni, ''), ' ', '') = ?
                """, (new_doc_n, new_doc_n, old_doc_n, old_doc_n))
                filas = cur.rowcount
                conn.commit()

        else:  # HERMANO
            # No hay columnas directas; actualizamos dentro del JSON de hermanos en TODOS los permisos
            filas = _update_hermano_doc_json(old_doc_n, new_doc_n)

        # Mover estado "oculto" si corresponde (si llevas esa bitácora por (rol, doc))
        if mover_oculto:
            try:
                if is_doc_oculto(rol, old_doc_n):
                    # marca visible el viejo y oculta el nuevo, conservando un motivo
                    mostrar_doc(rol, old_doc_n)
                    ocultar_doc(rol, new_doc_n, f"Migrado desde {old_doc_n}", creado_por="ADMIN")
            except Exception:
                # si tus funciones no existen o fallan, no rompemos la operación principal
                pass

        return True, f"Documento actualizado ({rol}): {old_doc_n} → {new_doc_n}. Registros afectados: {filas}.", filas

    except Exception as e:
        return False, f"Error actualizando documento: {e}", 0


    # Valida formato según tipo deducido (opcional: si parece DNI => 8 dígitos)
    def _deduce_tipo(num: str) -> str:
        d = "".join(ch for ch in (num or "") if ch.isdigit())
        return "DNI" if len(d) == 8 and d == num else "PASAPORTE"

    filas = propagar_cambio_doc(rol, old_doc_n, new_doc_n)

    # Si estaba oculto el viejo, migra marca de oculto al nuevo (para no “exponerlo” sin querer).
    if mover_oculto:
        try:
            with get_conn() as conn:
                # ¿existía oculto?
                cur = conn.execute(
                    "SELECT motivo, creado_por, creado_at FROM doc_ocultos WHERE rol=? AND doc_num=? LIMIT 1",
                    (rol, old_doc_n)
                )
                row = cur.fetchone()
                if row:
                    motivo, creado_por, creado_at = row
                    # borra el viejo y crea/asegura el nuevo
                    conn.execute("DELETE FROM doc_ocultos WHERE rol=? AND doc_num=?", (rol, old_doc_n))
                    conn.execute("""
                        INSERT OR IGNORE INTO doc_ocultos(rol, doc_num, motivo, creado_por, creado_at)
                        VALUES(?,?,?,?, COALESCE(?, datetime('now')))
                    """, (rol, new_doc_n, motivo or "MIGRADO POR ACTUALIZACIÓN", (creado_por or "ADMIN"), creado_at))
                    conn.commit()
        except Exception:
            # si falla, no rompemos la operación principal
            pass

    return True, f"Se actualizó {filas} permiso(s) histórico(s).", filas
# =====================================================
# === BACKUP AUTOMÁTICO Y MANUAL DE BASE DE DATOS =====
# =====================================================
import shutil, glob  # <-- estos imports sí, van aquí

BACKUP_DIR = os.path.join(BASE_DIR, "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

def backup_sqlite_y_emitidos(retention_days: int = 60) -> list[str]:
    """Hace copia segura de permisos.db y carpeta emitidos."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_paths = []

    # 1️⃣ Copia segura de la base de datos
    src = get_conn(timeout_sec=30)
    try:
        dst_path = os.path.join(BACKUP_DIR, f"permisos_{ts}.db")
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
        out_paths.append(dst_path)
    finally:
        src.close()

    # 2️⃣ Comprimir carpeta "emitidos"
    emitidos_dir = os.path.join(BASE_DIR, "emitidos")
    if os.path.isdir(emitidos_dir):
        zip_base = os.path.join(BACKUP_DIR, f"emitidos_{ts}")
        zip_path = shutil.make_archive(zip_base, "zip", emitidos_dir)
        out_paths.append(zip_path)

    # 3️⃣ Limpiar copias viejas
    limite_seg = retention_days * 24 * 3600
    now = datetime.now().timestamp()
    for p in glob.glob(os.path.join(BACKUP_DIR, "*")):
        try:
            if (now - os.path.getmtime(p)) > limite_seg:
                os.remove(p)
        except Exception:
            pass

    return out_paths

def anular_permiso(pid: int, motivo: str = "", usuario: str = "ADMIN"):
    perm = fetch_permiso_by_id(pid)
    if not perm:
        return False, "No existe el permiso."
    if str(perm.get("estado","")).upper() == "ANULADO":
        return False, "El permiso ya está ANULADO."

    data_upd = dict(perm)
    data_upd.update({
        "estado": "ANULADO",
        "anulado_at": datetime.now().isoformat(timespec="seconds"),
        "anulado_motivo": (motivo or "").strip().upper(),
        "anulado_por": (usuario or "ADMIN").upper(),
    })
    update_permiso(pid, data_upd)
    return True, "Permiso ANULADO."

def is_doc_oculto(rol: str, doc_num: str) -> bool:
    rol = (rol or "").upper()
    doc = (doc_num or "").strip().upper()
    if not rol or not doc:
        return False
    with get_conn() as conn:
        cur = conn.execute("SELECT 1 FROM doc_ocultos WHERE rol=? AND doc_num=? LIMIT 1", (rol, doc))
        return cur.fetchone() is not None

def ocultar_doc(rol: str, doc_num: str, motivo: str = "", creado_por: str = "") -> tuple[bool, str]:
    rol = (rol or "").upper()
    doc = (doc_num or "").strip().upper()
    if not rol or not doc:
        return False, "Falta rol o documento."
    try:
        with get_conn(timeout_sec=10) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO doc_ocultos(rol, doc_num, motivo, creado_por, creado_at)
                VALUES(?,?,?,?, datetime('now'))
            """, (rol, doc, motivo.strip().upper(), (creado_por or "USUARIO").upper()))
            conn.commit()
        return True, "Documento ocultado."
    except Exception as e:
        return False, f"No se pudo ocultar: {e}"

def mostrar_doc(rol: str, doc_num: str) -> tuple[bool, str]:
    rol = (rol or "").upper()
    doc = (doc_num or "").strip().upper()
    if not rol or not doc:
        return False, "Falta rol o documento."
    with get_conn(timeout_sec=10) as conn:
        conn.execute("DELETE FROM doc_ocultos WHERE rol=? AND doc_num=?", (rol, doc))
        conn.commit()
    return True, "Documento mostrado."

def fetch_docs_registrados_paged(
    rol: str | None,
    filtro_texto: str = "",
    incluir_ocultos: bool = True,
    limit: int = 20,
    offset: int = 0
):
    """
    Devuelve (rows, total) con paginación.
    rows: lista de tuplas (rol, doc, nombre, ult, oculto)
    total: enteros totales para ese filtro (sin LIMIT/OFFSET)
    """
    rol = (rol or "").strip().upper()
    ft = f"%{(filtro_texto or '').strip().upper()}%"
    inc = 1 if incluir_ocultos else 0

    base_sql = """
    WITH base AS (
        SELECT 'PADRE' AS rol,
               TRIM(COALESCE(NULLIF(padre_doc_num,''), padre_dni)) AS doc,
               UPPER(MAX(COALESCE(NULLIF(padre_nombre,''),'(SIN NOMBRE)'))) AS nombre,
               MAX(COALESCE(updated_at, fecha_registro)) AS ult
        FROM permisos
        WHERE TRIM(COALESCE(NULLIF(padre_doc_num,''), padre_dni)) <> ''
        GROUP BY doc

        UNION ALL

        SELECT 'MADRE' AS rol,
               TRIM(COALESCE(NULLIF(madre_doc_num,''), madre_dni)) AS doc,
               UPPER(MAX(COALESCE(NULLIF(madre_nombre,''),'(SIN NOMBRE)'))) AS nombre,
               MAX(COALESCE(updated_at, fecha_registro)) AS ult
        FROM permisos
        WHERE TRIM(COALESCE(NULLIF(madre_doc_num,''), madre_dni)) <> ''
        GROUP BY doc

        UNION ALL

        -- 👇 NUEVO: MENOR
        SELECT 'MENOR' AS rol,
               TRIM(COALESCE(NULLIF(menor_doc_num,''), menor_dni)) AS doc,
               UPPER(MAX(COALESCE(NULLIF(menor_nombre,''),'(SIN NOMBRE)'))) AS nombre,
               MAX(COALESCE(updated_at, fecha_registro)) AS ult
        FROM permisos
        WHERE TRIM(COALESCE(NULLIF(menor_doc_num,''), menor_dni)) <> ''
        GROUP BY doc
    
        UNION ALL

        -- 👇 NUEVO: HERMANO (extrae de JSON por cada permiso)
        SELECT 'HERMANO' AS rol,
               TRIM(COALESCE(NULLIF(json_extract(j.value,'$.doc_num'), ''),
                             json_extract(j.value,'$.dni'))) AS doc,
               UPPER(MAX(COALESCE(NULLIF(json_extract(j.value,'$.nombre'),''),'(SIN NOMBRE)'))) AS nombre,
               MAX(COALESCE(p.updated_at, p.fecha_registro)) AS ult
        FROM permisos p
        JOIN json_each(p.hermanos_json) AS j
        WHERE TRIM(COALESCE(NULLIF(json_extract(j.value,'$.doc_num'), ''),
                            json_extract(j.value,'$.dni'))) <> ''
        GROUP BY doc
    ),
    etiquetado AS (
        SELECT b.rol, b.doc, b.nombre, b.ult,
               CASE
                 WHEN EXISTS(
                   SELECT 1 FROM doc_ocultos o
                   WHERE o.rol = b.rol AND o.doc_num = b.doc
                 ) THEN 1 ELSE 0
               END AS oculto
        FROM base b
    )
    SELECT rol, doc, nombre, ult, oculto
    FROM etiquetado
    WHERE (? = '' OR rol = ?)
      AND (? = '' OR UPPER(doc) LIKE ? OR UPPER(nombre) LIKE ?)
      AND (? = 1 OR oculto = 0)
    """

    # total
    sql_total = f"SELECT COUNT(*) FROM ({base_sql})"
    # page
    sql_page = f"{base_sql} ORDER BY datetime(ult) DESC LIMIT ? OFFSET ?"

    params_common = [rol, rol, (filtro_texto or "").strip().upper(), ft, ft, inc]

    with get_conn(timeout_sec=10) as conn:
        cur = conn.execute(sql_total, params_common)
        total = cur.fetchone()[0]

        cur = conn.execute(sql_page, params_common + [int(limit), int(offset)])
        rows = cur.fetchall()

    return rows, total

def fetch_docs_registrados(rol: str | None = None, filtro_texto: str = "", incluir_ocultos: bool = True):
    """
    Devuelve lista de (rol, doc, nombre, ultima_actualizacion, oculto_bool).
    rol: PADRE|MADRE|MENOR  (o None para todos)
    """
    filtro_texto = (filtro_texto or "").strip().upper()
    rol = (rol or "").upper()

    sql_parts = []

    # PADRE
    if (not rol) or rol == "PADRE":
        sql_parts.append("""
            SELECT 'PADRE' AS rol,
                   UPPER(COALESCE(padre_doc_num, padre_dni)) AS doc,
                   UPPER(COALESCE(NULLIF(padre_nombre,''),'(SIN NOMBRE)')) AS nombre,
                   COALESCE(updated_at, fecha_registro) AS ultima
            FROM permisos
            WHERE COALESCE(padre_doc_num, padre_dni) IS NOT NULL
              AND TRIM(COALESCE(padre_doc_num, padre_dni)) <> ''
        """)

    # MADRE
    if (not rol) or rol == "MADRE":
        sql_parts.append("""
            SELECT 'MADRE' AS rol,
                   UPPER(COALESCE(madre_doc_num, madre_dni)) AS doc,
                   UPPER(COALESCE(NULLIF(madre_nombre,''),'(SIN NOMBRE)')) AS nombre,
                   COALESCE(updated_at, fecha_registro) AS ultima
            FROM permisos
            WHERE COALESCE(madre_doc_num, madre_dni) IS NOT NULL
              AND TRIM(COALESCE(madre_doc_num, madre_dni)) <> ''
        """)

    # MENOR  👈 NUEVO
    if (not rol) or rol == "MENOR":
        sql_parts.append("""
            SELECT 'MENOR' AS rol,
                   UPPER(COALESCE(menor_doc_num, menor_dni)) AS doc,
                   UPPER(COALESCE(NULLIF(menor_nombre,''),'(SIN NOMBRE)')) AS nombre,
                   COALESCE(updated_at, fecha_registro) AS ultima
            FROM permisos
            WHERE COALESCE(menor_doc_num, menor_dni) IS NOT NULL
              AND TRIM(COALESCE(menor_doc_num, menor_dni)) <> ''
        """)

    # HERMANO  👈 NUEVO
    if (not rol) or rol == "HERMANO":
        sql_parts.append("""
            SELECT 'HERMANO' AS rol,
                   UPPER(TRIM(COALESCE(NULLIF(json_extract(j.value,'$.doc_num'), ''),
                                       json_extract(j.value,'$.dni')))) AS doc,
                   UPPER(COALESCE(NULLIF(json_extract(j.value,'$.nombre'),''),'(SIN NOMBRE)')) AS nombre,
                   COALESCE(p.updated_at, p.fecha_registro) AS ultima
            FROM permisos p
            JOIN json_each(p.hermanos_json) AS j
            WHERE TRIM(COALESCE(NULLIF(json_extract(j.value,'$.doc_num'), ''),
                                json_extract(j.value,'$.dni'))) <> ''
        """)
    
    if not sql_parts:
        return []

    union_sql = " UNION ALL ".join(sql_parts)
    q = f"""
        SELECT rol, doc, MAX(nombre) AS nombre, MAX(ultima) AS ultima
        FROM ({union_sql})
        GROUP BY rol, doc
        ORDER BY datetime(ultima) DESC
    """

    with get_conn() as conn:
        cur = conn.execute(q)
        rows = cur.fetchall()

    # Post-filtro por texto y por ocultos
    out = []
    for r in rows:
        _rol, _doc, _nombre, _ultima = r
        oculto = is_doc_oculto(_rol, _doc)
        if not incluir_ocultos and oculto:
            continue
        if filtro_texto and (filtro_texto not in (_doc or "")) and (filtro_texto not in (_nombre or "")):
            continue
        out.append((_rol, _doc, _nombre, _ultima, oculto))

    return out
# ============ Helpers ============

def _tipo_permiso_tx(tipo_viaje: str) -> str:
    t = (tipo_viaje or "").upper()
    return "PERMISO VIAJE AL EXTERIOR" if t == "INTERNACIONAL" else "PERMISO VIAJE AL INTERIOR"

def _safe_up(x): 
    return (x or "").strip().upper()

def _hermanos_from_perm(perm: dict) -> list[dict]:
    """
    Devuelve lista de hermanos en formato [{nombre, sexo, doc_tipo, doc_num, fnac, nacionalidad}...]
    Soporta tanto 'hermanos_json' (string) como 'hermanos' (lista ya cargada).
    """
    # 1) si ya viene como lista, úsala
    hs = perm.get("hermanos")
    if isinstance(hs, list):
        return hs

    # 2) intenta parsear 'hermanos_json'
    raw = perm.get("hermanos_json") or ""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []

def _participantes_tx(perm: dict) -> str:
    """
    Construye el bloque multilínea usado en la columna 'Participantes' del Excel.
    Reglas:
      - PADRE : NOMBRE (si hay)
      - MADRE : NOMBRE (si hay)
      - MENOR : <MENOR PRINCIPAL>
      - MENOR : <HERMANO 1>
      - MENOR : <HERMANO 2>
      - Si el acompañante es TERCERO, agrega también APODERADO : <NOMBRE>
    """
    out = []

    padre = _safe_up(perm.get("padre_nombre"))
    madre = _safe_up(perm.get("madre_nombre"))
    menor = _safe_up(perm.get("menor_nombre"))

    if padre:
        out.append(f"PADRE : {padre}")
    if madre:
        out.append(f"MADRE : {madre}")

    # menor principal (siempre que haya nombre)
    if menor:
        out.append(f"MENOR : {menor}")

    # hermanos biológicos -> también como "MENOR : ..."
    for h in _hermanos_from_perm(perm):
        nom_h = _safe_up(h.get("nombre"))
        if nom_h:
            out.append(f"MENOR : {nom_h}")

    # si acompaña un tercero, muéstralo como APODERADO
    acomp = _safe_up(perm.get("acompanante"))
    if acomp == "TERCERO":
        apod_nom = _safe_up(perm.get("acomp1_nombre") or perm.get("tercero_nombre"))
        if apod_nom:
            out.append(f"APODERADO : {apod_nom}")

    return "\n".join(out)

def _cronologico_tx(perm: dict) -> str:
    # “N°0031 — NSC-2025”
    num = int(perm.get("numero") or 0)
    anio = int(perm.get("anio") or 0)
    nsc = s(perm.get("nsc") or "NSC")
    return f"N° {num:04d} — {nsc}-{anio}"

def _destino_tx(perm: dict) -> str:
    ori = s(perm.get("origen")).upper()
    des = s(perm.get("destino")).upper()
    # Puedes ajustar el separador si lo prefieres
    return f"{ori} – {des}"

def _fecha_ddmmyyyy(iso_ymd: str) -> str:
    x = s(iso_ymd)
    if not x:
        return ""
    try:
        d = datetime.strptime(x[:10], "%Y-%m-%d").date()
        return d.strftime("%d/%m/%Y")
    except Exception:
        return x

def s(x: str | None) -> str:
    return (x or "").strip()

def fecha_iso_a_letras(fecha_iso: str) -> str:
    if not fecha_iso:
        return ""
    dt = datetime.strptime(fecha_iso, "%Y-%m-%d").date()
    return f"{dt.day:02d} DE {MESES[dt.month]} DEL {dt.year}"

def _date_from_iso_like(x: str | None) -> date:
    """
    Convierte '2025-10-12T14:33:22' o '2025-10-12' a date.
    Si falla, devuelve date.today().
    """
    s = (x or "").strip()
    if not s:
        return date.today()
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        try:
            # intenta solo la parte YYYY-MM-DD
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except Exception:
            return date.today()

def calcular_edad(fecha_nac_iso: str, hoy: date | None = None) -> int:
    if not fecha_nac_iso:
        return 0
    d = datetime.strptime(fecha_nac_iso, "%Y-%m-%d").date()
    hoy = hoy or date.today()
    return hoy.year - d.year - ((hoy.month, hoy.day) < (d.month, d.day))

def edad_en_letras(n: int) -> str:
    return num2words(n, lang="es").upper()


def parse_iso(x: str | None):
    """Devuelve date si x='YYYY-MM-DD', si no, None."""
    try:
        return datetime.strptime((x or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None

# =========================
# Documentos: tipos y utils
# =========================
DOC_TIPOS_UI = ["DNI", "PASAPORTE", "DNI EXTRANJERO"]

_DOC_CANON = {
    "DNI": "DNI",
    "PASAPORTE": "PASAPORTE",
    "DNI EXTRANJERO": "DNI_EXTRANJERO",
}

def canon_doc(t: str) -> str:
    t = (t or "").strip().upper()
    return _DOC_CANON.get(t, "DNI")

def doc_label(t: str) -> str:
    ct = canon_doc(t)
    if ct == "DNI":             return "DNI"
    if ct == "PASAPORTE":       return "PASAPORTE"
    if ct == "DNI_EXTRANJERO":  return "DNI EXTRANJERO"
    return ct

# ================== Receptores (helpers) ==================

def _rec_doc_bloque(tipo: str, num: str, pais: str = "") -> str:
    """Devuelve bloque documento en mayúsculas para el receptor."""
    t = (tipo or "").upper()
    n = s(num).upper()
    p = s(pais).upper()
    if not n:
        return ""
    if t == "PASAPORTE":
        return f"CON PASAPORTE N° {n}"
    if t == "DNI EXTRANJERO":
        return f"CON DOCUMENTO NACIONAL DE IDENTIDAD N° {n}" + (f" {p}" if p else "")
    # default o DNI PERUANO
    return f"CON DOCUMENTO NACIONAL DE IDENTIDAD N° {n}"

def _recep_items_from_state() -> list[dict]:
    """
    Lee de st.session_state los campos dinámicos rec_*_i y arma la lista de receptores.
    Estructura: [{"nombre":..., "tipo":..., "num":..., "pais":...}, ...]
    Filtra items sin nombre.
    """
    rec_list = []
    total = int(st.session_state.get("rec_list_count", 0))
    for i in range(total):
        nom  = s(st.session_state.get(f"rec_nombre_{i}", "")).upper()
        tipo = s(st.session_state.get(f"rec_doc_tipo_{i}", "DNI PERUANO")).upper()
        num  = s(st.session_state.get(f"rec_doc_num_{i}", ""))
        pais = s(st.session_state.get(f"rec_doc_pais_{i}", "")).upper()
        if nom:
            rec_list.append({"nombre": nom, "tipo": tipo, "num": num, "pais": pais})
    return rec_list

def _obs_con_recepcion_plural(ac: dict, rec_list: list[dict]) -> str:
    """
    Construye: '... Y QUE A SU ARRIBO SERÁ(N) RECOGIDO(S)/A(S) POR X, DOC; Y/O POR Y, DOC.'
    Usa concordancias de 'ac'.
    """
    if not rec_list:
        return ""
    partes = []
    for r in rec_list:
        doc = _rec_doc_bloque(r.get("tipo"), r.get("num"), r.get("pais"))
        seg = f"POR {r.get('nombre','')}{', ' + doc if doc else ''}"
        partes.append(seg)
    por_txt = "; Y/O ".join(partes)
    return f"Y QUE A SU ARRIBO {ac['VERB_SER']} {ac['ADJ_RECOGIDO']} {por_txt}."

def _clear_form_keys_for_new():
    """
    Limpia del session_state TODAS las claves que usa el formulario,
    para que '➕ Nuevo permiso' no herede valores de '✏ Editar / Re-generar'.
    """
    # Prefijos habituales de tus widgets (padre, madre, menor, viaje, etc.)
    prefixes = [
        # padre/madre/menor
        "padre_", "madre_", "menor_",
        # campos simples
        "sexo_menor", "ciudad", "notario", "tipo_viaje",
        "origen", "destino", "empresa", "vias", "fs", "fr", "tiene_retorno",
        # acompañante / recepción
        "acompanante", "rol_acompanante", "acomp1_", "acomp_count", "viaja_solo",
        "recibe_si", "rec_nombre", "rec_doc_tipo", "rec_doc_num", "rec_doc_pais",
        # motivo/evento
        "motivo", "ciudad_evento", "fecha_evento", "organizador",
        # firmas
        "quien_firma", "quien_firma_int",
        # hermanos dinámicos
        "hermanos", "hermano_nombre_", "hermano_sexo_", "hermano_doc_tipo_",
        "hermano_doc_num_", "hermano_fnac_",
        # banderas internas que podrían reinyectar datos
        "_prefill_hermanos_pid", "pid_editing", "modo_edicion",
        "_did_clear_padre", "_did_clear_madre"
    ]

    # Palabras clave por si algún widget tiene key "libre"
    substrings_anywhere = [
        "padre", "madre", "menor",       # base
        "acomp", "acompan", "rol_acompanante",
        "recibe", "rec_",                # recepción
    ]

    # Claves explícitas comunes
    explicit_keys = {
        # Padre
        "padre_nombre","padre_dni","padre_doc_tipo","padre_doc_num",
        "padre_estado_civil","padre_direccion","padre_distrito",
        "padre_provincia","padre_departamento","padre_nacionalidad",
        # Madre
        "madre_nombre","madre_dni","madre_doc_tipo","madre_doc_num",
        "madre_estado_civil","madre_direccion","madre_distrito",
        "madre_provincia","madre_departamento","madre_nacionalidad",
        # Menor
        "menor_nombre","menor_dni","menor_doc_tipo","menor_doc_num",
        "menor_fnac","menor_nacionalidad","sexo_menor",
        # Recepción
        "recibe_si","rec_nombre","rec_doc_tipo","rec_doc_num","rec_doc_pais",
        # Varios
        "vias","fs","fr","tiene_retorno","quien_firma","quien_firma_int"
    }

    # ========================================================================
    # 🔥 NUEVO: Limpiar selectores UBIGEO explícitamente (ANTES del to_delete)
    # ========================================================================
    ubigeo_keys = [
        "padre_departamento_sel", "padre_provincia_sel", "padre_distrito_sel",
        "padre_provincia_sel_empty", "padre_distrito_sel_empty",
        "madre_departamento_sel", "madre_provincia_sel", "madre_distrito_sel",
        "madre_provincia_sel_empty", "madre_distrito_sel_empty"
    ]
    
    for k in ubigeo_keys:
        st.session_state.pop(k, None)
    
    # Limpia cachés de provincias/distritos
    keys_to_remove = [k for k in st.session_state.keys() 
                      if k.startswith("provincias_") or k.startswith("distritos_")]
    for k in keys_to_remove:
        st.session_state.pop(k, None)
    # ========================================================================
    # FIN DEL BLOQUE NUEVO
    # ========================================================================

    to_delete = set()
    # Recorre todas las claves (case-insensitive para prefijos/substrings)
    for k in list(st.session_state.keys()):
        kl = k.lower()

        if k in explicit_keys:
            to_delete.add(k); continue

        if any(kl.startswith(p) for p in prefixes):
            to_delete.add(k); continue

        if any(sub in kl for sub in substrings_anywhere):
            to_delete.add(k); continue

    # Borra sin error si no existe
    for k in to_delete:
        st.session_state.pop(k, None)
        
# --- Callbacks para limpiar buscadores/fields ---
def _limpiar_padre_cb():
    ss = st.session_state
    # quitar precarga y resetear widgets del PADRE
    ss.pop("prefill_padre", None)
    ss["doc_busca_padre"] = ""   # limpia el buscador

    for k, v in {
        "padre_nombre": "",
        "padre_doc_tipo": "DNI",   # default
        "padre_doc_num": "",
        "padre_dni": "",           # compat histórico
        "padre_nacionalidad": "",
        "padre_estado_civil": "",
        "padre_direccion": "",
        "padre_distrito": "",
        "padre_provincia": "",
        "padre_departamento": "",
    }.items():
        ss[k] = v

    # fuerza un rerender una vez
    ss["_did_clear_padre"] = True


def _limpiar_madre_cb():
    ss = st.session_state
    ss.pop("prefill_madre", None)
    ss["doc_busca_madre"] = ""

    for k, v in {
        "madre_nombre": "",
        "madre_doc_tipo": "DNI",
        "madre_doc_num": "",
        "madre_dni": "",           # compat histórico
        "madre_nacionalidad": "",
        "madre_estado_civil": "",
        "madre_direccion": "",
        "madre_distrito": "",
        "madre_provincia": "",
        "madre_departamento": "",
    }.items():
        ss[k] = v

    ss["_did_clear_madre"] = True

def _limpiar_menor_cb():
    st.session_state.pop("prefill_menor", None)
    st.session_state["doc_busca_menor"] = ""
    st.session_state["menor_nombre"] = ""
    st.session_state["menor_doc_tipo"] = "DNI"
    st.session_state["menor_doc_num"] = ""
    st.session_state["menor_dni"] = ""
    st.session_state["menor_nacionalidad"] = ""
    st.session_state["sexo_menor"] = ""
    st.session_state.pop("menor_fnac", None)
    st.session_state.pop("_prefill_hermanos_pid", None)

    
    # dentro de _limpiar_menor_cb(), al final de la parte que limpia hermanos:
    if "hermanos" in st.session_state:
        for i in range(len(st.session_state["hermanos"])):
            for k in (
                f"hermano_nombre_{i}", f"hermano_sexo_{i}",
                f"hermano_doc_tipo_{i}", f"hermano_doc_num_{i}",
                f"hermano_fnac_{i}"
            ):
                st.session_state.pop(k, None)
    st.session_state["hermanos"] = []


def _clear_lookup_buffers():
    """Limpia todo lo relacionado a buscadores y prefills (PADRE/MADRE/MENOR)."""
    for k in (
        "prefill_padre", "prefill_madre", "prefill_menor", "prefill_from_search",
        "doc_busca_padre", "doc_busca_madre"
    ):
        st.session_state.pop(k, None)

def _push_precarga_to_state(precarga: dict):
    """Empuja valores de precarga (del permiso) a session_state para que los widgets los tomen."""
    if not precarga:
        return
    
    if "menor_fnac" in precarga:
        st.session_state["menor_fnac"] = parse_iso(precarga.get("menor_fnac"))  # date | None
    if "salida" in precarga:
        st.session_state["salida"] = parse_iso(precarga.get("salida"))          # date | None
    if "retorno" in precarga:
        st.session_state["retorno"] = parse_iso(precarga.get("retorno"))
    
    for k in (
        # PADRE
        "padre_nombre","padre_doc_tipo","padre_doc_num","padre_dni","padre_nacionalidad",
        "padre_estado_civil","padre_direccion","padre_distrito","padre_provincia","padre_departamento",
        # MADRE
        "madre_nombre","madre_doc_tipo","madre_doc_num","madre_dni","madre_nacionalidad",
        "madre_estado_civil","madre_direccion","madre_distrito","madre_provincia","madre_departamento",
        # MENOR
        "menor_nombre","menor_doc_tipo","menor_doc_num","menor_dni","menor_nacionalidad","sexo_menor","menor_fnac",
        # VIAJE
        "origen","destino","vias","empresa","salida","retorno",
        # FIRMAS / VARIOS
        "quien_firma","quien_firma_int","acompanante","tercero_nombre","tercero_dni",
        "motivo","ciudad_evento","fecha_evento","organizador","ciudad","notario","tipo_viaje",
    ):
        if k in precarga:
            st.session_state[k] = precarga[k]
            
def hoy_en_letras(f: date | None = None):
    f = f or date.today()
    return {
        "DIA_EN_LETRAS": num2words(f.day, lang="es").upper(),
        "MES_EN_LETRAS": MESES[f.month],
        "ANIO_EN_LETRAS": num2words(f.year, lang="es").upper()
    }

def genero_menor_vars(sexo_menor: str):
    ssexo = (sexo_menor or "").upper()
    if ssexo == "F":
        return {
            "ART_MENOR":"LA","MENOR_TX":"MENOR","SOLO_A":"SOLA","REC_TX":"RECEPCIONADA",
            "IDENT_TX":"IDENTIFICADA"
        }
    return {
        "ART_MENOR":"EL","MENOR_TX":"MENOR","SOLO_A":"SOLO","REC_TX":"RECEPCIONADO",
        "IDENT_TX":"IDENTIFICADO"
    }

def viaje_vars(fecha_salida_iso: str | None, fecha_retorno_iso: str | None, vias: list[str] | None):
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
        "VERB_PL": "N" if acomp_count >= 2 else "",
        "SUF_PL": "S" if acomp_count >= 2 else "",
        "CONJ": "Y"
    }

def preparar_firmas(ctx: dict) -> dict:
    """Banderas para la sección de firmas en la plantilla."""
    for k in ("FIRMAN_AMBOS", "FIRMA_SOLO_PADRE", "FIRMA_SOLO_MADRE"):
        ctx[k] = False

    tipo = (ctx.get("TIPO_VIAJE") or "").upper()
    if tipo == "INTERNACIONAL":
        qf = (ctx.get("QUIEN_FIRMA_INT") or "").upper()
        if qf == "AMBOS":
            ctx["FIRMAN_AMBOS"] = True
        elif qf == "PADRE":
            ctx["FIRMA_SOLO_PADRE"] = True
        elif qf == "MADRE":
            ctx["FIRMA_SOLO_MADRE"] = True
        return ctx

    firmante = (ctx.get("QUIEN_FIRMA") or "").upper()
    if firmante == "AMBOS":
        ctx["FIRMAN_AMBOS"] = True
    elif firmante == "PADRE":
        ctx["FIRMA_SOLO_PADRE"] = True
    elif firmante == "MADRE":
        ctx["FIRMA_SOLO_MADRE"] = True
    return ctx

# --------- Bloques documento ----------

def _doc_bloque_menor(tipo: str, num: str, ident_tx: str, nacionalidad: str | None = None) -> str:
    """Arma el bloque de identificación del menor, respetando el género en ident_tx e incluyendo nacionalidad si corresponde."""
    t = (tipo or "").strip().upper()
    n = (num or "").strip()
    nac = (nacionalidad or "").strip().upper()

    nac_tx = f"DE NACIONALIDAD {nac}, " if nac else ""

    if not n:
        return nac_tx + ident_tx
    if t == "PASAPORTE":
        return f"{nac_tx}{ident_tx} CON PASAPORTE N° {n}"
    if t in ("DNI EXTRANJERO", "DNI_EXTRANJERO"):
        return f"{nac_tx}{ident_tx} CON CARNET DE EXTRANJERÍA N° {n}"
    return f"{nac_tx}{ident_tx} CON DOCUMENTO NACIONAL DE IDENTIDAD N° {n}"



def _doc_firma_adulto(tipo: str, num: str) -> str:
    """Etiqueta de firma (línea bajo el nombre)."""
    tipo = (tipo or "").upper()
    num = (num or "").strip()
    if not num:
        return ""
    if tipo == "PASAPORTE":
        return f"PASAPORTE N° {num}"
    if tipo in ("DNI EXTRANJERO", "DNI_EXTRANJERO"):
        return f"CARNET DE EXTRANJERÍA N° {num}"
    return f"DNI N° {num}"

# --------- Render DOCX ----------
def render_docx(plantilla_path: str, ctx: dict) -> bytes:
    doc = DocxTemplate(plantilla_path)
    doc.render(ctx)
    bio = BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.read()

def verificar_plantilla(plantilla_path: str, ctx: dict) -> set[str]:
    doc = DocxTemplate(plantilla_path)
    try:
        faltantes = doc.get_undeclared_template_variables(ctx)
        return set(faltantes) if faltantes else set()
    except Exception:
        return set()

def parse_iso(d: str | None) -> date | None:
    d = s(d)
    if not d:
        return None
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None

def _dict_from_row(cur, row):
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))

def search_por_doc_y_rol(doc: str, rol: str) -> dict | None:
    """
    Busca el último permiso donde el doc coincida SOLO con el rol indicado:
      rol: 'PADRE' | 'MADRE' | 'MENOR'
    Compara tanto *_doc_num como *_dni (compat histórico).
    """
    doc = s(doc)
    if not doc:
        return None

    rol = (rol or "").upper()
    if rol == "PADRE":
        sql = """
        SELECT * FROM permisos
        WHERE padre_doc_num = ? OR padre_dni = ?
        ORDER BY COALESCE(datetime(updated_at), datetime(fecha_registro)) DESC, id DESC
        LIMIT 1
        """
        params = (doc, doc)
    elif rol == "MADRE":
        sql = """
        SELECT * FROM permisos
        WHERE madre_doc_num = ? OR madre_dni = ?
        ORDER BY COALESCE(datetime(updated_at), datetime(fecha_registro)) DESC, id DESC
        LIMIT 1
        """
        params = (doc, doc)
    elif rol == "MENOR":
        sql = """
        SELECT * FROM permisos
        WHERE menor_doc_num = ? OR menor_dni = ?
        ORDER BY COALESCE(datetime(updated_at), datetime(fecha_registro)) DESC, id DESC
        LIMIT 1
        """
        params = (doc, doc)
    else:
        return None

    with get_conn() as conn:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        return _dict_from_row(cur, row)

def save_agenda(asunto: str, nota: str, vinculo_doc: str = "", creado_por: str = ""):
    fnow = datetime.now().isoformat(timespec="seconds")
    with get_conn(timeout_sec=10) as conn:
        conn.execute(
            "INSERT INTO agenda(fecha, asunto, nota, vinculo_doc, creado_por) VALUES(?,?,?,?,?)",
            (fnow, asunto.strip().upper(), nota.strip(), s(vinculo_doc).upper(), (creado_por or "USUARIO").upper())
        )
        conn.commit()

def fetch_agenda(vinculo_doc: str | None = None, limit: int = 20):
    sql = "SELECT fecha, asunto, nota, vinculo_doc, creado_por FROM agenda"
    params = []
    if s(vinculo_doc):
        sql += " WHERE vinculo_doc = ?"
        params.append(s(vinculo_doc).upper())
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    return rows

def valores_desde_permiso(perm: dict) -> dict:
    """
    Convierte un registro de 'permisos' a los nombres que usa el formulario_base para precarga.
    (No rellena correlativos ni anula nada; solo campos de personas/viaje.)
    """
    # Preparar vías para el multiselect
    vtx = s(perm.get("vias",""))
    if "Y/O" in vtx:
        vias_pre = [p.strip().upper() for p in vtx.split("Y/O") if p.strip()]
    elif vtx:
        vias_pre = [vtx.upper()]
    else:
        vias_pre = []

    return {
        # Cabecera
        "ciudad": perm.get("ciudad",""),
        "notario": perm.get("notario",""),
        "tipo_viaje": perm.get("tipo_viaje","NACIONAL"),

        # Padre
        "padre_nombre": perm.get("padre_nombre",""),
        "padre_dni": perm.get("padre_dni",""),
        "padre_estado_civil": perm.get("padre_estado_civil",""),
        "padre_direccion": perm.get("padre_direccion",""),
        "padre_distrito": perm.get("padre_distrito",""),
        "padre_provincia": perm.get("padre_provincia",""),
        "padre_departamento": perm.get("padre_departamento",""),
        "padre_doc_tipo": perm.get("padre_doc_tipo","DNI"),
        "padre_doc_num": perm.get("padre_doc_num", perm.get("padre_dni","")),
        "padre_nacionalidad": perm.get("padre_nacionalidad",""),

        # Madre
        "madre_nombre": perm.get("madre_nombre",""),
        "madre_dni": perm.get("madre_dni",""),
        "madre_estado_civil": perm.get("madre_estado_civil",""),
        "madre_direccion": perm.get("madre_direccion",""),
        "madre_distrito": perm.get("madre_distrito",""),
        "madre_provincia": perm.get("madre_provincia",""),
        "madre_departamento": perm.get("madre_departamento",""),
        "madre_doc_tipo": perm.get("madre_doc_tipo","DNI"),
        "madre_doc_num": perm.get("madre_doc_num", perm.get("madre_dni","")),
        "madre_nacionalidad": perm.get("madre_nacionalidad",""),

        # Menor
        "menor_nombre": perm.get("menor_nombre",""),
        "menor_dni": perm.get("menor_dni",""),
        "menor_fnac": perm.get("menor_fnac",""),
        "sexo_menor": perm.get("sexo_menor","F"),
        "menor_doc_tipo": perm.get("menor_doc_tipo","DNI"),
        "menor_doc_num": perm.get("menor_doc_num", perm.get("menor_dni","")),
        "menor_nacionalidad": perm.get("menor_nacionalidad",""),

        # Viaje
        "origen": perm.get("origen",""),
        "destino": perm.get("destino",""),
        "vias": vias_pre,
        "empresa": perm.get("empresa",""),
        "salida": perm.get("salida",""),
        "retorno": perm.get("retorno",""),

        # Acompañante
        "acompanante": perm.get("acompanante","SOLO"),
        "tercero_nombre": perm.get("tercero_nombre",""),
        "tercero_dni": perm.get("tercero_dni",""),

        # Motivo
        "motivo": perm.get("motivo",""),
        "ciudad_evento": perm.get("ciudad_evento",""),
        "fecha_evento": perm.get("fecha_evento",""),
        "organizador": perm.get("organizador",""),

        # Firmas
        "quien_firma": perm.get("firma_quien","PADRE"),
        "quien_firma_int": perm.get("firma_quien","AMBOS"),
    }

def valores_parciales_desde_perm(perm: dict, rol: str) -> dict:
    """Devuelve SOLO los campos del rol indicado: 'PADRE' | 'MADRE' | 'MENOR'."""
    rol = (rol or "").upper()
    if rol == "PADRE":
        return {
            "padre_nombre": perm.get("padre_nombre",""),
            "padre_doc_tipo": perm.get("padre_doc_tipo","DNI"),
            "padre_doc_num": perm.get("padre_doc_num", perm.get("padre_dni","")),
            "padre_dni": perm.get("padre_doc_num", perm.get("padre_dni","")),  # compat histórico
            "padre_nacionalidad": perm.get("padre_nacionalidad",""),
            "padre_estado_civil": perm.get("padre_estado_civil",""),
            "padre_direccion": perm.get("padre_direccion",""),
            "padre_distrito": perm.get("padre_distrito",""),
            "padre_provincia": perm.get("padre_provincia",""),
            "padre_departamento": perm.get("padre_departamento",""),
        }
    if rol == "MADRE":
        return {
            "madre_nombre": perm.get("madre_nombre",""),
            "madre_doc_tipo": perm.get("madre_doc_tipo","DNI"),
            "madre_doc_num": perm.get("madre_doc_num", perm.get("madre_dni","")),
            "madre_dni": perm.get("madre_doc_num", perm.get("madre_dni","")),  # compat histórico
            "madre_nacionalidad": perm.get("madre_nacionalidad",""),
            "madre_estado_civil": perm.get("madre_estado_civil",""),
            "madre_direccion": perm.get("madre_direccion",""),
            "madre_distrito": perm.get("madre_distrito",""),
            "madre_provincia": perm.get("madre_provincia",""),
            "madre_departamento": perm.get("madre_departamento",""),
        }
    # MENOR
    return {
        "menor_nombre": perm.get("menor_nombre",""),
        "menor_doc_tipo": perm.get("menor_doc_tipo","DNI"),
        "menor_doc_num": perm.get("menor_doc_num", perm.get("menor_dni","")),
        "menor_dni": perm.get("menor_doc_num", perm.get("menor_dni","")),  # compat histórico
        "menor_nacionalidad": perm.get("menor_nacionalidad",""),
        "sexo_menor": perm.get("sexo_menor",""),
        "menor_fnac": perm.get("menor_fnac",""),
    }

# ======= VALIDACIONES =======
import re
_PASSPORT_RE = re.compile(r"^[A-Z0-9\-.\s]{4,20}$", re.I)

def _es_dni(num: str) -> bool:
    n = (num or "").strip()
    return n.isdigit() and len(n) == 8

def _es_pasaporte(num: str) -> bool:
    n = (num or "").strip()
    return bool(_PASSPORT_RE.match(n))

def _doc_valido(tipo_can: str, num: str) -> bool:
    t = (tipo_can or "").upper()
    if t == "DNI":
        return num.isdigit() and len(num) == 8
    if t in ("PASAPORTE", "DNI_EXTRANJERO"):
        return bool(_PASSPORT_RE.match(num))
    return False

def _validar_firmantes(vals: dict, errores: list[str]):
    """Reglas de negocio para quién firma, según sea NACIONAL o INTERNACIONAL."""
    tipo = (vals.get("tipo_viaje") or "").upper()
    if tipo == "INTERNACIONAL":
        quien = (vals.get("quien_firma_int") or "").upper()
        if quien not in ("PADRE","MADRE","AMBOS"):
            errores.append("Internacional: selecciona quién(es) firmarán.")
        if quien in ("PADRE","AMBOS"):
            if not vals.get("padre_nombre") or not vals.get("padre_doc_num"):
                errores.append("Internacional: faltan datos del PADRE (nombre/documento).")
        if quien in ("MADRE","AMBOS"):
            if not vals.get("madre_nombre") or not vals.get("madre_doc_num"):
                errores.append("Internacional: faltan datos de la MADRE (nombre/documento).")
    else:
        quien = (vals.get("quien_firma") or "").upper()
        if quien not in ("PADRE","MADRE","AMBOS"):
            errores.append("Nacional: selecciona quién firmará (Padre/Madre/Ambos).")
        if quien in ("PADRE","AMBOS"):
            if not vals.get("padre_nombre") or not vals.get("padre_doc_num"):
                errores.append("Nacional: faltan datos del PADRE (nombre/documento).")
        if quien in ("MADRE","AMBOS"):
            if not vals.get("madre_nombre") or not vals.get("madre_doc_num"):
                errores.append("Nacional: faltan datos de la MADRE (nombre/documento).")

def _validar_documentos(vals: dict, errores: list[str]):
    """
    Valida doc según canon_doc y muestra el label correcto en el mensaje.
    No infiere tipos por el número, respeta exactamente lo que el usuario eligió.
    """
    checks = [
        ("PADRE", "padre_doc_tipo", "padre_doc_num"),
        ("MADRE", "madre_doc_tipo", "madre_doc_num"),
        ("MENOR", "menor_doc_tipo", "menor_doc_num"),
    ]

    for rol, k_tipo, k_num in checks:
        t_raw = (vals.get(k_tipo) or "").strip()          # lo que está en UI
        t_can = canon_doc(t_raw)                           # DNI | PASAPORTE | DNI_EXTRANJERO
        num   = (vals.get(k_num) or "").strip()

        if num and not _doc_valido(t_can, num):            # valida con el tipo canónico
            errores.append(f"Documento de {rol} inválido para tipo {doc_label(t_can)}.")



def _validar_fechas_y_viaje(vals: dict, errores: list[str]):
    # Edad
    if vals.get("edad_num", 0) >= 18:
        errores.append("El MENOR debe tener menos de 18 años.")
    # Vías
    vias = vals.get("vias") or []
    if not vias:
        errores.append("Selecciona al menos una VÍA (AÉREA/TERRESTRE).")
    # Fechas
    fs = vals.get("fs")
    fr = vals.get("fr")
    if fr and fs and (fr < fs):
        errores.append("La fecha de RETORNO no puede ser anterior a la de SALIDA.")

def _validar_campos_basicos(vals: dict, errores: list[str]):
    # ============ MENOR ============
    if not (vals.get("menor_nombre") and vals.get("menor_doc_num")):
        errores.append("Completa nombre y documento del MENOR.")
    
    if not vals.get("menor_fnac"):
        errores.append("La FECHA DE NACIMIENTO del MENOR es obligatoria.")
    
    # ============ VIAJE ============
    if not vals.get("origen"):
        errores.append("El campo ORIGEN es obligatorio.")
    if not vals.get("destino"):
        errores.append("El campo DESTINO es obligatorio.")
    
    # ============ PADRE ============
    if vals.get("padre_nombre"):
        if not vals.get("padre_estado_civil"):
            errores.append("El ESTADO CIVIL del PADRE es obligatorio.")
        if not vals.get("padre_direccion"):
            errores.append("La DIRECCIÓN del PADRE es obligatoria.")
        if not vals.get("padre_distrito"):
            errores.append("El DISTRITO del PADRE es obligatorio.")
        if not vals.get("padre_provincia"):
            errores.append("La PROVINCIA del PADRE es obligatoria.")
        if not vals.get("padre_departamento"):
            errores.append("El DEPARTAMENTO del PADRE es obligatorio.")
    
    # ============ MADRE ============
    if vals.get("madre_nombre"):
        if not vals.get("madre_estado_civil"):
            errores.append("El ESTADO CIVIL de la MADRE es obligatorio.")
        if not vals.get("madre_direccion"):
            errores.append("La DIRECCIÓN de la MADRE es obligatoria.")
        if not vals.get("madre_distrito"):
            errores.append("El DISTRITO de la MADRE es obligatorio.")
        if not vals.get("madre_provincia"):
            errores.append("La PROVINCIA de la MADRE es obligatoria.")
        if not vals.get("madre_departamento"):
            errores.append("El DEPARTAMENTO de la MADRE es obligatorio.")
    
    # ============ HERMANOS ============
    for i in range(len(st.session_state.get("hermanos", []))):
        h_nom = s(st.session_state.get(f"hermano_nombre_{i}", ""))
        h_doc = s(st.session_state.get(f"hermano_doc_num_{i}", ""))
        h_fnac = st.session_state.get(f"hermano_fnac_{i}")
        
        if h_nom and not h_doc:
            errores.append(f"El HERMANO {i+1} ({h_nom}) necesita un documento.")
        if h_nom and not h_fnac:
            errores.append(f"El HERMANO {i+1} ({h_nom}) necesita fecha de nacimiento.")
    
    # ============ RECEPCIÓN ============
    if vals.get("acompanante") in ["SOLO", "SOLO(A)/SOLOS(AS)"]:
        if vals.get("recibe_si") == "SI":
            rec_count = int(st.session_state.get("rec_list_count", 0))
            if rec_count == 0:
                errores.append("Si marcaste RECEPCIÓN SÍ, agrega al menos 1 persona que recibe.")
            else:
                for i in range(rec_count):
                    rec_nom = s(st.session_state.get(f"rec_nombre_{i}", ""))
                    rec_num = s(st.session_state.get(f"rec_doc_num_{i}", ""))
                    
                    if not rec_nom:
                        errores.append(f"La PERSONA QUE RECIBE {i+1} necesita un nombre.")
                    if not rec_num:
                        errores.append(f"La PERSONA QUE RECIBE {i+1} necesita un documento.")
    
    # ============ TERCERO ============
    if vals.get("acompanante") == "TERCERO":
        terceros_count = len(st.session_state.get("terceros", []))
        
        if terceros_count == 0:
            errores.append("Si el acompañante es TERCERO, agrega al menos 1 tercero.")
        else:
            for i in range(terceros_count):
                t_rol = s(st.session_state.get(f"tercero_rol_{i}", ""))
                t_nom = s(st.session_state.get(f"tercero_nombre_{i}", ""))
                t_dni = s(st.session_state.get(f"tercero_dni_{i}", ""))
                
                if not t_rol:
                    errores.append(f"El TERCERO {i+1} necesita un PARENTESCO/ROL.")
                if not t_nom:
                    errores.append(f"El TERCERO {i+1} necesita un NOMBRE.")
                if not t_dni:
                    errores.append(f"El TERCERO {i+1} necesita un DOCUMENTO.")

def validar_vals_para_generar(vals: dict) -> tuple[bool, list[str]]:
    errores: list[str] = []
    _validar_firmantes(vals, errores)
    _validar_documentos(vals, errores)
    _validar_fechas_y_viaje(vals, errores)
    _validar_campos_basicos(vals, errores)
    return (len(errores) == 0, errores)

def _mostrar_errores(errores: list[str]):
    if not errores: 
        return
    st.error("No se puede continuar por estas razones:")
    for e in errores:
        st.markdown(f"- {e}")

def _merge_nonempty(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in (extra or {}).items():
        if v not in (None, "", []):
            out[k] = v
    return out

def _ctx_comun_desde_perm(permiso: dict) -> dict:
    vias_list = []
    vtx = s(permiso.get("vias"))
    if "Y/O" in vtx:
        vias_list = [p.strip() for p in vtx.split("Y/O") if p.strip()]
    elif vtx:
        vias_list = [vtx]

    fnac_iso = s(permiso.get("menor_fnac"))
    edad_num = calcular_edad(fnac_iso) if fnac_iso else 0
    edad_letras = edad_en_letras(edad_num) if edad_num else ""

    gvars = genero_menor_vars(s(permiso.get("sexo_menor")))
    menor_bloque = _doc_bloque_menor(
        permiso.get("menor_doc_tipo"),
        permiso.get("menor_doc_num") or permiso.get("menor_dni",""),
        gvars.get("IDENT_TX","IDENTIFICADO"),
        permiso.get("menor_nacionalidad")
    )


    fecha_emision = _date_from_iso_like(permiso.get("fecha_registro"))

    return {
        "CIUDAD": s(permiso.get("ciudad")),
        "NOTARIO_NOMBRE": s(permiso.get("notario")),
        **hoy_en_letras(fecha_emision),

        # ===== PADRE =====
        "PADRE_NOMBRE": s(permiso.get("padre_nombre")),
        "PADRE_DNI": s(permiso.get("padre_dni")),
        "PADRE_ESTADO_CIVIL": s(permiso.get("padre_estado_civil")),
        "PADRE_DIRECCION": s(permiso.get("padre_direccion")),
        "PADRE_DISTRITO": s(permiso.get("padre_distrito")),
        "PADRE_PROVINCIA": s(permiso.get("padre_provincia")),
        "PADRE_DEPARTAMENTO": s(permiso.get("padre_departamento")),
        "PADRE_DOC_TIPO": s(permiso.get("padre_doc_tipo","DNI")).upper(),  # (igual que tenías)
        # CAMBIO: fallback a padre_dni para que nunca llegue vacío
        "PADRE_DOC_NUM": s(permiso.get("padre_doc_num") or permiso.get("padre_dni","")),  # CAMBIO
        "PADRE_NACIONALIDAD": s(permiso.get("padre_nacionalidad")),

        # ===== MADRE =====
        "MADRE_NOMBRE": s(permiso.get("madre_nombre")),
        "MADRE_DNI": s(permiso.get("madre_dni")),
        "MADRE_ESTADO_CIVIL": s(permiso.get("madre_estado_civil")),
        "MADRE_DIRECCION": s(permiso.get("madre_direccion")),
        "MADRE_DISTRITO": s(permiso.get("madre_distrito")),
        "MADRE_PROVINCIA": s(permiso.get("madre_provincia")),
        "MADRE_DEPARTAMENTO": s(permiso.get("madre_departamento")),
        "MADRE_DOC_TIPO": s(permiso.get("madre_doc_tipo","DNI")).upper(),
        # CAMBIO: fallback a madre_dni
        "MADRE_DOC_NUM": s(permiso.get("madre_doc_num") or permiso.get("madre_dni","")),  # CAMBIO
        "MADRE_NACIONALIDAD": s(permiso.get("madre_nacionalidad")),

        # ===== MENOR PRINCIPAL =====
        "MENOR_NOMBRE": s(permiso.get("menor_nombre")),
        "MENOR_DNI": s(permiso.get("menor_dni")),
        "MENOR_EDAD_LETRAS": s(edad_letras),
        "MENOR_EDAD_NUMERO": int(edad_num or 0),
        # CAMBIO: fuerza mayúscula coherente con el resto
        "SEXO_MENOR": s(permiso.get("sexo_menor")).upper(),  # CAMBIO
        "MENOR_DOC_BLOQUE": menor_bloque,
        # (Opcional, por si la plantilla lo usa en otro lado)
        "MENOR_DOC_TIPO": s(permiso.get("menor_doc_tipo","DNI")).upper(),  # CAMBIO (opcional)
        "MENOR_DOC_NUM": s(permiso.get("menor_doc_num") or permiso.get("menor_dni","")),  # CAMBIO (opcional)

        # ===== VIAJE =====
        "TIPO_VIAJE": s(permiso.get("tipo_viaje")),
        "ORIGEN": s(permiso.get("origen")),
        "DESTINO": s(permiso.get("destino")),
        "VIAS": vias_list,
        "EMPRESA": s(permiso.get("empresa")),
        # CAMBIO: soporta ambos labels para “solo”
        "VIAJA_SOLO": s(permiso.get("acompanante")).upper() in ["SOLO", "SOLO(A)/SOLOS(AS)"],  # CAMBIO
        "FECHA_SALIDA": s(permiso.get("salida")),
        "FECHA_RETORNO": s(permiso.get("retorno")),
        "FECHA_SALIDA_TX": fecha_iso_a_letras(s(permiso.get("salida"))) if s(permiso.get("salida")) else "",
        "FECHA_RETORNO_TX": fecha_iso_a_letras(s(permiso.get("retorno"))) if s(permiso.get("retorno")) else "",

        # ===== ACOMPAÑANTE / OBSERVACIONES =====
        "ACOMPANANTE": s(permiso.get("acompanante")),
        "ROL_ACOMPANANTE": "PADRES" if s(permiso.get("acompanante"))=="AMBOS" else s(permiso.get("acompanante")),
        "ACOMP1_NOMBRE": s(permiso.get("tercero_nombre")),
        "ACOMP1_DNI": s(permiso.get("tercero_dni")),
        "ACOMP_COUNT": 2 if s(permiso.get("acompanante"))=="AMBOS" else (1 if s(permiso.get("acompanante")) in ["PADRE","MADRE","TERCERO"] else 0),

        # CAMBIO: añade campos de recepción (para que luego OBS_TX se pueda construir al re-generar)
        "RECIBE_SI": s(permiso.get("recibe_si")).upper(),           # CAMBIO
        "REC_NOMBRE": s(permiso.get("rec_nombre")).upper(),         # CAMBIO
        "REC_DOC_TIPO": s(permiso.get("rec_doc_tipo")).upper(),     # CAMBIO
        "REC_DOC_NUM": s(permiso.get("rec_doc_num")),               # CAMBIO
        "REC_DOC_PAIS": s(permiso.get("rec_doc_pais")).upper(),     # CAMBIO

        # ===== MOTIVO =====
        "MOTIVO_VIAJE": s(permiso.get("motivo")),
        "CIUDAD_EVENTO": s(permiso.get("ciudad_evento")),
        "FECHA_EVENTO": s(permiso.get("fecha_evento")),
        "ORGANIZADOR": s(permiso.get("organizador")),

        # ===== METADATOS =====
        "ANIO": int(permiso.get("anio")),
        "NUMERO_PERMISO": int(permiso.get("numero")),
        "NSC": s(permiso.get("nsc","NSC")),

        "QUIEN_FIRMA": s(permiso.get("firma_quien")),
        "QUIEN_FIRMA_INT": s(permiso.get("firma_quien")),
    }

# ===== Helpers de documento (globales) =====

def _obs_terceros_multiples(terceros_list: list[dict], ac: dict) -> str:
    """
    Construye el texto de observaciones para múltiples terceros.
    
    Ejemplo con 2 terceros:
    "EN COMPAÑÍA DE SU ABUELA: LUDY SANTA CRUZ VERA, CON DOCUMENTO N°12345678; 
    Y/O SU HERMANO: JESUS SANTA CRUZ BRAVO, CON DOCUMENTO N°09090909, 
    QUIENES SERÁN RESPONSABLES DEL CUIDADO DEL MENOR..."
    
    Args:
        terceros_list: [{"rol": "ABUELA", "nombre": "...", "dni": "..."}, ...]
        ac: diccionario de concordancias (ART, SUST, VERB_VIAJAR, etc.)
    """
    if not terceros_list:
        return ""
    
    # Construir lista de acompañantes con formato
    partes = []
    for t in terceros_list:
        rol = s(t.get("rol", "")).upper()
        nombre = s(t.get("nombre", "")).upper()
        dni = s(t.get("dni", ""))
        
        if nombre:  # Solo incluir si tiene nombre
            parte = f"{rol}: {nombre}"
            if dni:
                parte += f", CON DOCUMENTO N°{dni}"
            partes.append(parte)
    
    if not partes:
        return ""
    
    # Unir con "; Y/O "
    acomp_txt = "; Y/O SU ".join(partes)
    
    # Concordancia singular/plural
    quien_txt = "QUIEN SERÁ RESPONSABLE" if len(partes) == 1 else "QUIENES SERÁN RESPONSABLES"
    
    return (
        f"SE DEJA CONSTANCIA QUE {ac['ART']} {ac['SUST']} {ac['VERB_VIAJAR']} "
        f"EN COMPAÑÍA DE SU {acomp_txt}; "
        f"{quien_txt} DEL CUIDADO DE {ac['ART']} {ac['SUST']} DURANTE SU ESTADÍA EN LA CIUDAD."
    )

def _doc_tx(tipo: str, num: str) -> str:
    t = (tipo or "").strip().upper()
    n = (num or "").strip()
    if not n:
        return ""
    if t == "PASAPORTE":
        return f"CON PASAPORTE N° {n}"
    if t in ("DNI EXTRANJERO", "DNI_EXTRANJERO"):
        return f"CON CARNET DE EXTRANJERÍA N° {n}"
    return f"CUYO DOCUMENTO NACIONAL DE IDENTIDAD ES N° {n}"

def regenerate_docx_for_permiso(permiso: dict, plantilla_path: str) -> str:
    ctx = _ctx_comun_desde_perm(permiso)

    # 👨‍👩‍👧‍👦 Lista combinada de menor principal + hermanos (formato legal enumerado)
    # ===== Menor principal + hermanos (mismo formato legal) =====
    menores_ctx = []

    # ---- Menor principal (NRO 1) ----
    ident_tx_p = genero_menor_vars(permiso.get("sexo_menor")).get("IDENT_TX", "IDENTIFICADO")
    doc_bloque_p = _doc_bloque_menor(
        permiso.get("menor_doc_tipo"),
        permiso.get("menor_doc_num") or permiso.get("menor_dni", ""),
        ident_tx_p,
        permiso.get("menor_nacionalidad")
    )


    # ✅ ARREGLO: normaliza la fecha a ISO antes de calcular edad
    fnac_p = permiso.get("menor_fnac")
    if fnac_p:
        try:
            if hasattr(fnac_p, "strftime"):  # date/datetime -> ISO
                fnac_iso_p = fnac_p.strftime("%Y-%m-%d")
            else:  # str -> parse a date -> ISO
                dtmp = parse_iso(fnac_p)
                fnac_iso_p = dtmp.strftime("%Y-%m-%d") if dtmp else ""
        except Exception:
            fnac_iso_p = ""
    else:
        fnac_iso_p = ""

    try:
        edad_num_p = calcular_edad(fnac_iso_p) if fnac_iso_p else ""
        edad_txt_p = edad_en_letras(edad_num_p) if (edad_num_p != "") else ""
    except Exception:
        edad_num_p, edad_txt_p = "", ""

    menores_ctx.append({
        "NRO": 1,
        "NOMBRE": s(permiso.get("menor_nombre","")).upper(),
        "DOC_BLOQUE": doc_bloque_p,
        "EDAD_NUM": edad_num_p,
        "EDAD_TXT": edad_txt_p
    })

    # ---- Hermanos (NRO 2..n) ----
    hermanos = permiso.get("hermanos", []) or []
    for idx, h in enumerate(hermanos, start=2):
        sexo_h = (h.get("sexo") or "").upper()
        ident_tx_h = genero_menor_vars(sexo_h).get("IDENT_TX", "IDENTIFICADO")

        # fnac normalizada a ISO -> edad
        fnac_h = h.get("fnac")
        if fnac_h:
            try:
                if hasattr(fnac_h, "strftime"):
                    fnac_iso = fnac_h.strftime("%Y-%m-%d")
                else:
                    dtmp = parse_iso(fnac_h)
                    fnac_iso = dtmp.strftime("%Y-%m-%d") if dtmp else ""
            except Exception:
                fnac_iso = ""
        else:
            fnac_iso = ""

        try:
            e_num = calcular_edad(fnac_iso) if fnac_iso else ""
            e_txt = edad_en_letras(e_num) if (e_num != "") else ""
        except Exception:
            e_num, e_txt = "", ""

        doc_bloque_h = _doc_bloque_menor(
            h.get("doc_tipo"),
            h.get("doc_num") or h.get("dni", ""),
            ident_tx_h,
            h.get("nacionalidad")   # <- NUEVO: usa la nacionalidad guardada del hermano
        )

        menores_ctx.append({
            "NRO": idx,
            "NOMBRE": s(h.get("nombre","")).upper(),
            "DOC_BLOQUE": doc_bloque_h,
            "EDAD_NUM": e_num,
            "EDAD_TXT": e_txt
        })

    ctx["MENORES_LISTA"] = menores_ctx
    ctx["MENORES_COUNT"] = len(menores_ctx)
    
    # ====== Concordancia y OBSERVACIONES (viajan solos / recepción / acompañados) ======

    def _acuerdos_plural_genero(sexo_principal: str, hermanos_list: list[dict]) -> dict:
        """Devuelve artículos, número y adjetivos con concordancia."""
        total = 1 + len([h for h in (hermanos_list or []) if s(h.get("nombre"))])
        all_f = (s(sexo_principal).upper() == "F") and all(
            (s(h.get("sexo")).upper() == "F") for h in (hermanos_list or []) if s(h.get("nombre"))
        )
        uno_f = (total == 1) and (s(sexo_principal).upper() == "F")

        if total == 1:
            return {
                "ART": "LA" if uno_f else "EL",
                "SUST": "MENOR",
                "VERB_VIAJAR": "VIAJARÁ",
                "ADJ_SOLO": "SOLA" if uno_f else "SOLO",
                "VERB_SER": "SERÁ",
                "ADJ_RECOGIDO": "RECOGIDA" if uno_f else "RECOGIDO",
                "PLURAL": False,
                "ALLF": uno_f
            }
        else:
            return {
                "ART": "LAS" if all_f else "LOS",
                "SUST": "MENORES",
                "VERB_VIAJAR": "VIAJARÁN",
                "ADJ_SOLO": "SOLAS" if all_f else "SOLOS",
                "VERB_SER": "SERÁN",
                "ADJ_RECOGIDO": "RECOGIDAS" if all_f else "RECOGIDOS",
                "PLURAL": True,
                "ALLF": all_f
            }

    # Concordancias con datos del permiso
    ac = _acuerdos_plural_genero(permiso.get("sexo_menor",""), permiso.get("hermanos", []))

    # Título HIJO(A)/HIJOS(AS) para la cabecera del bloque de menores
    ctx["MENORES_TITULO"] = "HIJO(A)" if ctx["MENORES_COUNT"] == 1 else "HIJOS(AS)"
    ctx["POSESIVO_PADRES"] = "SU" if ctx["MENORES_COUNT"] == 1 else "SUS"
    
    def _vias_empresa_tx(vias: str | list | None, empresa: str | None) -> str:
        """Devuelve 'POR VÍA(S) ... (EMPRESA)' en mayúsculas (admite list o str para 'vias')."""
        if isinstance(vias, list):
            vias_tx = " Y/O ".join(vias).upper() if vias else ""
        else:
            vias_tx = s(vias).upper()
        emp_tx = s(empresa).upper()
        if vias_tx and emp_tx:
            return f"POR {vias_tx} ({emp_tx})"
        if vias_tx:
            return f"POR {vias_tx}"
        if emp_tx:
            return f"({emp_tx})"
        return ""

    def _doc_num_preferido(num1: str | None, num2: str | None) -> str:
        n1, n2 = s(num1), s(num2)
        return n1 if n1 else n2

    def _acomp_bloque_perm(perm: dict) -> tuple[str, str, str, str]:
        """
        Devuelve (posesivo, rol_txt, nombre_txt, doc_txt) para PADRE/MADRE/AMBOS/TERCERO.
        posesivo: 'SU' o 'SUS'
        rol_txt: PADRE | MADRE | PADRES | <rol tercero>
        nombre_txt: puede venir vacío en AMBOS
        doc_txt: 'DOCUMENTO N° ...' si hay doc; si no, ''
        """
        acomp = s(perm.get("acompanante","")).upper()
        if acomp == "PADRE":
            rol_txt = "PADRE"
            nombre = s(perm.get("padre_nombre","")).upper()
            doc = _doc_num_preferido(perm.get("padre_doc_num"), perm.get("padre_dni"))
            doc_txt = f"DOCUMENTO N° {doc}" if doc else ""
            return "SU", rol_txt, nombre, doc_txt
        elif acomp == "MADRE":
            rol_txt = "MADRE"
            nombre = s(perm.get("madre_nombre","")).upper()
            doc = _doc_num_preferido(perm.get("madre_doc_num"), perm.get("madre_dni"))
            doc_txt = f"DOCUMENTO N° {doc}" if doc else ""
            return "SU", rol_txt, nombre, doc_txt
        elif acomp == "AMBOS":
            return "SUS", "PADRES", "", ""
        elif acomp == "TERCERO":
            rol_txt = s(perm.get("rol_acompanante","TERCERO")).upper()
            nombre = s(perm.get("acomp1_nombre","")).upper()
            doc = s(perm.get("acomp1_dni","")).upper()
            doc_txt = f"DOCUMENTO N° {doc}" if doc else ""
            return "SU", rol_txt, nombre, doc_txt
        return "SU", "", "", ""

    # Construcción de OBSERVACIONES (unificada)
    obs_tx = ""
    acompanante_val = s(permiso.get("acompanante","")).upper()

    if acompanante_val in ["SOLO(A)/SOLOS(AS)", "SOLO"]:
        if s(permiso.get("recibe_si","NO")).upper() == "NO":
            obs_tx = (
            f"SE DEJA CONSTANCIA QUE {ac['ART']} {ac['SUST']} "
            f"{ac['VERB_VIAJAR']} {ac['ADJ_SOLO']}."
            ).strip()
        else:
            # 1) intenta lista desde BD
            rec_list = []
            raw = permiso.get("rec_list_json") or ""
            try:
                rec_list = json.loads(raw) if raw else []
            except Exception:
                rec_list = []

            # 2) compat (si no hay lista, arma una con los campos legacy)
            if not rec_list:
                rec_list = [{
                    "nombre": s(permiso.get("rec_nombre","")).upper(),
                    "tipo":   s(permiso.get("rec_doc_tipo","DNI PERUANO")).upper(),
                    "num":    s(permiso.get("rec_doc_num","")),
                    "pais":   s(permiso.get("rec_doc_pais","")).upper(),
                }]

            base_viaje = (
                f"SE DEJA CONSTANCIA QUE {ac['ART']} {ac['SUST']} "
                f"{ac['VERB_VIAJAR']} {ac['ADJ_SOLO']}."
            )
            recep_txt = _obs_con_recepcion_plural(ac, rec_list)
            obs_tx = (base_viaje + " " + recep_txt).strip() if recep_txt else base_viaje
    else:
        # VIAJAN ACOMPAÑADOS (PADRE/MADRE/AMBOS/TERCERO)
        acomp_val = s(permiso.get("acompanante","")).upper()
    
        # 🆕 CASO ESPECIAL: TERCERO con múltiples acompañantes
        if acomp_val == "TERCERO":
            # Leer terceros desde terceros_json en BD
            terceros_list = []
            raw_t = permiso.get("terceros_json") or ""
            try:
                terceros_list = json.loads(raw_t) if raw_t else []
            except Exception:
                terceros_list = []
        
            # Generar OBS_TX usando la función helper
            obs_tx = _obs_terceros_multiples(terceros_list, ac)
    
        else:
            # Lógica normal para PADRE/MADRE/AMBOS
            posesivo, rol_txt, acomp_nom, acomp_doc = _acomp_bloque_perm(permiso)
            acomp_n = int(permiso.get("acomp_count") or 0)
            quien_txt = "QUIENES SERÁN RESPONSABLES" if acomp_n >= 2 else "QUIEN SERÁ RESPONSABLE"

            comp_tx = f"EN COMPAÑÍA DE {posesivo} {rol_txt}"
            if acomp_nom:
                comp_tx += f" {acomp_nom}"
            if acomp_doc:
                comp_tx += f", CON {acomp_doc}"

            obs_tx = (
                f"SE DEJA CONSTANCIA QUE {ac['ART']} {ac['SUST']} {ac['VERB_VIAJAR']} {comp_tx}; "
                f"{quien_txt} DEL CUIDADO DE {ac['ART']} {ac['SUST']} DURANTE SU ESTADÍA EN LA CIUDAD."
            )
    # Envía OBS a la plantilla
    ctx["OBS_TX"] = obs_tx
    
    
    # --- Observaciones precompuestas (por si tu .docx usa un bloque único ya armado) ---
    ctx["OBSERVACIONES_BLOQUE"] = (
        f"OBSERVACIONES: {ctx['OBS_TX']} {ctx.get('LINEA_SEPARADOR','')}"
        if ctx.get("OBS_TX") else ""
    )
    
    # Compat: por si alguna plantilla vieja aún usa HIJO_S
    ctx["HIJO_S"] = "HIJOS(AS)" if ctx["MENORES_COUNT"] and ctx["MENORES_COUNT"] > 1 else "HIJO(A)"


    ctx["PADRE_DOC_FIRMA"] = _doc_firma_adulto(permiso.get("padre_doc_tipo"), permiso.get("padre_doc_num") or permiso.get("padre_dni",""))
    ctx["MADRE_DOC_FIRMA"] = _doc_firma_adulto(permiso.get("madre_doc_tipo"), permiso.get("madre_doc_num") or permiso.get("madre_dni",""))

    # Normaliza tipo de documento a forma canónica para la PLANTILLA (SIEMPRE USAR "permiso" aquí)
    ctx["PADRE_DOC_TIPO_CAN"] = canon_doc(permiso.get("padre_doc_tipo"))
    ctx["MADRE_DOC_TIPO_CAN"] = canon_doc(permiso.get("madre_doc_tipo"))
    ctx["MENOR_DOC_TIPO_CAN"] = canon_doc(permiso.get("menor_doc_tipo"))
    
    ctx.update(concordancias_plural(ctx.get("ACOMP_COUNT", 0)))
    ctx.update(genero_menor_vars(ctx.get("SEXO_MENOR")))
    ctx.update(viaje_vars(ctx.get("FECHA_SALIDA"), ctx.get("FECHA_RETORNO"), ctx.get("VIAS")))
    ctx = preparar_firmas(ctx)
    
    # Texto para PADRE/MADRE resuelto (usa el helper global _doc_tx)
    ctx["PADRE_DOC_TEXTO"] = _doc_tx(
        permiso.get("padre_doc_tipo"),
        permiso.get("padre_doc_num") or permiso.get("padre_dni","")
    )
    ctx["MADRE_DOC_TEXTO"] = _doc_tx(
        permiso.get("madre_doc_tipo"),
        permiso.get("madre_doc_num") or permiso.get("madre_dni","")
    )

    falt = verificar_plantilla(plantilla_path, ctx)
    if falt:
        raise RuntimeError(f"Plantilla requiere variables no presentes: {sorted(falt)}")

    content = render_docx(plantilla_path, ctx)
    out_name = f"Permiso_{permiso['anio']}-{permiso['numero']}_v{permiso.get('version',1)}.docx"
    out_path = os.path.join(BASE_DIR, out_name)
    with open(out_path, "wb") as f:
        f.write(content)
    return out_name

# ============ UI ============
favicon_path = os.path.join(BASE_DIR, "assets", "favicon.png")
page_icon = "🧾"
if os.path.exists(favicon_path):
    try:
        page_icon = Image.open(favicon_path)
    except Exception:
        page_icon = "🧾"

st.set_page_config(page_title="IA Notarial – Permiso de Viaje", page_icon=page_icon, layout="centered")
cargar_css()
# Inicializa BD y sesión admin
init_db()
migrate_db()
init_admin_session()
if "_enviando" not in st.session_state:
    st.session_state._enviando = False
# Encabezado
logo_path = os.path.join(BASE_DIR, "assets", "logo.png")
if os.path.exists(logo_path):
    st.image(Image.open(logo_path), width=220)

st.markdown(
    """
    <div style="margin-top:-8px; margin-bottom:6px;">
      <h1 style="font-size: 28px; margin: 0;">IA Notarial — Permiso de Viaje de Menores</h1>
      <p style="color:#9CA3AF; margin: 2px 0 0 0;">Generador y gestor de permisos con control de correlativos</p>
    </div>
    """,
    unsafe_allow_html=True
)

st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
.block-container {max-width: 980px;}
.stButton>button {width: 100%;}
</style>
""", unsafe_allow_html=True)

# ============ Sidebar Admin ============
with st.sidebar.expander("🔐 Administrador", expanded=False):
    if not st.session_state.is_admin:
        u = st.text_input("Usuario", value="", key="admin_user_input")
        p = st.text_input("Contraseña", value="", type="password", key="admin_pass_input")
        if st.button("Iniciar sesión", use_container_width=True):
            login_admin(u, p)
    else:
        st.success(f"Conectado como **{st.session_state.admin_user or 'ADMIN'}**")
        if st.button("Cerrar sesión", use_container_width=True):
            logout_admin()
            
with st.sidebar.expander("🗓️ Agenda interna", expanded=False):
    st.caption("Crea notas internas (opcionalmente vinculadas a un DNI/Pasaporte).")
    asunto = st.text_input("Asunto")
    nota = st.text_area("Nota (detalle)")
    vinculo = st.text_input("Vincular a DNI/Pasaporte (opcional)").upper()
    if st.button("➕ Guardar nota", use_container_width=True):
        if not asunto.strip():
            st.warning("El asunto es obligatorio.")
        else:
            save_agenda(asunto, nota, vinculo, creado_por=st.session_state.admin_user or "USUARIO")
            st.success("Nota guardada en agenda.")

    st.markdown("---")
    vinculo_filtro = st.text_input("Filtrar por DNI/Pasaporte (opcional)").upper()
    limite = st.number_input("Mostrar últimos N", min_value=1, max_value=200, value=10, step=1)
    if st.button("🔄 Actualizar notas", use_container_width=True):
        st.session_state._agenda_refresh = True

    if st.session_state.get("_agenda_refresh", True):
        notas = fetch_agenda(vinculo_filtro, limit=limite)
        if notas:
            for (f, a, n, v, c) in notas:
                st.markdown(f"**{a}**  \n_{f}_  \nVínculo: `{v or '—'}`  \nPor: `{c}`  \n> {n or ''}")
                st.markdown("---")
        else:
            st.info("Sin notas.")
            
with st.sidebar.expander("🛡️ Copias de seguridad", expanded=False):
    if st.button("💾 Hacer copia ahora", use_container_width=True):
        rutas = backup_sqlite_y_emitidos(retention_days=60)
        st.success("Copia realizada ✅")
        for rp in rutas:
            st.caption(f"• {os.path.basename(rp)}")

# ======================================
# 🧰 MANTENIMIENTO (solo desarrollador)
# ======================================
with st.sidebar.expander("🧰 Mantenimiento (solo desarrollador)", expanded=False):
    DEV_KEY = "HACHIKO2025"  # cámbiala por tu clave real

    if "dev_mode" not in st.session_state:
        st.session_state.dev_mode = False

    if not st.session_state.dev_mode:
        # No uses key en el input, o si lo usas, no lo modifiques luego
        dev_pass = st.text_input("🔐 Clave de desarrollador", type="password", placeholder="Solo Hachiko")
        if st.button("Entrar modo desarrollador", use_container_width=True):
            if (dev_pass or "") == DEV_KEY:
                st.session_state.dev_mode = True
                st.rerun()  # no intentes limpiar dev_pass aquí
            else:
                st.error("Clave incorrecta ❌")
    else:
        st.info("⚙ Panel privado del desarrollador")

        colm1, colm2 = st.columns(2)
        with colm1:
            if st.button("✅ Verificar integridad", use_container_width=True):
                with get_conn() as conn:
                    out = conn.execute("PRAGMA integrity_check;").fetchone()[0]
                st.success(out)

            if st.button("🔄 Optimizar índices", use_container_width=True):
                with get_conn() as conn:
                    conn.execute("PRAGMA optimize;")
                st.success("Optimización completada ✅")

        with colm2:
            if st.button("🧹 Compactar (VACUUM)", use_container_width=True):
                st.warning("No cierres la app mientras se compacta…")
                import os
                before = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
                with get_conn(timeout_sec=60) as conn:
                    conn.execute("VACUUM;")
                after = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
                st.success(f"Compactación finalizada 🧾  Ahorro: {(before-after)/1024/1024:.2f} MB")

        st.markdown("---")
        st.subheader("🧾 Control del correlativo")

        from datetime import date
        anio_actual = date.today().year

        with get_conn() as conn:
            row = conn.execute("SELECT numero FROM correlativos WHERE anio=?", (anio_actual,)).fetchone()
            correl_actual = row[0] if row else None

        st.write(f"📅 Año actual: {anio_actual}")
        st.write(f"🔢 Correlativo actual: *{correl_actual if correl_actual is not None else 'Sin registrar'}*")

        nuevo_valor = st.number_input("Nuevo correlativo (último usado, el siguiente será +1)", min_value=0, value=correl_actual or 0, step=1)
        aplicar = st.button("💾 Actualizar correlativo", use_container_width=True)

        if aplicar:
            with get_conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO correlativos (anio, numero) VALUES (?, ?)",
                    (anio_actual, int(nuevo_valor))
                )
                conn.commit()
            st.success(f"✅ Correlativo actualizado. El siguiente permiso será *{int(nuevo_valor)+1}*.")
            st.rerun()
        
        st.divider()
        if st.button("🚪 Salir del modo desarrollador", use_container_width=True):
            st.session_state.dev_mode = False
            st.rerun()  # sin tocar dev_pass         

# ============ Selección de modo ============
modo = st.radio("¿Qué quieres hacer?", ["➕ Nuevo permiso", "✏️ Editar / Re-generar", "📇 DNI registrados", "🤖 Asistente IA"], horizontal=True)

prev_modo = st.session_state.get("_last_mode")
if prev_modo != modo:
    # 🔥 PASO 1: Marca que estamos en transición
    st.session_state._modo_transitorio = True
    
    # 🔥 PASO 2: Si vienes de "Editar/Re-generar" → limpia TODO
    if prev_modo == "✏️ Editar / Re-generar":
        st.session_state.sel_id = 0
        st.session_state.pop("pid_editing", None)
        st.session_state.modo_edicion = False
        # Limpia buscador de permisos
        for k in ["anio_buscar", "numero_buscar", "btn_buscar_correlativo"]:
            st.session_state.pop(k, None)
    
    # 🔥 PASO 3: Si entras a "Nuevo permiso" → limpieza AGRESIVA
    if modo == "➕ Nuevo permiso":
        # Limpia TODOS los widgets posibles (incluye los del modo anterior)
        keys_to_clean = [
            # Botones de búsqueda
            "btn_buscar_padre_dni", "btn_buscar_madre_dni", "btn_buscar_menor", "btn_limpiar_menor",
            "btn_buscar_correlativo",
            # Inputs de búsqueda
            "padre_dni_buscar", "madre_dni_buscar", "doc_busca_menor",
            "anio_buscar", "numero_buscar",
            # Flags internos
            "padre_dni_auto", "madre_dni_auto", "_did_clear_padre", "_did_clear_madre",
            # Selectores de provincia/distrito/departamento
            "padre_departamento_sel", "padre_provincia_sel", "padre_distrito_sel",
            "madre_departamento_sel", "madre_provincia_sel", "madre_distrito_sel",
        ]
        for k in keys_to_clean:
            st.session_state.pop(k, None)
    
    # 1) Limpia buffers de buscadores
    _clear_lookup_buffers()
    st.session_state.pop("_prefill_hermanos_pid", None)
    st.session_state.pop("_prefill_terceros_pid", None)
    st.session_state.pop("_prefill_recep_pid", None)
    
    # 🔥 Limpia botones y campos de búsqueda (para TODOS los modos)
    botones_busqueda = [
        "btn_buscar_padre_dni", "btn_buscar_madre_dni", "btn_buscar_menor", "btn_limpiar_menor",
        "padre_dni_buscar", "madre_dni_buscar", "doc_busca_menor",
        "padre_dni_auto", "madre_dni_auto", "_did_clear_padre", "_did_clear_madre",
        "btn_buscar_correlativo", "anio_buscar", "numero_buscar"
    ]
    for key in botones_busqueda:
        st.session_state.pop(key, None)
    
    # 2) Si entras a "Nuevo permiso", borra todo el formulario y siembra defaults
    if modo == "➕ Nuevo permiso":
        _clear_form_keys_for_new()
        # defaults mínimos para que los select/text no revivan valores viejos
        seed = {
            # tipos de doc por defecto
            "padre_doc_tipo": "DNI", "madre_doc_tipo": "DNI", "menor_doc_tipo": "DNI",
            # viaje
            "vias": [], "fs": None, "fr": None, "tiene_retorno": False,
            "origen": "", "destino": "", "empresa": "",
            # firmas
            "quien_firma": "PADRE", "quien_firma_int": "AMBOS",
            # acompañante/recepción
            "acompanante": "SOLO", "acomp_count": 0, "viaja_solo": False,
            "recibe_si": "NO", "rec_nombre": "", "rec_doc_tipo": "DNI PERUANO", "rec_doc_num": "", "rec_doc_pais": "",
            # menor
            "sexo_menor": "", "menor_fnac": None,
            # encabezado
            "ciudad": "", "notario": "", "tipo_viaje": "NACIONAL",
            # padre/madre/menor nombres/docs en blanco
            "padre_nombre":"", "padre_doc_num":"", "padre_dni":"", "padre_nacionalidad":"",
            "padre_estado_civil":"", "padre_direccion":"", "padre_distrito":"", "padre_provincia":"", "padre_departamento":"",
            "madre_nombre":"", "madre_doc_num":"", "madre_dni":"", "madre_nacionalidad":"",
            "madre_estado_civil":"", "madre_direccion":"", "madre_distrito":"", "madre_provincia":"", "madre_departamento":"",
            "menor_nombre":"", "menor_doc_num":"", "menor_dni":"", "menor_nacionalidad":"",
        }
        for k, v in seed.items():
            st.session_state[k] = v
        # limpia hermanos dinámicos
        if "hermanos" in st.session_state:
            for i in range(len(st.session_state["hermanos"])):
                for kk in (f"hermano_nombre_{i}", f"hermano_sexo_{i}", f"hermano_doc_tipo_{i}", f"hermano_doc_num_{i}", f"hermano_fnac_{i}"):
                    st.session_state.pop(kk, None)
        st.session_state["hermanos"] = []
        # saliendo de edición: baja flags
        st.session_state.modo_edicion = False
        st.session_state.pop("pid_editing", None)

    # 3) Memoriza modo y fuerza un rerun para que el formulario se dibuje ya limpio
    st.session_state["_last_mode"] = modo
    st.rerun()
else:
    # 🔥 Ya no estamos en transición
    st.session_state._modo_transitorio = False
# ============ Carga de plantilla ============
with st.expander("⚙️ Plantilla (.docx)", expanded=False):
    plantilla_subida = st.file_uploader("Usar una plantilla DOCX personalizada (opcional)", type=["docx"])
    if plantilla_subida:
        plantilla_path = os.path.join(BASE_DIR, "_tmp_plantilla.docx")
        with open(plantilla_path, "wb") as f:
            f.write(plantilla_subida.read())
    else:
        plantilla_path = PLANTILLA_DEFAULT

    st.write("**Plantilla activa:**", os.path.basename(plantilla_path))
    if not os.path.exists(plantilla_path):
        st.error("No se encontró la plantilla por defecto. Sube una plantilla .docx en este panel.")
        st.stop()

# ============ Formulario ============
def formulario_base(valores: dict | None = None, disabled: bool = False):
    def safe_index(options: list[str], value: str | None, default_idx: int = 0) -> int:
        """Nunca lanza ValueError (si value es '', None o inválido, devuelve default_idx)."""
        v = (value or "").strip().upper()
        try:
            return options.index(v)
        except Exception:
            return default_idx
        
    modo_edicion = st.session_state.get("modo_edicion", False)
    disable_lookup = disabled or modo_edicion
    valores = valores or {}

    # ===== Defaults seguros para recepción (evita NameError en el return) =====
    recibe_si = "NO"
    rec_nombre = ""
    rec_doc_tipo = ""
    rec_doc_num = ""
    rec_doc_pais = ""

    # --- Evita UnboundLocalError en "Nuevo permiso"
    perm = None
    if st.session_state.get("modo_edicion", False) and isinstance(valores, dict) and valores.get("id"):
        # en edición puedes querer tener el dict del permiso cargado
        perm = valores
    
    # --- Inicialización lista de hermanos (UI dinámica) ---
    if "hermanos" not in st.session_state:
        st.session_state.hermanos = []

    # --- Prefill de HERMANOS cuando estamos en Editar/Re-Generar ---
    _hermanos_bd = valores.get("hermanos") or []
    _perm_id_actual = valores.get("id") or valores.get("permiso_id") or valores.get("num_permiso")

    # 💡 SOLO si hay un permiso cargado (_perm_id_actual), hacemos prefill/limpieza
    if _perm_id_actual and isinstance(_hermanos_bd, list) and (_hermanos_bd or st.session_state.get("_prefill_hermanos_pid") != _perm_id_actual):
        # Limpia cualquier rastro anterior
        prev_len = len(st.session_state.get("hermanos", []))
        for i in range(prev_len):
            for k in (
                f"hermano_nombre_{i}", f"hermano_sexo_{i}",
                f"hermano_doc_tipo_{i}", f"hermano_doc_num_{i}",
                f"hermano_fnac_{i}",     f"hermano_nacionalidad_{i}"  # <- NUEVO
            ):
                st.session_state.pop(k, None)

        st.session_state.hermanos = []

        # Pobla desde BD
        for i, h in enumerate(_hermanos_bd):
            st.session_state.hermanos.append({})
            st.session_state[f"hermano_nombre_{i}"]   = s(h.get("nombre", ""))
            st.session_state[f"hermano_sexo_{i}"]     = (h.get("sexo", "F") or "F").upper()
            st.session_state[f"hermano_doc_tipo_{i}"] = (h.get("doc_tipo", "DNI") or "DNI").upper()
            st.session_state[f"hermano_doc_num_{i}"]  = s(h.get("doc_num", "") or h.get("dni", ""))

            _fnac_h = h.get("fnac")
            if _fnac_h:
                try:
                    if hasattr(_fnac_h, "strftime"):
                        _fnac_val = _fnac_h
                    else:
                        _fnac_tmp = parse_iso(_fnac_h)
                        _fnac_val = _fnac_tmp if _fnac_tmp else None
                except Exception:
                    _fnac_val = None
            else:
                _fnac_val = None
            st.session_state[f"hermano_fnac_{i}"] = _fnac_val
            st.session_state[f"hermano_nacionalidad_{i}"] = s(h.get("nacionalidad", "")).upper()


        st.session_state["_prefill_hermanos_pid"] = _perm_id_actual


        # Marca para no prefillar de nuevo en cada rerun
        st.session_state["_prefill_hermanos_pid"] = _perm_id_actual

    
    if not modo_edicion:
        for key in ("prefill_padre", "prefill_madre", "prefill_menor"):
            if key in st.session_state:
                valores = _merge_nonempty(valores, st.session_state[key])
        if "prefill_from_search" in st.session_state:
            v_search = dict(st.session_state.prefill_from_search)
            v_search = {k: v for k, v in v_search.items() if v not in (None, "", [])}
            valores = {**valores, **v_search}

    st.subheader("1) Cabecera")
    colA, colB = st.columns(2)
    with colA:
        ciudad = st.text_input(
            "Ciudad",
            value=s(valores.get("ciudad", "CHICLAYO")).upper(),
            disabled=disabled
        ).upper()
    with colB:
        notario = st.text_input(
            "Nombre del Notario",
            value=s(valores.get("notario", "SEGUNDO ALFREDO SANTA CRUZ VERA")).upper(),
            disabled=disabled
        ).upper()

    # ---- Tipo de viaje (seguro) ----
    opciones_viaje = ["NACIONAL", "INTERNACIONAL"]
    tipo_viaje = st.radio(
        "Tipo de viaje",
        opciones_viaje,
        index=safe_index(opciones_viaje, valores.get("tipo_viaje", "NACIONAL"), 0),
        horizontal=True,
        disabled=disabled
    )
    
    # 🔥 NUEVO: 2) Firmas (movido desde línea 4092)
    st.subheader("2) Firmas")
    opciones_firma_nac = ["PADRE", "MADRE", "AMBOS"]
    opciones_firma_int = ["PADRE", "MADRE", "AMBOS"]
    if tipo_viaje == "NACIONAL":
        quien_firma = st.radio(
            "¿Quién firmará? (Nacional)",
            opciones_firma_nac,
            index=safe_index(opciones_firma_nac, valores.get("quien_firma", "PADRE"), 0),
            horizontal=True,
            disabled=disabled
        )
        quien_firma_int = s(valores.get("quien_firma_int", "AMBOS"))
    else:
        quien_firma_int = st.radio(
            "¿Quién(es) firmarán? (Internacional)",
            opciones_firma_int,
            index=safe_index(opciones_firma_int, valores.get("quien_firma_int", "AMBOS"), 0),
            horizontal=True,
            disabled=disabled
        )
        quien_firma = s(valores.get("quien_firma", "PADRE"))
    
    # ============ 3) Comparecientes (padres) — CON API DNI + UBIGEO ============
    st.subheader("3) Comparecientes (padres)")

    # Opciones compartidas
    opciones_doc = DOC_TIPOS_UI

    # ============ LÓGICA CONDICIONAL: Mostrar PADRE/MADRE según quien firma ============
    # Determina qué selector usar según el tipo de viaje
    if tipo_viaje == "NACIONAL":
        mostrar_padre = quien_firma in ["PADRE", "AMBOS"]
        mostrar_madre = quien_firma in ["MADRE", "AMBOS"]
    else:  # INTERNACIONAL
        mostrar_padre = quien_firma_int in ["PADRE", "AMBOS"]
        mostrar_madre = quien_firma_int in ["MADRE", "AMBOS"]

    # ========== PADRE (solo si debe mostrarse) ==========
    if mostrar_padre:
        st.markdown("### 👨 Datos del Padre")

        # 🆕 Búsqueda por DNI del PADRE (MEJORADA - ahorra API + FIX UBIGEO)
        col_dni1, col_dni2 = st.columns([4, 1])
        with col_dni1:
            padre_dni_buscar = st.text_input(
                "DNI del Padre", 
                key="padre_dni_buscar",
                max_chars=8,
                help="Ingresa el DNI de 8 dígitos",
                disabled=disable_lookup
            )
        with col_dni2:
            st.write("")  # Espaciado
            st.write("")
            # Deshabilita si estamos cambiando de modo
            en_transicion = st.session_state.get("_modo_transitorio", False)
            buscar_padre_btn = st.button("🔍 Buscar", key="btn_buscar_padre_dni", disabled=(disable_lookup or en_transicion))

        # Procesar búsqueda de DNI
        if buscar_padre_btn and padre_dni_buscar:
            if len(padre_dni_buscar) == 8 and padre_dni_buscar.isdigit():
            
                # ═══════════════════════════════════════════════════════
                # 🔥 PASO 1: Buscar en BD LOCAL primero (0 peticiones API)
                # ═══════════════════════════════════════════════════════
                with st.spinner("🔎 Buscando en permisos anteriores..."):
                    perm_local = search_por_doc_y_rol(padre_dni_buscar, "PADRE")
            
                if perm_local:
                    # ✅ ENCONTRADO EN BD LOCAL (sin consumir API)
                    st.success("✅ DNI encontrado en permisos anteriores")
                
                    # Extraer datos del permiso encontrado
                    vals_padre = valores_parciales_desde_perm(perm_local, "PADRE")
                    vals_padre["padre_doc_num"] = padre_dni_buscar
                    vals_padre["padre_dni"] = padre_dni_buscar  # compatibilidad
                
                    # ══════════════════════════════════════════════════════════════════
                    # 🔥 FIX 1: Guardar en AMBAS keys (la normal Y la del selectbox)
                    # ══════════════════════════════════════════════════════════════════
                    _pid_suffix = f"_{st.session_state.get('pid_editing', 0)}" if st.session_state.get("modo_edicion", False) else ""
                
                    # Keys normales (para text_input y compatibilidad)
                    for k in ("padre_nombre", "padre_doc_tipo", "padre_doc_num", "padre_dni",
                              "padre_nacionalidad", "padre_estado_civil", "padre_direccion"):
                        st.session_state[k] = vals_padre.get(k, "")
                
                    # ══════════════════════════════════════════════════════════════════
                    # 🔥 FIX 2: Guardar UBIGEO en las keys de los selectbox
                    # ══════════════════════════════════════════════════════════════════
                    padre_dep = vals_padre.get("padre_departamento", "")
                    padre_prov = vals_padre.get("padre_provincia", "")
                    padre_dist = vals_padre.get("padre_distrito", "")
                
                    # Guardar en las keys normales también (para el payload final)
                    st.session_state["padre_departamento"] = padre_dep
                    st.session_state["padre_provincia"] = padre_prov
                    st.session_state["padre_distrito"] = padre_dist
                
                    # Guardar en las keys de los selectbox (las que usan los widgets)
                    if padre_dep:
                        st.session_state[f"padre_departamento_sel{_pid_suffix}"] = padre_dep
                
                    if padre_prov:
                        st.session_state[f"padre_provincia_sel{_pid_suffix}"] = padre_prov
                
                    if padre_dist:
                        st.session_state[f"padre_distrito_sel{_pid_suffix}"] = padre_dist
                
                    # ══════════════════════════════════════════════════════════════════
                    # 🔥 FIX 3: Pre-cargar cachés de provincias/distritos
                    # ══════════════════════════════════════════════════════════════════
                    if padre_dep:
                        # Cargar provincias del departamento
                        cache_key_prov = f"provincias_{padre_dep}"
                        if cache_key_prov not in st.session_state:
                            st.session_state[cache_key_prov] = obtener_provincias(padre_dep)
                    
                        if padre_prov:
                            # Cargar distritos de la provincia
                            cache_key_dist = f"distritos_{padre_dep}_{padre_prov}"
                            if cache_key_dist not in st.session_state:
                                st.session_state[cache_key_dist] = obtener_distritos(padre_dep, padre_prov)
                
                    # Guardar prefill para compatibilidad con el resto del código
                    st.session_state.prefill_padre = vals_padre
                
                    # 📊 Indicador de origen (trazabilidad)
                    st.info(f"📋 **Origen del dato**: Permiso N° {perm_local.get('numero'):04d}-NSC-{perm_local.get('anio')} (búsqueda local, 0 peticiones API usadas)")
                    st.rerun()
            
                else:
                    # ═══════════════════════════════════════════════════════
                    # 🔥 PASO 2: Si NO está en BD, llamar a API RENIEC
                    # ═══════════════════════════════════════════════════════
                    with st.spinner("🌐 No encontrado localmente. Consultando RENIEC... (consumirá 1 petición API)"):
                        datos_padre = consultar_dni_reniec(padre_dni_buscar)
                
                    if datos_padre:
                        # ✅ ENCONTRADO EN API RENIEC
                        st.success("✅ DNI encontrado en RENIEC")
                    
                        # Construir nombre completo en orden correcto: NOMBRES + APELLIDOS
                        nombres = datos_padre.get("nombres", "")
                        apellido_paterno = datos_padre.get("apellidoPaterno", "")
                        apellido_materno = datos_padre.get("apellidoMaterno", "")
                        nombre_completo = f"{nombres} {apellido_paterno} {apellido_materno}".strip().upper()
                    
                        # Guardar en session_state
                        st.session_state["padre_nombre"] = nombre_completo
                        st.session_state["padre_doc_num"] = padre_dni_buscar
                    
                        # 📊 Indicador de origen
                        st.info("📡 **Origen del dato**: API RENIEC (1 petición consumida)")
                        st.rerun()
                
                    else:
                        # ❌ NO ENCONTRADO ni en BD ni en API
                        st.warning("⚠️ No se pudo encontrar el DNI en ninguna fuente")
                    
                        # Mensaje detallado según el contexto
                        st.info("""
                        **Posibles causas**:
                        - El DNI no existe en la base de RENIEC
                        - Sin conexión a internet
                        - Se agotó la cuota mensual de la API (100 consultas/mes)
                        - El DNI tiene errores de digitación
                    
                        👉 **Soluciones**:
                        1. Verifica que el DNI esté correcto
                        2. Llena los campos manualmente (los inputs están habilitados)
                        3. Intenta nuevamente más tarde si es problema de cuota/internet
                        """)
            else:
                st.warning("⚠️ El DNI debe tener exactamente 8 dígitos numéricos")

        # Si viene de la API de búsqueda, usa ese valor; si no, usa valores de precarga
        if "padre_nombre" not in st.session_state:
            st.session_state["padre_nombre"] = valores.get("padre_nombre", "")

        padre_nombre = st.text_input(
            "Nombres completos del Padre",
            value=st.session_state["padre_nombre"].upper() if st.session_state.get("padre_nombre") else "",
            disabled=disabled,
            key="padre_nombre"  # 🔑 MANTENER LA KEY ORIGINAL
        ).upper()

        # Tipo de documento
        def _on_change_doc_tipo_padre():
            if canon_doc(st.session_state.get("padre_doc_tipo")) == "DNI":
                st.session_state["padre_nacionalidad"] = ""

        padre_doc_tipo = st.selectbox(
            "Padre – Tipo de documento",
            DOC_TIPOS_UI,
            index=safe_index(DOC_TIPOS_UI, valores.get("padre_doc_tipo", "DNI"), 0),
            disabled=disabled,
            key="padre_doc_tipo",
            on_change=_on_change_doc_tipo_padre,
        )

        # Determina el valor inicial ANTES del widget
        _padre_doc_val = ""
        if "padre_dni_auto" in st.session_state and st.session_state["padre_dni_auto"]:
            _padre_doc_val = st.session_state["padre_dni_auto"]
        elif "padre_doc_num" in st.session_state and st.session_state["padre_doc_num"]:
            _padre_doc_val = st.session_state["padre_doc_num"]
        elif valores.get("padre_doc_num"):
            _padre_doc_val = valores.get("padre_doc_num")
        elif valores.get("padre_dni"):
            _padre_doc_val = valores.get("padre_dni")

        padre_doc_num = st.text_input(
            f"Padre – Nº {'DNI' if canon_doc(padre_doc_tipo)=='DNI' else ('Pasaporte' if canon_doc(padre_doc_tipo)=='PASAPORTE' else 'DNI Extranjero')}",
            value=_padre_doc_val,
            disabled=disabled,
            key="padre_doc_num"
        )

        # Nacionalidad (solo si es pasaporte/extranjero)
        padre_nac = st.text_input(
            "Padre – Nacionalidad (si Pasaporte/DNI Extranjero)",
            value=s(st.session_state.get("padre_nacionalidad", valores.get("padre_nacionalidad",""))).upper(),
            disabled=disabled or (canon_doc(padre_doc_tipo) == "DNI"),
            key="padre_nacionalidad"
        ).upper()

        # Estado civil
        padre_ec = st.text_input(
            "Padre – Estado civil",
            value=s(st.session_state.get("padre_estado_civil", valores.get("padre_estado_civil",""))).upper(),
            disabled=disabled,
            key="padre_estado_civil"
        ).upper()

        # 🆕 Domicilio con UBIGEO en cascada
        st.markdown("**Domicilio del Padre:**")

        # Dirección (calle y número)
        padre_direccion = st.text_input(
            "Dirección (calle, número, urbanización)",
            value=s(st.session_state.get("padre_direccion", valores.get("padre_direccion",""))).upper(),
            disabled=disabled,
            key="padre_direccion"
        ).upper()

        # 🔧 Callbacks para limpiar cascada
        def _on_change_padre_depto():
            """Cuando cambia el departamento del padre, limpia provincia y distrito"""
            # Limpia selectores
            st.session_state.pop("padre_provincia_sel", None)
            st.session_state.pop("padre_distrito_sel", None)
        
            # 🔥 NUEVO: Limpia cachés de provincias/distritos
            keys_to_remove = [k for k in st.session_state.keys() 
                              if k.startswith("provincias_") or k.startswith("distritos_")]
            for k in keys_to_remove:
                st.session_state.pop(k, None)

        def _on_change_padre_prov():
            """Cuando cambia la provincia del padre, limpia distrito"""
            st.session_state.pop("padre_distrito_sel", None)

        # Selector de UBIGEO en cascada
        col_u1, col_u2, col_u3 = st.columns(3)

        # 🔥 NUEVO: Key dinámica basada en el permiso que se está editando
        _pid_suffix = f"_{st.session_state.get('pid_editing', 0)}" if st.session_state.get("modo_edicion", False) else ""

        with col_u1:
            # Cargar departamentos (caché global)
            if "departamentos_list" not in st.session_state:
                with st.spinner("Cargando departamentos..."):
                    st.session_state["departamentos_list"] = obtener_departamentos()

            padre_departamento = st.selectbox(
                "Departamento",
                options=[""] + st.session_state.get("departamentos_list", []),
                index=0 if not valores.get("padre_departamento") else (
                    st.session_state.get("departamentos_list", []).index(valores.get("padre_departamento")) + 1 
                    if valores.get("padre_departamento") in st.session_state.get("departamentos_list", []) else 0
                ),
                disabled=disabled,
                key=f"padre_departamento_sel{_pid_suffix}",  # 🔥 KEY DINÁMICA
                on_change=_on_change_padre_depto
            )

        with col_u2:
            if padre_departamento:
                # Cargar provincias del departamento seleccionado
                cache_key = f"provincias_{padre_departamento}"
                if cache_key not in st.session_state:
                    with st.spinner("Cargando provincias..."):
                        st.session_state[cache_key] = obtener_provincias(padre_departamento)

                padre_provincia = st.selectbox(
                    "Provincia",
                    options=[""] + st.session_state.get(cache_key, []),
                    index=0 if not valores.get("padre_provincia") else (
                        st.session_state.get(cache_key, []).index(valores.get("padre_provincia")) + 1 
                        if valores.get("padre_provincia") in st.session_state.get(cache_key, []) else 0
                    ),
                    disabled=disabled,
                    key=f"padre_provincia_sel{_pid_suffix}",  # 🔥 KEY DINÁMICA
                    on_change=_on_change_padre_prov
                )
            else:
                padre_provincia = st.selectbox("Provincia", [""], key=f"padre_provincia_sel_empty{_pid_suffix}", disabled=True)

        with col_u3:
            if padre_departamento and padre_provincia:
                # Cargar distritos de la provincia seleccionada
                cache_key = f"distritos_{padre_departamento}_{padre_provincia}"
                if cache_key not in st.session_state:
                    with st.spinner("Cargando distritos..."):
                        st.session_state[cache_key] = obtener_distritos(padre_departamento, padre_provincia)

                padre_distrito = st.selectbox(
                    "Distrito",
                    options=[""] + st.session_state.get(cache_key, []),
                    index=0 if not valores.get("padre_distrito") else (
                        st.session_state.get(cache_key, []).index(valores.get("padre_distrito")) + 1 
                        if valores.get("padre_distrito") in st.session_state.get(cache_key, []) else 0
                    ),
                    disabled=disabled,
                    key=f"padre_distrito_sel{_pid_suffix}"  # 🔥 KEY DINÁMICA
                )
            else:
                padre_distrito = st.selectbox("Distrito", [""], key=f"padre_distrito_sel_empty{_pid_suffix}", disabled=True)

        # Guardar valores en variables normales (no solo session_state)
        padre_dist = padre_distrito
        padre_prov = padre_provincia
        padre_dep = padre_departamento
        padre_dir = padre_direccion
    else:
        # 🔥 NUEVO: Si NO se muestra el padre, asignar valores vacíos
        padre_nombre = ""
        padre_doc_tipo = "DNI"
        padre_doc_num = ""
        padre_nac = ""
        padre_ec = ""
        padre_direccion = ""
        padre_departamento = ""
        padre_provincia = ""
        padre_distrito = ""
        padre_dist = ""
        padre_prov = ""
        padre_dep = ""
        padre_dir = ""

    st.markdown("---")

    # ========== MADRE (solo si debe mostrarse) ==========
    if mostrar_madre:
        st.markdown("### 👩 Datos de la Madre")

        # 🆕 Búsqueda por DNI de la MADRE (MEJORADA - ahorra API + FIX UBIGEO)
        col_dni1, col_dni2 = st.columns([4, 1])
        with col_dni1:
            madre_dni_buscar = st.text_input(
                "DNI de la Madre", 
                key="madre_dni_buscar",
                max_chars=8,
                help="Ingresa el DNI de 8 dígitos",
                disabled=disable_lookup
            )
        with col_dni2:
            st.write("")  # Espaciado
            st.write("")
            # Deshabilita si estamos cambiando de modo
            en_transicion = st.session_state.get("_modo_transitorio", False)
            buscar_madre_btn = st.button("🔍 Buscar", key="btn_buscar_madre_dni", disabled=(disable_lookup or en_transicion))

        # Procesar búsqueda de DNI
        if buscar_madre_btn and madre_dni_buscar:
            if len(madre_dni_buscar) == 8 and madre_dni_buscar.isdigit():
            
                # ═══════════════════════════════════════════════════════
                # 🔥 PASO 1: Buscar en BD LOCAL primero (0 peticiones API)
                # ═══════════════════════════════════════════════════════
                with st.spinner("🔎 Buscando en permisos anteriores..."):
                    perm_local = search_por_doc_y_rol(madre_dni_buscar, "MADRE")
            
                if perm_local:
                    # ✅ ENCONTRADO EN BD LOCAL (sin consumir API)
                    st.success("✅ DNI encontrado en permisos anteriores")
                
                    # Extraer datos del permiso encontrado
                    vals_madre = valores_parciales_desde_perm(perm_local, "MADRE")
                    vals_madre["madre_doc_num"] = madre_dni_buscar
                    vals_madre["madre_dni"] = madre_dni_buscar  # compatibilidad
                
                    # ══════════════════════════════════════════════════════════════════
                    # 🔥 FIX 1: Guardar en AMBAS keys (la normal Y la del selectbox)
                    # ══════════════════════════════════════════════════════════════════
                    _pid_suffix = f"_{st.session_state.get('pid_editing', 0)}" if st.session_state.get("modo_edicion", False) else ""
                
                    # Keys normales (para text_input y compatibilidad)
                    for k in ("madre_nombre", "madre_doc_tipo", "madre_doc_num", "madre_dni",
                              "madre_nacionalidad", "madre_estado_civil", "madre_direccion"):
                        st.session_state[k] = vals_madre.get(k, "")
                
                    # ══════════════════════════════════════════════════════════════════
                    # 🔥 FIX 2: Guardar UBIGEO en las keys de los selectbox
                    # ══════════════════════════════════════════════════════════════════
                    madre_dep = vals_madre.get("madre_departamento", "")
                    madre_prov = vals_madre.get("madre_provincia", "")
                    madre_dist = vals_madre.get("madre_distrito", "")
                
                    # Guardar en las keys normales también (para el payload final)
                    st.session_state["madre_departamento"] = madre_dep
                    st.session_state["madre_provincia"] = madre_prov
                    st.session_state["madre_distrito"] = madre_dist
                
                    # Guardar en las keys de los selectbox (las que usan los widgets)
                    if madre_dep:
                        st.session_state[f"madre_departamento_sel{_pid_suffix}"] = madre_dep
                
                    if madre_prov:
                        st.session_state[f"madre_provincia_sel{_pid_suffix}"] = madre_prov
                
                    if madre_dist:
                        st.session_state[f"madre_distrito_sel{_pid_suffix}"] = madre_dist
                
                    # ══════════════════════════════════════════════════════════════════
                    # 🔥 FIX 3: Pre-cargar cachés de provincias/distritos
                    # ══════════════════════════════════════════════════════════════════
                    if madre_dep:
                        # Cargar provincias del departamento
                        cache_key_prov = f"provincias_{madre_dep}"
                        if cache_key_prov not in st.session_state:
                            st.session_state[cache_key_prov] = obtener_provincias(madre_dep)
                    
                        if madre_prov:
                            # Cargar distritos de la provincia
                            cache_key_dist = f"distritos_{madre_dep}_{madre_prov}"
                            if cache_key_dist not in st.session_state:
                                st.session_state[cache_key_dist] = obtener_distritos(madre_dep, madre_prov)
                
                    # Guardar prefill para compatibilidad con el resto del código
                    st.session_state.prefill_madre = vals_madre
                
                    # 📊 Indicador de origen (trazabilidad)
                    st.info(f"📋 **Origen del dato**: Permiso N° {perm_local.get('numero'):04d}-NSC-{perm_local.get('anio')} (búsqueda local, 0 peticiones API usadas)")
                    st.rerun()
            
                else:
                    # ═══════════════════════════════════════════════════════
                    # 🔥 PASO 2: Si NO está en BD, llamar a API RENIEC
                    # ═══════════════════════════════════════════════════════
                    with st.spinner("🌐 No encontrado localmente. Consultando RENIEC... (consumirá 1 petición API)"):
                        datos_madre = consultar_dni_reniec(madre_dni_buscar)
                
                    if datos_madre:
                        # ✅ ENCONTRADO EN API RENIEC
                        st.success("✅ DNI encontrado en RENIEC")
                    
                        # Construir nombre completo en orden correcto: NOMBRES + APELLIDOS
                        nombres = datos_madre.get("nombres", "")
                        apellido_paterno = datos_madre.get("apellidoPaterno", "")
                        apellido_materno = datos_madre.get("apellidoMaterno", "")
                        nombre_completo = f"{nombres} {apellido_paterno} {apellido_materno}".strip().upper()
                    
                        # Guardar en session_state
                        st.session_state["madre_nombre"] = nombre_completo
                        st.session_state["madre_doc_num"] = madre_dni_buscar
                    
                        # 📊 Indicador de origen
                        st.info("📡 **Origen del dato**: API RENIEC (1 petición consumida)")
                        st.rerun()
                
                    else:
                        # ❌ NO ENCONTRADO ni en BD ni en API
                        st.warning("⚠️ No se pudo encontrar el DNI en ninguna fuente")
                    
                        # Mensaje detallado según el contexto
                        st.info("""
                        **Posibles causas**:
                        - El DNI no existe en la base de RENIEC
                        - Sin conexión a internet
                        - Se agotó la cuota mensual de la API (100 consultas/mes)
                        - El DNI tiene errores de digitación
                    
                        👉 **Soluciones**:
                        1. Verifica que el DNI esté correcto
                        2. Llena los campos manualmente (los inputs están habilitados)
                        3. Intenta nuevamente más tarde si es problema de cuota/internet
                        """)
            else:
                st.warning("⚠️ El DNI debe tener exactamente 8 dígitos numéricos")

       # Si viene de la API de búsqueda, usa ese valor; si no, usa valores de precarga
        if "madre_nombre" not in st.session_state:
            st.session_state["madre_nombre"] = valores.get("madre_nombre", "")

        madre_nombre = st.text_input(
            "Nombres completos de la Madre",
            value=st.session_state["madre_nombre"].upper() if st.session_state.get("madre_nombre") else "",
            disabled=disabled,
            key="madre_nombre"  # 🔑 MANTENER LA KEY ORIGINAL
        ).upper()

        # Tipo de documento
        def _on_change_doc_tipo_madre():
            if canon_doc(st.session_state.get("madre_doc_tipo")) == "DNI":
                st.session_state["madre_nacionalidad"] = ""

        madre_doc_tipo = st.selectbox(
            "Madre – Tipo de documento",
            DOC_TIPOS_UI,
            index=safe_index(DOC_TIPOS_UI, valores.get("madre_doc_tipo", "DNI"), 0),
            disabled=disabled,
            key="madre_doc_tipo",
            on_change=_on_change_doc_tipo_madre,
        )

        # Determina el valor inicial ANTES del widget
        _madre_doc_val = ""
        if "madre_dni_auto" in st.session_state and st.session_state["madre_dni_auto"]:
            _madre_doc_val = st.session_state["madre_dni_auto"]
        elif "madre_doc_num" in st.session_state and st.session_state["madre_doc_num"]:
            _madre_doc_val = st.session_state["madre_doc_num"]
        elif valores.get("madre_doc_num"):
            _madre_doc_val = valores.get("madre_doc_num")
        elif valores.get("madre_dni"):
            _madre_doc_val = valores.get("madre_dni")

        madre_doc_num = st.text_input(
            f"Madre – Nº {'DNI' if canon_doc(madre_doc_tipo)=='DNI' else ('Pasaporte' if canon_doc(madre_doc_tipo)=='PASAPORTE' else 'DNI Extranjero')}",
            value=_madre_doc_val,
            disabled=disabled,
            key="madre_doc_num"
        )

        # Nacionalidad (solo si es pasaporte/extranjero)
        madre_nac = st.text_input(
            "Madre – Nacionalidad (si Pasaporte/DNI Extranjero)",
            value=s(st.session_state.get("madre_nacionalidad", valores.get("madre_nacionalidad",""))).upper(),
            disabled=disabled or (canon_doc(madre_doc_tipo) == "DNI"),
            key="madre_nacionalidad"
        ).upper()

        # Estado civil
        madre_ec = st.text_input(
            "Madre – Estado civil",
            value=s(st.session_state.get("madre_estado_civil", valores.get("madre_estado_civil",""))).upper(),
            disabled=disabled,
            key="madre_estado_civil"
        ).upper()

        # 🆕 Domicilio con UBIGEO en cascada
        st.markdown("**Domicilio de la Madre:**")

        # Dirección (calle y número)
        madre_direccion = st.text_input(
            "Dirección (calle, número, urbanización)",
            value=s(st.session_state.get("madre_direccion", valores.get("madre_direccion",""))).upper(),
            disabled=disabled,
            key="madre_direccion"
        ).upper()

        # 🔧 Callbacks para limpiar cascada
        def _on_change_madre_depto():
            """Cuando cambia el departamento de la madre, limpia provincia y distrito"""
            # Limpia selectores
            st.session_state.pop("madre_provincia_sel", None)
            st.session_state.pop("madre_distrito_sel", None)
        
            # 🔥 NUEVO: Limpia cachés de provincias/distritos
            keys_to_remove = [k for k in st.session_state.keys() 
                              if k.startswith("provincias_") or k.startswith("distritos_")]
            for k in keys_to_remove:
                st.session_state.pop(k, None)

        def _on_change_madre_prov():
            """Cuando cambia la provincia de la madre, limpia distrito"""
            st.session_state.pop("madre_distrito_sel", None)

        # Selector de UBIGEO en cascada
        col_u1, col_u2, col_u3 = st.columns(3)

        # 🔥 MISMO sufijo dinámico que usamos para el padre
        _pid_suffix = f"_{st.session_state.get('pid_editing', 0)}" if st.session_state.get("modo_edicion", False) else ""

        with col_u1:
            # Usar la misma lista de departamentos que ya cargamos para el padre
            if "departamentos_list" not in st.session_state:
                with st.spinner("Cargando departamentos..."):
                    st.session_state["departamentos_list"] = obtener_departamentos()

            madre_departamento = st.selectbox(
                "Departamento",
                options=[""] + st.session_state.get("departamentos_list", []),
                index=0 if not valores.get("madre_departamento") else (
                    st.session_state.get("departamentos_list", []).index(valores.get("madre_departamento")) + 1 
                    if valores.get("madre_departamento") in st.session_state.get("departamentos_list", []) else 0
                ),
                disabled=disabled,
                key=f"madre_departamento_sel{_pid_suffix}",  # 🔥 KEY DINÁMICA
                on_change=_on_change_madre_depto
            )

        with col_u2:
            if madre_departamento:
                # Cargar provincias del departamento seleccionado
                cache_key = f"provincias_{madre_departamento}"
                if cache_key not in st.session_state:
                    with st.spinner("Cargando provincias..."):
                        st.session_state[cache_key] = obtener_provincias(madre_departamento)

                madre_provincia = st.selectbox(
                    "Provincia",
                    options=[""] + st.session_state.get(cache_key, []),
                    index=0 if not valores.get("madre_provincia") else (
                        st.session_state.get(cache_key, []).index(valores.get("madre_provincia")) + 1 
                        if valores.get("madre_provincia") in st.session_state.get(cache_key, []) else 0
                    ),
                    disabled=disabled,
                    key=f"madre_provincia_sel{_pid_suffix}",  # 🔥 KEY DINÁMICA
                    on_change=_on_change_madre_prov
                )
            else:
                madre_provincia = st.selectbox("Provincia", [""], key=f"madre_provincia_sel_empty{_pid_suffix}", disabled=True)

        with col_u3:
            if madre_departamento and madre_provincia:
                # Cargar distritos de la provincia seleccionada
                cache_key = f"distritos_{madre_departamento}_{madre_provincia}"
                if cache_key not in st.session_state:
                    with st.spinner("Cargando distritos..."):
                        st.session_state[cache_key] = obtener_distritos(madre_departamento, madre_provincia)

                madre_distrito = st.selectbox(
                    "Distrito",
                    options=[""] + st.session_state.get(cache_key, []),
                    index=0 if not valores.get("madre_distrito") else (
                        st.session_state.get(cache_key, []).index(valores.get("madre_distrito")) + 1 
                        if valores.get("madre_distrito") in st.session_state.get(cache_key, []) else 0
                    ),
                    disabled=disabled,
                    key=f"madre_distrito_sel{_pid_suffix}"  # 🔥 KEY DINÁMICA
                )
            else:
                madre_distrito = st.selectbox("Distrito", [""], key=f"madre_distrito_sel_empty{_pid_suffix}", disabled=True)

        # Guardar valores en variables normales (no solo session_state)
        madre_dist = madre_distrito
        madre_prov = madre_provincia
        madre_dep = madre_departamento
        madre_dir = madre_direccion
    else:
        # 🔥 NUEVO: Si NO se muestra la madre, asignar valores vacíos
        madre_nombre = ""
        madre_doc_tipo = "DNI"
        madre_doc_num = ""
        madre_nac = ""
        madre_ec = ""
        madre_direccion = ""
        madre_departamento = ""
        madre_provincia = ""
        madre_distrito = ""
        madre_dist = ""
        madre_prov = ""
        madre_dep = ""
        madre_dir = ""

    # ============ 4) Menor ============
    st.subheader("4) Menor")

    # Usa el helper de arriba
    def safe_index(options: list[str], value: str | None, default_idx: int = 0) -> int:
        v = (value or "").strip().upper()
        try:
            return options.index(v)
        except Exception:
            return default_idx

    opciones_doc_menor = DOC_TIPOS_UI

    # --- Buscador por documento del MENOR (MEJORADO - solo BD local) ---
    st.caption("🔎 Buscar MENOR por DNI/Pasaporte")
    doc_menor = st.text_input("Doc. MENOR", key="doc_busca_menor", disabled=(disabled or st.session_state.get("modo_edicion", False))).strip().upper()

    col_m1, col_m2 = st.columns(2)
    with col_m1:
        # Deshabilita si estamos cambiando de modo
        en_transicion = st.session_state.get("_modo_transitorio", False)
        if st.button("Buscar MENOR", key="btn_buscar_menor", disabled=(disabled or st.session_state.get("modo_edicion", False) or en_transicion)):
            if not doc_menor:
                st.warning("⚠️ Ingresa el documento del MENOR para buscar.")
            else:
                # ═══════════════════════════════════════════════════════
                # 🔥 Búsqueda en BD LOCAL (menores normalmente no usan API)
                # ═══════════════════════════════════════════════════════
                with st.spinner("🔎 Buscando en permisos anteriores..."):
                    perm = search_por_doc_y_rol(doc_menor, "MENOR")
            
                if perm:
                    # ✅ ENCONTRADO EN BD LOCAL
                
                    # Verificar si está oculto
                    if is_doc_oculto("MENOR", doc_menor):
                        st.warning("⚠️ Este documento de MENOR está marcado como OCULTO. No se precargará.")
                    else:
                        st.success("✅ MENOR encontrado en permisos anteriores")
                    
                        # Extraer datos del menor
                        vals_men = valores_parciales_desde_perm(perm, "MENOR")
                        numero_doc = doc_menor or perm.get("menor_doc_num") or perm.get("menor_dni", "")
                        vals_men["menor_doc_num"] = numero_doc
                        vals_men["menor_dni"] = numero_doc
                    
                        # NO inferir tipo de documento (respetar lo que viene del registro)
                        if not vals_men.get("menor_doc_tipo"):
                            vals_men["menor_doc_tipo"] = st.session_state.get("menor_doc_tipo", "DNI")
                    
                        # Guardar en session_state
                        st.session_state.prefill_menor = vals_men
                        for k in ("menor_nombre", "menor_doc_tipo", "menor_doc_num", "menor_nacionalidad",
                                  "menor_fnac", "sexo_menor", "menor_dni"):
                            if k == "menor_fnac":
                                st.session_state[k] = parse_iso(vals_men.get(k)) or date(2015, 1, 1)
                            else:
                                st.session_state[k] = vals_men.get(k, "")
                    
                        # 📊 Indicador de origen (trazabilidad)
                        st.info(f"📋 **Origen del dato**: Permiso N° {perm.get('numero'):04d}-NSC-{perm.get('anio')} (búsqueda local)")
                        st.success("✅ Datos del MENOR completados automáticamente.")
                        st.rerun()
                else:
                    # ❌ NO ENCONTRADO en BD
                    st.info(f"ℹ️ No hay registros previos del MENOR con documento **{doc_menor}**.")
                    st.caption("👉 Llena los campos manualmente para crear el primer permiso de este menor.")

    with col_m2:
        # Deshabilita si estamos cambiando de modo
        en_transicion = st.session_state.get("_modo_transitorio", False)
        st.button("Limpiar MENOR", key="btn_limpiar_menor", on_click=_limpiar_menor_cb, disabled=(disabled or st.session_state.get("modo_edicion", False) or en_transicion))

    # --- Campos del MENOR (mismo estilo que Padre/Madre) ---
    m1, m2, m3 = st.columns(3)
    with m1:
        menor_nombre = st.text_input(
            "Menor – Nombres y Apellidos",
            value=s(valores.get("menor_nombre", "")).upper(),
            disabled=disabled,
            key="menor_nombre"  # mantiene tu key
        ).upper()

    with m2:
        # 🔥 CAMBIO: Ahora SEXO va en la columna 2
        opciones_sexo = ["F", "M"]
        sexo_menor = st.selectbox(
            "Sexo del menor",
            opciones_sexo,
            index=safe_index(opciones_sexo, valores.get("sexo_menor", "F"), 0),
            disabled=disabled,
            key="sexo_menor"
        )

    with m3:
        # 🔥 CAMBIO: Ahora TIPO DE DOC va en la columna 3
        # Callback del menor: definir ANTES del selectbox
        def _on_change_doc_tipo_menor():
            if canon_doc(st.session_state.get("menor_doc_tipo")) == "DNI":
                st.session_state["menor_nacionalidad"] = ""

        menor_doc_tipo = st.selectbox(
            "Menor – Tipo de documento",
            DOC_TIPOS_UI,
            index=safe_index(DOC_TIPOS_UI, valores.get("menor_doc_tipo", "DNI"), 0),
            disabled=disabled,
            key="menor_doc_tipo",
            on_change=_on_change_doc_tipo_menor,  # <- AQUÍ
        )

    # 🔧 Normaliza la fecha del MENOR en session_state a datetime.date
    _fnac_state = st.session_state.get("menor_fnac", (valores.get("menor_fnac") or None))
    if isinstance(_fnac_state, str):
        # parse_iso debe devolver datetime.date o None si no puede
        _fnac_state = parse_iso(_fnac_state)
    if _fnac_state is None:
        _fnac_state = date(2015, 1, 1)
    st.session_state["menor_fnac"] = _fnac_state
    # Número (dinámico según tipo)
    menor_doc_num = st.text_input(
        f"Menor – Nº {'DNI' if canon_doc(menor_doc_tipo)=='DNI' else ('Pasaporte' if canon_doc(menor_doc_tipo)=='PASAPORTE' else 'DNI Extranjero')}",
        value=s(valores.get("menor_doc_num") or valores.get("menor_dni", "")),
        disabled=disabled,
        key="menor_doc_num"
    )

    # Nacionalidad: solo si PASAPORTE (si es DNI, deshabilitada)
    menor_nac = st.text_input(
        "Menor – Nacionalidad (si Pasaporte/DNI Extranjero)",
        value=s(valores.get("menor_nacionalidad", "")).upper(),
        disabled=disabled or (canon_doc(menor_doc_tipo) == "DNI"),
        key="menor_nacionalidad"
    ).upper()
    


    # Fecha de nacimiento: ¡UN SOLO date_input!
    fnac_default = parse_iso(valores.get("menor_fnac")) or date(2015, 1, 1)
    fnac = st.date_input(
        "Fecha de nacimiento",
        value=fnac_default,
        min_value=date(1900, 1, 1),
        max_value=date.today(),
        disabled=disabled,
        key="menor_fnac"  # este widget mantiene un date en session_state
    )
    # === 3) Menor ===
    st.markdown("### 👨‍👩‍👧‍👦 Hermanos biológicos (opcional)")

    if st.button("➕ Agregar hermano biológico", key="btn_add_hermano"):
        # (El dict aquí es solo un slot visual; los valores reales viven en session_state)
        st.session_state.hermanos.append({"nombre": "", "dni": "", "fnac": None})
        st.rerun()

    _min_d = date(1900, 1, 1)
    _max_d = date.today()

    for i in range(len(st.session_state.hermanos)):
        st.divider()
        st.markdown(f"**Hermano {i+1}**")

        # Nombre y sexo
        c1, c2 = st.columns([2, 1])
        with c1:
            st.text_input(
                f"Hermano {i+1} – Nombre completo",
                key=f"hermano_nombre_{i}",
                value=st.session_state.get(f"hermano_nombre_{i}", "")
            )
        with c2:
            st.selectbox(
                f"Hermano {i+1} – Sexo",
                ["F", "M"],
                key=f"hermano_sexo_{i}",
                index=0 if st.session_state.get(f"hermano_sexo_{i}", "F") == "F" else 1
            )

        # Tipo/N° de documento
        c3, c4 = st.columns([1, 1])
        with c3:
            _h_opts = ["DNI", "PASAPORTE", "DNI EXTRANJERO"]
            _curr   = (st.session_state.get(f"hermano_doc_tipo_{i}", "DNI") or "DNI").upper()
            _idx    = _h_opts.index(_curr) if _curr in _h_opts else 0

            st.selectbox(
                f"Hermano {i+1} – Tipo de documento",
                _h_opts,
                key=f"hermano_doc_tipo_{i}",
                index=_idx
            )

        with c4:
            # ✅ ESTA ES LA PARTE QUE PREGUNTABAS (va aquí)
            lbl = "Nº DNI" if _curr == "DNI" else ("Nº Pasaporte" if _curr == "PASAPORTE" else "Nº DNI Extranjero")
            st.text_input(
                f"Hermano {i+1} – {lbl}",
                key=f"hermano_doc_num_{i}",
                value=st.session_state.get(f"hermano_doc_num_{i}", "")
            )
        
        # Nacionalidad del hermano (solo si PASAPORTE o DNI EXTRANJERO)
        _h_tipo = (st.session_state.get(f"hermano_doc_tipo_{i}", "DNI") or "DNI").upper()
        if _h_tipo in ("PASAPORTE", "DNI EXTRANJERO"):
            st.text_input(
                f"Hermano {i+1} – Nacionalidad",
                key=f"hermano_nacionalidad_{i}",
                value=st.session_state.get(f"hermano_nacionalidad_{i}", "")
            )
        else:
            # Si cambian a DNI, limpiamos la nacionalidad para no guardar basura
            st.session_state.pop(f"hermano_nacionalidad_{i}", None)
  
        # Fecha de nacimiento — MISMO RANGO QUE EL MENOR (1900…HOY)
        _h_fnac_val = st.session_state.get(f"hermano_fnac_{i}", None)
        if _h_fnac_val is None:
            # default estable dentro del rango (puedes cambiarlo si quieres)
            _h_fnac_val = date(2015, 1, 1)
        # Recorta por si viene algo fuera de rango (seguridad)
        if _h_fnac_val < _min_d: _h_fnac_val = _min_d
        if _h_fnac_val > _max_d: _h_fnac_val = _max_d

        st.date_input(
            f"Hermano {i+1} – Fecha de nacimiento",
            key=f"hermano_fnac_{i}",
            value=_h_fnac_val,
            min_value=_min_d,
            max_value=_max_d,
        )

        # Eliminar hermano
        cols = st.columns([1, 4])
        with cols[0]:
            if st.button(f"❌ Eliminar", key=f"del_hermano_{i}"):
                for kk in (
                    f"hermano_nombre_{i}",
                    f"hermano_sexo_{i}",
                    f"hermano_doc_tipo_{i}",
                    f"hermano_doc_num_{i}",
                    f"hermano_fnac_{i}",
                    f"hermano_nacionalidad_{i}",   # <- NUEVO: limpiar nacionalidad también
                ):
                    st.session_state.pop(kk, None)
                st.session_state.hermanos.pop(i)
                st.rerun()

    # Edad calculada (en memoria, para validación y template)
    edad_num = calcular_edad(fnac.strftime("%Y-%m-%d"))
    edad_letras = edad_en_letras(edad_num)
    if (edad_num >= 18) and (not disabled):
        st.warning("⚠ La persona ya es *mayor de edad* (18+). Este permiso es para *menores*.")

    st.subheader("5) Viaje")
    v1, v2 = st.columns(2)
    with v1:
        origen = st.text_input(
            "Origen",
            value=s(valores.get("origen", "")).upper(),
            disabled=disabled
        ).upper()
        destino = st.text_input(
            "Destino",
            value=s(valores.get("destino", "")).upper(),
            disabled=disabled
        ).upper()
    with v2:
        vias_permitidas = ["TERRESTRE", "AÉREA"]
        vtx = s(valores.get("vias", ""))
        if isinstance(valores.get("vias"), list):
            vias_pre = [v for v in valores["vias"] if v in vias_permitidas]
        else:
            if "Y/O" in vtx:
                vias_pre = [p.strip().upper() for p in vtx.split("Y/O") if p.strip().upper() in vias_permitidas]
            elif vtx:
                vias_pre = [vtx.upper()] if vtx.upper() in vias_permitidas else []
            else:
                vias_pre = []
        if not vias_pre:
            vias_pre = ["AÉREA"]

        vias = st.multiselect("Vía", vias_permitidas, default=vias_pre, disabled=disabled)
        empresa = st.text_input(
            "Empresa (opcional)",
            value=s(valores.get("empresa", "")).upper(),
            disabled=disabled
        ).upper()

    fs_default = parse_iso(valores.get("salida")) or date.today()
    fr_default = parse_iso(valores.get("retorno")) or date.today()
    fs = st.date_input("Fecha de salida", value=fs_default, disabled=disabled)

    tiene_retorno_default = bool(s(valores.get("retorno", "")))
    tiene_retorno = st.toggle("Tiene fecha de retorno", value=tiene_retorno_default, disabled=disabled)
    fr = st.date_input("Fecha de retorno", value=fr_default, disabled=(not tiene_retorno or disabled)) if tiene_retorno else None

    st.subheader("6) Acompañante / Observaciones")

        # --- Opciones (con nuevo rótulo y compatibilidad hacia atrás) ---
    opciones_acomp = ["PADRE", "MADRE", "AMBOS", "TERCERO", "SOLO(A)/SOLOS(AS)"]
    _ini = s(valores.get("acompanante", "SOLO")).upper()
    if _ini == "SOLO":
        _ini = "SOLO(A)/SOLOS(AS)"  # compatibilidad con permisos antiguos
    acomp_idx = safe_index(opciones_acomp, _ini, opciones_acomp.index("SOLO(A)/SOLOS(AS)"))

    acompanante = st.radio(
        "¿Quién acompaña? (si viaja solo/a, elige 'SOLO(A)/SOLOS(AS)')",
        opciones_acomp,
        index=acomp_idx,
        horizontal=True,
        disabled=disabled
    )

    rol_acompanante, acomp1_nombre, acomp1_dni = "", "", ""
    acomp_count, viaja_solo = 0, False

    # --- Lógica de acompañante ---
    if acompanante in ("SOLO", "SOLO(A)/SOLOS(AS)"):
        viaja_solo = True

    elif acompanante == "PADRE":
        acomp_count = 1
        rol_acompanante = "PADRE"
        acomp1_nombre = s(valores.get("padre_nombre", ""))
        acomp1_dni = s(valores.get("padre_doc_num") or valores.get("padre_dni", ""))

    elif acompanante == "MADRE":
        acomp_count = 1
        rol_acompanante = "MADRE"
        acomp1_nombre = s(valores.get("madre_nombre", ""))
        acomp1_dni = s(valores.get("madre_doc_num") or valores.get("madre_dni", ""))

    elif acompanante == "AMBOS":
        acomp_count = 2
        rol_acompanante = "PADRES"

    elif acompanante == "TERCERO":
        # --- Inicializar lista de terceros en session_state ---
        if "terceros" not in st.session_state:
            st.session_state.terceros = []
    
        # Si no hay ninguno, crea el primero automáticamente
        if len(st.session_state.terceros) == 0:
            st.session_state.terceros.append({})
    
        acomp_count = len(st.session_state.terceros)
    
        # --- Botón para agregar más terceros ---
        if st.button("➕ Agregar tercero adicional", key="btn_add_tercero"):
            st.session_state.terceros.append({})
            st.rerun()
    
        st.markdown("---")
    
        # --- Renderizar campos para cada tercero ---
        for i in range(len(st.session_state.terceros)):
            st.markdown(f"**Tercero {i+1}**")
        
            col1, col2 = st.columns([2, 1])
            with col1:
                st.text_input(
                    f"Parentesco del tercero {i+1} (TUTOR/TUTORA/TÍA/TÍO/ABUELO/ABUELA/HERMANO/HERMANA)",
                    key=f"tercero_rol_{i}",
                    value=st.session_state.get(f"tercero_rol_{i}", ""),
                    disabled=disabled
                )
            with col2:
                pass  # Espacio visual
        
            st.text_input(
                f"Nombre del tercero {i+1}",
                key=f"tercero_nombre_{i}",
                value=st.session_state.get(f"tercero_nombre_{i}", ""),
                disabled=disabled
            )
        
            st.text_input(
                f"DNI/Pasaporte del tercero {i+1}",
                key=f"tercero_dni_{i}",
                value=st.session_state.get(f"tercero_dni_{i}", ""),
                disabled=disabled
            )
        
            # Botón eliminar (solo si hay más de 1 tercero)
            if len(st.session_state.terceros) > 1:
                if st.button(f"❌ Eliminar tercero {i+1}", key=f"del_tercero_{i}"):
                    # Limpiar keys del session_state
                    for k in (f"tercero_rol_{i}", f"tercero_nombre_{i}", f"tercero_dni_{i}"):
                        st.session_state.pop(k, None)
                    st.session_state.terceros.pop(i)
                    st.rerun()
        
            st.markdown("---")
    
        # Recopilar datos de todos los terceros para el payload
        rol_acompanante = ""  # No se usa en múltiples terceros
        acomp1_nombre = ""    # No se usa en múltiples terceros
        acomp1_dni = ""       # No se usa en múltiples terceros


    # ================== RECEPCIÓN AL ARRIBO (MÚLTIPLES PERSONAS) ==================
    # Solo cuando viajan solos
    recibe_si = "NO"  # valor de retorno (para que el llamador pueda usarlo)
    if acompanante in ("SOLO", "SOLO(A)/SOLOS(AS)"):
        st.markdown("#### ¿A su arribo será(n) recogido(s)/a(s)?")

        recibe_si = st.selectbox(
            "Seleccione una opción",
            ["NO", "SI"],
            index=1 if s(valores.get("recibe_si","NO")).upper()=="SI" else 0,
            key="recibe_si",
            disabled=disabled
        )

        # --------- LIMPIEZA ESTRICTA CUANDO ES "NO" ---------
        if s(st.session_state.get("recibe_si","NO")).upper() == "NO":
            # 1) contador a 0
            st.session_state["rec_list_count"] = 0
            # 2) borra TODAS las filas dinámicas rec_*_i si las hubiera
            i = 0
            while True:
                had_any = False
                for kk in (f"rec_nombre_{i}", f"rec_doc_tipo_{i}", f"rec_doc_num_{i}", f"rec_doc_pais_{i}"):
                    if kk in st.session_state:
                        st.session_state.pop(kk, None)
                        had_any = True
                if not had_any:
                    break
                i += 1
            # (opcional) deja también vacíos los campos "simples" por compat
            for kk in ("rec_nombre","rec_doc_tipo","rec_doc_num","rec_doc_pais"):
                st.session_state.pop(kk, None)
            # No renderizamos filas si es NO
        else:
            # ====== SI = "SI" → mostrar/editar filas ======
            # Inicializa contador (mínimo 1) de forma segura
            if "rec_list_count" not in st.session_state:
                st.session_state["rec_list_count"] = max(1, int(valores.get("rec_list_count", 0)))
            total = int(st.session_state["rec_list_count"])

            for i in range(total):
                st.markdown(f"Persona que recibe #{i+1}")

                c1, c2 = st.columns([2, 1])
                with c1:
                    st.text_input(
                        "Nombre completo de la persona que recibe",
                        value=s(st.session_state.get(f"rec_nombre_{i}", "")).upper(),
                        key=f"rec_nombre_{i}",
                        disabled=disabled
                    )
                with c2:
                    st.selectbox(
                        "Documento de la persona que recibe",
                        ["DNI PERUANO", "DNI EXTRANJERO", "PASAPORTE"],
                        index=0 if s(st.session_state.get(f"rec_doc_tipo_{i}",""))=="" else
                           ["DNI PERUANO", "DNI EXTRANJERO", "PASAPORTE"].index(
                               s(st.session_state.get(f"rec_doc_tipo_{i}","DNI PERUANO")).upper()
                        ),
                        key=f"rec_doc_tipo_{i}",
                        disabled=disabled
                    )

                c3, c4 = st.columns(2)
                with c3:
                    st.text_input(
                        "N° de documento",
                        value=s(st.session_state.get(f"rec_doc_num_{i}", "")),
                        key=f"rec_doc_num_{i}",
                        disabled=disabled
                    )
                with c4:
                    tipo_i = st.session_state.get(f"rec_doc_tipo_{i}", "DNI PERUANO")
                    st.text_input(
                        "País del DNI extranjero (p.ej. DEL REINO DE ESPAÑA)",
                        value=s(st.session_state.get(f"rec_doc_pais_{i}", "")).upper(),
                        key=f"rec_doc_pais_{i}",
                        disabled=disabled or (tipo_i != "DNI EXTRANJERO")
                    )

            cadd, crem = st.columns(2)
            with cadd:
                if st.button("➕ Agregar otra persona que recibe", use_container_width=True):
                    st.session_state["rec_list_count"] += 1
                    st.rerun()
            with crem:
                if st.session_state["rec_list_count"] > 1 and st.button("➖ Quitar la última", use_container_width=True):
                    st.session_state["rec_list_count"] -= 1
                    # limpia claves de la última fila
                    i = st.session_state["rec_list_count"]
                    for kk in (f"rec_nombre_{i}", f"rec_doc_tipo_{i}", f"rec_doc_num_{i}", f"rec_doc_pais_{i}"):
                        st.session_state.pop(kk, None)
                    st.rerun()

    else:
        # --------- NO VIAJAN SOLOS → LIMPIEZA COMPLETA ---------
        st.session_state["recibe_si"] = "NO"
        st.session_state["rec_list_count"] = 0
        i = 0
        while True:
            had_any = False
            for kk in (f"rec_nombre_{i}", f"rec_doc_tipo_{i}", f"rec_doc_num_{i}", f"rec_doc_pais_{i}"):
                if kk in st.session_state:
                    st.session_state.pop(kk, None)
                    had_any = True
            if not had_any:
                break
            i += 1
        for kk in ("rec_nombre","rec_doc_tipo","rec_doc_num","rec_doc_pais"):
            st.session_state.pop(kk, None)
    # ================== FIN RECEPCIÓN AL ARRIBO ==================

    st.subheader("7) Motivo del viaje")
    motivo = st.text_input(
        "Motivo",
        value=s(valores.get("motivo", "")).upper(),
        disabled=disabled
    ).upper()
    ciudad_evento = st.text_input(
        "Ciudad del evento (opcional)",
        value=s(valores.get("ciudad_evento", "")).upper(),
        disabled=disabled
    ).upper()
    fecha_evento = st.text_input(
        "Fecha del evento (opcional, ej. 10/12/2025)",
        value=s(valores.get("fecha_evento", "")),
        disabled=disabled
    )
    organizador = st.text_input(
        "Organizador (opcional)",
        value=s(valores.get("organizador", "")).upper(),
        disabled=disabled
    ).upper()

    # 🔥 NOTA: La sección "7) Firmas" YA NO EXISTE AQUÍ (se movió arriba después de "Tipo de viaje")
    
    # --- refresco único tras limpiar ---
    if st.session_state.get("_did_clear_padre"):
        st.session_state["_did_clear_padre"] = False
        st.rerun()
    if st.session_state.get("_did_clear_madre"):
        st.session_state["_did_clear_madre"] = False
        st.rerun()
        
    # ---- payload ----
    payload = {
        "ciudad": ciudad,
        "notario": notario,
        "tipo_viaje": tipo_viaje,

        "padre_nombre": padre_nombre,
        "padre_dni": padre_doc_num,  # compat histórico
        "padre_estado_civil": padre_ec,
        "padre_direccion": padre_dir,
        "padre_distrito": padre_dist,
        "padre_provincia": padre_prov,
        "padre_departamento": padre_dep,
        "padre_doc_tipo": st.session_state.get("padre_doc_tipo", "") if mostrar_padre else "",
        "padre_doc_num": st.session_state.get("padre_doc_num") or st.session_state.get("padre_dni", "") if mostrar_padre else "",
        "padre_nacionalidad": st.session_state.get("padre_nacionalidad", "") if mostrar_padre else "",

        "madre_nombre": madre_nombre,
        "madre_dni": madre_doc_num,  # compat histórico
        "madre_estado_civil": madre_ec,
        "madre_direccion": madre_dir,
        "madre_distrito": madre_dist,
        "madre_provincia": madre_prov,
        "madre_departamento": madre_dep,
        "madre_doc_tipo": st.session_state.get("madre_doc_tipo", "") if mostrar_madre else "",
        "madre_doc_num": st.session_state.get("madre_doc_num") or st.session_state.get("madre_dni", "") if mostrar_madre else "",
        "madre_nacionalidad": st.session_state.get("madre_nacionalidad", "") if mostrar_madre else "",

        "menor_nombre": menor_nombre,
        "menor_dni": menor_doc_num,  # compat histórico
        "menor_fnac": fnac.strftime("%Y-%m-%d"),
        "sexo_menor": sexo_menor,
        "menor_doc_tipo": st.session_state.get("menor_doc_tipo", ""),
        "menor_doc_num": st.session_state.get("menor_doc_num") or st.session_state.get("menor_dni", ""),
        "menor_nacionalidad": st.session_state.get("menor_nacionalidad", ""),

        "edad_num": edad_num,
        "edad_letras": edad_letras,

        "origen": origen,
        "destino": destino,
        "vias": vias,
        "empresa": empresa,
        "fs": fs,
        "fr": fr,
        "tiene_retorno": bool(fr),

        "acompanante": acompanante,
        "rol_acompanante": rol_acompanante,
        "acomp1_nombre": acomp1_nombre,
        "acomp1_dni": acomp1_dni,
        "acomp_count": 2 if acompanante == "AMBOS" else (1 if acompanante in ["PADRE", "MADRE", "TERCERO"] else 0),
        "viaja_solo": viaja_solo,
        
        "recibe_si": recibe_si,
        "rec_nombre": rec_nombre,
        "rec_doc_tipo": rec_doc_tipo,
        "rec_doc_num": rec_doc_num,
        "rec_doc_pais": rec_doc_pais,

        "motivo": motivo,
        "ciudad_evento": ciudad_evento,
        "fecha_evento": fecha_evento,
        "organizador": organizador,

        "quien_firma": quien_firma,
        "quien_firma_int": quien_firma_int,
    }
    return payload

# =========================
# 🤖 ASISTENTE IA (FAQ + SQL + NLQ + Router + Semántico opcional + Logs)
# =========================
import re, unicodedata, calendar
from datetime import date, datetime, timedelta
from textwrap import dedent

# NOTA: asegúrate de tener importados en tu app globalmente:
# import pandas as pd
# import streamlit as st
# from io import BytesIO   # solo si exportas

# ---- Utilidades básicas ----
def _safe_to_int(x, default=None):
    if x is None: return default
    m = re.search(r"\d+", str(x))
    return int(m.group()) if m else default

def _extract_year(text, default=None):
    for y in re.findall(r"\b(19\d{2}|20\d{2})\b", str(text)):
        yi = _safe_to_int(y)
        if yi and 2000 <= yi <= 2100:
            return yi
    return default

def _norm(x: str | None) -> str:
    return (x or "").strip()

def _u(x: str | None) -> str:
    return _norm(x).upper()

def _like_token(s: str) -> str:
    return f"%{_norm(s).upper()}%"

# ---- Limpieza/normalización de lenguaje natural ----
def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")

def _clean_text(x: str) -> str:
    t = _strip_accents(str(x)).lower()
    return re.sub(r"[^a-z0-9 ]+", " ", t).strip()

def _contains(t: str, needle: str) -> bool:
    return needle in t

_MONTHS_ES = {
    "enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,
    "julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12
}

def _ymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def _pick_tipo(txtc: str) -> str | None:
    if any(k in txtc for k in ["internacional", "internacion", "internacio"]):
        return "INTERNACIONAL"
    if any(k in txtc for k in ["nacional", "naciona", "nacionale"]):
        return "NACIONAL"
    return None

def _wants_count(txtc: str) -> bool:
    return any(k in txtc for k in ["cuanto","cuantos","cuantas","total","numero","conteo","contar"])

def _range_for_phrase(txtc: str) -> tuple[str, str] | None:
    today = date.today()
    if _contains(txtc, "hoy"):
        return _ymd(today), _ymd(today + timedelta(days=1))
    if _contains(txtc, "ayer"):
        return _ymd(today - timedelta(days=1)), _ymd(today)
    if _contains(txtc, "esta semana"):
        monday = today - timedelta(days=today.weekday())
        return _ymd(monday), _ymd(monday + timedelta(days=7))
    if _contains(txtc, "semana pasada"):
        monday = today - timedelta(days=today.weekday()+7)
        return _ymd(monday), _ymd(monday + timedelta(days=7))
    if _contains(txtc, "este mes"):
        first = today.replace(day=1)
        next_first = date(first.year + (1 if first.month==12 else 0), 1 if first.month==12 else first.month+1, 1)
        return _ymd(first), _ymd(next_first)
    if _contains(txtc, "mes pasado"):
        first = date(today.year-1, 12, 1) if today.month == 1 else date(today.year, today.month-1, 1)
        next_first = date(first.year + (1 if first.month==12 else 0), 1 if first.month==12 else first.month+1, 1)
        return _ymd(first), _ymd(next_first)
    if _contains(txtc, "este ano") or _contains(txtc, "este anio") or _contains(txtc, "este año"):
        first = date(today.year, 1, 1)
        return _ymd(first), _ymd(date(today.year+1, 1, 1))
    m = re.search(r"\ben\s+([a-z]+)(?:\s+de\s+(\d{4}))?", txtc)
    if m:
        mes_txt = m.group(1)
        y = int(m.group(2)) if m.group(2) else today.year
        if mes_txt in _MONTHS_ES:
            mm = _MONTHS_ES[mes_txt]
            first = date(y, mm, 1)
            last = calendar.monthrange(y, mm)[1]
            return _ymd(first), _ymd(date(y, mm, last) + timedelta(days=1))
    return None

# ---- FAQ cortas (sin BD) ----
def _faq_answer(q: str) -> str | None:
    Q = _u(q)
    F = [
        (r"COMO\s+ANULO|ANULAR\s+PERMISO",
         "Para anular: ✏ Editar / Re-generar → busca el permiso → ⚠ Anular permiso → escribe ANULAR y confirma."),
        (r"DIFERENCIAS?\s+ENTRE\s+EMITIDO|ANULAD|CORREGID",
         "Estados: EMITIDO (vigente), CORREGIDO (nueva versión), ANULADO (no válido; solo lectura)."),
        (r"DONDE\s+SE\s+GUARDA|RUTA\s+DE\s+ARCHIVOS",
         "Los DOCX se guardan en emitidos/<año>/. Si quieres, podemos separar corregidos en emitidos/corregidos/."),
        (r"EXPORTAR|EXCEL|CONTROL\s+ANUAL",
         "En ✏ Editar / Re-generar → 📤 Exportaciones puedes descargar el Excel anual."),
    ]
    for pat, ans in F:
        if re.search(pat, Q):
            return ans
    return None

# ---- Acceso a BD (usa tu get_conn) ----
def _query(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

# ---- Presentación ----
def _fmt_listado(rows: list[dict], max_n=10) -> str:
    if not rows: return "No encontré resultados."
    out = []
    for r in rows[:max_n]:
        nro = f"{int(r['numero']):04d}" if r.get('numero') is not None else "----"
        anio = r.get('anio', "----")
        out.append(f"- Permiso {nro} — NSC-{anio} | {r.get('tipo_viaje','')} | Destino: {r.get('destino','')} | Menor: {r.get('menor_nombre','')} | Firma: {r.get('firma_quien','')}")
    if len(rows) > max_n: out.append(f"… y {len(rows)-max_n} más.")
    return "\n".join(out)

def _show_rows_table(rows: list[dict]):
    if not rows: return
    df = pd.DataFrame(rows, columns=["id","anio","numero","tipo_viaje","destino","firma_quien","menor_nombre"])
    st.dataframe(df, use_container_width=True)

def _show_chart_if_applicable(rows: list[dict], query: str):
    """
    Muestra gráficos automáticos si la consulta es de tipo estadístico.
    """
    if not rows or len(rows) < 2:
        return  # No hay suficientes datos
    
    Q = _u(query)
    
    # 📊 Gráfico por TIPO DE VIAJE
    if "tipo_viaje" in rows[0]:
        tipos = {}
        for r in rows:
            t = s(r.get("tipo_viaje","")).upper()
            if t:
                tipos[t] = tipos.get(t, 0) + 1
        
        if len(tipos) > 1:
            st.markdown("### 📊 Distribución por Tipo de Viaje")
            df_tipos = pd.DataFrame(list(tipos.items()), columns=["Tipo", "Cantidad"])
            st.bar_chart(df_tipos.set_index("Tipo"))
    
    # 📊 Gráfico por DESTINO (top 10)
    if "destino" in rows[0] and len(rows) > 5:
        destinos = {}
        for r in rows:
            d = s(r.get("destino","")).upper()
            if d:
                destinos[d] = destinos.get(d, 0) + 1
        
        if len(destinos) > 1:
            st.markdown("### 📊 Top Destinos")
            sorted_dest = sorted(destinos.items(), key=lambda x: x[1], reverse=True)[:10]
            df_dest = pd.DataFrame(sorted_dest, columns=["Destino", "Cantidad"])
            st.bar_chart(df_dest.set_index("Destino"))

# ── A) ROUTER AVANZADO ───────────────────────────────────────
def _extract_entities(q_raw: str):
    Q  = _u(q_raw)
    Qc = _clean_text(q_raw)
    rng = _range_for_phrase(Qc)
    tipo = _pick_tipo(Qc)
    m_doc = re.search(r"(?:dni|documento|doc|pasaporte)\s+([a-z0-9]+)", Q, re.I)
    doc = m_doc.group(1).upper() if m_doc else None
    m_corr = re.search(r"(?:PERMISO|NSC)[^\d](\d{4}).?(\d+)", Q)
    correl = (int(m_corr.group(1)), int(m_corr.group(2))) if m_corr and m_corr.group(1).isdigit() and m_corr.group(2).isdigit() else None
    m_dest = re.search(r"(?:A|HACIA)\s+([A-ZÁÉÍÓÚÑ ]+)", Q)
    destino = _norm(m_dest.group(1)).upper() if m_dest else None
    m_nom = re.search(r"(?:NOMBRE|APELLID(?:O|OS|AS))\s+([A-ZÁÉÍÓÚÑ ]+)", Q)
    nombre = _norm(m_nom.group(1)).upper() if m_nom else None
    m_year = re.search(r"\b(20\d{2}|19\d{2})\b", Q)
    anio = int(m_year.group(1)) if m_year else None
    if anio and not (2000 <= anio <= 2100): anio = None
    wants_count = _wants_count(Qc)
    return {"rng": rng, "tipo": tipo, "doc": doc, "correl": correl, "destino": destino, "nombre": nombre, "anio": anio, "wants_count": wants_count}

def _h_conteo_periodo(ent):
    if not ent["rng"]: return None
    a, b = ent["rng"]
    if ent["tipo"]:
        row = _query("""SELECT COUNT(*) c FROM permisos
                        WHERE date(fecha_registro) >= ? AND date(fecha_registro) < ? AND UPPER(tipo_viaje)=?""",
                     (a, b, ent["tipo"]))[0]
        return (f"Se emitieron {row['c']} permisos {ent['tipo'].lower()}s entre {a} y {b}.", [])
    else:
        row = _query("""SELECT COUNT(*) c FROM permisos
                        WHERE date(fecha_registro) >= ? AND date(fecha_registro) < ?""", (a, b))[0]
        return (f"Se emitieron {row['c']} permisos entre {a} y {b}.", [])

def _h_listado_periodo(ent):
    if not ent["rng"]: return None
    a, b = ent["rng"]
    if ent["tipo"]:
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre, date(fecha_registro) as fecha
                         FROM permisos
                         WHERE date(fecha_registro) >= ? AND date(fecha_registro) < ? AND UPPER(tipo_viaje)=?
                         ORDER BY fecha ASC, numero ASC""", (a, b, ent["tipo"]))
        return (f"Permisos {ent['tipo'].lower()}s en {a} → {b}: {len(rows)}.", rows)
    else:
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre, date(fecha_registro) as fecha
                         FROM permisos
                         WHERE date(fecha_registro) >= ? AND date(fecha_registro) < ?
                         ORDER BY fecha ASC, numero ASC""", (a, b))
        return (f"Permisos en {a} → {b}: {len(rows)}.", rows)

def _h_correlativo(ent):
    if not ent["correl"]: return None
    anio, numero = ent["correl"]
    rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                     FROM permisos WHERE anio=? AND numero=?""", (anio, numero))
    msg = f"Encontré el correlativo {numero:04d} — NSC-{anio}." if rows else f"No encontré el correlativo {numero:04d} — NSC-{anio}."
    return (msg, rows)

def _h_documento(ent):
    if not ent["doc"]: return None
    like_d = f"%{ent['doc']}%"
    rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                     FROM permisos
                     WHERE UPPER(COALESCE(menor_doc_num, menor_dni, '')) LIKE ?
                        OR UPPER(COALESCE(padre_doc_num, padre_dni, '')) LIKE ?
                        OR UPPER(COALESCE(madre_doc_num, madre_dni, '')) LIKE ?
                     ORDER BY anio DESC, numero ASC""", (like_d, like_d, like_d))
    return (f"Permisos que contienen el documento {ent['doc']}: {len(rows)}.", rows)

def _h_destino(ent):
    if not ent["destino"]: return None
    like_t = f"%{ent['destino']}%"
    if ent["anio"]:
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                         FROM permisos WHERE anio=? AND UPPER(destino) LIKE ?
                         ORDER BY numero ASC""", (ent["anio"], like_t))
    else:
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                         FROM permisos WHERE UPPER(destino) LIKE ?
                         ORDER BY anio DESC, numero ASC""", (like_t,))
    return (f"Permisos con destino parecido a {ent['destino'].title()}: {len(rows)}.", rows)

def _h_nombre(ent):
    if not ent["nombre"]: return None
    like_n = f"%{ent['nombre']}%"
    rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                     FROM permisos
                     WHERE UPPER(menor_nombre) LIKE ?
                        OR UPPER(padre_nombre) LIKE ?
                        OR UPPER(madre_nombre) LIKE ?
                     ORDER BY anio DESC, numero ASC""", (like_n, like_n, like_n))
    return (f"Permisos que coinciden con el nombre/apellidos {ent['nombre'].title()}: {len(rows)}.", rows)

def _h_tipo_anio(ent):
    if not ent["tipo"] or not ent["anio"]: return None
    rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                     FROM permisos WHERE anio=? AND UPPER(tipo_viaje)=?
                     ORDER BY numero ASC""", (ent["anio"], ent["tipo"]))
    return (f"Permisos {ent['tipo'].lower()} en {ent['anio']}: {len(rows)}.", rows)

def _advanced_router(q: str):
    ent = _extract_entities(q)
    
    # ========== HANDLERS ORIGINALES ==========
    if ent["rng"] and ent["wants_count"]:
        return _h_conteo_periodo(ent)
    if ent["rng"]:
        return _h_listado_periodo(ent)
    r = _h_correlativo(ent)
    if r: return r
    r = _h_documento(ent)
    if r: return r
    r = _h_tipo_anio(ent)
    if r: return r
    r = _h_destino(ent)
    if r: return r
    r = _h_nombre(ent)
    if r: return r
    
    # ========== HANDLERS ESPECÍFICOS DE NOTARÍA ==========
    if re.search(r"VIAJAN?\s+SOL[OA]|SIN\s+ACOMPA[ÑN]ANTE", _u(q)):
        return _h_viajan_solos(ent)
    if re.search(r"CON\s+HERMANOS|HERMANOS?\s+BIOL[ÓO]GIC", _u(q)):
        return _h_con_hermanos(ent)
    if re.search(r"RECEPCI[ÓO]N|RECOG(EN|IDO)|RECIB(EN|IDO)", _u(q)):
        return _h_con_recepcion(ent)
    if re.search(r"ANULAD[OA]S?", _u(q)):
        return _h_anulados(ent)
    if re.search(r"TOP\s+DESTINOS|DESTINOS?\s+M[ÁA]S\s+FRECUENT", _u(q)):
        return _h_top_destinos(ent)
    if re.search(r"RECIENTE|ULTIMOS?|ÚLTIMOS?", _u(q)):
        return _h_ultimos(ent)
    
    # 🔥 NUEVO: Análisis avanzado
    r = _h_analisis_avanzado(q)
    if r: return r
    
    return None

# ── B) FAQ SEMÁNTICO LIGERO (RapidFuzz, sin Torch) ─────────────────────────
# Si RapidFuzz no está, el modo semántico se desactiva sin romper la app.
_RF_READY = False
try:
    from rapidfuzz import fuzz
    _RF_READY = True
except Exception:
    _RF_READY = False

# Base de conocimiento de FAQs (puedes ampliarla)
_FAQ_KB = [
    ("¿Cómo anulo un permiso?", "Ir a ✏ Editar/Re-generar → ⚠ Anular permiso → escribir ANULAR y confirmar."),
    ("¿Dónde se guardan los DOCX?", "En emitidos/<año>/; podemos crear emitidos/corregidos si deseas."),
    ("¿Cómo exporto el Excel anual?", "En ✏ Editar/Re-generar → 📤 Exportaciones → Descargar Excel anual."),
]
# OJO: _FAQ_CORPUS se define AQUÍ MISMO, así siempre existe
_FAQ_CORPUS = [q for q, _ in _FAQ_KB]

def _norm_q_sem(q: str) -> str:
    # Reutiliza tu normalizador para ser tolerante a faltas
    return _clean_text(q)

def _faq_semantic_answer(q: str) -> str | None:
    if not _RF_READY:
        return None
    qn = _norm_q_sem(q)
    best_score, best_idx = -1, -1
    for i, cand in enumerate(_FAQ_CORPUS):
        score = fuzz.token_set_ratio(qn, _norm_q_sem(cand))
        if score > best_score:
            best_score, best_idx = score, i
    # Umbral ajustable
    if best_score >= 78 and best_idx >= 0:
        return _FAQ_KB[best_idx][1]
    return None

def _suggest_alternatives(q: str) -> str | None:
    """Si la consulta no devolvió resultados, sugiere alternativas."""
    Q = _u(q)
    
    # Caso 1: Buscó un destino que no existe
    m = re.search(r"(?:DESTINO|A|HACIA)\s+([A-ZÁÉÍÓÚÑ ]+)", Q)
    if m:
        destino_buscado = m.group(1).upper()
        prefix = destino_buscado[:3]
        similar = _query("""
            SELECT DISTINCT UPPER(destino) AS dest
            FROM permisos
            WHERE UPPER(destino) LIKE ?
            LIMIT 5
        """, (f"{prefix}%",))
        
        if similar:
            sugs = ", ".join([r['dest'] for r in similar])
            return f"💡 No encontré permisos a **{destino_buscado}**. ¿Quizás buscabas: {sugs}?"
    
    # Caso 2: Buscó un año sin permisos
    y = _extract_year(q)
    if y:
        count = _query("SELECT COUNT(*) c FROM permisos WHERE anio = ?", (y,))[0]['c']
        if count == 0:
            alt = _query("""
                SELECT DISTINCT anio
                FROM permisos
                WHERE anio BETWEEN ? AND ?
                ORDER BY anio DESC
                LIMIT 3
            """, (y-2, y+2))
            if alt:
                sugs = ", ".join([str(r['anio']) for r in alt])
                return f"💡 No hay permisos en **{y}**. Años con datos cercanos: {sugs}"
    
    return None

# ── Handler "últimos" (SIN TILDES en el nombre) ────────────────────────────
def _h_ultimos(_ent=None):
    rows = _query("""
        SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
        FROM permisos
        ORDER BY COALESCE(datetime(updated_at), datetime(fecha_registro)) DESC, id DESC
        LIMIT 15
    """)
    return ("Últimos permisos registrados:", rows)

# ── Handlers específicos de notaría (NUEVOS) ────────────────────────────────
def _h_viajan_solos(ent=None):
    """Permisos donde el menor viaja solo (sin acompañantes)"""
    rows = _query("""
        SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
        FROM permisos
        WHERE UPPER(acompanante) IN ('SOLO', 'SOLO(A)/SOLOS(AS)')
           OR viaja_solo = 1
        ORDER BY anio DESC, numero ASC
        LIMIT 50
    """)
    return (f"Permisos donde el menor viaja solo: {len(rows)}.", rows)

def _h_con_hermanos(ent=None):
    """Permisos con hermanos biológicos"""
    rows = _query("""
        SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
        FROM permisos
        WHERE COALESCE(hermanos_json, '') <> ''
          AND hermanos_json <> '[]'
        ORDER BY anio DESC, numero ASC
        LIMIT 50
    """)
    return (f"Permisos con hermanos registrados: {len(rows)}.", rows)

def _h_con_recepcion(ent=None):
    """Permisos donde alguien recoge al menor al arribo"""
    rows = _query("""
        SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre, rec_nombre
        FROM permisos
        WHERE UPPER(COALESCE(recibe_si,'NO')) = 'SI'
        ORDER BY anio DESC, numero ASC
        LIMIT 50
    """)
    if rows:
        msg_extra = f"\nAlgunas personas que reciben: {', '.join(set([r['rec_nombre'] for r in rows[:5] if r.get('rec_nombre')]))}"
    else:
        msg_extra = ""
    return (f"Permisos con recepción al arribo: {len(rows)}.{msg_extra}", rows)

def _h_anulados(ent=None):
    """Permisos anulados"""
    rows = _query("""
        SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre, anulado_motivo
        FROM permisos
        WHERE UPPER(COALESCE(estado,'')) = 'ANULADO'
        ORDER BY datetime(anulado_at) DESC
        LIMIT 30
    """)
    return (f"Permisos ANULADOS: {len(rows)}.", rows)

def _h_top_destinos(ent=None):
    """Top 10 destinos más frecuentes"""
    rows = _query("""
        SELECT UPPER(destino) AS destino, COUNT(*) AS total
        FROM permisos
        WHERE COALESCE(destino,'') <> ''
        GROUP BY UPPER(destino)
        ORDER BY total DESC
        LIMIT 10
    """)
    if not rows:
        return ("No hay destinos registrados.", [])
    
    msg = "Top 10 destinos más frecuentes:\n"
    for r in rows:
        msg += f"- {r['destino']}: {r['total']} permisos\n"
    return (msg, rows)

def _h_analisis_avanzado(query: str):
    """
    Análisis avanzado: detecta patrones y tendencias en los datos.
    """
    Q = _u(query)
    
    # Detección de análisis temporal (tendencias)
    if re.search(r"TENDENCIA|EVOLUCI[ÓO]N|CRECIMIENTO|COMPARAR", Q):
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT strftime('%Y-%m', fecha_registro) AS mes, 
                       COUNT(*) AS total
                FROM permisos
                WHERE anio >= ?
                GROUP BY mes
                ORDER BY mes ASC
            """, (date.today().year - 1,)).fetchall()
        
        if rows:
            df = pd.DataFrame(rows, columns=["Mes", "Total"])
            st.markdown("### 📈 Tendencia de Permisos (últimos 12 meses)")
            st.line_chart(df.set_index("Mes"))
            return (f"Se encontró tendencia en {len(rows)} períodos.", [])
    
    # Comparación entre años
    if re.search(r"COMPARAR\s+(\d{4})\s+Y\s+(\d{4})", Q):
        m = re.search(r"COMPARAR\s+(\d{4})\s+Y\s+(\d{4})", Q)
        anio1, anio2 = int(m.group(1)), int(m.group(2))
        
        with get_conn() as conn:
            c1 = conn.execute("SELECT COUNT(*) FROM permisos WHERE anio = ?", (anio1,)).fetchone()[0]
            c2 = conn.execute("SELECT COUNT(*) FROM permisos WHERE anio = ?", (anio2,)).fetchone()[0]
        
        diff = c2 - c1
        porc = ((c2 - c1) / c1 * 100) if c1 > 0 else 0
        
        st.metric(f"Comparación {anio1} vs {anio2}", f"{diff:+,}", f"{porc:+.1f}%")
        return (f"En {anio1}: {c1} permisos. En {anio2}: {c2} permisos. Diferencia: {diff:+,} ({porc:+.1f}%).", [])
    
    return None

# ── C) LOGS (no rompe si falla) ──────────────────────────────────────────
def _log_q(q: str, msg: str, nrows: int):
    try:
        with get_conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS asistente_logs(
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                                pregunta TEXT, respuesta TEXT, filas INTEGER)""")
            conn.execute("INSERT INTO asistente_logs(pregunta,respuesta,filas) VALUES(?,?,?)",
                         (q, (msg or "")[:500], int(nrows or 0)))
    except Exception:
        pass

# ── Núcleo NLQ clásico (se mantiene por compatibilidad) ──────────────────
def _qa_sql(q: str) -> tuple[str, list[dict]] | None:
    Q = _u(q)
    Qc = _clean_text(q)
    rng = _range_for_phrase(Qc)
    if rng:
        start_iso, end_iso = rng
        tipo = _pick_tipo(Qc)
        if _wants_count(Qc):
            if tipo:
                row = _query("""SELECT COUNT(*) c FROM permisos
                                WHERE date(fecha_registro) >= ? AND date(fecha_registro) < ? AND UPPER(tipo_viaje)=?""",
                             (start_iso, end_iso, tipo))[0]
                return (f"Se emitieron {row['c']} permisos {tipo.lower()}s entre {start_iso} y {end_iso}.", [])
            else:
                row = _query("""SELECT COUNT(*) c FROM permisos
                                WHERE date(fecha_registro) >= ? AND date(fecha_registro) < ?""",
                             (start_iso, end_iso))[0]
                return (f"Se emitieron {row['c']} permisos entre {start_iso} y {end_iso}.", [])
        else:
            if tipo:
                rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre, date(fecha_registro) as fecha
                                 FROM permisos
                                 WHERE date(fecha_registro) >= ? AND date(fecha_registro) < ? AND UPPER(tipo_viaje)=?
                                 ORDER BY fecha ASC, numero ASC""", (start_iso, end_iso, tipo))
                return (f"Permisos {tipo.lower()}s en {start_iso} → {end_iso}: {len(rows)}.", rows)
            else:
                rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre, date(fecha_registro) as fecha
                                 FROM permisos
                                 WHERE date(fecha_registro) >= ? AND date(fecha_registro) < ?
                                 ORDER BY fecha ASC, numero ASC""", (start_iso, end_iso))
                return (f"Permisos en {start_iso} → {end_iso}: {len(rows)}.", rows)

    m = re.search(r"CU[ÁA]NT(OS|AS)\s+PERMIS(OS|AS).*?(\d{4})", Q)
    if m:
        anio = _extract_year(m.group(2), default=date.today().year)
        c = _query("SELECT COUNT(*) c FROM permisos WHERE anio=?", (anio,))[0]['c']
        return (f"Se emitieron {c} permisos en {anio}.", [])

    m = re.search(r"(INTERNACIONAL|NACIONAL)(ES)?(?:.*?)(\d{4})", Q)
    if m:
        tipo = "INTERNACIONAL" if "INTERNACIONAL" in m.group(1) else "NACIONAL"
        anio = int(m.group(3))
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                         FROM permisos WHERE anio=? AND UPPER(tipo_viaje)=?
                         ORDER BY numero ASC""", (anio, tipo))
        return (f"Permisos {tipo.lower()} en {anio}: {len(rows)}.", rows)

    m = re.search(r"(?:PERMISO|PERMISOS).*(?:A|HACIA)\s+([A-ZÁÉÍÓÚÑ ]+)(?:\s+EN\s+(\d{4}))?", Q)
    if m:
        destino = _like_token(m.group(1))
        anio = m.group(2)
        if anio:
            rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                             FROM permisos WHERE anio = ? AND UPPER(destino) LIKE ?
                             ORDER BY numero ASC""", (int(anio), destino))
        else:
            rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                             FROM permisos WHERE UPPER(destino) LIKE ?
                             ORDER BY anio DESC, numero ASC""", (destino,))
        return (f"Permisos con destino parecido a {_norm(m.group(1)).title()}: {len(rows)}.", rows)

    m = re.search(r"(?:NOMBRE|APELLID(?:O|OS|AS))\s+([A-ZÁÉÍÓÚÑ ]+)", Q)
    if m:
        name = _like_token(m.group(1))
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                         FROM permisos
                         WHERE UPPER(menor_nombre) LIKE ?
                            OR UPPER(padre_nombre) LIKE ?
                            OR UPPER(madre_nombre) LIKE ?
                         ORDER BY anio DESC, numero ASC""", (name, name, name))
        return (f"Permisos que coinciden con el nombre/apellidos {_norm(m.group(1)).title()}: {len(rows)}.", rows)

    m = re.search(r"(?:DNI|DOCUMENTO|DOC|PASAPORTE)\s+([A-Z0-9]+)", Q)
    if m:
        d = _u(m.group(1))
        like_d = f"%{d}%"
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                         FROM permisos
                         WHERE UPPER(COALESCE(menor_doc_num, menor_dni, '')) LIKE ?
                            OR UPPER(COALESCE(padre_doc_num, padre_dni, '')) LIKE ?
                            OR UPPER(COALESCE(madre_doc_num, madre_dni, '')) LIKE ?
                         ORDER BY anio DESC, numero ASC""", (like_d, like_d, like_d))
        return (f"Permisos que contienen el documento {d}: {len(rows)}.", rows)

    m = re.search(r"(MENOR|HIJO[A]?)\s+(LLAMAD[OA]|NOMBRE)\s+([A-ZÁÉÍÓÚÑ ]+)", Q)
    if m:
        nombre = _like_token(m.group(3))
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                         FROM permisos WHERE UPPER(menor_nombre) LIKE ?
                         ORDER BY anio DESC, numero ASC""", (nombre,))
        return (f"Permisos del menor que coincide con {_norm(m.group(3)).title()}: {len(rows)}.", rows)

    m = re.search(r"(FIRM[ÓO]|FIRMA)(?:\s+LA\s+MADRE|\s+EL\s+PADRE|\s+AMBOS)(?:.*?(\d{4}))?", Q)
    if m:
        quien = "MADRE" if "MADRE" in Q else ("PADRE" if "PADRE" in Q else "AMBOS")
        cond_tipo = " AND UPPER(tipo_viaje)='INTERNACIONAL'" if "INTERNACIONAL" in Q else ""
        m2 = re.search(r"(\d{4})", Q)
        if m2:
            rows = _query(f"""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                              FROM permisos WHERE anio=? AND UPPER(firma_quien)=?{cond_tipo}
                              ORDER BY anio DESC, numero ASC""", (int(m2.group(1)), quien))
        else:
            rows = _query(f"""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                              FROM permisos WHERE UPPER(firma_quien)=?{cond_tipo}
                              ORDER BY anio DESC, numero ASC""", (quien,))
        return (f"Permisos firmados por {quien}: {len(rows)}.", rows)

    m = re.search(r"(?:PERMISO|NSC)[^\d](\d{4}).?(\d+)", Q)
    if m and m.group(1).isdigit() and m.group(2).isdigit():
        anio, numero = int(m.group(1)), int(m.group(2))
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                         FROM permisos WHERE anio=? AND numero=?""", (anio, numero))
        msg = f"Encontré el correlativo {numero:04d} — NSC-{anio}." if rows else f"No encontré el correlativo {numero:04d} — NSC-{anio}."
        return (msg, rows)

    if re.search(r"RECIENTE|ULTIMOS?|ÚLTIMOS?", Q):
        rows = _query("""SELECT id, anio, numero, tipo_viaje, destino, firma_quien, menor_nombre
                         FROM permisos
                         ORDER BY COALESCE(datetime(updated_at), datetime(fecha_registro)) DESC, id DESC
                         LIMIT 15""")
        return ("Últimos permisos registrados:", rows)

    return None

# ── Wrappers ──────────────────────────────────────────────────────────────
def _answer_question_struct(q: str) -> dict:
    ans = _faq_answer(q)
    if ans:
        _log_q(q, ans, 0); return {"msg": ans, "rows": []}
    routed = _advanced_router(q)
    if routed:
        msg, rows = routed; _log_q(q, msg, len(rows or [])); return {"msg": msg, "rows": rows}
    res = _qa_sql(q)
    if res:
        msg, rows = res; _log_q(q, msg, len(rows or [])); return {"msg": msg, "rows": rows}
    ans2 = _faq_semantic_answer(q)
    if ans2:
        _log_q(q, ans2, 0); return {"msg": ans2, "rows": []}
    
    # Si llegamos aquí, no entendió nada
    sugerencia = _suggest_alternatives(q)
    if sugerencia:
        msg = sugerencia
    else:
        msg = ("No entendí. Prueba: “permisos nacionales este mes”, “internacionales ayer”, "
               "“destino PIURA mes pasado”, “dni 12345678”, “permiso 2025 número 31”.")
    _log_q(q, msg, 0)
    return {"msg": msg, "rows": []}

def _answer_question(q: str):
    res = _answer_question_struct(q)
    st.markdown(res["msg"])
    if res.get("rows"):
        st.markdown(_fmt_listado(res["rows"]))
        with st.expander("Ver tabla"):
            _show_rows_table(res["rows"])
        
        # 🔥 NUEVO: Mostrar gráficos automáticos
        _show_chart_if_applicable(res["rows"], q)  # ← AGREGAR ESTA LÍNEA
    
    try:
        st.session_state["ia_last_rows"] = res.get("rows", [])
    except Exception:
        pass
    
# --- Estado estable de edición ---
if "sel_id" not in st.session_state:
    st.session_state.sel_id = 0
if "sel_anio" not in st.session_state:
    st.session_state.sel_anio = date.today().year
if "sel_numero" not in st.session_state:
    st.session_state.sel_numero = 1  # mínimo 1
# ------------------- NUEVO -------------------

if modo == "➕ Nuevo permiso":

    vals = formulario_base()

    st.markdown("---")

    # ===== Confirmación en 2 pasos =====
    ask = st.session_state.get("_confirm_gen", False)

    if not ask:
        # Paso 1: pedir confirmación
        col1, col2 = st.columns([1,1])
        with col1:
            if st.button("🧾 Generar Permiso de Viaje", disabled=st.session_state._enviando, key="btn_gen_start"):
                st.session_state._confirm_gen = True
                st.rerun()
        with col2:
            st.caption("Al hacer clic, te pediremos confirmación antes de generar.")
        btn_gen = False  # no generar todavía
    else:
        # Paso 2: confirmar o cancelar
        st.warning("¿Estás seguro(a) que deseas GENERAR este permiso con los datos actuales?")
        c1, c2 = st.columns([1,1])
        with c1:
            btn_gen = st.button("✅ Sí, generar ahora", type="primary", disabled=st.session_state._enviando, key="btn_gen_confirm")
        with c2:
            if st.button("❌ Cancelar", key="btn_gen_cancel"):
                st.session_state._confirm_gen = False
                st.stop()

    if btn_gen:
        st.session_state._enviando = True
        try:
            # ============ VALIDACIÓN UNIFICADA ============
            ok, errs = validar_vals_para_generar(vals)
            if not ok:
                _mostrar_errores(errs)
                st.session_state._enviando = False
                st.session_state._confirm_gen = False
                st.stop()  # Corta el flujo: NO genera ni guarda

            # ============ (tu flujo original de generación/guardado) ============
            anio_actual = date.today().year
            numero_permiso = get_next_correlativo(anio_actual)

            fs_iso = vals["fs"].strftime("%Y-%m-%d")
            fr_iso = vals["fr"].strftime("%Y-%m-%d") if vals["fr"] else ""

            # Contexto para DOCX
            gvars = genero_menor_vars(vals["sexo_menor"])
            menor_bloque = _doc_bloque_menor(
                vals.get("menor_doc_tipo"),
                vals.get("menor_doc_num"),
                gvars["IDENT_TX"],
                vals.get("menor_nacionalidad")
            )


            ctx = {
                "CIUDAD": s(vals["ciudad"]),
                "NOTARIO_NOMBRE": s(vals["notario"]),
                **hoy_en_letras(),

                # Padres (texto general)
                "PADRE_NOMBRE": s(vals["padre_nombre"]),
                "PADRE_DNI": s(vals["padre_dni"]),
                "PADRE_ESTADO_CIVIL": s(vals["padre_estado_civil"]),
                "PADRE_DIRECCION": s(vals["padre_direccion"]),
                "PADRE_DISTRITO": s(vals["padre_distrito"]),
                "PADRE_PROVINCIA": s(vals["padre_provincia"]),
                "PADRE_DEPARTAMENTO": s(vals["padre_departamento"]),
                "PADRE_DOC_TIPO": s(vals["padre_doc_tipo"]).upper(),
                "PADRE_DOC_NUM": s(vals["padre_doc_num"]),
                "PADRE_NACIONALIDAD": s(vals["padre_nacionalidad"]),

                "MADRE_NOMBRE": s(vals["madre_nombre"]),
                "MADRE_DNI": s(vals["madre_dni"]),
                "MADRE_ESTADO_CIVIL": s(vals["madre_estado_civil"]),
                "MADRE_DIRECCION": s(vals["madre_direccion"]),
                "MADRE_DISTRITO": s(vals["madre_distrito"]),
                "MADRE_PROVINCIA": s(vals["madre_provincia"]),
                "MADRE_DEPARTAMENTO": s(vals["madre_departamento"]),
                "MADRE_DOC_TIPO": s(vals["madre_doc_tipo"]).upper(),
                "MADRE_DOC_NUM": s(vals["madre_doc_num"]),
                "MADRE_NACIONALIDAD": s(vals["madre_nacionalidad"]),

                # Menor
                "MENOR_NOMBRE": s(vals["menor_nombre"]),
                "MENOR_DNI": s(vals["menor_dni"]),
                "MENOR_EDAD_LETRAS": s(vals["edad_letras"]),
                "MENOR_EDAD_NUMERO": int(vals["edad_num"] or 0),
                "SEXO_MENOR": s(vals["sexo_menor"]),
                "MENOR_DOC_BLOQUE": menor_bloque,

                # Viaje
                "TIPO_VIAJE": s(vals["tipo_viaje"]),
                "ORIGEN": s(vals["origen"]),
                "DESTINO": s(vals["destino"]),
                "VIAS": vals["vias"],
                "EMPRESA": s(vals["empresa"]),
                "VIAJA_SOLO": bool(vals["viaja_solo"]),
                "FECHA_SALIDA": fs_iso,
                "FECHA_RETORNO": fr_iso,
                "FECHA_SALIDA_TX": fecha_iso_a_letras(fs_iso) if fs_iso else "",
                "FECHA_RETORNO_TX": fecha_iso_a_letras(fr_iso) if fr_iso else "",

                # Acompañante
                "ACOMPANANTE": s(vals["acompanante"]),
                "ROL_ACOMPANANTE": s(vals["rol_acompanante"]) or ("PADRES" if vals["acompanante"]=="AMBOS" else ""),
                "ACOMP1_NOMBRE": s(vals["acomp1_nombre"]),
                "ACOMP1_DNI": s(vals["acomp1_dni"]),
                "ACOMP_COUNT": vals["acomp_count"],
                "PERSONA_RECEPCION": "",
                "DNI_PERSONA_RECEPCION": "",

                # Motivo
                "MOTIVO_VIAJE": s(vals["motivo"]),
                "CIUDAD_EVENTO": s(vals["ciudad_evento"]),
                "FECHA_EVENTO": s(vals["fecha_evento"]),
                "ORGANIZADOR": s(vals["organizador"]),

                "ANIO": anio_actual,
                "NUMERO_PERMISO": numero_permiso,

                "QUIEN_FIRMA": s(vals["quien_firma"]),
                "QUIEN_FIRMA_INT": s(vals["quien_firma_int"])
            }
            
            # ===== Menor principal + hermanos (mismo formato legal) =====
            menores_ctx = []

            # ---- Menor principal (NRO 1) ----
            ident_tx_p = genero_menor_vars(vals.get("sexo_menor")).get("IDENT_TX", "IDENTIFICADO")

            # 1) Obtén la fecha desde vals o, si viene vacía, desde session_state (fallback)
            fnac_p = vals.get("menor_fnac")
            if not fnac_p:
                fnac_p = st.session_state.get("menor_fnac")  # <- fallback confiable del widget

            # 2) Normaliza a ISO (acepta date o str)
            if fnac_p:
                try:
                    if hasattr(fnac_p, "strftime"):  # date/datetime -> ISO
                        fnac_iso_p = fnac_p.strftime("%Y-%m-%d")
                    else:                             # str -> parse -> ISO
                        dtmp = parse_iso(fnac_p)
                        fnac_iso_p = dtmp.strftime("%Y-%m-%d") if dtmp else ""
                except Exception:
                    fnac_iso_p = ""
            else:
                fnac_iso_p = ""

            # 3) Calcula la edad del menor principal
            try:
                edad_num_p = calcular_edad(fnac_iso_p) if fnac_iso_p else ""
                edad_txt_p = edad_en_letras(edad_num_p) if (edad_num_p != "") else ""
            except Exception:
                edad_num_p, edad_txt_p = "", ""

            doc_bloque_p = _doc_bloque_menor(
                vals.get("menor_doc_tipo"),
                vals.get("menor_doc_num") or vals.get("menor_dni", ""),
                ident_tx_p,
                vals.get("menor_nacionalidad")
            )


            menores_ctx.append({
                "NRO": 1,
                "NOMBRE": s(vals.get("menor_nombre","")).upper(),
                "DOC_BLOQUE": doc_bloque_p,
                "EDAD_NUM": edad_num_p,
                "EDAD_TXT": edad_txt_p
            })

            for i, _ in enumerate(st.session_state.get("hermanos", [])):
                h_nom = s(st.session_state.get(f"hermano_nombre_{i}", ""))
                if not h_nom:
                    continue

                # Lee SIEMPRE desde el state (NO crear inputs aquí)
                h_sex  = (st.session_state.get(f"hermano_sexo_{i}", "") or "").upper()
                h_tipo = (st.session_state.get(f"hermano_doc_tipo_{i}", "DNI") or "DNI").upper()
                h_num  = s(st.session_state.get(f"hermano_doc_num_{i}", ""))
                h_fnac = st.session_state.get(f"hermano_fnac_{i}", None)

                # Normaliza fnac a ISO -> edad
                if h_fnac:
                    try:
                        if hasattr(h_fnac, "strftime"):
                            fnac_iso_h = h_fnac.strftime("%Y-%m-%d")
                        else:
                            dtmp = parse_iso(h_fnac)
                            fnac_iso_h = dtmp.strftime("%Y-%m-%d") if dtmp else ""
                    except Exception:
                        fnac_iso_h = ""
                else:
                    fnac_iso_h = ""

                try:
                    e_num = calcular_edad(fnac_iso_h) if fnac_iso_h else ""
                    e_txt = edad_en_letras(e_num) if (e_num != "") else ""
                except Exception:
                    e_num, e_txt = "", ""

                ident_tx_h = genero_menor_vars(h_sex).get("IDENT_TX", "IDENTIFICADO")

                # Solo LEE nacionalidad (si aplica). NO crees inputs aquí.
                h_nac = s(st.session_state.get(f"hermano_nacionalidad_{i}", "")) if h_tipo in ("PASAPORTE", "DNI EXTRANJERO") else ""

                # Construye el bloque correcto con nacionalidad cuando aplique
                doc_bloque_h = _doc_bloque_menor(h_tipo, h_num, ident_tx_h, h_nac)

                # Agrega al contexto
                menores_ctx.append({
                    "NRO": len(menores_ctx) + 1,
                    "NOMBRE": h_nom.upper(),
                    "DOC_BLOQUE": doc_bloque_h,
                    "EDAD_NUM": e_num,
                    "EDAD_TXT": e_txt
                })

            # Pon la lista y el total en el contexto del DOCX
            ctx["MENORES_LISTA"] = menores_ctx
            ctx["MENORES_COUNT"] = len(menores_ctx)
            
            # === Título y posesivo coherentes con la cantidad ===
            ctx["MENORES_TITULO"] = "HIJO(A)" if ctx["MENORES_COUNT"] == 1 else "HIJOS(AS)"
            ctx["POSESIVO_PADRES"] = "SU" if ctx["MENORES_COUNT"] == 1 else "SUS"

            # === Concordancia desde el CONTEXTO (como en Editar/Re-generar) ===
            def _acuerdos_plural_genero_from_ctx(ctx_local: dict) -> dict:
                total = int(ctx_local.get("MENORES_COUNT", 1))

                sex_principal = s(ctx_local.get("SEXO_MENOR","")).upper()
                # Recolecta sexos de hermanos desde la UI (si existieran):
                hermanos_sex = []
                for i, _ in enumerate(st.session_state.get("hermanos", [])):
                    hermanos_sex.append( s(st.session_state.get(f"hermano_sexo_{i}", "")).upper() )

                all_f = (total >= 1) and (sex_principal == "F") and all(x == "F" for x in hermanos_sex if x)

                if total == 1:
                    return {
                        "ART": "LA" if sex_principal == "F" else "EL",
                        "SUST": "MENOR",
                        "VERB_VIAJAR": "VIAJARÁ",
                        "ADJ_SOLO": "SOLA" if sex_principal == "F" else "SOLO",
                        "VERB_SER": "SERÁ",
                        "ADJ_RECOGIDO": "RECOGIDA" if sex_principal == "F" else "RECOGIDO",
                        "PLURAL": False,
                        "ALLF": (sex_principal == "F"),
                    }
                else:
                    return {
                        "ART": "LAS" if all_f else "LOS",
                        "SUST": "MENORES",
                        "VERB_VIAJAR": "VIAJARÁN",
                        "ADJ_SOLO": "SOLAS" if all_f else "SOLOS",
                        "VERB_SER": "SERÁN",
                        "ADJ_RECOGIDO": "RECOGIDAS" if all_f else "RECOGIDOS",
                        "PLURAL": True,
                        "ALLF": all_f,
                    }

            # Usa la versión basada en CONTEXTO:
            ac = _acuerdos_plural_genero_from_ctx(ctx)
            
            def _vias_empresa_tx(vias: list[str] | None, empresa: str | None) -> str:
                vias_tx = " Y/O ".join(vias).upper() if vias else ""
                emp_tx = s(empresa).upper()
                if vias_tx and emp_tx: return f"POR {vias_tx} ({emp_tx})"
                if vias_tx: return f"POR {vias_tx}"
                if emp_tx:  return f"({emp_tx})"
                return ""

            obs_tx = ""
            if s(vals.get("acompanante","")).upper() in ["SOLO","SOLO(A)/SOLOS(AS)"]:
                # 1) Oración base: EL/LA/LOS/LAS MENOR(ES) VIAJARÁ(N) SOLO/SOLA/SOLOS/SOLAS.
                base_viaje = (
                    f"SE DEJA CONSTANCIA QUE {ac['ART']} {ac['SUST']} "
                    f"{ac['VERB_VIAJAR']} {ac['ADJ_SOLO']}."
                )

                # 2) ¿Hay recepción?
                if s(vals.get("recibe_si","NO")).upper() == "SI":
                    # Toma la lista múltiple desde la UI (rec_*_i)
                    rec_list = _recep_items_from_state()

                    # Compat: si el usuario solo llenó los campos “simples”, arma 1 item
                    if not rec_list:
                        rec_list = [{
                            "nombre": s(vals.get("rec_nombre","")).upper(),
                            "tipo":   s(vals.get("rec_doc_tipo","DNI PERUANO")).upper(),
                            "num":    s(vals.get("rec_doc_num","")),
                            "pais":   s(vals.get("rec_doc_pais","")).upper(),
                        }]

                    recep_txt = _obs_con_recepcion_plural(ac, rec_list)  # “Y QUE A SU ARRIBO SERÁ(N) RECOGIDO(S) ...”
                    obs_tx = (base_viaje + " " + recep_txt).strip() if recep_txt else base_viaje
                else:
                    obs_tx = base_viaje
            else:
                # === VIAJAN ACOMPAÑADOS (PADRE/MADRE/AMBOS/TERCERO) ===
                def _doc_num_preferido(num1: str | None, num2: str | None) -> str:
                    n1, n2 = s(num1), s(num2)
                    return n1 if n1 else n2

                def _acomp_bloque_vals(v: dict) -> tuple[str, str, str, str]:
                    """
                    Devuelve (posesivo, rol_txt, nombre_txt, doc_txt) para PADRE/MADRE/AMBOS/TERCERO.
        
                    NOTA: Para TERCERO con múltiples acompañantes, devuelve vacíos.
                    La lógica de múltiples terceros se maneja por separado.
                    """
                    acomp = s(v.get("acompanante","")).upper()
                    if acomp == "PADRE":
                        rol_txt = "PADRE"
                        nombre = s(v.get("padre_nombre","")).upper()
                        doc = _doc_num_preferido(v.get("padre_doc_num"), v.get("padre_dni"))
                        doc_txt = f"DOCUMENTO N° {doc}" if doc else ""
                        return "SU", rol_txt, nombre, doc_txt
                    elif acomp == "MADRE":
                        rol_txt = "MADRE"
                        nombre = s(v.get("madre_nombre","")).upper()
                        doc = _doc_num_preferido(v.get("madre_doc_num"), v.get("madre_dni"))
                        doc_txt = f"DOCUMENTO N° {doc}" if doc else ""
                        return "SU", rol_txt, nombre, doc_txt
                    elif acomp == "AMBOS":
                        return "SUS", "PADRES", "", ""
                    elif acomp == "TERCERO":
                        # 👉 NUEVO: retornar vacíos para manejar múltiples terceros por separado
                        return "", "", "", ""
                    return "SU", "", "", ""

                acomp_val = s(vals.get("acompanante","")).upper()
    
                # 🆕 CASO ESPECIAL: TERCERO con múltiples acompañantes
                if acomp_val == "TERCERO":
                    # Recopilar todos los terceros desde session_state
                    terceros_list = []
                    for i in range(len(st.session_state.get("terceros", []))):
                        rol = s(st.session_state.get(f"tercero_rol_{i}", "")).upper()
                        nombre = s(st.session_state.get(f"tercero_nombre_{i}", "")).upper()
                        dni = s(st.session_state.get(f"tercero_dni_{i}", ""))
            
                        if nombre:  # Solo agregar si tiene nombre
                            terceros_list.append({"rol": rol, "nombre": nombre, "dni": dni})
        
                    # Generar OBS_TX usando la función helper
                    obs_tx = _obs_terceros_multiples(terceros_list, ac)
    
                else:
                    # Lógica normal para PADRE/MADRE/AMBOS
                    posesivo, rol_txt, acomp_nom, acomp_doc = _acomp_bloque_vals(vals)

                    def _acomp_plural_count(v: dict) -> int:
                        a = s(v.get("acompanante","")).upper()
                        if a == "AMBOS": return 2
                        if a in ("PADRE","MADRE"): return 1
                        return 0

                    acomp_n = _acomp_plural_count(vals)
                    quien_txt = "QUIENES SERÁN RESPONSABLES" if acomp_n >= 2 else "QUIEN SERÁ RESPONSABLE"

                    comp_tx = f"EN COMPAÑÍA DE {posesivo} {rol_txt}"
                    if acomp_nom:
                        comp_tx += f" {acomp_nom}"
                    if acomp_doc:
                        comp_tx += f", CON {acomp_doc}"

                    obs_tx = (
                        f"SE DEJA CONSTANCIA QUE {ac['ART']} {ac['SUST']} {ac['VERB_VIAJAR']} {comp_tx}; "
                        f"{quien_txt} DEL CUIDADO DE {ac['ART']} {ac['SUST']} DURANTE SU ESTADÍA EN LA CIUDAD."
                    )

            ctx["OBS_TX"] = obs_tx
            
            # Observaciones precompuestas (opcional, por si la plantilla usa el bloque entero)
            ctx["OBSERVACIONES_BLOQUE"] = (
                f"OBSERVACIONES: {ctx['OBS_TX']} {ctx.get('LINEA_SEPARADOR','')}"
                if ctx.get("OBS_TX") else ""
            )

            # --- Tipos canónicos para que la PLANTILLA decida el texto correcto ---
            ctx["PADRE_DOC_TIPO_CAN"] = canon_doc(ctx.get("PADRE_DOC_TIPO") or vals.get("padre_doc_tipo"))
            ctx["MADRE_DOC_TIPO_CAN"] = canon_doc(ctx.get("MADRE_DOC_TIPO") or vals.get("madre_doc_tipo"))
            ctx["MENOR_DOC_TIPO_CAN"] = canon_doc(ctx.get("MENOR_DOC_TIPO") or vals.get("menor_doc_tipo"))

            # Texto para PADRE/MADRE resuelto (usa el helper global _doc_tx)
            ctx["PADRE_DOC_TEXTO"] = _doc_tx(
                ctx.get("PADRE_DOC_TIPO") or vals.get("padre_doc_tipo"),
                ctx.get("PADRE_DOC_NUM")  or (vals.get("padre_doc_num") or vals.get("padre_dni",""))
            )
            ctx["MADRE_DOC_TEXTO"] = _doc_tx(
                ctx.get("MADRE_DOC_TIPO") or vals.get("madre_doc_tipo"),
                ctx.get("MADRE_DOC_NUM")  or (vals.get("madre_doc_num") or vals.get("madre_dni",""))
            )

            # (opcional) Compatibilidad con plantillas viejas:
            ctx["HIJO_S"] = "HIJOS(AS)" if ctx["MENORES_COUNT"] and ctx["MENORES_COUNT"] > 1 else "HIJO(A)"
           
            # Firmas (línea inferior sin "CON")
            ctx["PADRE_DOC_FIRMA"] = _doc_firma_adulto(vals.get("padre_doc_tipo"), vals.get("padre_doc_num"))
            ctx["MADRE_DOC_FIRMA"] = _doc_firma_adulto(vals.get("madre_doc_tipo"), vals.get("madre_doc_num"))

            ctx.update(concordancias_plural(ctx.get("ACOMP_COUNT", 0)))
            ctx.update(genero_menor_vars(ctx.get("SEXO_MENOR")))
            ctx.update(viaje_vars(ctx.get("FECHA_SALIDA"), ctx.get("FECHA_RETORNO"), ctx.get("VIAS")))
            ctx = preparar_firmas(ctx)
            
            # Validación dura de plantilla
            faltantes_gen = verificar_plantilla(plantilla_path, ctx)
            if faltantes_gen:
                st.error("Faltan variables en el contexto para esta plantilla. Revísalas antes de generar:")
                st.code("\n".join(sorted(map(str, faltantes_gen))), language="text")
                st.session_state._enviando = False
                st.stop()

            # Render y guardado
            content = render_docx(plantilla_path, ctx)

            # ================================================================
            # 🔒 GUARDAR DOCUMENTO CON VALIDACIÓN DE ESPACIO Y CORRUPCIÓN
            # ================================================================
            emitidos_dir = os.path.join(BASE_DIR, "emitidos", str(anio_actual))
            os.makedirs(emitidos_dir, exist_ok=True)

            try:
                # 🔥 VALIDACIÓN 1: Verificar espacio en disco ANTES de guardar
                disco_stats = shutil.disk_usage(emitidos_dir)
                disco_libre_mb = disco_stats.free / (1024 * 1024)
    
                if disco_libre_mb < 100:  # Menos de 100 MB libres
                    st.error(f"⚠️ **Espacio en disco insuficiente**")
                    st.error(f"Solo quedan {disco_libre_mb:.1f} MB libres. Se requieren al menos 100 MB.")
                    st.info("**Solución:** Libera espacio en el disco o contacta al administrador del sistema.")
                    logger.error(f"❌ Disco lleno: {disco_libre_mb:.1f} MB libres (mínimo: 100 MB)")
                    st.session_state._enviando = False
                    st.session_state._confirm_gen = False
                    st.stop()
    
                # 🔥 VALIDACIÓN 2: Guardar archivo
                archivo_salida = os.path.join(
                    emitidos_dir,
                    f"Permiso_{numero_permiso:04d}_NSC-{anio_actual}.docx"
                )
    
                with open(archivo_salida, "wb") as f:
                    f.write(content)
    
                # 🔥 VALIDACIÓN 3: Verificar que se guardó correctamente
                if not os.path.exists(archivo_salida):
                    raise IOError("El archivo no se creó en el disco")
    
                tamanio_kb = os.path.getsize(archivo_salida) / 1024
    
                if tamanio_kb < 5:  # Archivos DOCX nunca son menores a 5 KB
                    os.remove(archivo_salida)  # Elimina el archivo corrupto
                    raise IOError(f"El archivo generado está corrupto (solo {tamanio_kb:.1f} KB)")
    
                # ✅ TODO OK: Log exitoso
                logger.info(f"✅ Archivo guardado: Permiso_{numero_permiso:04d}_NSC-{anio_actual}.docx ({tamanio_kb:.1f} KB)")
                logger.info(f"📊 Espacio disponible en disco: {disco_libre_mb:.1f} MB")
    
            except Exception as e:
                logger.error(f"❌ Error al guardar documento: {e}")
                st.error(f"❌ No se pudo guardar el documento: {e}")
    
                # Limpia archivo parcial si existe
                if 'archivo_salida' in locals() and os.path.exists(archivo_salida):
                    try:
                        os.remove(archivo_salida)
                        logger.info(f"🗑️ Archivo corrupto eliminado: {archivo_salida}")
                    except:
                        pass
    
                st.session_state._enviando = False
                st.session_state._confirm_gen = False
                st.stop()

            # ================================================================
            # FIN DE VALIDACIÓN - CONTINÚA CON TU CÓDIGO NORMAL
            # ================================================================

            vias_tx = " Y/O ".join(vals["vias"]).upper() if vals["vias"] else ""
            firma_quien_tx = (vals["quien_firma"] if vals["tipo_viaje"]=="NACIONAL" else vals["quien_firma_int"]) or ""
            
            # --- Tomar hermanos de la UI y serializar a JSON para BD (SOLO LECTURA; sin inputs aquí) ---
            hermanos_list = []
            for i, _ in enumerate(st.session_state.get("hermanos", [])):
                h_nom = s(st.session_state.get(f"hermano_nombre_{i}", ""))
                if not h_nom:
                    continue

                h_sex  = (st.session_state.get(f"hermano_sexo_{i}", "") or "").upper()
                h_tipo = (st.session_state.get(f"hermano_doc_tipo_{i}", "DNI") or "DNI").upper()
                h_num  = s(st.session_state.get(f"hermano_doc_num_{i}", ""))
                h_fnac = st.session_state.get(f"hermano_fnac_{i}", None)

                # Normaliza fecha a ISO
                if h_fnac:
                    try:
                        if hasattr(h_fnac, "strftime"):
                            fnac_iso_h = h_fnac.strftime("%Y-%m-%d")
                        else:
                            dtmp = parse_iso(h_fnac)
                            fnac_iso_h = dtmp.strftime("%Y-%m-%d") if dtmp else ""
                    except Exception:
                        fnac_iso_h = ""
                else:       
                    fnac_iso_h = ""

                # Solo leer nacionalidad (no crear inputs aquí)
                h_nac = s(st.session_state.get(f"hermano_nacionalidad_{i}", "")) if h_tipo in ("PASAPORTE", "DNI EXTRANJERO") else ""

                hermanos_list.append({
                    "nombre":       h_nom,
                    "sexo":         h_sex,
                    "doc_tipo":     h_tipo,
                    "doc_num":      h_num,
                    "fnac":         fnac_iso_h,
                    "nacionalidad": h_nac,   # siempre definido ("" si no aplica)
                })

            hermanos_json = json.dumps(hermanos_list, ensure_ascii=False)

            # --- Recepción múltiple: tomar de la UI y serializar a JSON para BD ---
            viaja_solo_calc = s(vals.get("acompanante","")).upper() in ["SOLO","SOLO(A)/SOLOS(AS)"]

            recep_items = []
            rec_count = int(st.session_state.get("rec_list_count", 0))
            for i in range(rec_count):
                nombre = s(st.session_state.get(f"rec_nombre_{i}", "")).upper()
                doc_tipo = s(st.session_state.get(f"rec_doc_tipo_{i}", "DNI PERUANO")).upper()
                doc_num  = s(st.session_state.get(f"rec_doc_num_{i}", ""))
                doc_pais = s(st.session_state.get(f"rec_doc_pais_{i}", "")).upper()
                if nombre or doc_num:
                    recep_items.append({
                        "nombre": nombre,
                        "tipo": doc_tipo,
                        "num":  doc_num,
                        "pais": doc_pais
                    })

            rec_list_json = json.dumps(recep_items, ensure_ascii=False)
            recibe_si_val = "SI" if (viaja_solo_calc and len(recep_items) > 0) else "NO"

            rec0_nombre = recep_items[0]["nombre"]   if recep_items else ""
            rec0_tipo   = recep_items[0]["tipo"] if recep_items else ""
            rec0_num    = recep_items[0]["num"]  if recep_items else ""
            rec0_pais   = recep_items[0]["pais"] if recep_items else ""

             # --- Serializar TERCEROS a JSON para guardar en BD ---
            terceros_list = []
            if s(vals.get("acompanante","")).upper() == "TERCERO":
                for i in range(len(st.session_state.get("terceros", []))):
                    rol = s(st.session_state.get(f"tercero_rol_{i}", "")).upper()
                    nombre = s(st.session_state.get(f"tercero_nombre_{i}", "")).upper()
                    dni = s(st.session_state.get(f"tercero_dni_{i}", ""))
        
                    if nombre:  # Solo guardar si tiene nombre
                        terceros_list.append({
                            "rol": rol,
                            "nombre": nombre,
                            "dni": dni
                        })

            terceros_json = json.dumps(terceros_list, ensure_ascii=False)
            
            save_permiso_registro({
                "anio": anio_actual,
                "numero": numero_permiso,
                "nsc": "NSC",
                "ciudad": vals["ciudad"],
                "notario": vals["notario"],

                "padre_nombre": vals["padre_nombre"],
                "padre_dni": vals["padre_dni"],
                "padre_estado_civil": vals["padre_estado_civil"], "padre_direccion": vals["padre_direccion"],
                "padre_distrito": vals["padre_distrito"], "padre_provincia": vals["padre_provincia"],
                "padre_departamento": vals["padre_departamento"],
                "padre_doc_tipo": vals["padre_doc_tipo"], "padre_doc_num": vals["padre_doc_num"], "padre_nacionalidad": vals["padre_nacionalidad"],

                "madre_nombre": vals["madre_nombre"],
                "madre_dni": vals["madre_dni"],
                "madre_estado_civil": vals["madre_estado_civil"], "madre_direccion": vals["madre_direccion"],
                "madre_distrito": vals["madre_distrito"], "madre_provincia": vals["madre_provincia"],
                "madre_departamento": vals["madre_departamento"],
                "madre_doc_tipo": vals["madre_doc_tipo"], "madre_doc_num": vals["madre_doc_num"], "madre_nacionalidad": vals["madre_nacionalidad"],

                "menor_nombre": vals["menor_nombre"],
                "menor_dni": vals["menor_dni"],
                "menor_fnac": vals["menor_fnac"], "sexo_menor": vals["sexo_menor"],
                "menor_doc_tipo": vals["menor_doc_tipo"], "menor_doc_num": vals["menor_doc_num"], "menor_nacionalidad": vals["menor_nacionalidad"],

                "tipo_viaje": vals["tipo_viaje"], "firma_quien": firma_quien_tx,
                "origen": vals["origen"], "destino": vals["destino"],
                "vias": vias_tx, "empresa": vals["empresa"],
                "salida": fs_iso, "retorno": fr_iso,

                "acompanante": vals["acompanante"],
                "tercero_nombre": vals["acomp1_nombre"] if vals["acompanante"]=="TERCERO" else "",
                "tercero_dni": vals["acomp1_dni"] if vals["acompanante"]=="TERCERO" else "",
                "rol_acompanante": vals.get("rol_acompanante",""),
                "acomp1_nombre": s(vals.get("acomp1_nombre","")),
                "acomp1_dni": s(vals.get("acomp1_dni","")),
                "acomp_count": int(vals.get("acomp_count") or 0),
                "viaja_solo": viaja_solo_calc,
                "recibe_si":  recibe_si_val,
                "rec_nombre": rec0_nombre,
                "rec_doc_tipo": rec0_tipo,
                "rec_doc_num":  rec0_num,
                "rec_doc_pais": rec0_pais,
                "rec_list_json": rec_list_json,
                
                "motivo": vals["motivo"], "ciudad_evento": vals["ciudad_evento"],
                "fecha_evento": vals["fecha_evento"], "organizador": vals["organizador"],
                "hermanos_json": hermanos_json,
                "terceros_json": terceros_json,
                "archivo_generado": archivo_salida
            })

            st.success(f"Documento generado ✅ — N° {numero_permiso:04d} - NSC-{anio_actual}")
            st.download_button(
                label="⬇ Descargar Permiso_Viaje_Generado.docx",
                data=content,
                file_name=f"Permiso_{numero_permiso:04d}_NSC-{anio_actual}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )

            # --- limpieza confirmación tras éxito ---
            st.session_state._confirm_gen = False   # ✅ agrega esta línea aquí

        except Exception as e:
            st.error(f"Error al generar el documento: {e}")
            st.session_state._confirm_gen = False   # 🔁 opcional, para limpiar también si ocurre error
        finally:
            st.session_state._enviando = False

# ------------------- EDITAR / REGENERAR -------------------
if modo == "✏️ Editar / Re-generar":
    st.markdown("### 📚 Historial de permisos emitidos")
    filtro_anio = st.number_input("Filtrar por año", min_value=2000, max_value=2100, value=date.today().year, step=1)

    cols, rows = fetch_permisos(int(filtro_anio))
    if rows:
        df = pd.DataFrame(rows, columns=cols)
        st.dataframe(
            df[["id","anio","numero","nsc","fecha_registro","padre_nombre","madre_nombre",
                "menor_nombre","menor_dni","tipo_viaje","firma_quien","origen","destino",
                "vias","salida","retorno","estado","version"]],
            use_container_width=True
        )

        with st.expander("📄 Descargas", expanded=False):
            for _, r in df.iterrows():
                archivo = r["archivo_generado"]
                estado = str(r["estado"]).upper()
                btn_label = f"Descargar N° {int(r['numero']):04d} — NSC-{int(r['anio'])}"
                disabled = (estado == "ANULADO") or (not archivo) or (not os.path.exists(archivo))
                st.download_button(
                    btn_label,
                    data=open(archivo, "rb").read() if (archivo and os.path.exists(archivo) and estado != "ANULADO") else b"",
                    file_name=os.path.basename(archivo) if archivo else "permiso.docx",
                    disabled=disabled,
                    key=f"dl_{int(r['id'])}"
                )
                if estado == "ANULADO":
                    st.caption(f"ID {int(r['id'])}: ⛔ Documento anulado: descarga deshabilitada.")
                elif not archivo or not os.path.exists(archivo):
                    st.caption(f"ID {int(r['id'])}: ⚠️ Archivo no encontrado en disco.")

        st.markdown("## 📤 Exportaciones")

        col_e1, col_e2 = st.columns([1,1])
        with col_e1:
            anio_export = st.number_input("Año a exportar", min_value=2000, max_value=2100, value=date.today().year, step=1, key="anio_export")

        with col_e2:
            if st.button("📥 Exportar Control Anual (Excel)"):
                # 1) Traer registros del año
                with get_conn() as conn:
                    cur = conn.execute("""
                        SELECT *
                        FROM permisos
                        WHERE anio = ?
                        ORDER BY numero ASC, id ASC
                    """, (int(anio_export),))
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description]

                if not rows:
                    st.warning("No hay permisos para ese año.")
                else:
                    # 2) Convertir cada permiso a dict y armar filas
                    data = []
                    for row in rows:
                        perm = dict(zip(cols, row))

                        data.append({
                            "Nro Control": int(perm.get("id")),
                            "Cronológico": _cronologico_tx(perm),
                            "Participantes": _participantes_tx(perm),
                            "Fecha Crono.": _fecha_ddmmyyyy(perm.get("fecha_registro")),
                            "Tip. Permiso": _tipo_permiso_tx(perm.get("tipo_viaje")),
                            "Destino": _destino_tx(perm),
                        })

                    df = pd.DataFrame(data, columns=[
                        "Nro Control","Cronológico","Participantes","Fecha Crono.","Tip. Permiso","Destino"
                    ])

                    # 3) Escribir Excel con formato (texto multilínea y anchos)
                    bio = BytesIO()
                    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
                        sheet = "Control"
                        df.to_excel(writer, index=False, sheet_name=sheet)
                        ws = writer.sheets[sheet]
                        wb = writer.book

                        # formatos
                        wrap = wb.add_format({"text_wrap": True, "valign": "top"})
                        date_fmt = wb.add_format({"num_format": "dd/mm/yyyy", "valign": "top"})
                        normal = wb.add_format({"valign": "top"})

                        # anchos de columna
                        ws.set_column("A:A", 10, normal)   # Nro Control
                        ws.set_column("B:B", 20, normal)   # Cronológico
                        ws.set_column("C:C", 55, wrap)     # Participantes (multilínea)
                        ws.set_column("D:D", 14, normal)   # Fecha Crono. (guardamos como texto dd/mm/yyyy)
                        ws.set_column("E:E", 26, normal)   # Tip. Permiso
                        ws.set_column("F:F", 40, wrap)     # Destino

                    # Asegura que no existan NaN y todo sea texto
                    df = df.fillna("")

                    # Configuración base
                    BASE_PER_LINE = 15  # altura base por línea (ajusta entre 14–17 según se vea)
                    chars_per_line = {
                        "Participantes": 55,  # ancho estimado columna C
                        "Destino": 40,        # ancho estimado columna F
                    }

                    # Ajuste automático del alto de filas
                    for ridx, row in df.iterrows():
                        lines = 1
                        for col_name in ("Participantes", "Destino"):
                            txt = str(row.get(col_name, "") or "")
                            if not txt:
                                continue

                        # Líneas reales por saltos de línea manuales
                        manual = txt.count("\n") + 1

                        # Líneas estimadas por cantidad de texto (wrap automático)
                        wrap_est = 1
                        if col_name in chars_per_line and chars_per_line[col_name] > 0:
                            wrap_est = math.ceil(len(txt) / chars_per_line[col_name])

                        # Determinar el máximo de líneas necesarias
                        lines = max(lines, manual, wrap_est)

                    # Calcular altura final y aplicarla (+1 porque fila 0 es encabezado)
                    height = BASE_PER_LINE * lines + 4
                    ws.set_row(ridx + 1, height)

                bio.seek(0)
                st.download_button(
                    "⬇️ Descargar Excel",
                    data=bio.getvalue(),
                    file_name=f"Control_Permisos_{anio_export}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
        
    else:
        st.info("No hay permisos registrados para ese año.")
        df = pd.DataFrame(columns=cols)

    st.markdown("---")
    # === Selección por correlativo (Año + Número) ===
        # === Selección por correlativo (Año + Número) ===
    # === Selección por correlativo (Año + Número) ===
    st.subheader("Selecciona un permiso")

    # 1) Buscar por AÑO + NÚMERO (correlativo)
    col_a, col_b, col_c = st.columns([1, 1, 1.2])
    with col_a:
        anio_sel = st.number_input(
            "Año",
            min_value=2000, max_value=2100,
            value=st.session_state.sel_anio,
            step=1, key="anio_buscar"
        )
    with col_b:
        numero_buscar = st.number_input(
            "Número (correlativo)",
            min_value=1, step=1,
            value=st.session_state.sel_numero,
            key="numero_buscar"
        )
    with col_c:
        st.write("")
        # 🔥 NUEVO: Deshabilita el botón durante transición de modo
        en_transicion = st.session_state.get("_modo_transitorio", False)
    
        if st.button("🔎 Buscar", key="btn_buscar_correlativo", disabled=en_transicion):
            pid_found = get_id_por_correlativo(int(st.session_state.anio_buscar), int(st.session_state.numero_buscar))
        
            if pid_found:
                st.session_state.sel_id = int(pid_found)
                st.session_state.sel_anio = int(st.session_state.anio_buscar)
                st.session_state.sel_numero = int(st.session_state.numero_buscar)
                st.success(f"Encontrado: ID {pid_found}")
                st.rerun()
            else:
                st.session_state.sel_id = 0
                st.warning("No se encontró un permiso con ese (Año, Número).")
                st.rerun()

    pid = st.session_state.sel_id

    # 3) Cargar el permiso y continuar tu flujo normal
    if pid:
        perm = fetch_permiso_by_id(int(pid))
        if not perm:
            st.warning("No se encontró ese permiso.")
        else:
            estado_perm = str(perm.get("estado", "EMITIDO")).upper()
            disabled_form = (estado_perm == "ANULADO")

        st.caption(
            f"Correlativo: N° {perm['numero']:04d} - NSC-{perm['anio']}  |  "
            f"Versión actual: {perm.get('version',1)}  |  Estado: {estado_perm}"
        )
        if disabled_form:
            st.warning("Este permiso está *ANULADO. El formulario se muestra en modo **solo lectura*.")

        
        # === Precarga y resto de tu flujo existente ===
        precarga = {
            "id": perm.get("id"),
            "hermanos": perm.get("hermanos", []),

            "ciudad": perm.get("ciudad",""),
            "notario": perm.get("notario",""),
            "tipo_viaje": perm.get("tipo_viaje","NACIONAL"),

            # --- PADRE ---
            "padre_nombre": perm.get("padre_nombre",""),
            "padre_dni": perm.get("padre_dni",""),
            "padre_estado_civil": perm.get("padre_estado_civil",""),
            "padre_direccion": perm.get("padre_direccion",""),
            "padre_distrito": perm.get("padre_distrito",""),
            "padre_provincia": perm.get("padre_provincia",""),
            "padre_departamento": perm.get("padre_departamento",""),
            "padre_doc_tipo": perm.get("padre_doc_tipo","DNI"),
            "padre_doc_num": perm.get("padre_doc_num", perm.get("padre_dni","")),
            "padre_nacionalidad": perm.get("padre_nacionalidad",""),

            # --- MADRE ---
            "madre_nombre": perm.get("madre_nombre",""),
            "madre_dni": perm.get("madre_dni",""),
            "madre_estado_civil": perm.get("madre_estado_civil",""),
            "madre_direccion": perm.get("madre_direccion",""),
            "madre_distrito": perm.get("madre_distrito",""),
            "madre_provincia": perm.get("madre_provincia",""),
            "madre_departamento": perm.get("madre_departamento",""),
            "madre_doc_tipo": perm.get("madre_doc_tipo","DNI"),
            "madre_doc_num": perm.get("madre_doc_num", perm.get("madre_dni","")),
            "madre_nacionalidad": perm.get("madre_nacionalidad",""),

            # --- MENOR ---
            "menor_nombre": perm.get("menor_nombre",""),
            "menor_dni": perm.get("menor_dni",""),
            "menor_fnac": perm.get("menor_fnac",""),
            "sexo_menor": perm.get("sexo_menor","F"),
            "menor_doc_tipo": perm.get("menor_doc_tipo","DNI"),
            "menor_doc_num": perm.get("menor_doc_num", perm.get("menor_dni","")),
            "menor_nacionalidad": perm.get("menor_nacionalidad",""),

            # --- VIAJE ---
            "origen": perm.get("origen",""),
            "destino": perm.get("destino",""),
            "vias": perm.get("vias",""),
            "empresa": perm.get("empresa",""),
            "salida": perm.get("salida",""),
            "retorno": perm.get("retorno",""),

            # --- ACOMPAÑANTE (EXISTENTES) ---
            "acompanante": perm.get("acompanante","SOLO"),
            "tercero_nombre": perm.get("tercero_nombre",""),
            "tercero_dni": perm.get("tercero_dni",""),

            # ==================== NUEVO: ACOMPAÑANTE/OBSERVACIONES ====================
            "rol_acompanante": perm.get("rol_acompanante",""),
            "acomp1_nombre": perm.get("acomp1_nombre",""),
            "acomp1_dni": perm.get("acomp1_dni",""),
            "acomp_count": perm.get("acomp_count", 0),
            "viaja_solo": bool(perm.get("viaja_solo", False)),

            # ==================== NUEVO: RECEPCIÓN AL ARRIBO ====================
            "recibe_si": perm.get("recibe_si","NO"),
            "rec_nombre": perm.get("rec_nombre",""),
            "rec_doc_tipo": perm.get("rec_doc_tipo",""),
            "rec_doc_num": perm.get("rec_doc_num",""),
            "rec_doc_pais": perm.get("rec_doc_pais",""),

            # --- MOTIVO / ORGANIZADOR ---
            "motivo": perm.get("motivo",""),
            "ciudad_evento": perm.get("ciudad_evento",""),
            "fecha_evento": perm.get("fecha_evento",""),
            "organizador": perm.get("organizador",""),

            # --- FIRMAS ---
            "quien_firma": perm.get("firma_quien","PADRE"),
            "quien_firma_int": perm.get("firma_quien","AMBOS"),
        }
        
        # --- Compat: preseed de claves que usa el formulario para TERCERO ---
        # Si tu formulario usa 'tercero_' o 'acomp1_', deja ambos cargados
        precarga["acomp1_nombre"] = s(perm.get("acomp1_nombre","")) or s(perm.get("tercero_nombre",""))
        precarga["acomp1_dni"]    = s(perm.get("acomp1_dni",""))    or s(perm.get("tercero_dni",""))

        # (opcional, por si el formulario todavía lee 'tercero_*')
        precarga["tercero_nombre"] = precarga["acomp1_nombre"]
        precarga["tercero_dni"]    = precarga["acomp1_dni"]
        
        # 👇 INJECTO: cuando cambias de permiso, limpia y precarga fresco
        if st.session_state.get("pid_editing") != int(pid):
            _clear_lookup_buffers()          # tu helper existente (buscadores, etc.)
            _clear_form_keys_for_new()       # limpia el formulario

            # 🔥 PASO 1: Limpiar TODOS los selectores UBIGEO (incluyendo los que tienen valor)
            ubigeo_keys_all = [
                "padre_departamento_sel", "padre_provincia_sel", "padre_distrito_sel",
                "padre_provincia_sel_empty", "padre_distrito_sel_empty",
                "madre_departamento_sel", "madre_provincia_sel", "madre_distrito_sel",
                "madre_provincia_sel_empty", "madre_distrito_sel_empty",
                # También las versiones sin _sel (por si el formulario usa ambas)
                "padre_departamento", "padre_provincia", "padre_distrito",
                "madre_departamento", "madre_provincia", "madre_distrito",
            ]
    
            for key in ubigeo_keys_all:
                st.session_state.pop(key, None)

            # 🔥 PASO 2: Limpiar cachés de provincias/distritos
            keys_to_remove = [k for k in list(st.session_state.keys()) 
                              if k.startswith("provincias_") or k.startswith("distritos_")]
            for k in keys_to_remove:
                st.session_state.pop(k, None)

            # 🔥 PASO 3: Cargar precarga general
            _push_precarga_to_state(precarga)
    
            # 🔥 PASO 4: PRE-CARGAR UBIGEO **ANTES** de que se rendericen los selectores
            # Estos valores se usan para calcular el index correcto en los selectbox
            st.session_state["padre_departamento"] = precarga.get("padre_departamento", "")
            st.session_state["padre_provincia"] = precarga.get("padre_provincia", "")
            st.session_state["padre_distrito"] = precarga.get("padre_distrito", "")
    
            st.session_state["madre_departamento"] = precarga.get("madre_departamento", "")
            st.session_state["madre_provincia"] = precarga.get("madre_provincia", "")
            st.session_state["madre_distrito"] = precarga.get("madre_distrito", "")
    
            # 🔥 PASO 5: Pre-cargar los cachés de provincias/distritos para que existan al renderizar
            padre_dep = precarga.get("padre_departamento", "")
            if padre_dep:
                # Fuerza carga del caché de provincias del padre
                cache_key_p = f"provincias_{padre_dep}"
                if cache_key_p not in st.session_state:
                    st.session_state[cache_key_p] = obtener_provincias(padre_dep)
        
                padre_prov = precarga.get("padre_provincia", "")
                if padre_prov:
                    # Fuerza carga del caché de distritos del padre
                    cache_key_d = f"distritos_{padre_dep}_{padre_prov}"
                    if cache_key_d not in st.session_state:
                        st.session_state[cache_key_d] = obtener_distritos(padre_dep, padre_prov)
    
            madre_dep = precarga.get("madre_departamento", "")
            if madre_dep:
                # Fuerza carga del caché de provincias de la madre
                cache_key_p = f"provincias_{madre_dep}"
                if cache_key_p not in st.session_state:
                    st.session_state[cache_key_p] = obtener_provincias(madre_dep)
        
                madre_prov = precarga.get("madre_provincia", "")
                if madre_prov:
                    # Fuerza carga del caché de distritos de la madre
                    cache_key_d = f"distritos_{madre_dep}_{madre_prov}"
                    if cache_key_d not in st.session_state:
                        st.session_state[cache_key_d] = obtener_distritos(madre_dep, madre_prov)
    
            st.session_state.modo_edicion = True
            st.session_state.pid_editing = int(pid)
            st.session_state["rol_acompanante"] = precarga.get("rol_acompanante","")

            # Reinicia marcadores de prefill
            st.session_state.pop("_prefill_hermanos_pid", None)
            st.session_state.pop("_prefill_recep_pid", None)
            st.session_state.pop("_prefill_terceros_pid", None)
    
            # 🔥 PASO 6: FORZAR RERUN para que los selectores se redibujen con los nuevos valores
            st.rerun()
            
        # ---------- PRE-CARGA HERMANOS (ÚNICO BLOQUE) ----------
        # Solo en el primer render de este permiso (no volver a pisar lo que el usuario tecleó)
        if st.session_state.get("_prefill_hermanos_pid") != int(pid):
            hermanos = []
            raw_h = perm.get("hermanos_json") or ""
            try:
                hermanos = json.loads(raw_h) if raw_h else []
            except Exception:
                hermanos = []

            # Setea el contador y llena los campos dinámicos
            st.session_state["hermanos"] = list(range(len(hermanos)))  # controla cuántas filas hay
            for i, h in enumerate(hermanos):
                st.session_state[f"hermano_nombre_{i}"]    = s(h.get("nombre",""))
                st.session_state[f"hermano_sexo_{i}"]      = s(h.get("sexo","")).upper() or ""
                st.session_state[f"hermano_doc_tipo_{i}"]  = s(h.get("doc_tipo","DNI")).upper() or "DNI"
                st.session_state[f"hermano_doc_num_{i}"]   = s(h.get("doc_num",""))
                st.session_state[f"hermano_nacionalidad_{i}"] = s(h.get("nacionalidad","")).upper()
                # fnac puede venir "YYYY-MM-DD": intenta parsearlo a date para el date_input
                fnac_h = s(h.get("fnac",""))
                st.session_state[f"hermano_fnac_{i}"] = parse_iso(fnac_h) if fnac_h else None

            st.session_state["_prefill_hermanos_pid"] = int(pid)
        # ---------- FIN PRE-CARGA HERMANOS ----------

        # ---------- PRE-CARGA TERCEROS (ÚNICO BLOQUE) ----------
        # SIEMPRE limpia si cambió el permiso
        if st.session_state.get("_prefill_terceros_pid") != int(pid):
    
            # 🔥 LIMPIEZA AGRESIVA: borra TODO antes de cargar
            # 1) Borra el contador
            if "terceros" in st.session_state:
                old_count = len(st.session_state.get("terceros", []))
                st.session_state.pop("terceros", None)
            else:
                old_count = 10  # limpia hasta 10 por si acaso
    
            # 2) Borra todos los campos dinámicos (hasta old_count)
            for i in range(old_count):
                for k in (f"tercero_rol_{i}", f"tercero_nombre_{i}", f"tercero_dni_{i}"):
                    st.session_state.pop(k, None)
    
            # 3) Ahora carga los terceros del permiso actual
            terceros = []
            raw_t = perm.get("terceros_json") or ""
    
            try:
                terceros = json.loads(raw_t) if raw_t else []
            except Exception:
                terceros = []
    
            # 4) Pobla los nuevos valores
            if terceros:
                st.session_state["terceros"] = list(range(len(terceros)))
                for i, t in enumerate(terceros):
                    st.session_state[f"tercero_rol_{i}"]    = s(t.get("rol", ""))
                    st.session_state[f"tercero_nombre_{i}"] = s(t.get("nombre", ""))
                    st.session_state[f"tercero_dni_{i}"]    = s(t.get("dni", ""))
            else:
                # Si este permiso NO tiene terceros, deja la lista vacía
                st.session_state["terceros"] = []
    
            # 5) Marca que ya se precargó este permiso
            st.session_state["_prefill_terceros_pid"] = int(pid)
        # ---------- FIN PRE-CARGA TERCEROS ----------

        # ---------- PRE-CARGA RECEPCIÓN MÚLTIPLE (ÚNICO BLOQUE) ----------
        # Solo en el primer render de este permiso (no volver a pisar lo que el usuario tecleó)
        if st.session_state.get("_prefill_recep_pid") != int(pid):
            raw = perm.get("rec_list_json") or ""
            try:
                recs = json.loads(raw) if raw else []
            except Exception:
                recs = []

            # Fallback legacy si no hay lista y el permiso dice SI
            if not recs and s(perm.get("recibe_si","NO")).upper() == "SI":
                recs = [{
                    "nombre": s(perm.get("rec_nombre","")).upper(),
                    "tipo":   s(perm.get("rec_doc_tipo","DNI PERUANO")).upper(),
                    "num":    s(perm.get("rec_doc_num","")),
                    "pais":   s(perm.get("rec_doc_pais","")).upper(),
                }]

            if recs:
                st.session_state["rec_list_count"] = len(recs)
                for i, r in enumerate(recs):
                    st.session_state[f"rec_nombre_{i}"]   = s(r.get("nombre","")).upper()
                    st.session_state[f"rec_doc_tipo_{i}"] = s(r.get("tipo","DNI PERUANO")).upper() or "DNI PERUANO"
                    st.session_state[f"rec_doc_num_{i}"]  = s(r.get("num",""))
                    st.session_state[f"rec_doc_pais_{i}"] = s(r.get("pais","")).upper()
                # fuerza el select en SI y deja un hint de count
                precarga["recibe_si"] = "SI"
                precarga["rec_list_count"] = len(recs)
            else:
                st.session_state["rec_list_count"] = 0
                precarga["recibe_si"] = s(perm.get("recibe_si","NO")).upper()
                precarga["rec_list_count"] = 0

            st.session_state["_prefill_recep_pid"] = int(pid)
        # ---------- FIN PRE-CARGA RECEPCIÓN MÚLTIPLE ----------
        vals = formulario_base(precarga, disabled=disabled_form)

        st.markdown("---")
        c_upd, c_regen, c_anular = st.columns(3)

            # Antes del bloque de botones (c_upd, c_regen, c_anular):
        propagar_docs = st.checkbox(
                "Propagar cambios de DNI/Pasaporte a TODOS los permisos históricos",
                value=False,  # déjalo activado por defecto si quieres esta conducta siempre
                help="Si está marcado, cuando cambies el documento de PADRE/MADRE/MENOR, se actualizarán todos los permisos antiguos con el nuevo número."
            )
            # ===================== Guardar cambios (con validaciones y anti doble click) =====================
# asegúrate de tener definidas las funciones:
# validar_vals_para_generar(vals)  y  _mostrar_errores(errores)

        with c_upd:
                if st.button("💾 Guardar cambios", disabled=disabled_form):
                    if disabled_form:
                        st.warning("No puedes guardar cambios porque el permiso está ANULADO.")
                    else:
                        if st.session_state._enviando:
                            st.warning("⏳ Ya estás guardando un permiso, espera un momento…")
                        else:
                            st.session_state._enviando = True
                            try:
                                ok, errores = validar_vals_para_generar(vals)
                                if not ok:
                                    _mostrar_errores(errores)
                                    st.session_state._enviando = False
                                    st.stop()

                                # --- Preparar y guardar actualización ---
                                vias_tx = " Y/O ".join(vals["vias"]).upper() if vals.get("vias") else ""

                                # documentos antiguos (para propagación)
                                old_padre_doc = s(perm.get("padre_doc_num") or perm.get("padre_dni", ""))
                                old_madre_doc = s(perm.get("madre_doc_num") or perm.get("madre_dni", ""))
                                old_menor_doc = s(perm.get("menor_doc_num") or perm.get("menor_dni", ""))

                                # ===== Recepción: viajan solos + lista múltiple (EDITAR/REGENERAR usa las filas dinámicas) =====
                                viaja_solo_calc = s(vals.get("acompanante","")).upper() in ("SOLO", "SOLO(A)/SOLOS(AS)")

                                # 1) leer receptores desde los widgets dinámicos rec_*_i
                                rec_items = []
                                if viaja_solo_calc and s(vals.get("recibe_si","NO")).upper() == "SI":
                                    total_rec = int(st.session_state.get("rec_list_count", 0) or 0)
                                    for i in range(total_rec):
                                        nom  = s(st.session_state.get(f"rec_nombre_{i}", "")).upper()
                                        tipo = s(st.session_state.get(f"rec_doc_tipo_{i}", "")).upper()
                                        num  = s(st.session_state.get(f"rec_doc_num_{i}", ""))
                                        pais = s(st.session_state.get(f"rec_doc_pais_{i}", "")).upper()
                                        if nom and (num or tipo):
                                            rec_items.append({"nombre": nom, "tipo": tipo, "num": num, "pais": pais})

                                # 2) legacy (primer receptor para compatibilidad)
                                rec0_nombre = rec_items[0]["nombre"] if rec_items else ""
                                rec0_tipo   = rec_items[0]["tipo"]   if rec_items else ""
                                rec0_num    = rec_items[0]["num"]    if rec_items else ""
                                rec0_pais   = rec_items[0]["pais"]   if rec_items else ""

                                # 3) flags y json
                                recibe_si_val = "SI" if rec_items else "NO"
                                rec_list_json = json.dumps(rec_items, ensure_ascii=False)

                                # --- Hermanos desde la UI (NECESARIO para data_upd["hermanos_json"]) ---
                                hermanos_list = []
                                for i, _ in enumerate(st.session_state.get("hermanos", [])):
                                    h_nom = s(st.session_state.get(f"hermano_nombre_{i}", ""))
                                    if not h_nom:
                                        continue

                                    h_sex  = (st.session_state.get(f"hermano_sexo_{i}", "") or "").upper()
                                    h_tipo = (st.session_state.get(f"hermano_doc_tipo_{i}", "DNI") or "DNI").upper()
                                    h_num  = s(st.session_state.get(f"hermano_doc_num_{i}", ""))
                                    h_fnac = st.session_state.get(f"hermano_fnac_{i}", None)

                                    # Normaliza fecha a ISO
                                    if h_fnac:
                                        try:
                                            if hasattr(h_fnac, "strftime"):
                                                fnac_iso_h = h_fnac.strftime("%Y-%m-%d")
                                            else:
                                                dtmp = parse_iso(h_fnac)
                                                fnac_iso_h = dtmp.strftime("%Y-%m-%d") if dtmp else ""
                                        except Exception:
                                            fnac_iso_h = ""
                                    else:
                                        fnac_iso_h = ""

                                    # 🚫 NUNCA crear inputs aquí. Solo LEER lo que ya existe en session_state:
                                    h_nac = s(st.session_state.get(f"hermano_nacionalidad_{i}", "")) if h_tipo in ("PASAPORTE", "DNI EXTRANJERO") else ""

                                    hermanos_list.append({
                                        "nombre":       h_nom,
                                        "sexo":         h_sex,
                                        "doc_tipo":     h_tipo,
                                        "doc_num":      h_num,
                                        "fnac":         fnac_iso_h,
                                        "nacionalidad": h_nac,
                                    })

                                # 🆕 NUEVO: Terceros desde la UI (para guardar en BD al editar)
                                terceros_list = []
                                if s(vals.get("acompanante","")).upper() == "TERCERO":
                                    for i in range(len(st.session_state.get("terceros", []))):
                                        rol = s(st.session_state.get(f"tercero_rol_{i}", "")).upper()
                                        nombre = s(st.session_state.get(f"tercero_nombre_{i}", "")).upper()
                                        dni = s(st.session_state.get(f"tercero_dni_{i}", ""))
        
                                        if nombre:  # Solo guardar si tiene nombre
                                            terceros_list.append({
                                                "rol": rol,
                                                "nombre": nombre,
                                                "dni": dni
                                            })

                                # ===== AHORA SÍ: construir data_upd de una vez (sin .update antes) =====
                                data_upd = {
                                    # CIUDAD / NOTARIO
                                    "ciudad": vals["ciudad"], "notario": vals["notario"],

                                    # PADRE
                                    "padre_nombre": vals["padre_nombre"], "padre_dni": vals["padre_dni"],
                                    "padre_estado_civil": vals["padre_estado_civil"], "padre_direccion": vals["padre_direccion"],
                                    "padre_distrito": vals["padre_distrito"], "padre_provincia": vals["padre_provincia"],
                                    "padre_departamento": vals["padre_departamento"],
                                    "padre_doc_tipo": vals["padre_doc_tipo"], "padre_doc_num": vals["padre_doc_num"],
                                    "padre_nacionalidad": vals["padre_nacionalidad"],

                                    # MADRE
                                    "madre_nombre": vals["madre_nombre"], "madre_dni": vals["madre_dni"],
                                    "madre_estado_civil": vals["madre_estado_civil"], "madre_direccion": vals["madre_direccion"],
                                    "madre_distrito": vals["madre_distrito"], "madre_provincia": vals["madre_provincia"],
                                    "madre_departamento": vals["madre_departamento"],
                                    "madre_doc_tipo": vals["madre_doc_tipo"], "madre_doc_num": vals["madre_doc_num"],
                                    "madre_nacionalidad": vals["madre_nacionalidad"],

                                    # MENOR
                                    "menor_nombre": vals["menor_nombre"], "menor_dni": vals["menor_dni"],
                                    "menor_fnac": vals["menor_fnac"], "sexo_menor": vals["sexo_menor"],
                                    "menor_doc_tipo": vals["menor_doc_tipo"], "menor_doc_num": vals["menor_doc_num"],
                                    "menor_nacionalidad": vals["menor_nacionalidad"],

                                    # VIAJE
                                    "tipo_viaje": vals["tipo_viaje"],
                                    "firma_quien": (vals["quien_firma"] if vals["tipo_viaje"]=="NACIONAL" else vals["quien_firma_int"]),
                                    "origen": vals["origen"], "destino": vals["destino"],
                                    "vias": vias_tx, "empresa": vals["empresa"],
                                    "salida": vals["fs"].strftime("%Y-%m-%d"),
                                    "retorno": vals["fr"].strftime("%Y-%m-%d") if vals["fr"] else "",

                                    # ACOMPAÑANTE
                                    "acompanante": vals["acompanante"],
                                    "rol_acompanante": s(vals.get("rol_acompanante","")),
                                    "acomp_count": int(vals.get("acomp_count") or 0),
                                    # valores provenientes del form (con fallback)
                                    "_tmp_acomp1_nombre": s(vals.get("acomp1_nombre") or vals.get("tercero_nombre","")),
                                    "_tmp_acomp1_dni":    s(vals.get("acomp1_dni")    or vals.get("tercero_dni","")),
                                    # aplicar según el tipo de acompañante
                                    "acomp1_nombre": (s(vals.get("acomp1_nombre") or vals.get("tercero_nombre",""))
                                                      if s(vals.get("acompanante","")).upper()=="TERCERO" else ""),
                                    "acomp1_dni":    (s(vals.get("acomp1_dni")    or vals.get("tercero_dni",""))
                                                      if s(vals.get("acompanante","")).upper()=="TERCERO" else ""),
                                    # espejo legacy
                                    "tercero_nombre": (s(vals.get("acomp1_nombre") or vals.get("tercero_nombre",""))
                                                       if s(vals.get("acompanante","")).upper()=="TERCERO" else ""),
                                    "tercero_dni":    (s(vals.get("acomp1_dni")    or vals.get("tercero_dni",""))
                                                       if s(vals.get("acompanante","")).upper()=="TERCERO" else ""),

                                    # RECEPCIÓN (nueva estructura con lista + campos legacy)
                                    "viaja_solo": viaja_solo_calc,
                                    "recibe_si":  recibe_si_val,
                                    "rec_nombre": rec0_nombre,
                                    "rec_doc_tipo": rec0_tipo,
                                    "rec_doc_num":  rec0_num,
                                    "rec_doc_pais": rec0_pais,
                                    "rec_list_json": rec_list_json,

                                    # MOTIVO
                                    "motivo": vals["motivo"], "ciudad_evento": vals["ciudad_evento"],
                                    "fecha_evento": vals["fecha_evento"], "organizador": vals["organizador"],

                                    # META
                                    "archivo_generado": perm.get("archivo_generado",""),
                                    "estado": "CORREGIDO" if estado_perm != "ANULADO" else "ANULADO",
                                    "version": perm.get("version",1),
                                    "anulado_at": perm.get("anulado_at",""),
                                    "anulado_motivo": perm.get("anulado_motivo",""),
                                    "anulado_por": perm.get("anulado_por",""),
                                }

                                # Si ya calculaste 'hermanos_list' antes, añádelo:
                                data_upd["hermanos_json"] = json.dumps(hermanos_list, ensure_ascii=False)
                                data_upd["terceros_json"] = json.dumps(terceros_list, ensure_ascii=False)  

                                # 5) guardar
                                update_permiso(int(pid), data_upd)

                    # Propagación de cambios de documentos (opcional)
                                new_padre_doc = s(vals.get("padre_doc_num") or vals.get("padre_dni", ""))
                                new_madre_doc = s(vals.get("madre_doc_num") or vals.get("madre_dni", ""))
                                new_menor_doc = s(vals.get("menor_doc_num") or vals.get("menor_dni", ""))

                                # --- PROPAGACIÓN (si el usuario marcó el checkbox) ---
                                if propagar_docs:
                                    total = 0
                                    if old_padre_doc and new_padre_doc and old_padre_doc != new_padre_doc:
                                        total += propagar_cambio_doc("PADRE", old_padre_doc, new_padre_doc)
                                    if old_madre_doc and new_madre_doc and old_madre_doc != new_madre_doc:
                                        total += propagar_cambio_doc("MADRE", old_madre_doc, new_madre_doc)
                                    if old_menor_doc and new_menor_doc and old_menor_doc != new_menor_doc:
                                        total += propagar_cambio_doc("MENOR", old_menor_doc, new_menor_doc)
                                    st.success(f"Cambios guardados ✅. Se propagaron {total} permiso(s) histórico(s).")
                                else:
                                    st.success("Cambios guardados ✅. Sin propagación de documentos.")
                            except Exception as e:
                                st.error(f"Ocurrió un error: {e}")
                            finally:
                                st.session_state._enviando = False
# ================================================================================================

            # Re-generar DOCX
        with c_regen:
                disabled_regen = (estado_perm == "ANULADO")
                if st.button("🧾 Re-generar DOCX (nueva versión)", disabled=disabled_regen):
                    if disabled_regen:
                        st.warning("⛔ No se puede re-generar un permiso ANULADO.")
                    else:
                        perm_act = fetch_permiso_by_id(int(pid))
                        perm_act["version"] = perm_act.get("version",1) + 1
                        
                        # 👇 Ajuste de conteo de acompañantes (para OBSERVACIONES)
                        a = s(perm_act.get("acompanante","")).upper()
                        if a == "AMBOS":
                            acomp_count_eff = 2
                        elif a in ("PADRE","MADRE","TERCERO"):
                            acomp_count_eff = 1
                        else:
                            acomp_count_eff = 0

                        perm_act["acomp_count"] = acomp_count_eff

                        # ==== HERMANOS DESDE LA UI (para regenerar) ====
                        perm_act["hermanos"] = []
                        for i in range(len(st.session_state.get("hermanos", []))):
                            h_nom = s(st.session_state.get(f"hermano_nombre_{i}", ""))
                            if not h_nom:
                                continue
                            h_sex = (st.session_state.get(f"hermano_sexo_{i}", "") or "").upper()
                            h_tipo = (st.session_state.get(f"hermano_doc_tipo_{i}", "DNI") or "DNI").upper()
                            h_num = s(st.session_state.get(f"hermano_doc_num_{i}", ""))
                            h_fnac = st.session_state.get(f"hermano_fnac_{i}", None)
                            h_nac = s(st.session_state.get(f"hermano_nacionalidad_{i}", "")) if h_tipo in ("PASAPORTE","DNI EXTRANJERO") else ""

                            perm_act["hermanos"].append({
                                "nombre": h_nom,
                                "sexo": h_sex,
                                "doc_tipo": h_tipo,
                                "doc_num": h_num,
                                "fnac": h_fnac,
                                "nacionalidad": h_nac,   # ← viaja a la regeneración
                            })
                            # ==== FIN HERMANOS ====
                  
                        # justo antes del perm_act.update(...)
                        viaja_solo_calc = s(vals.get("acompanante","")).upper() in ["SOLO","SOLO(A)/SOLOS(AS)"]
                        # <<<<<<<<<< AQUI: ACTUALIZA perm_act CON LO EDITADO EN EL FORM >>>>>>>>>>
                        perm_act.update({
                            "acompanante": vals.get("acompanante"),
                            "rol_acompanante": vals.get("rol_acompanante"),
                            "acomp1_nombre": vals.get("acomp1_nombre"),
                            "acomp1_dni": vals.get("acomp1_dni"),
                            "acomp_count": vals.get("acomp_count"),
                            "viaja_solo": viaja_solo_calc,

                        # recepción (SI/NO y datos de la persona que recibe)
                            "recibe_si": (s(vals.get("recibe_si")) or "NO").upper(),
                            "rec_nombre": s(vals.get("rec_nombre")).upper(),
                            "rec_doc_tipo": s(vals.get("rec_doc_tipo")).upper(),
                            "rec_doc_num": s(vals.get("rec_doc_num")),
                            "rec_doc_pais": s(vals.get("rec_doc_pais")).upper(),

                        # viaje (por si cambió en la edición)
                            "vias": vals.get("vias"),
                            "empresa": s(vals.get("empresa")),
                            "destino": s(vals.get("destino")),
                        })

                        # --- Normaliza tipos para regenerar (lo que _ctx_comun_desde_perm espera) ---
                        # 'vias' debe ser STRING con "Y/O", no lista
                        v = perm_act.get("vias")
                        if isinstance(v, list):
                            # une las vías en un string "AEREA Y/O TERRESTRE" (en mayúsculas, sin huecos vacíos)
                            perm_act["vias"] = " Y/O ".join([s(x).upper() for x in v if s(x)])
                        elif v is None:
                            perm_act["vias"] = ""  # evita None

                        # (opcional) asegura que empresa/destino sean strings
                        perm_act["empresa"] = s(perm_act.get("empresa"))
                        perm_act["destino"] = s(perm_act.get("destino"))

                        # recepción: forzar a string (por si vinieran None)
                        for k in ("recibe_si","rec_nombre","rec_doc_tipo","rec_doc_num","rec_doc_pais"):
                            perm_act[k] = s(perm_act.get(k))
                        
                        # --- Reglas de limpieza de recepción ---
                        if not viaja_solo_calc:
                            # Si NO viajan solos, no debe quedar recepción
                            perm_act["recibe_si"] = "NO"
                            perm_act["rec_nombre"] = ""
                            perm_act["rec_doc_tipo"] = ""
                            perm_act["rec_doc_num"] = ""
                            perm_act["rec_doc_pais"] = ""
                        elif perm_act["recibe_si"] == "NO":
                            # Viajan solos pero marcaste NO recepción → limpia igual
                            perm_act["rec_nombre"] = ""
                            perm_act["rec_doc_tipo"] = ""
                            perm_act["rec_doc_num"] = ""
                            perm_act["rec_doc_pais"] = ""
                        
                        
                        # (Recomendado) documentos actuales de PADRE/MADRE si se editaron
                        perm_act.update({
                            "padre_doc_tipo": vals.get("padre_doc_tipo"),
                            "padre_doc_num":  vals.get("padre_doc_num"),
                            "madre_doc_tipo": vals.get("madre_doc_tipo"),
                            "madre_doc_num":  vals.get("madre_doc_num"),
                        })
                        
                                                
                        plantilla_regen = PLANTILLA_DEFAULT
                        tmp_custom = os.path.join(BASE_DIR,"_tmp_plantilla.docx")
                        if os.path.exists(tmp_custom):
                            plantilla_regen = tmp_custom

                        try:
                            nuevo_archivo = regenerate_docx_for_permiso(perm_act, plantilla_regen)
                            perm_act["archivo_generado"] = os.path.join(BASE_DIR, nuevo_archivo)
                            perm_act["estado"] = "CORREGIDO"
                            update_permiso(int(pid), perm_act)

                            st.success(f"Documento re-generado: {nuevo_archivo}")
                            st.download_button(
                                "⬇️ Descargar DOCX",
                                data=open(os.path.join(BASE_DIR, nuevo_archivo), "rb").read(),
                                file_name=nuevo_archivo,
                                use_container_width=True
                            )
                        except Exception as e:
                            st.error(f"No se pudo re-generar: {e}")

            # Anular
        with c_anular:
                st.markdown("**⚠️ Anular permiso**")
                if not st.session_state.is_admin:
                    st.info("🔒 Solo un **ADMIN** puede anular. Inicia sesión en el panel **🔐 Administrador** (barra lateral).")
                    st.button("⛔ Anular definitivamente", type="primary", disabled=True)
                else:
                    motivo_anula = st.text_input("Motivo de anulación (opcional)").upper()
                    confirm = st.text_input("Para anular escribe: ANULAR").upper()
                    if st.button("⛔ Anular definitivamente", type="primary", disabled=(estado_perm=="ANULADO")):
                        if estado_perm == "ANULADO":
                            st.warning("Este permiso ya está ANULADO.")
                        elif confirm != "ANULAR":
                            st.error("Debes escribir **ANULAR** para confirmar.")
                        else:
                            ok, msg = anular_permiso(int(pid), motivo_anula, usuario=(st.session_state.admin_user or "ADMIN"))
                            if ok:
                                st.success(msg)
                            else:
                                st.warning(msg)
    
# ------------------- DNI REGISTRADOS -------------------
if modo == "📇 DNI registrados":
    st.subheader("📇 DNI registrados (PADRE/MADRE/MENOR)")

    # ---------- Expander: Actualizar DNI/Pasaporte (ADMIN) ----------
    with st.expander("🔁 Actualizar DNI/Pasaporte en histórico (solo ADMIN)", expanded=False):
        if not st.session_state.is_admin:
            st.info("Inicia sesión como administrador para actualizar documentos masivamente.")
        else:
            colu1, colu2, colu3 = st.columns([1, 1, 2])
            with colu1:
                rol_upd = st.selectbox("Rol", ["PADRE", "MADRE", "MENOR"], index=0, key="upd_rol")
            with colu2:
                old_doc_in = st.text_input("Documento actual", key="upd_old").strip().upper()
            with colu3:
                new_doc_in = st.text_input("Documento nuevo", key="upd_new").strip().upper()

            st.caption("Esta acción reemplaza el documento en TODOS los permisos históricos del rol seleccionado.")

            c1, c2 = st.columns([1,3])
            with c1:
                go = st.button("🔁 Actualizar documento en histórico", use_container_width=True, key="btn_admin_actualizar_doc")
            with c2:
                st.write("")

            if go:
                if not old_doc_in or not new_doc_in:
                    st.warning("Completa ambos campos: documento actual y documento nuevo.")
                elif old_doc_in == new_doc_in:
                    st.warning("El documento nuevo no puede ser igual al actual.")
                else:
                    ok, msg, n = admin_actualizar_doc(rol_upd, old_doc_in, new_doc_in, mover_oculto=True)
                    if ok:
                        st.success(f"✅ {msg}")
                        st.session_state._dni_refresh = True
                    else:
                        st.error(f"❌ {msg}")

    st.markdown("---")

    # ---------- Filtros + paginación ----------
    colf1, colf2, colf3, colf4 = st.columns([1.2, 1.2, 2.2, 1.0])
    with colf1:
        rol_sel = st.selectbox("Rol", ["(Todos)", "PADRE", "MADRE", "MENOR", "HERMANO"], index=0, key="dni_rol_sel")
        rol_query = None if rol_sel == "(Todos)" else rol_sel
    with colf2:
        incluir_ocultos = st.checkbox("Incluir ocultos", value=False, key="dni_inc_ocultos")
    with colf3:
        filtro_txt_in = st.text_input(
            "Buscar por DOC o NOMBRE (Enter o clic en Buscar)",
            key="dni_filtro_txt"
        ).upper().strip()
    with colf4:
        page_size = st.selectbox("Tamaño página", [10, 20, 50, 100], index=1, key="dni_page_size")

    # Estado de paginación
    if "_dni_page" not in st.session_state:
        st.session_state._dni_page = 1
    if "_dni_query_cache" not in st.session_state:
        st.session_state._dni_query_cache = {
            "rol": rol_query, "filtro": filtro_txt_in,
            "ocultos": incluir_ocultos, "page_size": page_size
        }

    # Botón Buscar (para debouncing)
    buscar = st.button("🔎 Buscar", key="dni_buscar_btn")

    # Si cambian filtros o se presiona Buscar, resetea página
    changed_filters = (
        st.session_state._dni_query_cache.get("rol") != rol_query or
        st.session_state._dni_query_cache.get("filtro") != filtro_txt_in or
        st.session_state._dni_query_cache.get("ocultos") != incluir_ocultos or
        st.session_state._dni_query_cache.get("page_size") != page_size or
        st.session_state.get("_dni_refresh", False)
    )
    if buscar or changed_filters:
        st.session_state._dni_page = 1
        st.session_state._dni_query_cache = {
            "rol": rol_query, "filtro": filtro_txt_in,
            "ocultos": incluir_ocultos, "page_size": page_size
        }
        st.session_state._dni_refresh = False

    # Cálculo de offset
    page = max(1, int(st.session_state._dni_page))
    offset = (page - 1) * int(page_size)

    # Cargar página
    registros, total = fetch_docs_registrados_paged(
        rol=rol_query,                       # ← ahora acepta MENOR también
        filtro_texto=filtro_txt_in,
        incluir_ocultos=incluir_ocultos,
        limit=int(page_size),
        offset=int(offset)
    )

    # Info y navegación
    if total == 0:
        st.info("No hay resultados para el filtro actual.")
    else:
        total_pages = max(1, (total + int(page_size) - 1) // int(page_size))
        st.caption(f"Mostrando {len(registros)} de {total} — Página {page} de {total_pages}")

        nav1, nav2, nav3 = st.columns([1,1,3])
        with nav1:
            if st.button("⟵ Anterior", disabled=(page <= 1), key=f"dni_prev_{page}"):
                st.session_state._dni_page = page - 1
                st.rerun()
        with nav2:
            if st.button("Siguiente ⟶", disabled=(page >= total_pages), key=f"dni_next_{page}"):
                st.session_state._dni_page = page + 1
                st.rerun()
        with nav3:
            st.write("")

        # Motivo para ocultar/mostrar
        motivo_ocultar = st.text_input(
            "Motivo (para ocultar/mostrar)",
            placeholder="Error de digitación / homónimo / etc.",
            key="dni_motivo_ocultar"
        ).upper()

        # Tabla por filas (botones con keys únicas)
        for (r_rol, r_doc, r_nom, r_ult, r_oculto) in registros:
            cont1, cont2, cont3, cont4 = st.columns([1.2, 1.6, 2.4, 1.3])
            with cont1:
                st.write(r_rol)
            with cont2:
                st.write(r_doc)
            with cont3:
                st.write(r_nom or "—")
            with cont4:
                st.markdown("🟧 OCULTO" if r_oculto else "🟩 VISIBLE")

            btns1, btns2, btns3 = st.columns([1,1,2])
            with btns1:
                if st.button(
                    "👁 Mostrar",
                    key=f"btn_show_{r_rol}_{r_doc}",
                    disabled=(not r_oculto) or (not st.session_state.is_admin)
                ):
                    ok, msg = mostrar_doc(r_rol, r_doc)
                    if ok:
                        st.success(msg); st.session_state._dni_refresh = True; st.rerun()
                    else:
                        st.error(msg)
            with btns2:
                if st.button(
                    "🙈 Ocultar",
                    key=f"btn_hide_{r_rol}_{r_doc}",
                    disabled=r_oculto or (not st.session_state.is_admin)
                ):
                    if not motivo_ocultar.strip():
                        st.warning("Indica un motivo para ocultar.")
                    else:
                        ok, msg = ocultar_doc(
                            r_rol, r_doc, motivo_ocultar,
                            creado_por=st.session_state.admin_user or "USUARIO"
                        )
                        if ok:
                            st.success(msg); st.session_state._dni_refresh = True; st.rerun()
                        else:
                            st.error(msg)
            with btns3:
                st.caption(f"Última act.: {r_ult or '—'}")

        st.caption(f"Mostrando {len(registros)} de {total} — Página {page} de {total_pages}")
        
if modo == "🤖 Asistente IA":
    st.markdown("## 🤖 Asistente IA - Consultas Inteligentes")
    
    # ══════════════════════════════════════════════════════════════════
    # 🎨 CSS ULTRA-MEJORADO (contenedor scrollable + input fijo)
    # ══════════════════════════════════════════════════════════════════
    st.markdown("""
    <style>
    /* ========== OCULTAR PADDING EXTRA DE STREAMLIT ========== */
    .main .block-container {
        padding-top: 2rem !important;
        padding-bottom: 1rem !important;
        max-width: 100% !important;
    }
    
    /* ========== CONTENEDOR DE MENSAJES (altura fija + scroll) ========== */
    .chat-messages-container {
        height: calc(100vh - 350px);
        overflow-y: auto;
        overflow-x: hidden;
        padding: 20px;
        margin-bottom: 20px;
        background: #0e0e0e;
        border-radius: 12px;
        border: 1px solid #2a2a2a;
    }
    
    /* ========== SCROLL PERSONALIZADO ========== */
    .chat-messages-container::-webkit-scrollbar {
        width: 8px;
    }
    .chat-messages-container::-webkit-scrollbar-track {
        background: #1a1a1a;
        border-radius: 4px;
    }
    .chat-messages-container::-webkit-scrollbar-thumb {
        background: #d4af37;
        border-radius: 4px;
    }
    .chat-messages-container::-webkit-scrollbar-thumb:hover {
        background: #f1c550;
    }
    
    /* ========== MENSAJES DE CHAT (animación suave) ========== */
    .chat-message {
        padding: 18px 22px;
        border-radius: 14px;
        margin-bottom: 18px;
        animation: slideIn 0.3s ease;
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
    }
    
    @keyframes slideIn {
        from { 
            opacity: 0; 
            transform: translateY(15px); 
        }
        to { 
            opacity: 1; 
            transform: translateY(0); 
        }
    }
    
    /* TÚ (usuario) - cuadro dorado */
    .user-message {
        background: linear-gradient(135deg, #2a2520 0%, #1e1a15 100%);
        border-left: 5px solid #d4af37;
        color: #f1c550;
        margin-left: 60px;
    }
    
    /* ASISTENTE - cuadro azul oscuro */
    .assistant-message {
        background: linear-gradient(135deg, #1a1f2e 0%, #0f1419 100%);
        border-left: 5px solid #4a9eff;
        color: #e8e8e8;
        margin-right: 60px;
    }
    
    /* Encabezado del mensaje */
    .chat-message strong {
        display: block;
        margin-bottom: 8px;
        font-size: 14px;
        opacity: 0.9;
    }
    
    /* Contenido */
    .chat-message-content {
        font-size: 15px;
        line-height: 1.6;
    }
    
    /* Mensaje de bienvenida */
    .welcome-chat {
        text-align: center;
        padding: 100px 20px;
        color: #888;
    }
    .welcome-chat h2 {
        color: #d4af37;
        margin-bottom: 12px;
        font-size: 28px;
    }
    
    /* ========== INPUT DEL CHAT (nativo de Streamlit) ========== */
    [data-testid="stChatInput"] {
        position: sticky !important;
        bottom: 0 !important;
        background: linear-gradient(to top, #0e0e0e 90%, transparent) !important;
        padding: 15px 0 !important;
        margin-top: 20px !important;
        z-index: 999 !important;
    }
    
    [data-testid="stChatInput"] input {
        font-size: 16px !important;
        padding: 16px 18px !important;
        border-radius: 14px !important;
        border: 2px solid #d4af37 !important;
        background: #1e1e1e !important;
        color: #ffffff !important;
        transition: all 0.2s ease !important;
    }
    
    [data-testid="stChatInput"] input:focus {
        border-color: #f1c550 !important;
        box-shadow: 0 0 12px rgba(212, 175, 55, 0.5) !important;
        outline: none !important;
    }
    
    [data-testid="stChatInput"] input::placeholder {
        color: #888 !important;
        font-style: italic;
    }
    
    /* Botón de envío */
    [data-testid="stChatInput"] button {
        background: linear-gradient(135deg, #d4af37 0%, #f1c550 100%) !important;
        color: #0e0e0e !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 10px 18px !important;
        font-weight: bold !important;
        transition: all 0.2s ease !important;
    }
    
    [data-testid="stChatInput"] button:hover {
        background: linear-gradient(135deg, #f1c550 0%, #d4af37 100%) !important;
        transform: scale(1.05) !important;
        box-shadow: 0 4px 12px rgba(212, 175, 55, 0.4) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # ══════════════════════════════════════════════════════════════════
    # 📊 Estadísticas del sistema
    # ══════════════════════════════════════════════════════════════════
    with st.expander("📊 Estadísticas del Sistema", expanded=False):
        try:
            with get_conn() as conn:
                total_permisos = conn.execute("SELECT COUNT(*) FROM permisos").fetchone()[0]
                anio_actual = date.today().year
                permisos_anio = conn.execute(
                    "SELECT COUNT(*) FROM permisos WHERE anio = ?", 
                    (anio_actual,)
                ).fetchone()[0]
                hace_30_dias = (date.today() - timedelta(days=30)).isoformat()
                permisos_mes = conn.execute(
                    "SELECT COUNT(*) FROM permisos WHERE date(fecha_registro) >= ?", 
                    (hace_30_dias,)
                ).fetchone()[0]
                ultimo = conn.execute("""
                    SELECT numero, anio, fecha_registro 
                    FROM permisos 
                    ORDER BY datetime(fecha_registro) DESC 
                    LIMIT 1
                """).fetchone()
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Permisos", f"{total_permisos:,}")
            with col2:
                st.metric(f"Este Año ({anio_actual})", f"{permisos_anio:,}")
            with col3:
                st.metric("Últimos 30 días", f"{permisos_mes:,}")
            with col4:
                if ultimo:
                    st.metric("Último N°", f"{ultimo[0]:04d}-{ultimo[1]}")
                else:
                    st.metric("Último N°", "N/A")
        except Exception as e:
            st.caption(f"No se pudieron cargar stats: {e}")
    
    # ══════════════════════════════════════════════════════════════════
    # 💬 HISTORIAL DE CHAT (USANDO st.chat_message NATIVO)
    # ══════════════════════════════════════════════════════════════════

    # Inicializar historial
    if "ia_chat_history" not in st.session_state:
        st.session_state.ia_chat_history = []

    # Botón limpiar
    col_title, col_clear = st.columns([4, 1])
    with col_title:
        st.markdown("### 💬 Conversación")
    with col_clear:
        if st.button("🗑️ Limpiar", key="clear_chat"):
            st.session_state.ia_chat_history = []
            st.rerun()
    # ========== CONTENEDOR SCROLLABLE DE MENSAJES (NATIVO STREAMLIT) ==========
    chat_container = st.container()

    with chat_container:
        if not st.session_state.ia_chat_history:
            st.info("👋 ¡Hola! Soy tu asistente IA. Escribe una consulta abajo para empezar.")
            st.caption("**Ejemplo:** _permisos nacionales este mes_")
        else:
            # Renderizar cada mensaje con st.chat_message (componente nativo de Streamlit 1.50+)
            for msg in st.session_state.ia_chat_history:
                if msg["role"] == "user":
                    with st.chat_message("user", avatar="🧑"):
                        st.markdown(msg["content"])
                else:
                    with st.chat_message("assistant", avatar="🤖"):
                        st.markdown(msg["content"])
    # Mostrar tablas/gráficos FUERA del contenedor de mensajes
    if st.session_state.ia_chat_history:
        last_msg = st.session_state.ia_chat_history[-1]
        if last_msg.get("role") == "assistant" and last_msg.get("rows"):
            with st.expander("📋 Ver tabla de resultados", expanded=False):
                _show_rows_table(last_msg["rows"])
            _show_chart_if_applicable(last_msg["rows"], last_msg["content"])
    
    # ══════════════════════════════════════════════════════════════════
    # 🎯 INPUT FIJO ABAJO (usando st.chat_input nativo)
    # ══════════════════════════════════════════════════════════════════
    
    query_user = st.chat_input(
        placeholder="Escribe tu consulta aquí... (presiona Enter para enviar)",
        key="ia_chat_input"
    )
    
    # Procesar cuando hay input
    if query_user and query_user.strip():
        # Agregar pregunta
        st.session_state.ia_chat_history.append({
            "role": "user",
            "content": query_user.strip()
        })
        
        # Procesar respuesta
        try:
            res = _answer_question_struct(query_user.strip())
            st.session_state.ia_chat_history.append({
                "role": "assistant",
                "content": res["msg"],
                "rows": res.get("rows", [])
            })
        except Exception as e:
            st.session_state.ia_chat_history.append({
                "role": "assistant",
                "content": f"❌ Error: {e}"
            })
        
        # Refrescar interfaz
        st.rerun()
    
    # ══════════════════════════════════════════════════════════════════
    # 📚 AYUDA
    # ══════════════════════════════════════════════════════════════════
    with st.expander("❓ ¿Qué puedo preguntar?", expanded=False):
        st.markdown("""
        **📅 Por fecha:** "Permisos este mes", "Internacionales en 2025"
        
        **🌍 Por destino:** "Destino SANTIAGO", "Permisos a PIURA"
        
        **👤 Por persona:** "DNI 12345678", "Nombre JUAN PEREZ"
        
        **🔢 Por número:** "Permiso 2025 número 31", "Últimos 10 permisos"
        
        **📊 Análisis:** "Tendencias", "Top destinos", "Comparar años"
        
        **🔍 Especiales:** "Viajan solos", "Con hermanos", "Recepción", "Anulados"
        """)