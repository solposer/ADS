from flask import Flask, render_template_string

# Importamos las aplicaciones Flask de cada archivo
from ruteo import app as app_ruteo
from escaneo import app as app_escaneo
from entrega import app as app_entrega

app = Flask(__name__)

# Montamos los endpoints/rutas de los módulos si están definidos dentro de los archivos
# o los ejecutamos de forma unificada vía blueprints/dispatchers.

HTML_INDEX = """<!doctype html>
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
    }
    body {
      margin: 0;
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      display: flex;
      flex-direction: column;
      align-items: center;
      min-height: 100vh;
    }
    header {
      text-align: center;
      padding: 40px 20px 20px;
    }
    header h1 {
      margin: 0;
      font-size: 2.2rem;
      color: var(--accent);
    }
    header p {
      color: var(--text-muted);
      margin-top: 8px;
    }
    main {
      width: 100%;
      max-width: 900px;
      padding: 20px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid #334155;
      border-radius: 12px;
      padding: 24px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 0.2s, border-color 0.2s;
    }
    .card:hover {
      transform: translateY(-4px);
      border-color: var(--accent);
    }
    .card h2 {
      margin: 0 0 10px;
      font-size: 1.25rem;
    }
    .card p {
      font-size: 0.9rem;
      color: var(--text-muted);
      line-height: 1.4;
      margin-bottom: 20px;
    }
    .btn {
      display: inline-block;
      text-align: center;
      background: var(--accent);
      color: #0f172a;
      font-weight: 600;
      padding: 12px 18px;
      border-radius: 8px;
      text-decoration: none;
      transition: opacity 0.2s;
    }
    .btn:hover {
      opacity: 0.9;
    }
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
        <p>Prototipo de ruteo e interfaz por actor (ERP, Operador, Conductor, Cliente, Motor de Tráfico).</p>
      </div>
      <a href="/ruteo/" class="btn">Abrir RutaPro</a>
    </div>

    <div class="card">
      <div>
        <h2>2. Sistema de Packing</h2>
        <p>Escaneo, validación de electrodomésticos, gestión de alertas e integración WMS (CU-01 a CU-09).</p>
      </div>
      <a href="/escaneo/" class="btn">Abrir Escaneo / Packing</a>
    </div>

    <div class="card">
      <div>
        <h2>3. Entrega y Cliente</h2>
        <p>Ripley Rama 3: Seguimiento, cálculo de ETA, proximidad GPS y registro de entrega (10 Casos de Uso).</p>
      </div>
      <a href="/entrega/" class="btn">Abrir Entrega Ripley</a>
    </div>
  </main>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_INDEX)

if __name__ == "__main__":
    # Importante: para unir las 3 apps en un solo servidor de Flask,
    # se usa Werkzeug DispatcherMiddleware:
    from werkzeug.middleware.dispatcher import DispatcherMiddleware
    from werkzeug.serving import run_simple

    application = DispatcherMiddleware(app, {
        '/ruteo': app_ruteo,
        '/escaneo': app_escaneo,
        '/entrega': app_entrega
    })

    run_simple('127.0.0.1', 5000, application, use_reloader=True, use_debugger=True)