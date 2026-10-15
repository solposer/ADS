"""RIPLEY - Rama 3: Entrega y comunicación con el cliente
Prototipo web integrado con los 10 casos de uso en Flask.
"""
import datetime
import json
import math
import random
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request

app = Blueprint("entrega", __name__)

# -----------------------------------------------------------------------------
# Parámetros de simulación
# -----------------------------------------------------------------------------
DISTANCIA_TOTAL = 18.0
VELOCIDAD_TRAFICO = [32, 22, 13]  # Fluido, Moderado, Denso
VELOCIDAD_HISTORICA = 20
TRAFICO = ["Fluido", "Moderado", "Denso"]
MIN_POR_PARADA = 6
UMBRAL_ESTABLE = 5
UMBRAL_RETRASO = 30
RADIO_PROXIMIDAD_BASE = 1.0
MODELO_ETA = "ETA-Ripley v1.4"
ESTADOS = ["Preparado", "En ruta", "En domicilio", "Entregado"]

PEDIDOS_BASE = [
    ("#RIP-48213", "Refrigeradora Samsung 380 L", "Av. Javier Prado Este 1450, San Isidro", "Ana Torres", "ana.torres@correo.com"),
    ("#RIP-48230", "Lavadora LG 13 kg", "Jr. Cusco 320, Santiago de Surco", "Luis Rojas", "luis.rojas@correo.com"),
    ("#RIP-48244", "Televisor Samsung 55\"", "Av. Benavides 2100, Miraflores", "Marta Díaz", "marta.diaz@correo.com"),
]

E = {}

def hhmm(minutos):
    m = round(minutos)
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"

def fecha_hoy():
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    d = datetime.date.today()
    return f"{dias[d.weekday()]} {d.day} de {meses[d.month - 1]}"

def aviso(msg, ok=True):
    return {"msg": msg, "ok": ok}

def pedido_actual():
    return E["pedidos"][E["sel"]]

def restante():
    return max(0.0, DISTANCIA_TOTAL * (1 - E["gps"]["p"]))

def indice_estado(estado):
    if estado == "Listo para despacho": return 0
    if estado == "En ruta": return 1
    if estado in ("En domicilio", "Entrega no concretada"): return 2
    if estado == "Entregado": return 3
    return 0

def ventana(pron):
    if not pron: return "—"
    return f"{hhmm(pron['eta'] - pron['margen'])} – {hhmm(pron['eta'] + pron['margen'])}"

def registrar(cu, mensaje, nivel="", tipo="evento", pedido_id=None, valor=None):
    hora = hhmm(E["hora"])
    E["log"].insert(0, {"hora": hora, "cu": cu, "msg": mensaje, "nivel": nivel})
    del E["log"][80:]
    E["trazabilidad"].insert(0, {
        "hora": hora, "cu": cu, "tipo": tipo,
        "pedido": pedido_id or pedido_actual()["id"],
        "detalle": mensaje, "valor": valor,
    })
    del E["trazabilidad"][250:]

def notificar(pedido, titulo, cuerpo, tipo="general", enviada=True):
    n = {
        "hora": hhmm(E["hora"]), "pedido": pedido["id"], "cliente": pedido["cliente"],
        "titulo": titulo, "cuerpo": cuerpo, "tipo": tipo, "enviada": enviada,
    }
    E["notificaciones"].insert(0, n)
    del E["notificaciones"][50:]
    return n

def pronosticar(pedido, inicial=False):
    p = E["params"]
    km = restante() if E["gps"]["paquete"] else DISTANCIA_TOTAL
    velocidad = VELOCIDAD_TRAFICO[p["trafico"]] if p["info_trafico"] else VELOCIDAD_HISTORICA
    extra_incidente = 25 if E["incidente"] > 0 else 0
    conduccion = km / max(1, velocidad) * 60
    min_paradas = max(0, p["paradas"] - E["sel"]) * MIN_POR_PARADA
    margen = 5 + 3 * p["trafico"] + p["paradas"] + (5 if not p["gps_disponible"] else 0)
    confianza = 95 - 8 * p["trafico"] - 2 * p["paradas"] - (22 if not p["gps_disponible"] else 0) - (10 if not p["info_trafico"] else 0)
    return {
        "eta": E["hora"] + conduccion + min_paradas + extra_incidente,
        "margen": margen, "conf": round(max(35, min(96, confianza))),
        "pre": not p["gps_disponible"], "sin_trafico": not p["info_trafico"],
        "km": round(km, 1), "conduccion": round(conduccion),
        "paradas_min": min_paradas, "calculado": E["hora"],
        "modelo": MODELO_ETA, "inicial": inicial,
    }

def asegurar_eta_inicial(pedido):
    if not pedido["eta_inicial"]:
        pr = pronosticar(pedido, inicial=True)
        pedido["eta_inicial"] = pr
        pedido["eta"] = dict(pr)
        pedido["eta_historial"].append({"hora": hhmm(E["hora"]), "eta": hhmm(pr["eta"]), "ventana": ventana(pr), "tipo": "Inicial"})
        registrar("CU-03", f"ETA inicial calculada para {pedido['id']}: {ventana(pr)}", pedido_id=pedido["id"], tipo="eta", valor=hhmm(pr["eta"]))
    return pedido["eta_inicial"]

def actualizar_eta(pedido, motivo="actualización"):
    asegurar_eta_inicial(pedido)
    nueva = pronosticar(pedido)
    vigente = pedido["eta"] or pedido["eta_inicial"]
    delta = nueva["eta"] - vigente["eta"]

    if E["incidente"] > 0: E["incidente"] -= 1

    if abs(delta) < UMBRAL_ESTABLE:
        E["estado_eta"] = "Pronóstico estable"
        registrar("CU-04", f"Variación {delta:+.0f} min (< {UMBRAL_ESTABLE}); se mantiene {ventana(vigente)}", pedido_id=pedido["id"], tipo="eta")
    else:
        pedido["eta"] = nueva
        if delta > UMBRAL_RETRASO:
            E["estado_eta"] = "Retraso crítico"
            nivel = "b"
        else:
            E["estado_eta"] = "Pronóstico actualizado"
            nivel = "w"
        registrar("CU-04", f"ETA actualizada ({delta:+.0f} min) por {motivo}: {ventana(nueva)}", nivel, pedido_id=pedido["id"], tipo="eta", valor=hhmm(nueva["eta"]))

    pr = pedido["eta"] or vigente
    pedido["eta_historial"].append({"hora": hhmm(E["hora"]), "eta": hhmm(pr["eta"]), "ventana": ventana(pr), "tipo": E["estado_eta"]})
    del pedido["eta_historial"][:-30]
    return pr

def snapshot_cliente(pedido):
    pr = pedido["eta"] or pedido["eta_inicial"]
    return {
        "id": pedido["id"], "producto": pedido["producto"], "estado": pedido["estado"],
        "idx": indice_estado(pedido["estado"]),
        "eta": ventana(pr) if pr and pedido["estado"] not in ("Entregado", "Entrega no concretada") else ("Pedido entregado" if pedido["estado"] == "Entregado" else "Sin entrega" if pedido["estado"] == "Entrega no concretada" else "—"),
        "eta_hora": hhmm(pr["eta"]) if pr else None, "conf": pr["conf"] if pr else None,
        "actualizado": hhmm(E["hora"]), "km": round(restante(), 1), "proximidad": pedido["proximidad"],
        "entregado": pedido["estado"] == "Entregado", "hora_real": pedido["hora_real"],
    }

def detectar_proximidad(pedido, automatico=False):
    distancia = restante()
    dentro = distancia <= E["radio_proximidad"]
    E["ultima_comparacion"] = {"distancia": round(distancia, 2), "radio": E["radio_proximidad"], "dentro": dentro, "hora": hhmm(E["hora"])}
    if dentro and not pedido["proximidad"]:
        pedido["proximidad"] = True
        pedido["hora_proximidad"] = hhmm(E["hora"])
        registrar("CU-07", f"Proximidad detectada: {distancia:.2f} km <= radio {E['radio_proximidad']:.1f} km", pedido_id=pedido["id"], tipo="proximidad", valor=round(distancia, 2))
        if E["auto_alerta"]: enviar_alerta_proximidad(pedido, automatico=True)
    elif not dentro and not automatico:
        registrar("CU-07", f"Aún fuera del radio: {distancia:.2f} km > {E['radio_proximidad']:.1f} km", "w", pedido_id=pedido["id"], tipo="proximidad", valor=round(distancia, 2))
    return dentro

def enviar_alerta_proximidad(pedido, automatico=False):
    if not pedido["proximidad"]:
        registrar("CU-08", "No se envió alerta: primero debe detectarse proximidad", "w", pedido_id=pedido["id"], tipo="alerta")
        return aviso("Primero debe detectarse que el vehículo ingresó al radio de proximidad.", False)
    if pedido["alerta_proximidad_enviada"]:
        return aviso("La alerta de proximidad ya fue registrada para este pedido.", False)

    enviada = E["push_habilitado"]
    pedido["alerta_proximidad_enviada"] = True
    pedido["hora_alerta"] = hhmm(E["hora"])
    cuerpo = "Tu pedido está cerca. El vehículo ingresó al radio de proximidad de tu domicilio."
    notificar(pedido, "Tu pedido está cerca", cuerpo, "proximidad", enviada)
    registrar("CU-08", "Alerta de proximidad " + ("enviada mediante App Ripley" if enviada else "registrada en la App; push desactivado"), "" if enviada else "w", pedido_id=pedido["id"], tipo="alerta")
    return aviso("Alerta enviada al cliente." if enviada else "Push desactivado: la alerta quedó disponible dentro de la App Ripley.")

def aplicar_estado(pedido, nuevo):
    E["hora"] += 2
    anterior = pedido["estado"]
    pedido["estado"] = nuevo
    pedido["actualizado"] = hhmm(E["hora"])
    pedido["historial"].insert(0, [hhmm(E["hora"]), nuevo])
    registrar("CU-05", f"{pedido['id']}: {anterior} -> {nuevo}", pedido_id=pedido["id"], tipo="estado", valor=nuevo)
    notificar(pedido, "Estado de tu pedido actualizado", f"Tu pedido ahora está: {nuevo}.", "estado", True)

def actualizar_estado(pedido, nuevo):
    permitidas = {
        "En ruta": ["En domicilio", "Entrega no concretada"],
        "En domicilio": ["Entrega no concretada"],
    }
    if pedido["estado"] not in permitidas:
        return aviso(f"El pedido está '{pedido['estado']}' y no admite cambios desde CU-05.", False)
    if nuevo == "Entregado":
        registrar("CU-05", "Transición a Entregado rechazada: debe registrarse en CU-09", "b", pedido_id=pedido["id"])
        return aviso("Para marcar el pedido como Entregado debe usar CU-09 · Registrar entrega efectiva.", False)
    if nuevo not in permitidas[pedido["estado"]]:
        return aviso(f"Transición no permitida: {pedido['estado']} -> {nuevo}.", False)
    if not E["conexion"]:
        pedido["pendiente"] = nuevo
        registrar("CU-05", f"Sin conexión: '{nuevo}' quedó en cola", "w", pedido_id=pedido["id"], tipo="estado")
        return aviso("Sin conexión: el cambio quedó en cola y se sincronizará al recuperar conexión.")
    aplicar_estado(pedido, nuevo)
    return aviso(f"Estado actualizado a '{nuevo}'. El cliente fue notificado.")

def registrar_entrega(pedido):
    if pedido["estado"] == "Entregado": return aviso("La entrega ya fue registrada.", False)
    if pedido["estado"] != "En domicilio":
        registrar("CU-09", f"No se puede entregar desde estado '{pedido['estado']}'", "w", pedido_id=pedido["id"], tipo="entrega")
        return aviso("Primero el pedido debe estar en estado 'En domicilio' (CU-05).", False)
    pedido["estado"] = "Entregado"
    pedido["hora_real"] = hhmm(E["hora"])
    pedido["actualizado"] = pedido["hora_real"]
    pedido["historial"].insert(0, [pedido["hora_real"], "Entregado"])
    registrar("CU-09", f"Entrega efectiva registrada a las {pedido['hora_real']}", pedido_id=pedido["id"], tipo="entrega", valor=pedido["hora_real"])
    notificar(pedido, "Pedido entregado", f"Tu pedido fue registrado como entregado a las {pedido['hora_real']}.", "entrega", True)
    E["gps"]["corriendo"] = False
    return aviso("Entrega registrada correctamente y cliente notificado.")

def reiniciar():
    E.clear()
    E.update(
        hora=540.0, activo=False, confirmando=False, sin_pedidos=False, falla_correo=False,
        sel=0, conexion=True, params={"paradas": 3, "trafico": 1, "gps_disponible": True, "info_trafico": True},
        gps={"p": 0.0, "corriendo": False, "senal": True, "invalido": False, "intervalo": 30,
             "recibidas": 0, "descartadas": 0, "antiguedad": 0, "velocidad": 0,
             "paquete": None, "estado": "En espera"},
        incidente=0, estado_eta="Sin calcular", radio_proximidad=RADIO_PROXIMIDAD_BASE,
        ultima_comparacion=None, push_habilitado=True, auto_alerta=True, auto_eta=True,
        correos=[], notificaciones=[], log=[], trazabilidad=[], cliente_snapshot=None,
        pedidos=[{
            "id": p[0], "producto": p[1], "direccion": p[2], "cliente": p[3], "correo": p[4],
            "estado": "Listo para despacho", "historial": [], "eta_inicial": None, "eta": None,
            "eta_historial": [], "pendiente": None, "actualizado": None, "hora_real": None,
            "proximidad": False, "hora_proximidad": None, "alerta_proximidad_enviada": False,
            "hora_alerta": None,
        } for p in PEDIDOS_BASE]
    )
    registrar("CU-10", "Prototipo reiniciado: estado inicial registrado", tipo="sistema")
    E["cliente_snapshot"] = snapshot_cliente(pedido_actual())

def iniciar_recorrido():
    if E["activo"]: return aviso("El recorrido ya está activo.", False)
    if E["sin_pedidos"]: return aviso("No existen pedidos asignados para iniciar el recorrido.", False)
    E["activo"] = True
    E["confirmando"] = False
    for i, p in enumerate(E["pedidos"]):
        p["estado"] = "En ruta"
        p["actualizado"] = hhmm(E["hora"])
        p["historial"].insert(0, [hhmm(E["hora"]), "En ruta"])
        asegurar_eta_inicial(p)
        enviada = not (E["falla_correo"] and i == len(E["pedidos"]) - 1)
        if enviada: E["correos"].append({"para": p["correo"], "pedido": p["id"], "asunto": "Tu pedido va en camino"})
        registrar("CU-01", f"{p['id']} inicia seguimiento y pasa a En ruta", pedido_id=p["id"], tipo="inicio")
    E["gps"]["estado"] = "Listo para recibir GPS"
    E["cliente_snapshot"] = snapshot_cliente(pedido_actual())
    enviados = len(E["correos"])
    return aviso(f"Recorrido iniciado. Seguimiento activo y {enviados}/{len(E['pedidos'])} avisos de despacho enviados.", enviados == len(E["pedidos"]))

def recibir_posicion():
    g = E["gps"]
    E["hora"] += g["intervalo"] / 60
    g["antiguedad"] += g["intervalo"]
    if not E["activo"]:
        g["estado"] = "Recorrido no iniciado"
        return aviso("Primero inicie el seguimiento en CU-01.", False)
    if not g["senal"]:
        g["estado"] = "Sin señal"
        registrar("CU-02", "Sin señal GPS: se conserva la última posición", "w", tipo="gps")
        return aviso("No se recibió posición: señal GPS no disponible.", False)
    if g["invalido"]:
        g["invalido"] = False
        g["descartadas"] += 1
        g["estado"] = "Dato descartado"
        registrar("CU-02", "Dato GPS inválido descartado", "b", tipo="gps")
        return aviso("Dato GPS inválido: se descartó y quedó registrado.", False)

    vel = 24 + round(math.sin(E["hora"] / 4) * 5 + random.random() * 3)
    g["velocidad"] = vel
    g["p"] = min(1.0, g["p"] + vel * g["intervalo"] / 3600 / DISTANCIA_TOTAL)
    g["recibidas"] += 1
    g["antiguedad"] = 0
    g["estado"] = "Señal activa" if g["p"] < 1 else "En destino"
    g["paquete"] = {
        "vehiculo": "V-214", "lat": round(-12.213 + 0.116 * g["p"], 5),
        "lng": round(-76.94 - 0.09 * g["p"], 5), "vel_kmh": vel, "hora": hhmm(E["hora"]),
    }
    registrar("CU-02", f"Posición recibida · {vel} km/h · faltan {restante():.1f} km", tipo="gps", valor=round(restante(), 1))

    p = pedido_actual()
    if p["eta_inicial"] is None: asegurar_eta_inicial(p)
    if E.get("auto_eta", True): actualizar_eta(p, "nueva posición GPS")
    detectar_proximidad(p, automatico=True)
    if g["p"] >= 1:
        g["corriendo"] = False
        registrar("CU-02", "Vehículo llegó al destino; GPS automático detenido", tipo="gps")
    return aviso("Ubicación GPS recibida y registrada.")

def pron_json(pr):
    if not pr: return None
    return {
        "ventana": ventana(pr), "eta": hhmm(pr["eta"]), "conf": pr["conf"], "pre": pr["pre"],
        "sin_trafico": pr["sin_trafico"], "km": pr["km"], "conduccion": pr["conduccion"],
        "paradas_min": pr["paradas_min"], "margen": pr["margen"], "calculado": hhmm(pr["calculado"]),
        "modelo": pr["modelo"],
    }

def vista(msg=None):
    s = pedido_actual()
    return {
        "aviso": msg, "fecha": fecha_hoy(), "hora": hhmm(E["hora"]), "activo": E["activo"],
        "confirmando": E["confirmando"], "sin_pedidos": E["sin_pedidos"], "falla_correo": E["falla_correo"],
        "conexion": E["conexion"], "sel": E["sel"], "trafico_nombres": TRAFICO, "params": E["params"],
        "gps": dict(E["gps"], p=round(E["gps"]["p"], 4), km=round(restante(), 1)),
        "incidente": E["incidente"] > 0, "estado_eta": E["estado_eta"], "radio": E["radio_proximidad"],
        "comparacion": E["ultima_comparacion"], "push": E["push_habilitado"], "auto_alerta": E["auto_alerta"],
        "auto_eta": E["auto_eta"],
        "pedidos": [{
            "id": p["id"], "producto": p["producto"], "direccion": p["direccion"], "cliente": p["cliente"],
            "correo": p["correo"], "estado": p["estado"], "idx": indice_estado(p["estado"]),
            "historial": p["historial"], "pendiente": p["pendiente"], "actualizado": p["actualizado"],
            "eta_inicial": pron_json(p["eta_inicial"]), "eta": pron_json(p["eta"]),
            "eta_historial": p["eta_historial"], "proximidad": p["proximidad"],
            "hora_proximidad": p["hora_proximidad"], "alerta": p["alerta_proximidad_enviada"],
            "hora_alerta": p["hora_alerta"], "hora_real": p["hora_real"],
        } for p in E["pedidos"]],
        "cliente": E["cliente_snapshot"], "correos": E["correos"], "notificaciones": E["notificaciones"],
        "log": E["log"], "trazabilidad": E["trazabilidad"],
        "maps_url": "https://www.google.com/maps/dir/?api=1&origin=" + quote("Centro de Distribución Villa El Salvador, Lima") + "&destination=" + quote(s["direccion"] + ", Lima"),
    }

PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Ripley · Rama 3 · 10 Casos de Uso</title>
<style>
*{box-sizing:border-box} :root{--bg:#f3effa;--p:#fff;--ink:#24143a;--mt:#75688a;--ln:#e4dcf2;--ac:#5b2a8c;--ac2:#f0e7fb;--ok:#14865a;--wn:#b4690e;--bd:#c2306a;--r:18px;--ff:'Segoe UI',system-ui,sans-serif}
@media(prefers-color-scheme:dark){:root{--bg:#170f24;--p:#231838;--ink:#f1eaff;--mt:#b0a3c8;--ln:#3a2c58;--ac:#b98af0;--ac2:#33224f;--ok:#4cc38a;--wn:#e5b04a;--bd:#ff7aa8}}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 var(--ff)} [hidden]{display:none!important}
.bar{position:sticky;top:0;z-index:10;background:var(--p);border-bottom:1px solid var(--ln);padding:12px 18px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}.brand{font-weight:800;color:var(--ac);white-space:nowrap}.tabs{display:flex;gap:6px;overflow-x:auto;flex:1;padding-bottom:2px}.tab{border:1px solid var(--ln);background:var(--bg);color:var(--ink);padding:7px 11px;border-radius:99px;cursor:pointer;white-space:nowrap;font:inherit}.tab.on{background:var(--ac);color:white;border-color:var(--ac)}
.strip{display:flex;gap:18px;flex-wrap:wrap;padding:8px 18px;border-bottom:1px solid var(--ln);background:var(--p);color:var(--mt)}.strip b{color:var(--ink)}
.pg{max-width:1200px;margin:auto;padding:18px;display:grid;gap:14px}.two{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:14px}.col{display:grid;gap:14px;align-content:start}.cell{background:var(--p);border-radius:var(--r);padding:18px;box-shadow:0 1px 0 var(--ln),0 14px 30px -22px rgba(50,20,90,.5)}.cell h2,.cell h3{margin:0 0 10px}.hero{background:var(--ac);color:#fff}.hero h1{margin:8px 0;font-size:30px}.mt{color:var(--mt)}.hero .mt{color:#eadfff}.pill,.badge{display:inline-block;padding:3px 9px;border-radius:99px;font-size:12px;background:var(--ac2);color:var(--ink)}.hero .pill{background:#ffffff25;color:#fff}.badge.ok{background:var(--ok);color:#fff}.badge.wn{background:var(--wn);color:#fff}.badge.bd{background:var(--bd);color:#fff}
.btn{font:inherit;font-weight:650;border:1px solid var(--ac);background:var(--ac);color:#fff;padding:9px 13px;border-radius:12px;cursor:pointer}.btn.g{background:transparent;color:var(--ac)}.btn.bad{background:var(--bd);border-color:var(--bd)}.btn:disabled{opacity:.45;cursor:not-allowed}.row{display:flex;gap:8px;flex-wrap:wrap}.fld{display:grid;gap:5px;margin-bottom:10px}.fld label{font-size:12px;color:var(--mt)}select,input[type=number]{font:inherit;padding:8px 10px;border:1px solid var(--ln);border-radius:10px;background:var(--p);color:var(--ink)}input[type=range]{width:100%;accent-color:var(--ac)}.chk{display:flex;gap:8px;align-items:center;margin:8px 0}
.kg{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}.k{background:var(--bg);border-radius:14px;padding:12px}.k small{display:block;color:var(--mt)}.k b{font-size:18px}.nt{padding:10px 12px;border-left:4px solid var(--ac);background:var(--bg);border-radius:10px;margin:8px 0}.nt.ok{border-color:var(--ok)}.nt.wn{border-color:var(--wn)}.nt.bad{border-color:var(--bd)}
.pipe{list-style:none;padding:0;margin:0;display:grid;gap:7px}.pipe li{padding:9px 12px;background:var(--bg);border-radius:12px;color:var(--mt)}.pipe li.on{background:var(--ac);color:#fff}.app{border:1px solid var(--ln);background:var(--bg);border-radius:24px;padding:16px;max-width:370px;margin:auto;display:grid;gap:10px}.oc{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:10px 12px;border:1px solid var(--ln);border-radius:12px;background:var(--p)}.oc.on{border-color:var(--ac);background:var(--ac2)}button.oc{font:inherit;color:inherit;text-align:left;width:100%;cursor:pointer}.eta{background:var(--ac);color:#fff;border-radius:14px;padding:12px}.eta small{display:block;opacity:.85}.eta b{font-size:24px}.stp{display:flex;gap:5px;flex-wrap:wrap}.stp span{padding:5px 9px;border-radius:99px;background:var(--p);color:var(--mt);font-size:11px}.stp span.done{background:var(--ac2);color:var(--ink)}.stp span.on{background:var(--ac);color:#fff}
.map{height:260px;border:1px solid var(--ln);border-radius:16px;background:linear-gradient(#ffffffbb,#ffffffbb),repeating-linear-gradient(0deg,#ddd 0 1px,transparent 1px 42px),repeating-linear-gradient(90deg,#ddd 0 1px,transparent 1px 56px);position:relative;overflow:hidden}.road{position:absolute;left:35px;top:195px;width:260px;height:8px;background:var(--ln);transform:rotate(-27deg);border-radius:99px}.done-road{position:absolute;left:35px;top:195px;height:8px;background:var(--ac);transform:rotate(-27deg);transform-origin:left center;border-radius:99px}.truck{position:absolute;font-size:27px;transition:.5s}.home{position:absolute;right:28px;top:38px;font-size:30px}.radar{position:absolute;right:-20px;top:-10px;width:175px;height:175px;border-radius:50%;border:2px dashed var(--ac);background:#8e62bf12;opacity:.25}.radar.in{border-color:var(--ok);opacity:.8}
.flowgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}.cu-card{padding:14px;background:var(--p);border:1px solid var(--ln);border-radius:15px}.cu-card b{display:block;margin-bottom:4px}.cu-card small{color:var(--mt)}.log{list-style:none;padding:0;margin:0;max-height:280px;overflow:auto}.log li{display:grid;grid-template-columns:50px 50px 1fr;gap:8px;padding:6px 0;border-bottom:1px solid var(--ln);font-size:12px}.log li.w{color:var(--wn)}.log li.b{color:var(--bd)}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:7px;border-bottom:1px solid var(--ln);text-align:left;vertical-align:top}th{color:var(--mt)}.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 16px;border-radius:12px;z-index:30;max-width:90vw}.toast.bad{background:var(--bd);color:#fff}
@media(max-width:850px){.two{grid-template-columns:1fr}.hero h1{font-size:24px}.log li{grid-template-columns:45px 45px 1fr}}
</style>
</head>
<body>
<div class="bar"><div style="margin-right: 12px;"><a href="/" style="color: var(--mt); text-decoration: none; font-size: 13px;">← Volver al Portal</a></div><div class="brand">Ripley · Rama 3</div><nav id="tabs" class="tabs"></nav></div>
<div class="strip"><span>Pedido: <b id="gPed">—</b></span><span>Estado: <b id="gSt">—</b></span><span>Hora: <b id="gHora">—</b></span><span>Restan: <b id="gKm">—</b></span><span>ETA: <b id="gEta">—</b></span></div>
<div class="pg">

<section id="v0" class="col">
  <div class="cell hero"><span class="pill">Prototipo integrado · 10 casos de uso</span><h1>Entrega y comunicación inteligente con el cliente</h1><p>Un solo recorrido conecta inicio, GPS, ETA, estado, consulta del cliente, proximidad, alerta, entrega final y trazabilidad.</p><button class="btn" style="background:#fff;color:var(--ac);border-color:#fff" onclick="ir(1)">Comenzar por CU-01 →</button></div>
  <div id="resumenCU" class="flowgrid"></div>
  <div class="cell"><h3>Secuencia recomendada para la demostración</h3><p class="mt">CU-01 → CU-02 → CU-03 → CU-04 → CU-05/CU-06 → CU-07 → CU-08 → CU-09 → CU-10. Todos comparten el mismo estado y cualquier cambio se refleja en las demás pantallas.</p></div>
</section>

<section id="v1" hidden class="col"><div class="two"><div class="cell"><h2>CU-01 · Iniciar seguimiento del pedido</h2><p class="mt">Actor: Transportista / Sistema de Gestión · RF1</p><div id="cu01app" class="app"></div></div><div class="col"><div class="cell"><h3>Proceso</h3><ol class="pipe"><li class="on">Transportista inicia el recorrido</li><li>Sistema identifica pedidos asignados</li><li>Registra fecha y hora de inicio</li><li>Activa seguimiento y calcula ETA inicial</li></ol></div><div class="cell"><h3>Flujos alternos</h3><div class="row"><button class="btn g" id="b01sin">Sin pedidos asignados</button><label class="chk"><input id="c01mail" type="checkbox">Simular falla de un aviso</label></div></div></div></div></section>

<section id="v2" hidden class="col"><div class="two"><div class="cell"><h2>CU-02 · Recibir ubicación GPS</h2><p class="mt">Actor: Servicio de Geolocalización / GPS · RF2</p><div id="map02"></div><div class="row"><button class="btn" id="b02run">Iniciar envíos GPS</button><button class="btn g" id="b02step">Recibir una posición</button><button class="btn g" id="b02sig">Perder señal</button><button class="btn g" id="b02bad">Dato inválido</button></div></div><div class="col"><div class="kg"><div class="k"><small>Enlace</small><b id="k02a">—</b></div><div class="k"><small>Recibidas</small><b id="k02b">—</b></div><div class="k"><small>Descartadas</small><b id="k02c">—</b></div><div class="k"><small>Velocidad</small><b id="k02d">—</b></div></div><div class="cell"><label class="fld"><span>Intervalo simulado</span><select id="s02int"><option value="10">10 s</option><option value="30">30 s</option><option value="60">60 s</option></select></label><pre id="gpsRaw" style="white-space:pre-wrap"></pre></div></div></div></section>

<section id="v3" hidden class="col"><div class="two"><div class="cell"><h2>CU-03 · Calcular ETA</h2><p class="mt">Actor: Sistema de Gestión de Pedidos / Logística · RF3</p><div class="fld"><label>Pedido</label><select id="s03ped"></select></div><div class="fld"><label>Paradas pendientes</label><input id="n03par" type="number" min="0" max="5"></div><label class="chk"><input id="c03gps" type="checkbox">GPS disponible</label><label class="chk"><input id="c03traf" type="checkbox">Información de tráfico disponible</label><button class="btn" id="b03calc">Calcular ETA inicial</button></div><div class="col"><div class="kg"><div class="k"><small>ETA</small><b id="k03a">—</b></div><div class="k"><small>Ventana</small><b id="k03b">—</b></div><div class="k"><small>Confianza</small><b id="k03c">—</b></div></div><div class="cell"><h3>Detalle del cálculo</h3><p id="d03" class="mt">—</p></div></div></div></section>

<section id="v4" hidden class="col"><div class="two"><div class="cell"><h2>CU-04 · Actualizar ETA</h2><p class="mt">Actor: Sistema de Gestión de Pedidos / Logística · RF4</p><div class="fld"><label>Tráfico</label><select id="s04traf"><option value="0">Fluido</option><option value="1">Moderado</option><option value="2">Denso</option></select></div><div class="row"><button class="btn" id="b04upd">Actualizar ETA</button><button class="btn g" id="b04inc">Simular incidente +25 min</button></div><label class="chk"><input id="c04auto" type="checkbox">Actualizar ETA automáticamente al recibir GPS</label></div><div class="col"><div class="kg"><div class="k"><small>Estado</small><b id="k04a">—</b></div><div class="k"><small>Inicial</small><b id="k04b">—</b></div><div class="k"><small>Vigente</small><b id="k04c">—</b></div></div><div class="cell"><h3>Historial de ETA</h3><div id="etaHist"></div></div></div></div></section>

<section id="v5" hidden class="col"><div class="two"><div class="cell"><h2>CU-05 · Actualizar estado del pedido</h2><p class="mt">Actor: Transportista · RF5, RF10</p><div id="cu05app" class="app"></div></div><div class="col"><div class="cell"><h3>Conectividad</h3><p id="p05conn" class="mt"></p><button class="btn g" id="b05conn">Perder conexión</button></div><div class="cell"><h3>Regla importante</h3><p class="mt">CU-05 puede pasar a “En domicilio” o “Entrega no concretada”. El estado “Entregado” se reserva exclusivamente en CU-09.</p></div></div></div></section>

<section id="v6" hidden class="col"><div class="two"><div class="cell"><h2>CU-06 · Consultar estado y ETA</h2><p class="mt">Actor: Cliente · RF6</p><div id="cu06app" class="app"></div></div><div class="col"><div class="cell"><h3>Datos del sistema</h3><div class="kg"><div class="k"><small>GPS</small><b id="k06gps">—</b></div><div class="k"><small>Tráfico</small><b id="k06tr">—</b></div><div class="k"><small>Proximidad</small><b id="k06prox">—</b></div><div class="k"><small>Notificaciones</small><b id="k06not">—</b></div></div></div><div class="cell"><button class="btn" id="b06ref">Actualizar App Ripley</button></div></div></div></section>

<section id="v7" hidden class="col"><div class="two"><div class="cell"><h2>CU-07 · Detectar proximidad</h2><p class="mt">Actor: Sistema de Gestión de Pedidos / Logística · RF8</p><div id="map07"></div><div class="fld"><label>Radio de proximidad (km)</label><input id="r07" type="range" min="0.5" max="3" step="0.5"></div><div class="row"><button class="btn" id="b07det">Comparar distancia con radio</button><button class="btn g" id="b07near">Simular vehículo a 0.8 km</button></div></div><div class="col"><div class="kg"><div class="k"><small>Distancia</small><b id="k07a">—</b></div><div class="k"><small>Radio</small><b id="k07b">—</b></div><div class="k"><small>Resultado</small><b id="k07c">—</b></div></div><div class="cell"><h3>Última comparación</h3><p id="d07" class="mt">Aún no se ejecutó.</p></div></div></div></section>

<section id="v8" hidden class="col"><div class="two"><div class="cell"><h2>CU-08 · Enviar alerta de proximidad</h2><p class="mt">Actor: Cliente · RF9</p><div id="cu08app" class="app"></div></div><div class="col"><div class="cell"><label class="chk"><input id="c08push" type="checkbox">Notificaciones push habilitadas</label><label class="chk"><input id="c08auto" type="checkbox">Enviar alerta automáticamente al detectar proximidad</label><button class="btn" id="b08send">Enviar alerta ahora</button></div><div class="cell"><h3>Notificaciones generadas</h3><div id="notifs"></div></div></div></div></section>

<section id="v9" hidden class="col"><div class="two"><div class="cell"><h2>CU-09 · Registrar entrega efectiva</h2><p class="mt">Actor: Transportista · RF11</p><div id="cu09app" class="app"></div></div><div class="col"><div class="cell"><h3>Condición de cierre</h3><p class="mt">El pedido debe estar en “En domicilio”. La confirmación registra la hora real y cambia el estado final a “Entregado”.</p><div class="row"><button class="btn g" id="b09arr">Simular llegada física</button><button class="btn" id="b09del">Registrar entrega</button></div></div></div></div></section>

<section id="v10" hidden class="col"><div class="two"><div class="cell"><h2>CU-10 · Registrar tiempos e historial</h2><p class="mt">Actor: Sistema de Gestión de Pedidos / Logística · RF13, RNF7</p><div class="kg"><div class="k"><small>ETA inicial</small><b id="k10a">—</b></div><div class="k"><small>ETA vigente</small><b id="k10b">—</b></div><div class="k"><small>Hora real</small><b id="k10c">—</b></div><div class="k"><small>Eventos</small><b id="k10d">—</b></div></div><div class="row" style="margin-top:10px"><button class="btn" id="b10snap">Registrar snapshot</button><a class="btn g" href="/entrega/api/cu10/exportar" target="_blank">Exportar JSON</a></div></div><div class="cell"><h3>Trazabilidad consolidada</h3><div id="trace"></div></div></div></section>

<section class="cell"><div class="row" style="justify-content:space-between"><h3>Registro general de eventos</h3><button class="btn g" id="bReset">Reiniciar todo</button></div><ul id="log" class="log"></ul></section>
</div>
<script>
function $(id){ return document.getElementById(id); }
function T(id,v){ const e=$(id); if(e) e.textContent=v; }
let E=null, tt=null;

const CUS=[
['CU-01','Iniciar seguimiento del pedido','Transportista / Sistema de Gestión'],
['CU-02','Recibir ubicación GPS','Servicio GPS'],
['CU-03','Calcular ETA','Sistema de Gestión'],
['CU-04','Actualizar ETA','Sistema de Gestión'],
['CU-05','Actualizar estado del pedido','Transportista'],
['CU-06','Consultar estado y ETA','Cliente'],
['CU-07','Detectar proximidad','Sistema de Gestión'],
['CU-08','Enviar alerta de proximidad','Cliente'],
['CU-09','Registrar entrega efectiva','Transportista'],
['CU-10','Registrar tiempos e historial','Sistema de Gestión']
];

function ir(i){
  for(let k=0; k<=10; k++){
    const el = $('v'+k);
    if(el) el.hidden = (k !== i);
  }
  const tabs = document.querySelectorAll('#tabs .tab');
  tabs.forEach((b, k) => b.classList.toggle('on', k === i));
  window.scrollTo(0, 0);
}

function toast(a){
  document.querySelectorAll('.toast').forEach(x=>x.remove());
  const d=document.createElement('div');
  d.className='toast'+(a.ok?'':' bad');
  d.textContent=a.msg;
  document.body.appendChild(d);
  clearTimeout(tt);
  tt=setTimeout(()=>d.remove(),3500);
}

async function api(path, data={}){
  const url = path.startsWith('/entrega') ? path : '/entrega' + path;
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    const e = await r.json();
    if(e.aviso) toast(e.aviso);
    draw(e);
    return e;
  } catch(err) {
    console.error('API Error:', err);
  }
}

async function tick(){
  try {
    const r = await fetch('/entrega/api/tick', {method:'POST'});
    const data = await r.json();
    draw(data);
  } catch(e){}
  setTimeout(tick, 900);
}

function stateSteps(idx){
  return '<div class="stp">' + ['Preparado','En ruta','En domicilio','Entregado'].map((x,k)=>`<span class="${k<idx?'done':k===idx?'on':''}">${x}</span>`).join('') + '</div>';
}

function mapHtml(e){
  const p=e.gps.p, x=38+230*p, y=205-135*p, w=260*p;
  return `<div class="map"><div class="radar ${e.pedidos[e.sel].proximidad?'in':''}"></div><div class="road"></div><div class="done-road" style="width:${w}px"></div><div class="truck" style="left:${x}px;top:${y}px">🚚</div><div class="home">⌂</div></div>`;
}

function pedido(){ return E.pedidos[E.sel]; }
function etaText(p){ return p.eta ? p.eta.ventana : (p.eta_inicial ? p.eta_inicial.ventana : '—'); }

function draw(e){
  E=e; const p=pedido();
  T('gPed',p.id); T('gSt',p.estado); T('gHora',e.hora); T('gKm',e.gps.km+' km'); T('gEta',etaText(p));
  $('log').innerHTML=e.log.map(x=>`<li class="${x.nivel}"><time>${x.hora}</time><b>${x.cu}</b><span>${x.msg}</span></li>`).join('');
  renderResumen(); render01(); render02(); render03(); render04(); render05(); render06(); render07(); render08(); render09(); render10();
}

function renderResumen(){ $('resumenCU').innerHTML=CUS.map((c,i)=>`<div class="cu-card"><span class="badge">${c[0]}</span><b>${c[1]}</b><small>${c[2]}</small><br><button class="btn g" style="margin-top:8px" onclick="ir(${i+1})">Abrir</button></div>`).join(''); }

function render01(){
  const p=pedido();
  let h=`<b>Ruta de hoy · Camión V-214</b><small class="mt">${E.fecha}</small>`;
  if(!E.activo){
    h+=E.sin_pedidos?'<div class="nt bad">Sin pedidos asignados.</div>':E.pedidos.map(x=>`<div class="oc"><span><b>${x.id}</b><small>${x.producto}</small></span><span class="badge">${x.estado}</span></div>`).join('');
    h+=E.confirmando?'<div class="nt ok">¿Confirmar inicio del seguimiento?</div><div class="row"><button class="btn g" onclick="api(\'/api/cu01/cancelar\')">Cancelar</button><button class="btn" onclick="api(\'/api/cu01/confirmar\')">Confirmar</button></div>':`<button class="btn" ${E.sin_pedidos?'disabled':''} onclick="api('/api/cu01/preparar')">Iniciar recorrido</button>`;
  } else {
    h+=`<div class="nt ok"><b>Seguimiento activo</b><br>${E.pedidos.length} pedidos en ruta.</div>${stateSteps(p.idx)}<a class="btn g" href="${E.maps_url}" target="_blank">Abrir ruta en Maps</a>`;
  }
  $('cu01app').innerHTML=h;
  T('b01sin',E.sin_pedidos?'Volver a asignar pedidos':'Sin pedidos asignados');
  $('b01sin').disabled=E.activo;
  $('c01mail').checked=E.falla_correo;
}

function render02(){ $('map02').innerHTML=mapHtml(E);T('b02run',E.gps.corriendo?'Pausar envíos GPS':'Iniciar envíos GPS');T('b02sig',E.gps.senal?'Perder señal':'Restablecer señal');T('k02a',E.gps.estado);T('k02b',E.gps.recibidas);T('k02c',E.gps.descartadas);T('k02d',E.gps.velocidad?E.gps.velocidad+' km/h':'—');$('s02int').value=E.gps.intervalo;$('gpsRaw').textContent=E.gps.paquete?JSON.stringify(E.gps.paquete,null,2):'Aún no se recibió un paquete GPS.';}
function render03(){const p=pedido();$('s03ped').innerHTML=E.pedidos.map((x,i)=>`<option value="${i}">${x.id} · ${x.producto}</option>`).join('');$('s03ped').value=E.sel;$('n03par').value=E.params.paradas;$('c03gps').checked=E.params.gps_disponible;$('c03traf').checked=E.params.info_trafico;const pr=p.eta_inicial;T('k03a',pr?pr.eta:'—');T('k03b',pr?pr.ventana:'—');T('k03c',pr?pr.conf+' %':'—');T('d03',pr?`${pr.conduccion} min conducción + ${pr.paradas_min} min paradas · margen ±${pr.margen} min · ${pr.modelo}`:'Aún no hay ETA inicial.');}
function render04(){const p=pedido();$('s04traf').value=E.params.trafico;$('c04auto').checked=E.auto_eta!==false;T('k04a',E.estado_eta);T('k04b',p.eta_inicial?p.eta_inicial.ventana:'—');T('k04c',p.eta?p.eta.ventana:'—');$('etaHist').innerHTML=p.eta_historial.length?`<table><tr><th>Hora</th><th>ETA</th><th>Tipo</th></tr>${p.eta_historial.slice().reverse().map(x=>`<tr><td>${x.hora}</td><td>${x.ventana}</td><td>${x.tipo}</td></tr>`).join('')}</table>`:'<p class="mt">Sin actualizaciones.</p>';}
function render05(){const p=pedido(),ops=p.estado==='En ruta'?['En domicilio','Entrega no concretada']:p.estado==='En domicilio'?['Entrega no concretada']:[];let h=`<b>${p.id} · ${p.producto}</b>${stateSteps(p.idx)}<div class="oc"><span>Estado actual</span><span class="badge">${p.estado}</span></div>`; if(!E.activo)h+='<div class="nt bad">Primero inicie CU-01.</div>';else if(ops.length)h+=`<div class="fld"><label>Nuevo estado</label><select id="s05new">${ops.map(x=>`<option>${x}</option>`).join('')}<option>Entregado</option></select></div><button class="btn" onclick="api('/api/cu05/estado',{nuevo:$('s05new').value})">Guardar estado</button>`;else h+='<div class="nt">No hay transiciones disponibles desde CU-05.</div>';if(p.pendiente)h+=`<div class="nt wn">Pendiente de sincronizar: ${p.pendiente}</div>`;$('cu05app').innerHTML=h;T('p05conn',E.conexion?'Conexión activa. Los cambios se registran inmediatamente.':'Sin conexión. Los cambios se guardan en cola.');T('b05conn',E.conexion?'Perder conexión':'Restablecer conexión');}
function render06(){const p=pedido(),c=E.cliente;$('cu06app').innerHTML=`<b>App Ripley · Mis pedidos</b><div class="row">${E.pedidos.map((x,i)=>`<button class="tab ${i===E.sel?'on':''}" onclick="api('/api/cu06/seleccionar',{valor:${i}})">${x.id}</button>`).join('')}</div><div class="oc"><span><b>${p.producto}</b><small>${p.direccion}</small></span><span class="badge">${c.estado}</span></div>${stateSteps(c.idx)}<div class="eta"><small>Llegada estimada</small><b>${c.eta}</b><small>Actualizado ${c.actualizado}</small></div>${c.proximidad?'<div class="nt ok">Tu pedido está cerca.</div>':''}${c.entregado?`<div class="nt ok">Entrega registrada a las ${c.hora_real}.</div>`:''}`;T('k06gps',E.gps.senal?'Disponible':'Sin señal');T('k06tr',E.trafico_nombres[E.params.trafico]);T('k06prox',p.proximidad?'Dentro del radio':'No detectada');T('k06not',E.notificaciones.length);}
function render07(){const p=pedido();$('map07').innerHTML=mapHtml(E);$('r07').value=E.radio;T('k07a',E.gps.km+' km');T('k07b',E.radio+' km');T('k07c',p.proximidad?'Dentro del radio':'Fuera del radio');T('d07',E.comparacion?`${E.comparacion.distancia} km ${E.comparacion.dentro?'<=':'>'} ${E.comparacion.radio} km · ${E.comparacion.dentro?'proximidad detectada':'continúa monitoreo'} · ${E.comparacion.hora}`:'Aún no se ejecutó la comparación.');}
function render08(){const p=pedido();$('c08push').checked=E.push;$('c08auto').checked=E.auto_alerta;$('b08send').disabled=!p.proximidad\vert{}\vert{}p.alerta;$('cu08app').innerHTML=`<b>App Ripley</b><div class="oc"><span><b>${p.id}</b><small>${p.producto}</small></span><span class="badge ${p.proximidad?'ok':''}">${p.proximidad?'Cerca':'En ruta'}</span></div>${p.alerta?'<div class="nt ok"><b>🔔 Tu pedido está cerca</b><br>El vehículo ingresó al radio de proximidad.</div>':'<div class="nt">Aún no se generó una alerta de proximidad.</div>'}`;$('notifs').innerHTML=E.notificaciones.length?E.notificaciones.slice(0,6).map(n=>`<div class="oc"><span><b>${n.titulo}</b><small>${n.hora} · ${n.pedido}<br>${n.cuerpo}</small></span><span class="badge ${n.enviada?'ok':'wn'}">${n.enviada?'Enviada':'En App'}</span></div>`).join(''):'<p class="mt">Sin notificaciones.</p>';}
function render09(){const p=pedido();$('cu09app').innerHTML=`<b>${p.id} · ${p.producto}</b>${stateSteps(p.idx)}<div class="oc"><span>Estado</span><span class="badge ${p.estado==='Entregado'?'ok':''}">${p.estado}</span></div>${p.hora_real?`<div class="nt ok">Hora real de entrega: <b>${p.hora_real}</b></div>`:'<div class="nt">Aún no se registró la entrega efectiva.</div>'}`;$('b09del').disabled=p.estado!=='En domicilio'||p.estado==='Entregado';}
function render10(){const p=pedido();T('k10a',p.eta_inicial?p.eta_inicial.eta:'—');T('k10b',p.eta?p.eta.eta:'—');T('k10c',p.hora_real||'—');T('k10d',E.trazabilidad.length);$('trace').innerHTML=`<table><tr><th>Hora</th><th>CU</th><th>Tipo</th><th>Pedido</th><th>Detalle</th></tr>${E.trazabilidad.slice(0,30).map(x=>`<tr><td>${x.hora}</td><td>${x.cu}</td><td>${x.tipo}</td><td>${x.pedido}</td><td>${x.detalle}</td></tr>`).join('')}</table>`;}

document.addEventListener("DOMContentLoaded", function() {
  $('b01sin').onclick=()=>api('/api/cu01/sin_pedidos');$('c01mail').onchange=e=>api('/api/cu01/falla_correo',{valor:e.target.checked});
  $('b02run').onclick=()=>api('/api/cu02/toggle');$('b02step').onclick=()=>api('/api/cu02/paso');
  $('b02sig').onclick=()=>api('/api/cu02/senal');$('b02bad').onclick=()=>api('/api/cu02/invalido');
  $('s02int').onchange=e=>api('/api/cu02/intervalo',{valor:+e.target.value});$('s03ped').onchange=e=>api('/api/cu06/seleccionar',{valor:+e.target.value});
  $('n03par').onchange=e=>api('/api/params',{paradas:+e.target.value});$('c03gps').onchange=e=>api('/api/params',{gps:e.target.checked});
  $('c03traf').onchange=e=>api('/api/params',{info:e.target.checked});$('b03calc').onclick=()=>api('/api/cu03/calcular');
  $('s04traf').onchange=e=>api('/api/cu04/trafico',{valor:+e.target.value});$('b04upd').onclick=()=>api('/api/cu04/actualizar');
  $('b04inc').onclick=()=>api('/api/cu04/incidente');$('c04auto').onchange=e=>api('/api/cu04/auto',{valor:e.target.checked});
  $('b05conn').onclick=()=>api('/api/conexion');$('b06ref').onclick=()=>api('/api/cu06/actualizar');
  $('r07').onchange=e=>api('/api/cu07/radio',{valor:+e.target.value});$('b07det').onclick=()=>api('/api/cu07/detectar');
  $('b07near').onclick=()=>api('/api/cu07/acercar');$('c08push').onchange=e=>api('/api/cu08/push',{valor:e.target.checked});
  $('c08auto').onchange=e=>api('/api/cu08/auto',{valor:e.target.checked});$('b08send').onclick=()=>api('/api/cu08/enviar');
  $('b09arr').onclick=()=>api('/api/cu09/llegada');$('b09del').onclick=()=>api('/api/cu09/entregar');
  $('b10snap').onclick=()=>api('/api/cu10/snapshot');$('bReset').onclick=()=>api('/api/reiniciar');

  $('tabs').innerHTML='<button class="tab on" onclick="ir(0)">Guía</button>'+CUS.map((c,i)=>`<button class="tab" onclick="ir(${i+1})">${c[0]}</button>`).join('');
  ir(0);
  tick();
});
</script>
</body>
</html>"""

# -----------------------------------------------------------------------------
# API Routes
# -----------------------------------------------------------------------------
def datos():
    return request.get_json(silent=True) or {}

@app.route("/")
def index():
    return Response(PAGINA, mimetype="text/html")

@app.get("/api/estado")
def api_estado():
    return jsonify(vista())

@app.post("/api/tick")
def api_tick():
    if E["gps"]["corriendo"] and E["activo"] and E["gps"]["p"] < 1:
        recibir_posicion()
    return jsonify(vista())

# CU-01
@app.post("/api/cu01/preparar")
def api_cu01_preparar():
    if E["activo"]:
        return jsonify(vista(aviso("El recorrido ya está activo.", False)))
    if E["sin_pedidos"]:
        return jsonify(vista(aviso("No hay pedidos asignados.", False)))
    E["confirmando"] = True
    return jsonify(vista())

@app.post("/api/cu01/cancelar")
def api_cu01_cancelar():
    E["confirmando"] = False
    registrar("CU-01", "Inicio cancelado; pedidos permanecen listos para despacho", "w", tipo="inicio")
    return jsonify(vista(aviso("Inicio cancelado.")))

@app.post("/api/cu01/confirmar")
def api_cu01_confirmar():
    return jsonify(vista(iniciar_recorrido()))

@app.post("/api/cu01/sin_pedidos")
def api_cu01_sin_pedidos():
    if not E["activo"]:
        E["sin_pedidos"] = not E["sin_pedidos"]
        E["confirmando"] = False
        registrar("CU-01", "Sin pedidos asignados" if E["sin_pedidos"] else "Pedidos asignados nuevamente", "w" if E["sin_pedidos"] else "", tipo="inicio")
    return jsonify(vista())

@app.post("/api/cu01/falla_correo")
def api_cu01_falla_correo():
    E["falla_correo"] = bool(datos().get("valor"))
    return jsonify(vista())

# CU-02
@app.post("/api/cu02/toggle")
def api_cu02_toggle():
    if not E["activo"]:
        return jsonify(vista(aviso("Primero inicie CU-01.", False)))
    E["gps"]["corriendo"] = not E["gps"]["corriendo"]
    E["gps"]["estado"] = "Señal activa" if E["gps"]["corriendo"] and E["gps"]["senal"] else "En pausa"
    registrar("CU-02", "Envío periódico GPS " + ("iniciado" if E["gps"]["corriendo"] else "pausado"), tipo="gps")
    return jsonify(vista())

@app.post("/api/cu02/paso")
def api_cu02_paso():
    return jsonify(vista(recibir_posicion()))

@app.post("/api/cu02/senal")
def api_cu02_senal():
    E["gps"]["senal"] = not E["gps"]["senal"]
    registrar("CU-02", "Señal GPS restablecida" if E["gps"]["senal"] else "Señal GPS perdida", "" if E["gps"]["senal"] else "w", tipo="gps")
    return jsonify(vista())

@app.post("/api/cu02/invalido")
def api_cu02_invalido():
    E["gps"]["invalido"] = True
    registrar("CU-02", "Se inyectó un dato inválido para el próximo envío", "w", tipo="gps")
    return jsonify(vista())

@app.post("/api/cu02/intervalo")
def api_cu02_intervalo():
    v = int(datos().get("valor", 30))
    if v in (10, 30, 60):
        E["gps"]["intervalo"] = v
    return jsonify(vista())

# Parámetros compartidos
@app.post("/api/params")
def api_params():
    d = datos()
    if "paradas" in d:
        E["params"]["paradas"] = max(0, min(5, int(d["paradas"])))
    if "gps" in d:
        E["params"]["gps_disponible"] = bool(d["gps"])
    if "info" in d:
        E["params"]["info_trafico"] = bool(d["info"])
    return jsonify(vista())

# CU-03
@app.post("/api/cu03/calcular")
def api_cu03_calcular():
    if not E["activo"]:
        return jsonify(vista(aviso("Primero inicie el seguimiento en CU-01.", False)))
    p = pedido_actual()
    if p["eta_inicial"]:
        registrar("CU-03", "ETA inicial recalculada manualmente para demostración", "w", pedido_id=p["id"], tipo="eta")
        pr = pronosticar(p, inicial=True)
        p["eta_inicial"] = pr
        p["eta"] = dict(pr)
        p["eta_historial"].append({"hora": hhmm(E["hora"]), "eta": hhmm(pr["eta"]), "ventana": ventana(pr), "tipo": "Inicial recalculada"})
    else:
        asegurar_eta_inicial(p)
    E["estado_eta"] = "ETA inicial calculada"
    return jsonify(vista(aviso("ETA inicial calculada y registrada.")))

# CU-04
@app.post("/api/cu04/actualizar")
def api_cu04_actualizar():
    if not E["activo"]:
        return jsonify(vista(aviso("Primero inicie CU-01.", False)))
    actualizar_eta(pedido_actual(), "actualización manual")
    return jsonify(vista(aviso("ETA actualizada.")))

@app.post("/api/cu04/incidente")
def api_cu04_incidente():
    E["incidente"] = 3
    registrar("CU-04", "Incidente en vía: +25 min durante las próximas actualizaciones", "w", tipo="eta")
    return jsonify(vista())

@app.post("/api/cu04/trafico")
def api_cu04_trafico():
    v = int(datos().get("valor", 1))
    if v in (0, 1, 2):
        E["params"]["trafico"] = v
        registrar("CU-04", f"Tráfico configurado como {TRAFICO[v]}", "w", tipo="eta")
    return jsonify(vista())

@app.post("/api/cu04/auto")
def api_cu04_auto():
    E["auto_eta"] = bool(datos().get("valor", True))
    return jsonify(vista())

# CU-05
@app.post("/api/cu05/estado")
def api_cu05_estado():
    return jsonify(vista(actualizar_estado(pedido_actual(), datos().get("nuevo"))))

@app.post("/api/conexion")
def api_conexion():
    E["conexion"] = not E["conexion"]
    if E["conexion"]:
        n = 0
        for p in E["pedidos"]:
            if p["pendiente"]:
                nuevo = p["pendiente"]
                p["pendiente"] = None
                aplicar_estado(p, nuevo)
                n += 1
        registrar("CU-05", f"Conexión restablecida; {n} cambio(s) sincronizado(s)", tipo="estado")
        return jsonify(vista(aviso(f"Conexión restablecida. {n} cambio(s) sincronizado(s).")))
    registrar("CU-05", "Conexión perdida; próximos cambios se guardarán en cola", "w", tipo="estado")
    return jsonify(vista(aviso("Sin conexión: cambios posteriores quedarán en cola.", False)))

# CU-06
@app.post("/api/cu06/seleccionar")
def api_cu06_seleccionar():
    i = int(datos().get("valor", 0))
    if 0 <= i < len(E["pedidos"]):
        E["sel"] = i
        E["cliente_snapshot"] = snapshot_cliente(pedido_actual())
        registrar("CU-06", f"Cliente seleccionó {pedido_actual()['id']} en Mis pedidos", pedido_id=pedido_actual()["id"], tipo="consulta")
    return jsonify(vista())

@app.post("/api/cu06/actualizar")
def api_cu06_actualizar():
    E["cliente_snapshot"] = snapshot_cliente(pedido_actual())
    registrar("CU-06", "Cliente actualizó estado y ETA en la App Ripley", pedido_id=pedido_actual()["id"], tipo="consulta")
    return jsonify(vista(aviso("Información de la App actualizada.")))

# CU-07
@app.post("/api/cu07/detectar")
def api_cu07_detectar():
    dentro = detectar_proximidad(pedido_actual())
    return jsonify(vista(aviso("Vehículo dentro del radio de proximidad." if dentro else "Vehículo todavía fuera del radio.", dentro)))

@app.post("/api/cu07/acercar")
def api_cu07_acercar():
    E["gps"]["p"] = max(E["gps"]["p"], 1 - 0.8 / DISTANCIA_TOTAL)
    E["gps"]["estado"] = "Señal activa"
    E["gps"]["paquete"] = {"vehiculo": "V-214", "lat": -12.101, "lng": -77.032, "vel_kmh": 18, "hora": hhmm(E["hora"])}
    registrar("CU-07", "Se simuló una posición a 0.8 km del destino", tipo="proximidad")
    detectar_proximidad(pedido_actual())
    return jsonify(vista(aviso("Vehículo colocado a 0.8 km del destino para la demostración.")))

@app.post("/api/cu07/radio")
def api_cu07_radio():
    v = float(datos().get("valor", 1.0))
    E["radio_proximidad"] = max(0.5, min(3.0, v))
    registrar("CU-07", f"Radio de proximidad configurado en {E['radio_proximidad']:.1f} km", tipo="proximidad")
    return jsonify(vista())

# CU-08
@app.post("/api/cu08/enviar")
def api_cu08_enviar():
    return jsonify(vista(enviar_alerta_proximidad(pedido_actual())))

@app.post("/api/cu08/push")
def api_cu08_push():
    E["push_habilitado"] = bool(datos().get("valor", True))
    registrar("CU-08", "Push habilitado" if E["push_habilitado"] else "Push deshabilitado", "" if E["push_habilitado"] else "w", tipo="alerta")
    return jsonify(vista())

@app.post("/api/cu08/auto")
def api_cu08_auto():
    E["auto_alerta"] = bool(datos().get("valor", True))
    return jsonify(vista())

# CU-09
@app.post("/api/cu09/llegada")
def api_cu09_llegada():
    E["gps"]["p"] = 1.0
    E["gps"]["corriendo"] = False
    E["gps"]["estado"] = "En destino"
    registrar("CU-09", "Vehículo llegó físicamente al destino", tipo="entrega")
    detectar_proximidad(pedido_actual(), automatico=True)
    return jsonify(vista(aviso("Llegada física registrada. Actualice el estado a «En domicilio» en CU-05 si aún no lo hizo.")))

@app.post("/api/cu09/entregar")
def api_cu09_entregar():
    return jsonify(vista(registrar_entrega(pedido_actual())))

# CU-10
@app.post("/api/cu10/snapshot")
def api_cu10_snapshot():
    p = pedido_actual()
    detalle = f"Snapshot: estado={p['estado']}, ETA={etaText_py(p)}, hora_real={p['hora_real'] or '—'}, km={restante():.1f}"
    registrar("CU-10", detalle, tipo="snapshot", pedido_id=p["id"])
    return jsonify(vista(aviso("Snapshot de trazabilidad registrado.")))

def etaText_py(p):
    pr = p["eta"] or p["eta_inicial"]
    return ventana(pr) if pr else "—"

@app.get("/api/cu10/exportar")
def api_cu10_exportar():
    payload = {
        "generado": datetime.datetime.now().isoformat(timespec="seconds"),
        "pedido": pedido_actual()["id"],
        "trazabilidad": list(reversed(E["trazabilidad"])),
        "notificaciones": list(reversed(E["notificaciones"])),
    }
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype="application/json", headers={"Content-Disposition": "attachment; filename=trazabilidad_ripley.json"})

@app.post("/api/reiniciar")
def api_reiniciar():
    reiniciar()
    return jsonify(vista(aviso("Prototipo reiniciado.")))

reiniciar()