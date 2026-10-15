from flask import Flask, render_template_string
from ruteo import app as app_ruteo
from escaneo import app as app_escaneo
from entrega import app as app_entrega

app = Flask(__name__)

# Registrar Blueprints
app.register_blueprint(app_ruteo, url_prefix="/ruteo")
app.register_blueprint(app_escaneo, url_prefix="/escaneo")
app.register_blueprint(app_entrega, url_prefix="/entrega")

INDEX_HTML = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Portal Unificado de Soluciones Logísticas</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --accent: #38bdf8;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --line: #334155;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
      padding: 20px;
    }
    header { text-align: center; padding: 30px 20px 10px; }
    header h1 { margin: 0; font-size: 2.2rem; color: var(--accent); }
    header p { color: var(--text-muted); margin-top: 8px; font-size: 1rem; }
    main {
      width: 100%;
      max-width: 960px;
      padding: 20px 0;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 24px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.2s, border-color 0.2s;
    }
    .card:hover { transform: translateY(-4px); border-color: var(--accent); }
    .card h2 { margin: 0 0 10px; font-size: 1.3rem; color: #fff; }
    .card p { font-size: 0.92rem; color: var(--text-muted); line-height: 1.5; margin-bottom: 24px; }
    .btn {
      display: inline-block;
      text-align: center;
      background: var(--accent);
      color: #0f172a;
      font-weight: 700;
      padding: 12px 18px;
      border-radius: 8px;
      text-decoration: none;
      transition: opacity 0.2s;
    }
    .btn:hover { opacity: 0.9; }
  </style>
</head>
<body>
  <header>
    <h1>Plataforma de Control Logístico</h1>
    <p>Seleccione el módulo que desea ejecutar</p>
  </header>
  <main>
    <div class="card">
      <div>
        <h2>1. RutaPro</h2>
        <p>Prototipo con interfaz por actor (ERP, Operador Logístico, Conductor, Cliente Final y Motor de Tráfico/Mapas).</p>
      </div>
      <a href="/ruteo/" class="btn">Abrir RutaPro</a>
    </div>

    <div class="card">
      <div>
        <h2>2. Sistema de Packing</h2>
        <p>Escaneo y validación de electrodomésticos, gestión de inconsistencias, etiquetas e integración WMS (CU-01 a CU-09).</p>
      </div>
      <a href="/escaneo/" class="btn">Abrir Escaneo / Packing</a>
    </div>

    <div class="card">
      <div>
        <h2>3. Entrega y Cliente</h2>
        <p>Ripley Rama 3: Seguimiento del pedido, cálculo y actualización de ETA, proximidad GPS y registro de entrega efectiva.</p>
      </div>
      <a href="/entrega/" class="btn">Abrir Entrega Ripley</a>
    </div>
  </main>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

# Exponer la app para la arquitectura Serverless de Vercel
app_instance = app

if __name__ == "__main__":
    app.run(debug=True, port=5000)