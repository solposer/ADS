"""RutaPro - prototipo con una interfaz por actor (datos falsos, en memoria).
Actores: Sistema ERP / Pedidos, Operador Logistico, Conductor, Cliente Final, Motor de Trafico / Mapas.
"""
from copy import deepcopy
from datetime import datetime, timedelta
from itertools import permutations
from math import asin, cos, radians, sin, sqrt
import time

from flask import Blueprint, render_template_string, request

app = Blueprint("ruteo", __name__)
LEG_MS = 3300  # duracion simulada de cada tramo entre paradas

# ------------------------------------------------------------------ datos
DEPOT = "Almacén (Ate)"
COORD = {
    DEPOT: (-12.0260, -76.9170),
    "Ate": (-12.0300, -76.9000),
    "Miraflores": (-12.1211, -77.0297),
    "San Isidro": (-12.0977, -77.0365),
    "Surco": (-12.1450, -76.9930),
    "La Molina": (-12.0850, -76.9100),
    "San Borja": (-12.1080, -77.0030),
    "Jesús María": (-12.0700, -77.0500),
    "Lince": (-12.0830, -77.0340),
}
TRAFICO = {
    d: f
    for d, f in zip(
        list(COORD)[1:], (1.0, 1.5, 1.4, 1.2, 1.0, 1.2, 1.3, 1.3)
    )
}
E = "En ERP"
L = "Listo para despacho"
_p = lambda i, c, d, di, kg, m3, b, v: dict(
    id=i,
    cliente=c,
    distrito=d,
    dir=di,
    kg=kg,
    m3=m3,
    bultos=b,
    veh=v,
    estado=E,
)
PEDIDOS = [
    _p(4821, "Rosa Gómez", "Miraflores", "Av. Larco 345", 180, 0.9, 2, "V1"),
    _p(4822, "Tienda Andina SAC", "San Isidro", "Calle Los Pinos 120", 240, 1.4, 3, "V1"),
    _p(4823, "Carlos Medina", "Surco", "Av. Primavera 1250", 150, 0.8, 1, "V1"),
    _p(4825, "Hogar Ideal SRL", "Lince", "Av. Arenales 1840", 120, 0.7, 2, "V2"),
    _p(4826, "Marco Ríos", "Jesús María", "Av. Brasil 2320", 200, 1.0, 2, "V2"),
    _p(4827, "Elena Castro", "San Borja", "Av. San Luis 2100", 160, 0.9, 1, "V2"),
    _p(4828, "Electro Plus", "La Molina", "Av. La Molina 3400", 400, 2.6, 5, "V3"),
    _p(4829, "Julio Vega", "Surco", "Av. Benavides 4100", 380, 2.2, 4, "V3"),
    _p(4830, "Mueblería Sur", "Ate", "Av. Nicolás Ayllón 2900", 350, 2.4, 4, "V3"),
]
FLOTA = {
    "V1": dict(
        tipo="Camión",
        placa="C-02",
        cap=1200,
        vol=8.0,
        cond="Luis Ramírez",
        estado="Disponible",
    ),
    "V2": dict(
        tipo="Furgoneta",
        placa="F-05",
        cap=800,
        vol=5.0,
        cond="Carla Soto",
        estado="Disponible",
    ),
    "V3": dict(
        tipo="Camión",
        placa="C-07",
        cap=1000,
        vol=7.0,
        cond="Jorge Paredes",
        estado="Disponible",
    ),
}
RUTAS, INC, LOG, MOT = {}, [], [], []
ST = dict(sel=None, gen=False, crit=None, cond=None, cli=4823)
P0, T0 = deepcopy(PEDIDOS), deepcopy(TRAFICO)
hora = lambda: datetime.now().strftime("%H:%M:%S")


def log(m):
    LOG.insert(0, (hora(), m))


def pd(i):
    return next(p for p in PEDIDOS if p["id"] == i)


def sig(r):
    return next((s for s in r["stops"] if s["estado"] == "Pendiente"), None)


# ------------------------------------------------------------ optimizacion
def km(a, b):
    la1, lo1, la2, lo2 = map(radians, (*COORD[a], *COORD[b]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin(
        (lo2 - lo1) / 2
    ) ** 2
    return 2 * 6371 * asin(sqrt(h)) * 1.35


def evalua(orden, ini=DEPOT):
    pts, d, t = [ini] + [p["distrito"] for p in orden], 0, 0
    for a, b in zip(pts, pts[1:]):
        k = km(a, b)
        d += k
        t += k / 30 * 60 * TRAFICO.get(b, 1)
    return round(d, 1), round(t)


def alternativas(ped):
    cer, rest, cur = [], list(ped), DEPOT
    while rest:
        n = min(rest, key=lambda p: km(cur, p["distrito"]))
        cer.append(n)
        rest.remove(n)
        cur = n["distrito"]
    base = {
        "rapida": (
            "Menor tiempo",
            list(min(permutations(ped), key=lambda o: evalua(o)[1])),
        ),
        "corta": (
            "Menor distancia",
            list(min(permutations(ped), key=lambda o: evalua(o)[0])),
        ),
        "cercano": ("Vecino más cercano", cer),
    }
    return {
        k: dict(n=n, orden=o, km=evalua(o)[0], min=evalua(o)[1])
        for k, (n, o) in base.items()
    }


def recalcula(vid):
    r = RUTAS[vid]
    pend = [s for s in r["stops"] if s["estado"] == "Pendiente"]
    hechos = [s for s in r["stops"] if s["estado"] != "Pendiente"]
    if len(pend) < 2:
        return
    ini = pd(hechos[-1]["pid"])["distrito"] if hechos else DEPOT
    r["stops"] = hechos + list(
        min(
            permutations(pend),
            key=lambda o: evalua([pd(s["pid"]) for s in o], ini)[1],
        )
    )
    r["aviso"] = (
        "Tráfico intenso: la ruta se recalculó y las paradas se reordenaron."
    )
    if r["fase"] == "viajando":
        r["t0"] = time.time()
    log(f"Ruta de {FLOTA[vid]['placa']} recalculada por cambio de tráfico")


def siguiente(vid):
    r = RUTAS[vid]
    r["aviso"] = None
    if sig(r):
        r["fase"] = "viajando"
        r["t0"] = time.time()
    else:
        r["fase"] = "finalizada"
        FLOTA[vid]["estado"] = "Disponible"
        log(f"Ruta de {FLOTA[vid]['placa']} finalizada")


def tick():
    for vid, r in RUTAS.items():
        if (
            r["fase"] == "viajando"
            and (time.time() - r["t0"]) * 1000 >= LEG_MS
        ):
            r["fase"] = "en_parada"
            log(f"{FLOTA[vid]['cond']} llegó al pedido #{sig(r)['pid']}")


# --------------------------------------------------------------------- API
@app.post("/api/<a>")
def api(a):
    f = request.form
    tick()
    vid = ST["cond"]
    r = RUTAS.get(vid)
    if a == "erp":
        for p in PEDIDOS:
            if p["estado"] == E:
                p["estado"] = L
        log("ERP envió los pedidos listos (direcciones, pesos y volúmenes)")
    elif a == "op_sel":
        ST.update(sel=f["veh"], gen=False, crit=None)
    elif a == "op_gen":
        ST["gen"] = True
        MOT.insert(
            0,
            f"{hora()} Consulta de rutas para {FLOTA[ST['sel']]['placa']}: 3"
            " alternativas devueltas",
        )
    elif a == "op_crit":
        ST["crit"] = f["crit"]
    elif a == "op_asignar":
        v = ST["sel"]
        ped = [p for p in PEDIDOS if p["veh"] == v and p["estado"] == L]
        al = alternativas(ped)
        x = al[ST["crit"] or min(al, key=lambda k: al[k]["min"])]
        RUTAS[v] = dict(
            stops=[dict(pid=p["id"], estado="Pendiente") for p in x["orden"]],
            fase="asignada",
            t0=0,
            crit=x["n"],
            km=x["km"],
            aus=None,
            aviso=None,
        )
        FLOTA[v]["estado"] = "En ruta"
        ST.update(cond=v, sel=None, gen=False, crit=None)
        for p in ped:
            p["estado"] = "En ruta"
        log(
            f"Ruta registrada: {FLOTA[v]['placa']} con {FLOTA[v]['cond']}"
            f" ({x['n']}, {x['km']} km)"
        )
    elif a == "c_sel":
        ST["cond"] = f["veh"]
    elif a == "c_iniciar":
        r["fase"] = "viajando"
        r["t0"] = time.time()
        log(f"{FLOTA[vid]['cond']} inició su ruta")
    elif a == "c_entregar":
        s = sig(r)
        s["estado"] = "Entregado"
        pd(s["pid"])["estado"] = "Entregado"
        log(f"Pedido #{s['pid']} entregado. Notificación enviada a Logística")
        siguiente(vid)
    elif a == "c_aus":
        r["aus"] = dict(
            paso=1,
            pid=sig(r)["pid"],
            log=[f"{hora()} Cliente ausente marcado"],
        )
    elif a == "c_contactar":
        r["aus"]["log"] += [
            f"{hora()} Motivo: {f['motivo']}",
            f"{hora()} Intento de contacto por llamada",
        ]
        r["aus"].update(paso=2, motivo=f["motivo"])
    elif a == "c_resp":
        r["aus"] = None
    elif a == "c_sin":
        x = r["aus"]
        next(s for s in r["stops"] if s["pid"] == x["pid"])["estado"] = "Fallido"
        pd(x["pid"])["estado"] = "Entrega fallida"
        INC.append(dict(id=len(INC) + 1, pid=x["pid"], estado="Pendiente"))
        x["log"] += [
            f"{hora()} Sin respuesta del cliente",
            f"{hora()} Estado: Entrega fallida - cliente ausente",
            f"{hora()} Notificación enviada a Logística",
        ]
        x["paso"] = 3
        log(
            f"Incidencia en pedido #{x['pid']}: cliente ausente. Notificación"
            " enviada a Logística"
        )
    elif a == "c_fin":
        r["aus"] = None
        siguiente(vid)
    elif a == "mot":
        TRAFICO[f["d"]] = 3.0
        MOT.insert(0, f"{hora()} Tráfico intenso informado en {f['d']}")
        for k, x in RUTAS.items():
            if x["fase"] in ("viajando", "en_parada"):
                recalcula(k)
    elif a == "cli":
        ST["cli"] = int(f["pid"])
    elif a in ("cli_fecha", "cli_dev"):
        p = pd(ST["cli"])
        i = next(
            i
            for i in INC
            if i["pid"] == p["id"] and i["estado"] == "Pendiente"
        )
        if a == "cli_fecha":
            i["estado"] = "Reprogramada"
            p["estado"] = L
            p["nota"] = "Reprogramado para " + f["fecha"]
            log(f"Pedido #{p['id']} reprogramado para {f['fecha']}")
        else:
            i["estado"] = "Devuelta"
            p["estado"] = "Devuelto a almacén"
            log(f"Pedido #{p['id']} devuelto al almacén")
    elif a == "reset":
        PEDIDOS[:] = deepcopy(P0)
        TRAFICO.update(T0)
        RUTAS.clear()
        INC.clear()
        LOG.clear()
        MOT.clear()
        for x in FLOTA.values():
            x["estado"] = "Disponible"
        ST.update(sel=None, gen=False, crit=None, cond=None, cli=4823)
    return "ok"


# ------------------------------------------------------------------- vistas
@app.get("/vista/<actor>")
def vista(actor):
    tick()
    c = dict(
        FLOTA=FLOTA,
        pd=pd,
        ST=ST,
        COORD=COORD,
        TRAFICO=TRAFICO,
        LOG=LOG[:6],
        MOT=MOT[:5],
        E=E,
        L=L,
    )
    if actor == "erp":
        c["ped"] = PEDIDOS
    elif actor == "operador":
        v = FLOTA.get(ST["sel"])
        ped = [p for p in PEDIDOS if p["veh"] == ST["sel"] and p["estado"] == L]
        kg, m3 = sum(p["kg"] for p in ped), round(sum(p["m3"] for p in ped), 1)
        ok = bool(v and ped and kg <= v["cap"] and m3 <= v["vol"])
        al = alternativas(ped) if ok and ST["gen"] else None
        rec = min(al, key=lambda k: al[k]["min"]) if al else None
        carga = {
            k: sum(
                p["kg"]
                for p in PEDIDOS
                if p["veh"] == k and p["estado"] in (L, "En ruta")
            )
            for k in FLOTA
        }
        listos = {
            k: sum(
                p["veh"] == k and p["estado"] == L for p in PEDIDOS
            )
            for k in FLOTA
        }
        c.update(
            v=v,
            ped=ped,
            kg=kg,
            m3=m3,
            ok=ok,
            al=al,
            rec=rec,
            crit=ST["crit"] or rec,
            carga=carga,
            listos=listos,
            rutas=RUTAS,
            live=any(
                r["fase"] in ("viajando", "en_parada") for r in RUTAS.values()
            ),
        )
    elif actor == "conductor":
        vid = (
            ST["cond"]
            if ST["cond"] in RUTAS
            else next(iter(RUTAS), None)
        )
        r = RUTAS.get(vid)
        c.update(rutas=RUTAS, vid=vid, r=r, sig=sig(r) if r else None)
        if r and r["fase"] == "viajando":
            ms = (time.time() - r["t0"]) * 1000
            c.update(
                prog=min(100, int(ms * 100 / LEG_MS)),
                rest=max(0, int(LEG_MS - ms)),
            )
    elif actor == "cliente":
        c.update(
            ped=[p for p in PEDIDOS if p["estado"] != E] or PEDIDOS,
            p=pd(ST["cli"]),
            fechas=[
                (datetime.now() + timedelta(days=n)).strftime("%d/%m")
                for n in (1, 2, 3)
            ],
        )
        r = next(
            (
                x
                for x in RUTAS.values()
                if any(s["pid"] == ST["cli"] for s in x["stops"])
            ),
            None,
        )
        c["falt"] = (
            sum(s["estado"] == "Pendiente" for s in r["stops"]) if r else None
        )
        c["pend"] = any(
            i["pid"] == ST["cli"] and i["estado"] == "Pendiente" for i in INC
        )
    return render_template_string(T[actor], **c)


@app.get("/")
def home():
    return render_template_string(T["home"])


# ---------------------------------------------------------------- plantillas
T = {}
T["home"] = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RutaPro - prototipo por actor</title><style>
:root{--ink:#1b2a38;--mut:#5d6b78;--line:#d3dce3;--acc:#0f766e;--accbg:#d9f0ec;--gold:#fff2cc;--bad:#b42318}
*{box-sizing:border-box}body{margin:0;background:#f2f5f7;color:var(--ink);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
header{background:#1b2a38;color:#fff;padding:14px 20px}header h1{margin:0;font-size:20px}header p{margin:2px 0 10px;color:#9fb0bf;font-size:13px}
.tabs{display:flex;gap:8px;flex-wrap:wrap}.tabs button{background:#2c4156;color:#dbe5ec;text-align:left;padding:8px 14px;line-height:1.3;border:0;border-radius:6px;cursor:pointer}.tabs button small{display:block;color:#9fb0bf;font-size:12px}
.tabs button.on{background:#fff;color:var(--ink)}.tabs button.on small{color:var(--mut)}.tabs .r{margin-left:auto;background:transparent;border:1px solid #476078}
main{max-width:980px;margin:0 auto;padding:20px 16px 48px}h3{margin:0 0 10px;font-size:16px}.m{color:var(--mut)}
.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:14px;overflow-x:auto}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600}
button{font:inherit;background:var(--acc);color:#fff;border:0;border-radius:6px;padding:9px 14px;cursor:pointer}button.sec{background:#fff;color:var(--ink);border:1px solid var(--line)}
button:focus-visible,select:focus-visible{outline:3px solid #7cc4bb;outline-offset:2px}select{font:inherit;padding:8px;border:1px solid var(--line);border-radius:6px}
.flash{background:var(--accbg);border:1px solid #9dd3cb;border-radius:6px;padding:9px 12px;margin-bottom:10px}.err{background:#fde8e6;border:1px solid #f1b3ad;color:var(--bad);padding:9px 12px;border-radius:6px;margin:10px 0}
.b{display:inline-block;padding:1px 8px;border-radius:10px;background:#e6ebef;font-size:13px;white-space:nowrap}.ok{background:var(--accbg)}.no{background:#fde8e6}
.gold{background:var(--gold);border:1px solid #c9a227;border-radius:4px;padding:1px 8px;font-size:13px;font-weight:400;margin-left:6px}
.bar{height:10px;background:#e6ebef;border-radius:5px;overflow:hidden;min-width:90px}.bar i{display:block;height:100%;background:var(--acc)}.bar.over i{background:var(--bad)}
label.opt{display:flex;gap:10px;border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:8px;cursor:pointer}label.opt.rec{border-color:var(--acc);background:var(--accbg)}
.stop{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin-bottom:8px}.stop.now{border-color:var(--acc);background:var(--accbg)}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.phone{max-width:420px}
</style></head><body>
<header><div style="margin-bottom: 8px;"><a href="/" style="color: #9fb0bf; text-decoration: none; font-size: 13px;">← Volver al Portal Principal</a></div><h1>RutaPro - prototipo por actor</h1><p>Elige un actor para ver su interfaz. Orden sugerido: ERP, Operador, Conductor, Cliente. Un viaje simulado dura unos 10 segundos.</p>
<div class="tabs" id="tabs"></div></header><main id="panel"></main>
<script>
const A=[["erp","Sistema ERP / Pedidos","Sistema externo"],["operador","Operador Logístico","Persona, interna"],["conductor","Conductor","Persona, interna"],
["cliente","Cliente Final","Persona, externa"],["motor","Motor de Tráfico / Mapas","Sistema externo"]];
let cur="erp",tm=null;const panel=document.getElementById("panel");
document.getElementById("tabs").innerHTML=A.map(a=>`<button id="t-${a[0]}" onclick="load('${a[0]}')">${a[1]}<small>${a[2]}</small></button>`).join("")+`<button class="r" onclick="act('/ruteo/api/reset').then(()=>load('erp'))">Reiniciar datos</button>`;
async function load(v){if(v)cur=v;clearTimeout(tm);panel.innerHTML=await (await fetch("/ruteo/vista/"+cur)).text();
 A.forEach(a=>document.getElementById("t-"+a[0]).className=a[0]==cur?"on":"");
 const t=document.getElementById("tb");if(t){const rest=+t.dataset.rest;setTimeout(()=>{t.style.transition="width "+rest+"ms linear";t.style.width="100%"},30);tm=setTimeout(()=>load(),rest+250)}
 else if(document.getElementById("live"))tm=setTimeout(()=>load(),1500)}
async function act(u,d){await fetch(u,{method:"POST",body:new URLSearchParams(d||{})});if(!u.endsWith("reset"))load()}
load("erp");
</script></body></html>"""

T["erp"] = """<div class="card"><h3>Sistema ERP / Pedidos <span class="b">Sistema externo, CU-01 y CU-02</span></h3>
<p class="m">Panel del ERP que entrega a RutaPro los pedidos listos con su dirección, coordenadas, peso, volumen y bultos.</p>
<table><tr><th>Pedido</th><th>Dirección</th><th>Coordenadas</th><th>Peso</th><th>Volumen</th><th>Bultos</th><th>Estado</th></tr>
{% for p in ped %}<tr><td>#{{ p.id }}</td><td>{{ p.dir }}, {{ p.distrito }}</td><td>{{ '%.3f'|format(COORD[p.distrito][0]) }}, {{ '%.3f'|format(COORD[p.distrito][1]) }}</td>
<td>{{ p.kg }} kg</td><td>{{ p.m3 }} m³</td><td>{{ p.bultos }}</td><td><span class="b {{ 'no' if p.estado==E else 'ok' }}">{{ 'Pendiente de envío' if p.estado==E else 'Enviado' }}</span></td></tr>{% endfor %}</table>
<p><button onclick="act('/ruteo/api/erp')">Enviar pedidos listos a RutaPro</button></p></div>"""

T["operador"] = """{% if live %}<span id="live"></span>{% endif %}
<div class="card"><h3>Flota <span class="b">CU-03</span></h3><table><tr><th>Vehículo</th><th>Conductor</th><th>Capacidad</th><th>Carga</th><th>Pedidos listos</th><th>Estado</th><th></th></tr>
{% for k,f in FLOTA.items() %}<tr><td>{{ f.tipo }} {{ f.placa }}</td><td>{{ f.cond }}</td><td>{{ f.cap }} kg / {{ f.vol }} m³</td>
<td>{{ carga[k] }} kg<div class="bar {{ 'over' if carga[k]>f.cap }}"><i style="width:{{ [carga[k]*100//f.cap,100]|min }}%"></i></div></td><td>{{ listos[k] }}</td>
<td><span class="b {{ 'ok' if f.estado=='Disponible' else '' }}">{{ f.estado }}</span></td>
<td>{% if f.estado=='Disponible' and listos[k] %}<button class="sec" onclick="act('/ruteo/api/op_sel',{veh:'{{ k }}'})">Planificar</button>{% endif %}</td></tr>{% endfor %}</table>
{% if not carga.values()|sum %}<p class="m">Aún no hay pedidos recibidos. Entra como Sistema ERP y envía los pedidos.</p>{% endif %}</div>
{% if v %}<div class="card"><h3>Validar capacidad <span class="b">CU-05</span> - {{ v.tipo }} {{ v.placa }}</h3>
<p>Peso {{ kg }} de {{ v.cap }} kg. Volumen {{ m3 }} de {{ v.vol }} m³.</p>
{% if ok %}{% if not al %}<button onclick="act('/ruteo/api/op_gen')">Generar alternativas de ruta</button>{% endif %}
{% else %}<div class="err">La carga excede la capacidad del vehículo. Reasigna pedidos a otro vehículo antes de generar rutas.</div>{% endif %}</div>{% endif %}
{% if al %}<div class="card"><h3>Alternativas de ruta <span class="gold">Caso de uso diferenciador, CU-04</span></h3>
{% for k,a in al.items() %}<label class="opt {{ 'rec' if k==rec }}" onclick="act('/ruteo/api/op_crit',{crit:'{{ k }}'})"><input type="radio" name="c" {{ 'checked' if k==crit }}><span>
<strong>{{ a.n }}</strong>{% if k==rec %} <span class="b ok">Recomendada</span>{% endif %}<br>{{ a.orden|map(attribute='distrito')|join(' → ') }}<br><span class="m">{{ a.km }} km, {{ a.min }} min</span></span></label>{% endfor %}
<button onclick="act('/ruteo/api/op_asignar')">Seleccionar y asignar a vehículo y conductor (CU-06, CU-07)</button></div>{% endif %}
<div class="card"><h3>Seguimiento en vivo</h3>{% if rutas %}<table><tr><th>Vehículo</th><th>Conductor</th><th>Avance</th><th>Estado</th></tr>
{% for k,r in rutas.items() %}<tr><td>{{ FLOTA[k].placa }}</td><td>{{ FLOTA[k].cond }}</td><td>{{ r.stops|rejectattr('estado','eq','Pendiente')|list|length }} de {{ r.stops|length }} paradas</td>
<td><span class="b">{{ {'asignada':'Asignada','viajando':'En camino','en_parada':'En una parada','finalizada':'Finalizada'}[r.fase] }}</span></td></tr>{% endfor %}</table>
{% else %}<p class="m">Sin rutas asignadas.</p>{% endif %}</div>
<div class="card"><h3>Historial <span class="b">CU-08</span></h3>{% for h,m in LOG %}<div><span class="m">{{ h }}</span> {{ m }}</div>{% else %}<p class="m">Sin eventos.</p>{% endfor %}</div>"""

T["conductor"] = """{% if not r %}<div class="card"><p class="m">No tienes rutas asignadas. El Operador Logístico debe asignarte una ruta.</p></div>{% else %}
<div class="row" style="margin-bottom:10px">{% for k in rutas %}<button class="{{ '' if k==vid else 'sec' }}" onclick="act('/ruteo/api/c_sel',{veh:'{{ k }}'})">{{ FLOTA[k].cond }}</button>{% endfor %}</div>
<div class="card phone"><h3>Ruta de {{ FLOTA[vid].cond }} <span class="b">CU-09</span></h3><p class="m">{{ FLOTA[vid].placa }}, {{ r.crit }}, {{ r.km }} km</p>
{% if r.aviso %}<div class="flash">{{ r.aviso }} <span class="b">CU-10</span></div>{% endif %}
{% for s in r.stops %}{% set p = pd(s.pid) %}<div class="stop {{ 'now' if s==sig }}"><strong>Parada {{ loop.index }}: pedido #{{ p.id }}</strong>
<span class="b {{ 'ok' if s.estado=='Entregado' else ('no' if s.estado=='Fallido') }}">{{ s.estado }}</span><br>{{ p.dir }}, {{ p.distrito }}<br><span class="m">{{ p.cliente }}</span></div>{% endfor %}
{% if r.fase=='asignada' %}<button onclick="act('/ruteo/api/c_iniciar')">Iniciar ruta</button>
{% elif r.fase=='viajando' %}<p>En camino a la parada {{ r.stops|rejectattr('estado','eq','Pendiente')|list|length + 1 }}...</p><div class="bar"><i id="tb" style="width:{{ prog }}%" data-rest="{{ rest }}"></i></div>
{% elif r.fase=='en_parada' %}{% set a = r.aus %}
 {% if not a %}<p>Llegaste a la dirección del pedido #{{ sig.pid }}.</p><div class="row"><button onclick="act('/ruteo/api/c_entregar')">Confirmar entrega</button><button class="sec" onclick="act('/ruteo/api/c_aus')">Cliente ausente</button></div>
 {% elif a.paso==1 %}<h3>Registrar cliente ausente <span class="b">CU-11</span></h3><select id="mo" aria-label="Motivo"><option>Nadie atiende en el domicilio</option><option>Dirección cerrada o sin acceso</option><option>Cliente no está en casa</option></select>
  <p><button onclick="act('/ruteo/api/c_contactar',{motivo:document.getElementById('mo').value})">Contactar al cliente (llamada)</button></p>
 {% elif a.paso==2 %}<div class="flash">Llamando al cliente...</div><div class="row"><button class="sec" onclick="act('/ruteo/api/c_resp')">El cliente respondió</button><button onclick="act('/ruteo/api/c_sin')">Sin respuesta</button></div>
 {% else %}<div class="flash">Incidencia registrada. Logística fue notificada.</div><ul>{% for l in a.log %}<li>{{ l }}</li>{% endfor %}</ul>
  <p class="m">El pedido queda pendiente de reprogramar o devolver (CU-12).</p><button onclick="act('/ruteo/api/c_fin')">Continuar con la ruta</button>{% endif %}
{% else %}<div class="flash">Ruta finalizada. Todas las paradas fueron atendidas.</div>{% endif %}</div>{% endif %}"""

T["cliente"] = """<div class="card phone"><h3>Mi pedido <span class="b">Cliente Final, CU-12</span></h3>
<select aria-label="Pedido" onchange="act('/ruteo/api/cli',{pid:this.value})">{% for x in ped %}<option value="{{ x.id }}" {{ 'selected' if x.id==p.id }}>#{{ x.id }} - {{ x.cliente }}</option>{% endfor %}</select>
<p><strong>#{{ p.id }}</strong>, {{ p.dir }}, {{ p.distrito }}<br>Estado: <span class="b {{ 'ok' if p.estado in ('Entregado','En ruta') else ('no' if p.estado=='Entrega fallida') }}">{{ p.estado }}</span>{% if p.nota %}<br><span class="m">{{ p.nota }}</span>{% endif %}</p>
{% if p.estado==E %}<p class="m">Tu pedido aún no fue enviado por el ERP.</p>
{% elif p.estado=='En ruta' %}<p>Tu pedido está en camino. {% if falt is not none %}Faltan {{ falt }} parada(s) pendientes en la ruta.{% endif %}</p>
{% elif p.estado=='Entregado' %}<div class="flash">Recibiste tu paquete. Gracias.</div>
{% elif p.estado=='Entrega fallida' and pend %}<div class="err">No pudimos entregar tu pedido porque no te encontramos. Elige una nueva fecha:</div>
<div class="row">{% for f in fechas %}<button class="sec" onclick="act('/ruteo/api/cli_fecha',{fecha:'{{ f }}'})">{{ f }}</button>{% endfor %}<button class="sec" onclick="act('/ruteo/api/cli_dev')">Devolver al almacén</button></div>
{% elif p.estado==L %}<p class="m">Tu pedido está listo para despacho.</p>{% endif %}</div>"""

T["motor"] = """<div class="card"><h3>Motor de Tráfico / Mapas <span class="b">Sistema externo, CU-04 y CU-10</span></h3>
<p class="m">Entrega distancias y tráfico a RutaPro. Si informas tráfico intenso, las rutas en ejecución se recalculan solas.</p>
<table><tr><th>Distrito</th><th>Factor de tráfico</th><th>Estado</th><th></th></tr>{% for d,f in TRAFICO.items() %}<tr><td>{{ d }}</td><td>{{ f }}</td>
<td><span class="b {{ 'no' if f>=3 else 'ok' }}">{{ 'Intenso' if f>=3 else 'Normal' }}</span></td><td><button class="sec" onclick="act('/ruteo/api/mot',{d:'{{ d }}'})">Informar tráfico intenso</button></td></tr>{% endfor %}</table></div>
<div class="card"><h3>Últimos eventos</h3>{% for m in MOT %}<div>{{ m }}</div>{% else %}<p class="m">Sin consultas todavía.</p>{% endfor %}</div>"""