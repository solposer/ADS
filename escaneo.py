"""SISTEMA DE PACKING CON ESCANEO Y VALIDACIÓN DE ELECTRODOMÉSTICOS · FLUJO COMPLETO (CU-01 a CU-09)
Adaptación nativa en Flask para integración en el Portal Logístico Central.
"""
from datetime import datetime
import html
from flask import Blueprint, render_template_string, request, session, redirect, jsonify

app = Blueprint("escaneo", __name__)

# ---------------------------------- DATOS Y ESTADO ----------------------------------
ORDEN_DEMO = {
    "nro": "OC-2026-00481",
    "canal": "Web",
    "cliente": "Juan Pérez Rojas",
    "entrega": "17/10/2026",
    "items": [
        {"sku": "LAV-LG-13K", "modelo": "Lavadora LG 13 kg", "marca": "LG", "capacidad": "13 kg", "cantidad": 2, "series": ["SN-LG-0001", "SN-LG-0002"]},
        {"sku": "REF-SAM-300", "modelo": "Refrigeradora Samsung 300 L", "marca": "Samsung", "capacidad": "300 L", "cantidad": 1, "series": ["SN-SAM-0101"]},
    ],
}
OPERARIOS = ["op01"]
ESTACIONES = ["PK-01", "PK-02", "PK-03"]
TURNOS = ["Mañana", "Tarde", "Noche"]
SUPERVISORES = {"sup01": "9999"}
MAX_REINTENTOS = 3

NOMBRES_CU = {
    "CU-01": "Recibir orden de compra en estación de packing",
    "CU-02": "Escanear y validar código de barras",
    "CU-03": "Emitir alerta de inconsistencia",
    "CU-04": "Reintentar escaneo",
    "CU-05": "Verificar pedido por imagen de la etiqueta",
    "CU-06": "Registrar validación manual",
    "CU-07": "Liberar bloqueo del sistema",
    "CU-08": "Emitir etiqueta de despacho",
    "CU-09": "Actualizar estado del pedido en el WMS",
}

STATE = {
    "usuario": None, "turno": None, "estacion": None,
    "orden": None, "estado_orden": "Sin orden", "unidades": [],
    "alerta": None, "intentos": 0, "historial_intentos": [],
    "bloqueado": False, "manual_idx": None,
    "res_imagen": None, "imagen_fallida": False,
    "etiqueta": None, "wms": "Pendiente",
    "eventos": [], "pantalla": "CU-01", "ultimo": None,
}

def log_event(evento, detalle=""):
    STATE["eventos"].append({
        "Hora": datetime.now().strftime("%H:%M:%S"),
        "Operario": STATE["usuario"] or "-",
        "Evento": evento,
        "Detalle": detalle
    })

def reset_all():
    STATE.update({
        "usuario": None, "turno": None, "estacion": None,
        "orden": None, "estado_orden": "Sin orden", "unidades": [],
        "alerta": None, "intentos": 0, "historial_intentos": [],
        "bloqueado": False, "manual_idx": None,
        "res_imagen": None, "imagen_fallida": False,
        "etiqueta": None, "wms": "Pendiente",
        "eventos": [], "pantalla": "CU-01", "ultimo": None,
    })

def reset_orden():
    STATE.update({
        "orden": None, "alerta": None, "manual_idx": None, "res_imagen": None,
        "etiqueta": None, "ultimo": None, "unidades": [], "historial_intentos": [],
        "intentos": 0, "bloqueado": False, "imagen_fallida": False,
        "estado_orden": "Sin orden", "wms": "Pendiente", "pantalla": "CU-01"
    })

def cargar_orden():
    unidades = []
    for it in ORDEN_DEMO["items"]:
        for serie in it["series"]:
            unidades.append({"sku": it["sku"], "modelo": it["modelo"], "serie": serie, "estado": "Pendiente", "metodo": "-", "hora": "-"})
    STATE["orden"] = ORDEN_DEMO
    STATE["unidades"] = unidades
    STATE["estado_orden"] = "Recibida"
    log_event("Orden recibida del WMS", ORDEN_DEMO["nro"])

def contador():
    u = STATE["unidades"]
    return sum(1 for x in u if x["estado"] != "Pendiente"), len(u)

def idx_pendiente():
    for i, u in enumerate(STATE["unidades"]):
        if u["estado"] == "Pendiente":
            return i
    return None

def completo():
    hechas, total = contador()
    return total > 0 and hechas == total and not STATE["bloqueado"]

def marcar(idx, metodo):
    u = STATE["unidades"][idx]
    u["estado"] = "Validada manual" if metodo == "Manual" else "Correcto"
    u["metodo"] = metodo
    u["hora"] = datetime.now().strftime("%H:%M:%S")
    log_event(f"Unidad validada ({metodo})", f'{u["sku"]} · {u["serie"]}')

def validar_codigo(codigo):
    c = (codigo or "").strip().upper()
    if not c: return "vacio", None
    for i, u in enumerate(STATE["unidades"]):
        if u["estado"] == "Pendiente" and c in (u["serie"].upper(), u["sku"].upper()):
            return "ok", i
    if any(c in (u["serie"].upper(), u["sku"].upper()) for u in STATE["unidades"]):
        return "duplicado", None
    return "incorrecto", None

def activar_alerta(codigo, motivo):
    i = idx_pendiente()
    esperado = STATE["unidades"][i] if i is not None else {"sku": "-", "modelo": "-"}
    STATE["alerta"] = {
        "codigo": codigo or "(sin lectura)", "motivo": motivo,
        "esperado_sku": esperado["sku"], "esperado_modelo": esperado["modelo"],
        "hora": datetime.now().strftime("%H:%M:%S")
    }
    STATE["intentos"] = 0
    STATE["historial_intentos"] = []
    STATE["res_imagen"] = None
    STATE["imagen_fallida"] = False
    log_event("ALERTA de inconsistencia", f'{STATE["alerta"]["codigo"]}')

def resolver_alerta():
    STATE["alerta"] = None
    STATE["intentos"] = 0
    STATE["historial_intentos"] = []
    STATE["res_imagen"] = None
    STATE["imagen_fallida"] = False

# ---------------------------------- RUTAS FLASK ----------------------------------
@app.route("/")
@app.route("/<cu>")
def index(cu="CU-01"):
    if cu in NOMBRES_CU:
        STATE["pantalla"] = cu
    return render_template_string(LAYOUT, state=STATE, nombres=NOMBRES_CU, cu=STATE["pantalla"], contador=contador(), completo=completo())

@app.route("/action", methods=["POST"])
def action():
    act = request.form.get("act")
    
    if act == "reset_demo":
        reset_all()
        return redirect("/escaneo/CU-01")
        
    elif act == "recibir_orden":
        if request.form.get("sim_falla"):
            log_event("Error WMS", "No se pudo descargar la orden")
            STATE["ultimo_err"] = "❌ No se pudo conectar con el WMS. Verifique la conexión."
        else:
            cargar_orden()
            STATE["ultimo_err"] = None
            
    elif act == "login":
        uid = request.form.get("uid", "").strip().lower()
        est = request.form.get("est", "").strip().upper()
        turno = request.form.get("turno")
        if uid not in OPERARIOS or est not in ESTACIONES:
            STATE["ultimo_err"] = "❌ ID o estación no válidos."
        else:
            STATE["usuario"] = uid
            STATE["estacion"] = est
            STATE["turno"] = turno
            STATE["ultimo_err"] = None
            log_event("Inicio de sesión", f"{uid} · {turno} · {est}")
            
    elif act == "iniciar_escaneo":
        STATE["estado_orden"] = "En packing"
        log_event("Orden en packing", STATE["orden"]["nro"])
        return redirect("/escaneo/CU-02")
        
    elif act == "validar_escaneo":
        codigo = request.form.get("codigo", "")
        res, idx = validar_codigo(codigo)
        if res == "ok":
            marcar(idx, "Escáner")
            u = STATE["unidades"][idx]
            STATE["ultimo"] = f'{u["sku"]} · {u["serie"]} validada correctamente'
        elif res == "vacio":
            STATE["ultimo_err"] = "Escanee o escriba un código."
        else:
            activar_alerta(codigo.strip().upper(), "no_coincide" if res == "incorrecto" else "duplicado")
            return redirect("/escaneo/CU-03")

    elif act == "falla_lectura":
        activar_alerta("", "lectura")
        return redirect("/escaneo/CU-03")

    elif act == "reintento_escaneo":
        codigo = request.form.get("codigo", "")
        res, idx = validar_codigo(codigo)
        if res == "ok":
            marcar(idx, "Reintento")
            u = STATE["unidades"][idx]
            STATE["ultimo"] = f'{u["sku"]} · {u["serie"]} validada en el reintento'
            resolver_alerta()
            return redirect("/escaneo/CU-02")
        else:
            STATE["intentos"] += 1
            STATE["historial_intentos"].append({
                "Intento": STATE["intentos"], "Hora": datetime.now().strftime("%H:%M:%S"),
                "Código": codigo.strip().upper() or "(sin lectura)", "Resultado": "❌ No coincide"
            })
            log_event("Reintento fallido", f"Intento {STATE['intentos']}/{MAX_REINTENTOS}")
            if STATE["intentos"] >= MAX_REINTENTOS:
                return redirect("/escaneo/CU-05")

    elif act == "verificar_imagen":
        modo = request.form.get("modo")
        a = STATE["alerta"]
        if modo == "ok":
            idx = next((i for i, u in enumerate(STATE["unidades"]) if u["estado"] == "Pendiente" and u["sku"] == a["esperado_sku"]), None)
            if idx is not None:
                marcar(idx, "Imagen")
                u = STATE["unidades"][idx]
                STATE["ultimo"] = f'{u["sku"]} · {u["serie"]} validada por imagen'
                resolver_alerta()
                return redirect("/escaneo/CU-02")
        else:
            STATE["res_imagen"] = {"estado": modo}
            STATE["imagen_fallida"] = True
            log_event("Verificación por imagen fallida", modo)

    elif act == "validar_manual":
        dato = request.form.get("dato", "")
        detalle = request.form.get("detalle", "").strip()
        if not detalle:
            STATE["ultimo_err"] = "❌ Complete el detalle del motivo antes de continuar."
        else:
            res, idx = validar_codigo(dato)
            if res != "ok":
                log_event("Validación manual rechazada", f"Dato: {dato.strip().upper()}")
                STATE["ultimo_err"] = "❌ El dato no coincide con la orden."
            else:
                marcar(idx, "Manual")
                STATE["manual_idx"] = idx
                STATE["bloqueado"] = True
                log_event("Validación manual registrada", detalle)
                resolver_alerta()
                return redirect("/escaneo/CU-07")

    elif act == "liberar_bloqueo":
        visual = request.form.get("visual")
        sid = request.form.get("sid", "").strip().lower()
        clave = request.form.get("clave", "")
        if not visual:
            STATE["ultimo_err"] = "❌ Debe confirmar la verificación visual."
        elif SUPERVISORES.get(sid) != clave:
            log_event("Credenciales supervisor inválidas", sid)
            STATE["ultimo_err"] = "❌ Credenciales inválidas de supervisor."
        else:
            STATE["bloqueado"] = False
            STATE["manual_idx"] = None
            log_event("Bloqueo liberado", f"Supervisor: {sid}")
            STATE["ultimo"] = "Bloqueo liberado por el supervisor. Continúe."
            return redirect("/escaneo/CU-02")

    elif act == "emitir_etiqueta":
        if request.form.get("sim_falla"):
            log_event("Falla de impresión", "No se pudo generar")
            STATE["ultimo_err"] = "❌ Falla de la impresora."
        else:
            STATE["etiqueta"] = {
                "id": f'ET-{STATE["orden"]["nro"]}', "orden": STATE["orden"]["nro"],
                "cliente": STATE["orden"]["cliente"], "operario": STATE["usuario"],
                "fecha": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "unidades": [{"sku": u["sku"], "serie": u["serie"]} for u in STATE["unidades"]]
            }
            STATE["estado_orden"] = "Etiqueta emitida"
            log_event("Etiqueta emitida", STATE["etiqueta"]["id"])

    elif act == "actualizar_wms":
        if request.form.get("sim_caida"):
            STATE["wms"] = "Pendiente de reintento"
            log_event("Error de conexión WMS", "Guardado para reintento")
        else:
            STATE["wms"] = "Actualizado"
            STATE["estado_orden"] = "Packing completado"
            log_event("Pedido actualizado WMS", STATE["orden"]["nro"])

    return redirect(f"/escaneo/{STATE['pantalla']}")

# ---------------------------------- PLANTILLA HTML ----------------------------------
LAYOUT = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Packing CD · Escaneo y Validación</title>
  <style>
    :root { --bg: #f8fafc; --panel: #ffffff; --ink: #0f172a; --line: #e2e8f0; --acc: #2563eb; --bad: #dc2626; --ok: #16a34a; --warn: #d97706; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--ink); display: flex; min-height: 100vh; }
    aside { width: 300px; background: #1e293b; color: #fff; padding: 20px; display: flex; flex-direction: column; gap: 8px; }
    aside h2 { margin: 0 0 4px; font-size: 1.2rem; color: #38bdf8; }
    aside .sub { font-size: 0.8rem; color: #94a3b8; margin-bottom: 12px; }
    aside a.nav-btn { display: block; padding: 10px 12px; border-radius: 6px; color: #cbd5e1; text-decoration: none; font-size: 0.88rem; background: #334155; margin-bottom: 4px; }
    aside a.nav-btn.active { background: var(--acc); color: #fff; font-weight: 600; }
    main { flex: 1; padding: 24px; max-width: 1000px; }
    .bar { display: flex; gap: 16px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; }
    .bar div { flex: 1; } .bar label { display: block; font-size: 0.75rem; color: #64748b; } .bar span { font-weight: 600; font-size: 0.95rem; }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; margin-bottom: 16px; }
    .panel-rojo { background: #fef2f2; border-left: 6px solid var(--bad); color: #991b1b; padding: 12px; border-radius: 6px; margin-bottom: 12px; }
    .panel-ok { background: #f0fdf4; border-left: 6px solid var(--ok); color: #166534; padding: 12px; border-radius: 6px; margin-bottom: 12px; }
    .panel-ambar { background: #fffbeb; border-left: 6px solid var(--warn); color: #92400e; padding: 12px; border-radius: 6px; margin-bottom: 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; margin-top: 8px; }
    th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--line); } th { color: #64748b; }
    button, input[type="submit"] { background: var(--acc); color: #fff; border: 0; padding: 8px 14px; border-radius: 6px; cursor: pointer; font-weight: 600; }
    button.sec { background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; }
    input[type="text"], select, textarea { width: 100%; padding: 8px; border: 1px solid var(--line); border-radius: 6px; margin-top: 4px; margin-bottom: 12px; font: inherit; }
  </style>
</head>
<body>
  <aside>
    <div style="margin-bottom: 12px;"><a href="/" style="color: #94a3b8; text-decoration: none; font-size: 12px;">← Volver al Portal Principal</a></div>
    <h2>📦 Packing CD</h2>
    <div class="sub">Sistema de escaneo y validación</div>
    {% for k, v in nombres.items() %}
      <a href="/escaneo/{{ k }}" class="nav-btn {{ 'active' if k == cu else '' }}">{{ k }} · {{ v }}</a>
    {% endfor %}
    <form action="/escaneo/action" method="post" style="margin-top: auto;">
      <input type="hidden" name="act" value="reset_demo">
      <button type="submit" class="sec" style="width: 100%;">🔄 Reiniciar demo</button>
    </form>
  </aside>

  <main>
    <h2>{{ cu }} · {{ nombres[cu] }}</h2>
    
    <div class="bar">
      <div><label>Orden</label><span>{{ state.orden.nro if state.orden else '—' }}</span></div>
      <div><label>Operario / Estación</label><span>{{ state.usuario or '—' }} · {{ state.estacion or '—' }}</span></div>
      <div><label>Validadas</label><span>{{ contador[0] }} / {{ contador[1] }}</span></div>
      <div><label>Estado Sistema</label><span>{{ '🔒 Bloqueado' if state.bloqueado else ('⚠️ Alerta' if state.alerta else '🟢 Operativo') }}</span></div>
    </div>

    {% if state.ultimo_err %}
      <div class="panel-rojo">{{ state.ultimo_err }}</div>
    {% endif %}

    {% if cu == 'CU-01' %}
      <div class="card">
        <h3>1. Descargar Orden del WMS</h3>
        {% if not state.orden %}
          <form action="/escaneo/action" method="post">
            <input type="hidden" name="act" value="recibir_orden">
            <label><input type="checkbox" name="sim_falla" value="1"> Simular falla de conexión WMS</label><br><br>
            <button type="submit">📥 Recibir Orden del WMS</button>
          </form>
        {% else %}
          <div class="panel-ok">✅ Orden {{ state.orden.nro }} descargada correctamente.</div>
        {% endif %}
      </div>

      <div class="card">
        <h3>2. Inicio de Sesión de Operario</h3>
        {% if not state.usuario %}
          <form action="/escaneo/action" method="post">
            <input type="hidden" name="act" value="login">
            <label>ID Operario (Demo: op01)</label>
            <input type="text" name="uid" placeholder="op01" required>
            <label>Turno</label>
            <select name="turno"><option>Mañana</option><option>Tarde</option><option>Noche</option></select>
            <label>Estación (Demo: PK-01)</label>
            <input type="text" name="est" placeholder="PK-01" required>
            <button type="submit">Ingresar</button>
          </form>
        {% else %}
          <div class="panel-ok">✅ Sesión activa: {{ state.usuario }} (Estación {{ state.estacion }})</div>
        {% endif %}
      </div>

      {% if state.orden and state.usuario %}
        <div class="card">
          <h3>3. Iniciar Trabajo</h3>
          <form action="/escaneo/action" method="post">
            <input type="hidden" name="act" value="iniciar_escaneo">
            <button type="submit">▶️ Iniciar Escaneo (CU-02)</button>
          </form>
        </div>
      {% endif %}

    {% elif cu == 'CU-02' %}
      {% if state.bloqueado %}
        <div class="panel-ambar">🔒 Sistema Bloqueado. Se requiere liberación por supervisor (CU-07).</div>
      {% elif state.alerta %}
        <div class="panel-rojo">⚠️ Alerta activa. Resuélvala en CU-03 antes de continuar.</div>
      {% elif completo %}
        <div class="panel-ok">✅ Todas las unidades validadas. Puede emitir la etiqueta (CU-08) o actualizar el WMS (CU-09).</div>
      {% else %}
        <div class="card">
          <h3>Escanee el producto / N.º de Serie</h3>
          <form action="/escaneo/action" method="post">
            <input type="hidden" name="act" value="validar_escaneo">
            <input type="text" name="codigo" placeholder="Ej: SN-LG-0001, LAV-LG-13K" autofocus required>
            <button type="submit">Validar Unidad</button>
          </form>
          <form action="/escaneo/action" method="post" style="margin-top: 10px;">
            <input type="hidden" name="act" value="falla_lectura">
            <button type="submit" class="sec">⚠️ El lector no logra leer el código</button>
          </form>
        </div>
      {% endif %}

      <div class="card">
        <h3>Unidades de la Orden</h3>
        <table>
          <tr><th>SKU</th><th>Modelo</th><th>Serie</th><th>Estado</th><th>Método</th></tr>
          {% for u in state.unidades %}
            <tr><td>{{ u.sku }}</td><td>{{ u.modelo }}</td><td>{{ u.serie }}</td><td>{{ u.estado }}</td><td>{{ u.metodo }}</td></tr>
          {% endfor %}
        </table>
      </div>

    {% elif cu == 'CU-03' %}
      {% if state.alerta %}
        <div class="panel-rojo">
          🚨 <strong>INCONSISTENCIA DETECTADA</strong><br>
          Código escaneado: {{ state.alerta.codigo }}<br>
          Producto esperado: {{ state.alerta.esperado_sku }} ({{ state.alerta.esperado_modelo }})
        </div>
        <div class="card">
          <h3>Opciones de Resolución</h3>
          <a href="/escaneo/CU-04"><button>🔁 Reintentar Escaneo (CU-04)</button></a>
          <a href="/escaneo/CU-05"><button class="sec">🖼️ Verificar por Imagen (CU-05)</button></a>
          <a href="/escaneo/CU-06"><button class="sec">⌨️ Validación Manual (CU-06)</button></a>
        </div>
      {% else %}
        <div class="panel-ok">No hay ninguna alerta activa actualmente.</div>
      {% endif %}

    {% elif cu == 'CU-04' %}
      <div class="card">
        <h3>Reintento de Escaneo (Intento {{ state.intentos }} / 3)</h3>
        <form action="/escaneo/action" method="post">
          <input type="hidden" name="act" value="reintento_escaneo">
          <input type="text" name="codigo" placeholder="Escanee nuevamente" required>
          <button type="submit">Reintentar</button>
        </form>
      </div>

    {% elif cu == 'CU-05' %}
      <div class="card">
        <h3>Verificación de Etiqueta por Imagen</h3>
        <form action="/escaneo/action" method="post">
          <input type="hidden" name="act" value="verificar_imagen">
          <label>Resultado simulado de cámara/OCR:</label>
          <select name="modo">
            <option value="ok">Imagen coincide con la orden</option>
            <option value="no_coincide">Imagen no coincide</option>
            <option value="ilegible">Etiqueta ilegible</option>
          </select>
          <button type="submit">Procesar Imagen</button>
        </form>
      </div>

    {% elif cu == 'CU-06' %}
      <div class="card">
        <h3>Registro de Validación Manual</h3>
        <form action="/escaneo/action" method="post">
          <input type="hidden" name="act" value="validar_manual">
          <label>SKU o Serie a ingresar</label>
          <input type="text" name="dato" placeholder="Ej: SN-LG-0001" required>
          <label>Detalle / Justificación obligatoria</label>
          <textarea name="detalle" required placeholder="Motivo del ingreso manual..."></textarea>
          <button type="submit">Registrar y Bloquear para Autorización</button>
        </form>
      </div>

    {% elif cu == 'CU-07' %}
      <div class="card">
        <h3>Liberación de Bloqueo por Supervisor</h3>
        <form action="/escaneo/action" method="post">
          <input type="hidden" name="act" value="liberar_bloqueo">
          <label><input type="checkbox" name="visual" value="1"> Confirmo verificación visual del producto</label><br><br>
          <label>ID Supervisor (Demo: sup01)</label>
          <input type="text" name="sid" placeholder="sup01" required>
          <label>Contraseña (Demo: 9999)</label>
          <input type="password" name="clave" required>
          <button type="submit">🔓 Liberar Bloqueo</button>
        </form>
      </div>

    {% elif cu == 'CU-08' %}
      <div class="card">
        <h3>Emisión de Etiqueta de Despacho</h3>
        {% if state.etiqueta %}
          <div class="panel-ok">
            <strong>Etiqueta Emitida: {{ state.etiqueta.id }}</strong><br>
            Orden: {{ state.etiqueta.orden }} | Cliente: {{ state.etiqueta.cliente }}
          </div>
        {% else %}
          <form action="/escaneo/action" method="post">
            <input type="hidden" name="act" value="emitir_etiqueta">
            <label><input type="checkbox" name="sim_falla" value="1"> Simular falla de impresora</label><br><br>
            <button type="submit">🖨️ Emitir Etiqueta</button>
          </form>
        {% endif %}
      </div>

    {% elif cu == 'CU-09' %}
      <div class="card">
        <h3>Actualización en Sistema WMS</h3>
        <p>Estado WMS: <strong>{{ state.wms }}</strong></p>
        <form action="/escaneo/action" method="post">
          <input type="hidden" name="act" value="actualizar_wms">
          <label><input type="checkbox" name="sim_caida" value="1"> Simular caída de red con el WMS</label><br><br>
          <button type="submit">📤 Enviar Actualización al WMS</button>
        </form>
      </div>
    {% endif %}

    <div class="card">
      <h3>Historial de Eventos</h3>
      <table>
        <tr><th>Hora</th><th>Operario</th><th>Evento</th><th>Detalle</th></tr>
        {% for ev in state.eventos[::-1][:6] %}
          <tr><td>{{ ev.Hora }}</td><td>{{ ev.Operario }}</td><td>{{ ev.Evento }}</td><td>{{ ev.Detalle }}</td></tr>
        {% endfor %}
      </table>
    </div>
  </main>
</body>
</html>
"""