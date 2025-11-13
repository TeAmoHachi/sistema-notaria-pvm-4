# verificar_terceros.py
import sqlite3

conn = sqlite3.connect("permisos.db")
cur = conn.cursor()

# Ver columnas
cur.execute("PRAGMA table_info(permisos);")
cols = [c[1] for c in cur.fetchall()]
print("📋 Columnas actuales:", cols)

if "terceros_json" in cols:
    print("✅ La columna 'terceros_json' existe")
    
    # Ver si hay datos
    cur.execute("SELECT id, numero, anio, terceros_json FROM permisos WHERE terceros_json IS NOT NULL AND terceros_json != '' LIMIT 5;")
    rows = cur.fetchall()
    print(f"\n📊 {len(rows)} permisos tienen terceros guardados:")
    for r in rows:
        print(f"  ID {r[0]} - NSC-{r[2]}-{r[1]:04d}: {r[3][:100]}...")
else:
    print("❌ La columna 'terceros_json' NO EXISTE")
    print("💡 Ejecuta esto para crearla:")
    print('   ALTER TABLE permisos ADD COLUMN terceros_json TEXT;')

conn.close()