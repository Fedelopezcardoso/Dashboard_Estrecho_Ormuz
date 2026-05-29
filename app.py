import os
import time
import threading
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
from dotenv import load_dotenv

# Cargar variables de entorno estáticas desde un .env si existe
load_dotenv()

app = Flask(__name__)
CORS(app)

# ==========================================
# 🛡️ SEGURIDAD Y CONTROL DE ACCESO
# ==========================================
# Se requiere un Bearer Token para consumir los endpoints desde fuera.
# Si la IP es 127.0.0.1 (Localhost), para facilitar tu desarrollo, lo dejamos pasar.
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN", "ORMUZ-SECURE-KEY-2026")

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = request.remote_addr
        
        # Permitir localhost siempre
        if client_ip in ['127.0.0.1', '::1', 'localhost']:
            return f(*args, **kwargs)
            
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized", "message": "Falta Bearer Token de autorización."}), 401
            
        token = auth_header.split(" ")[1]
        if token != API_BEARER_TOKEN:
            return jsonify({"error": "Forbidden", "message": "Token inválido en el área operativa."}), 403
            
        return f(*args, **kwargs)
    return decorated


# ==========================================
# 🗄️ CONFIGURACIÓN DE BASE DE DATOS SQLite
# ==========================================
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "ormuz_sense.db")

def get_db_connection():
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # Permite acceder a las columnas por nombre como un dict
        return conn
    except Exception as e:
        print(f"[!] ERROR CRÍTICO: No se pudo conectar a SQLite: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn:
        return
        
    cursor = conn.cursor()
    
    # Crear tabla incidentes
    tabla_query = """
        CREATE TABLE IF NOT EXISTS incidentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_utc DATETIME NOT NULL,
            fuente TEXT NOT NULL,
            mensaje_crudo TEXT NOT NULL,
            nivel_riesgo TEXT CHECK(nivel_riesgo IN ('Bajo', 'Medio', 'Critico')) NOT NULL,
            impacto_logistico INTEGER CHECK (impacto_logistico >= 1 AND impacto_logistico <= 10),
            link TEXT
        )
    """
    cursor.execute(tabla_query)
    
    # Intentar agregar la columna link si la base de datos ya existía de antes (falla silencioso si ya existe)
    try:
        cursor.execute("ALTER TABLE incidentes ADD COLUMN link TEXT")
    except sqlite3.OperationalError:
        pass # La columna ya existe, no hay problema
        
    conn.commit()
    conn.close()
    print("[+] Base de datos local SQLite (ormuz_sense.db) inicializada correctamente.")


# ==========================================
# 🧠 IA Y LÓGICA DE CLASIFICACIÓN
# ==========================================
def analizar_riesgo_con_ia(mensaje_crudo):
    """
    PLACEHOLDER: Integración futura con Gemini/GPT para inferencia NLP.
    Actualmente usa un motor basado en reglas (keywords) para pruebas.
    """
    # ... Aquí iría el código: response = gemini_client.generate_content(prompt)
    
    mensaje_lower = mensaje_crudo.lower()
    
    # Reglas Dummy Básicas de Clasificación (Pre-IA)
    críticos = ["missile", "attack", "sinking", "fire", "houthi", "strike", "war", "escalation",
                "misil", "ataque", "hundimiento", "fuego", "hutí", "hutíes", "guerra", "escalada", "golpe"]
    medios = ["drone", "irgc", "blockade", "strait", "warning", "tension", "yemen", "navy", "guard",
              "dron", "drones", "bloqueo", "estrecho", "alarma", "advertencia", "tensión", "armada", "guardia"]
    
    if any(palabra in mensaje_lower for palabra in críticos):
        return "Critico", 9
    elif any(palabra in mensaje_lower for palabra in medios):
        return "Medio", 6
    else:
        return "Bajo", 2

def guardar_incidente(fuente, mensaje, link=None):
    conn = get_db_connection()
    if not conn: return
    
    cursor = conn.cursor()
    
    nivel_riesgo, impacto = analizar_riesgo_con_ia(mensaje)
    timestamp_actual = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    
    sql = "INSERT INTO incidentes (timestamp_utc, fuente, mensaje_crudo, nivel_riesgo, impacto_logistico, link) VALUES (?, ?, ?, ?, ?, ?)"
    val = (timestamp_actual, fuente, mensaje, nivel_riesgo, impacto, link)
    cursor.execute(sql, val)
    conn.commit()
    
    print(f"[INTEL] Nuevo Incidente Guardado -> Riesgo: {nivel_riesgo} | Impacto: {impacto}/10")
    
    conn.close()


# ==========================================
# 📡 INTEGRACIÓN NOTICIAS (RSS OSINT REAL)
# ==========================================
import feedparser
from deep_translator import GoogleTranslator

def recolector_noticias_rss():
    """
    Recopila noticias reales mediante feeds RSS de última hora.
    """
    feeds = [
        "https://www.aljazeera.com/xml/rss/all.xml",            # Al Jazeera (Global & Middle East)
        "https://defense-update.com/feed",                      # Defense Update
        "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml" # BBC Middle East
    ]
    
    # Palabras clave tácticas: Golfo, Ormuz, Mar Rojo, Yemen, Hutíes, Irán, Barcos, Drones
    keywords = ["iran", "houthi", "yemen", "red sea", "hormuz", "strait", "vessel", "drone", "missile", "ship", "tanker", "gulf", "navy", "maritime", "attack"]
    
    titulos_vistos = set()
    
    print("[+] Módulo OSINT RSS Iniciado. Escuchando noticias globales en tiempo real...")
    
    while True:
        try:
            for url in feeds:
                feed = feedparser.parse(url)
                for entry in feed.entries[:8]: # Revisar las 8 noticias más recientes por feed
                    titulo = entry.title
                    
                    if titulo in titulos_vistos:
                        continue
                        
                    titulo_lower = titulo.lower()
                    # Si menciona alguna de las palabras clave de riesgo
                    if any(kw in titulo_lower for kw in keywords):
                        # Extraer resumen si lo hay para dar más contexto
                        resumen = entry.get('summary', '')
                        # Limpiar HTML básico del resumen si existe y limitarlo a 250 ops
                        resumen = resumen.split('<')[0][:250]
                        
                        # Extraer el enlace original de la noticia
                        url_noticia = entry.get('link', '#')

                        # Traducir al español on-the-fly
                        try:
                            traductor = GoogleTranslator(source='auto', target='es')
                            titulo_es = traductor.translate(titulo)
                            resumen_es = traductor.translate(resumen) if resumen else ""
                            mensaje_alerta = f"[{titulo_es}] {resumen_es}"
                            titulo_log = titulo_es
                        except Exception as e:
                            print(f"[!] Error de traducción interceptado: {e}")
                            mensaje_alerta = f"[{titulo}] {resumen}"
                            titulo_log = titulo
                            
                        fuente = "RSS_OSINT_Feed"
                        
                        guardar_incidente(fuente, mensaje_alerta, url_noticia)
                        print(f"[OSINT RSS] Alerta traducida y guardada: {titulo_log}")
                    
                    titulos_vistos.add(titulo)
                        
            # Evitar que el set crezca infinitamente (limpiar después de 1000 noticias)
            if len(titulos_vistos) > 1000:
                titulos_vistos.clear()
                
        except Exception as e:
            print(f"[!] Error leyendo Feeds RSS: {e}")
            
        time.sleep(180) # Escanear cada 3 minutos (180 segundos) para no saturar servidores y mantener frescura


# ==========================================
# 🌐 ENDPOINTS DE LA API (FLASK)
# ==========================================
@app.route('/api/v1/alerts', methods=['GET'])
@require_auth
def get_alerts():
    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Error interno del servidor", "details": "DB unreach"}), 500
        
    cursor = conn.cursor()
    
    # Extraer los últimos 15 incidentes, ordenados desde el más reciente
    query = """
        SELECT id, timestamp_utc, fuente, mensaje_crudo, nivel_riesgo, impacto_logistico, link
        FROM incidentes 
        ORDER BY timestamp_utc DESC 
        LIMIT 15
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    
    # Convertir sqlite3.Row a diccionarios estándar
    data = [dict(row) for row in rows]
    
    conn.close()
    
    return jsonify({
        "status": "success",
        "count": len(data),
        "data": data
    }), 200


if __name__ == '__main__':
    print("====================================")
    print(" ORMUZ SENSE - BACKEND INTELLIGENCE ")
    print("====================================")
    
    # 1. Chequear tabla y db MySQL
    init_db()
    
    # 2. Iniciar Recolector de Inteligencia RSS Real
    threading.Thread(target=recolector_noticias_rss, daemon=True).start()
    
    # 3. Arrancar Flask Server
    app.run(host='0.0.0.0', port=5000, debug=False)
