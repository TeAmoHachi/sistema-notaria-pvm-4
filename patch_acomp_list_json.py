import sqlite3

DB = "permisos.db"

con = sqlite3.connect(DB)
cur = con.cursor()

print("🔍 Verificando estructura...")

# 1) Agregar columna si no existe
try:
    cur.execute("ALTER TABLE permisos ADD COLUMN acomp_list_json TEXT;")
    print("✅ Columna 'acomp_list_json' agregada.")
except Exception as e:
    if "duplicate" in str(e).lower():
        print("ℹ La columna 'acomp_list_json' ya existe.")
    else:
        raise

# 2) Normalizar NULL → ""
cur.execute("UPDATE permisos SET acomp_list_json = '' WHERE acomp_list_json IS NULL;")
con.commit()

# 3) Mostrar columnas actuales
cur.execute("PRAGMA table_info(permisos);")
cols = [c[1] for c in cur.fetchall()]
print("🧱 Columnas actuales:", cols)

# 4) Verificar que no queden NULL
cur.execute("SELECT COUNT(*) FROM permisos WHERE acomp_list_json IS NULL;")
restantes = cur.fetchone()[0]
print("🔄 Registros aún con NULL:", restantes)

con.close()
print("🎯 Parche aplicado correctamente.")