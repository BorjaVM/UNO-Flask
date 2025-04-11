import eventlet
eventlet.monkey_patch() 

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import random
import os


proyecto1 = Flask(__name__)
socketio = SocketIO(proyecto1)


# Variables Globales
barajas = {}
jugadores = {}
sala_host = {}
turno_actual = {}
carta_inicial_salas = {}  # Almacena la carta inicial de cada sala
salas_activas = {}  # Clave: nombre de sala, Valor: True si ya comenzó
jugador_a_sala = {}  # Clave: nombre_jugador, Valor: nombre_sala
mazo_descartes = {}  # Contendrá las cartas que se han jugado y que se pueden volver a usar.



colores = ["verde", "rojo", "azul", "amarillo", ]
#colores = ["azul"]
#valores =["0"]
valores = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "prohibido", "cambioSentido", "+2"]
especiales = ["+4", "cambioColor","cambioBaraja"]

def crear_baraja():
    baraja = [{"Color": color, "valor": valor} for color in colores for valor in valores] * 2
    baraja.extend([{"Color": "negro", "valor": valor} for valor in especiales] *4)
    random.shuffle(baraja)
    return baraja

def repartir_baraja(sala):
    for id_jugador in jugadores[sala]:
        jugadores[sala][id_jugador]["mano"] = [barajas[sala].pop() for _ in range(7)]
    
    carta_inicial = barajas[sala].pop()
    while carta_inicial["valor"] in ["+4", "cambioColor","prohibido", "cambioSentido", "+2","cambioBaraja"]:
        barajas[sala].append(carta_inicial)
        random.shuffle(barajas[sala])
        carta_inicial = barajas[sala].pop()
    
    return carta_inicial


@proyecto1.route("/")
def index():
    return render_template("index.html")


@socketio.on("unirse_sala")
def unirse_sala(datos):
    try:
        id_jugador = str(datos.get("id"))
        nombre = datos.get("nombre")
        sala = datos.get("sala")

        if not id_jugador or not nombre or not sala:
            emit("error", {"mensaje": "Datos inválidos para unirse a la sala."}, room=request.sid)
            return

        # Verificar si la sala ya ha comenzado
        if salas_activas.get(sala, False) and id_jugador not in jugadores[sala]:
            emit("error", {"mensaje": "La sala está ocupada, el juego ya ha comenzado.", "id": id_jugador}, room=request.sid)
            return

        # Si ya estaba en otra sala, removerlo
        sala_anterior = jugador_a_sala.get(id_jugador)
        if sala_anterior and sala_anterior != sala:
            if id_jugador in jugadores.get(sala_anterior, {}):
                del jugadores[sala_anterior][id_jugador]
                leave_room(sala_anterior)
                emit("jugador_salio", {"id": id_jugador}, room=sala_anterior)

                if not jugadores[sala_anterior]:
                    jugadores.pop(sala_anterior)
                    barajas.pop(sala_anterior, None)
                    turno_actual.pop(sala_anterior, None)
                    carta_inicial_salas.pop(sala_anterior, None)
                    salas_activas.pop(sala_anterior, None)
                    sala_host.pop(sala_anterior, None)

        join_room(sala)

        if sala not in jugadores:
            jugadores[sala] = {}
            barajas[sala] = crear_baraja()
            sala_host[sala] = id_jugador
            turno_actual[sala] = id_jugador
            carta_inicial_salas[sala] = None

        if id_jugador in jugadores[sala]:
            emit("cartas_repartidas", {"jugadores": jugadores[sala]}, room=request.sid)
            return

        jugadores[sala][id_jugador] = {"nombre": nombre, "mano": [],  "sid": request.sid  }
        jugador_a_sala[id_jugador] = sala  # ← Asignar nueva sala

        emit("mostrar_comenzar", {
            "host": sala_host[sala],
            "jugadores": list(jugadores[sala].values())
        }, room=sala)

        # Aquí enviamos el nombre de la sala al cliente para actualizar la UI
        emit("actualizar_sala", {"sala": sala}, room=request.sid)
    except Exception as e:
        print(f"Error al unir jugador a la sala: {str(e)}")
        emit("error", {"mensaje": "Ocurrió un error al unirse a la sala."}, room=request.sid)


    
@socketio.on("salir_sala")
def salir_sala(datos):
    id_jugador = str(datos["id"])
    sala = datos["sala"]

    if sala in jugadores and id_jugador in jugadores[sala]:
        leave_room(sala)
        del jugadores[sala][id_jugador]

        if sala_host[sala] == id_jugador and jugadores[sala]:
            sala_host[sala] = next(iter(jugadores[sala]))

        if not jugadores[sala]:
            del jugadores[sala]
            del barajas[sala]
            del sala_host[sala]
            del turno_actual[sala]
            del carta_inicial_salas[sala]

        emit("jugador_salio", {"id": id_jugador}, room=sala)

@socketio.on("comenzar_juego")
def comenzar_juego(datos):
    sala = datos["sala"]

    # Marcar la sala como activa (ya comenzó el juego)
    salas_activas[sala] = True

    # Repartir las cartas de la sala
    carta_inicial_salas[sala] = repartir_baraja(sala)

    # Emitir las cartas a los jugadores
    emit("cartas_repartidas", {"jugadores": jugadores[sala]}, room=sala)

    # Emitir que el juego ha comenzado
    emit("juego_comenzado", {
        "turno": turno_actual[sala],
        "carta_inicial": carta_inicial_salas[sala],
        "host": sala_host[sala]
    }, room=sala)

    # Aquí es donde puedes excluir esta sala de la lista de salas disponibles.
    # El evento "lista_salas" ya excluye automáticamente las salas activas.


@socketio.on("obtener_estado")
def obtener_estado(datos):
    sala = datos["sala"]
    id_jugador = request.sid

    if sala in jugadores:
        if len(jugadores[sala]) < 2:
            return

        carta_inicial = carta_inicial_salas.get(sala, None)
        if carta_inicial is None and len(barajas[sala]) > 0:
            carta_inicial = barajas[sala].pop()
            carta_inicial_salas[sala] = carta_inicial

        turno = turno_actual.get(sala, "")
        if not turno:
            turno = next(iter(jugadores[sala]))

        juego_activo = salas_activas.get(sala, False)

        emit("estado_actual", {
            "juegoActivo": juego_activo,
            "turno": turno if juego_activo else None,
            "host": sala_host.get(sala, ""),
            "carta_inicial": carta_inicial if juego_activo else None
        }, room=id_jugador)

        if juego_activo:
            socketio.emit("estado_actualizado", {
                "turno": turno,
                "nueva_carta": carta_inicial
            }, room=sala)



@socketio.on("validarCarta")
def validarCarta(datos):
    sala = datos["sala"]
    id_jugador = str(datos["id"])
    color = datos["color"]
    valor = datos["valor"]
    carta_seleccionada = {"Color": color, "valor": valor}

    if turno_actual.get(sala) != id_jugador:
        emit("error", {"mensaje": "No es tu turno."}, room=request.sid)
        return

    if carta_seleccionada in jugadores[sala][id_jugador]["mano"]:
        jugadores[sala][id_jugador]["mano"].remove(carta_seleccionada)
        
        if sala not in mazo_descartes:
            mazo_descartes[sala] = []
            mazo_descartes[sala].append(carta_seleccionada)
        
        if len(barajas[sala]) == 0:
            barajas[sala] = mazo_descartes[sala]
            mazo_descartes[sala] = []
            random.shuffle(barajas[sala])
            
        if len(jugadores[sala][id_jugador]["mano"]) == 0:
            print(f"Emitido evento jugador_ganador para {id_jugador}")
            emit("jugador_ganador", {"id": id_jugador,"sala":sala}, room=sala)
            # Cerrar la sala eliminando todos los datos relacionados
            del jugadores[sala]
            del barajas[sala]
            del sala_host[sala]
            del turno_actual[sala]
            del carta_inicial_salas[sala]
            return
        
      
        # Manejar "cambioBaraja"
        if valor == "cambioBaraja":
            ids_jugadores = list(jugadores[sala].keys())
            
            # Buscar un jugador distinto al actual (si hay más de uno)
            otros_jugadores = [jid for jid in ids_jugadores if jid != id_jugador]
            if not otros_jugadores:
                emit("error", {"mensaje": "No hay otro jugador para intercambiar barajas."}, room=request.sid)
                return

            # Por simplicidad, elegimos al siguiente jugador en la lista
            turno_index = ids_jugadores.index(id_jugador)
            otro_jugador = ids_jugadores[(turno_index + 1) % len(ids_jugadores)]

            # Intercambiar las manos
            jugadores[sala][id_jugador]["mano"], jugadores[sala][otro_jugador]["mano"] = (
                jugadores[sala][otro_jugador]["mano"],
                jugadores[sala][id_jugador]["mano"]
            )
           
            # Emitir un evento para notificar el intercambio
            emit("mensaje_cambioBaraja", {
                "jugador1": id_jugador,
                "jugador2": otro_jugador
            }, room=sala)

            # Emitir las manos actualizadas a los jugadores afectados
            emit("actualizar_mano", {
                "id": id_jugador,
                "cartas": jugadores[sala][id_jugador]["mano"]
            }, room=jugadores[sala][id_jugador]["sid"])
            
            emit("actualizar_mano", {
                "id": otro_jugador,
                "cartas": jugadores[sala][otro_jugador]["mano"]
            }, room=jugadores[sala][otro_jugador]["sid"])
            emit("cartas_repartidas", {"jugadores": jugadores[sala]}, room=sala)

            carta_inicial_salas[sala] = carta_seleccionada
            emit("carta_actualizada", {"carta": carta_seleccionada}, room=sala)
            estado_actual = {
                "turno": turno_actual[sala],
                "nueva_carta":carta_inicial_salas[sala],
                "jugadores": jugadores[sala],
                "juegoActivo": True  # El juego sigue activo
            }

            emit("estado_actualizado", estado_actual, room=sala)
            emit("elegir_color", {"id": id_jugador, "sala": sala, "valor":valor}, room=request.sid) 
            return
        
        
        # Manejar "cambio de sentido"
        if valor == "cambioSentido":
                ids_jugadores = list(jugadores[sala].keys())
                
                if len(ids_jugadores) == 2:  # Si solo hay 2 jugadores, el cambio de sentido no afecta el flujo
                    # En el caso de 2 jugadores, solo se invierte el turno entre ellos, que es lo mismo que seguir el flujo normal
                    siguiente_jugador = id_jugador
                else:
                    ids_jugadores.reverse()  # Invertir el orden de los jugadores si hay más de 2
                    jugadores[sala] = {id: jugadores[sala][id] for id in ids_jugadores}  # Actualizar el orden de los jugadores
                    siguiente_jugador = ids_jugadores[(ids_jugadores.index(id_jugador) + 1) % len(ids_jugadores)]  # Obtener el siguiente jugador según el nuevo orden

                turno_actual[sala] = siguiente_jugador
                emit("sentido_cambiado", {"nuevo_sentido": list(jugadores[sala].keys())}, room=sala)
                carta_inicial_salas[sala] = carta_seleccionada
                emit("carta_actualizada", {"carta": carta_seleccionada}, room=sala)
                estado_actual = {
                    "turno": turno_actual[sala],
                    "nueva_carta": carta_inicial_salas[sala],
                    "jugadores": jugadores[sala],
                    "juegoActivo": True  # El juego sigue activo
                }
                emit("estado_actualizado", estado_actual, room=sala)
                return

        # Manejar "prohibido"
        if valor == "prohibido":
                ids_jugadores = list(jugadores[sala].keys())
                turno_index = ids_jugadores.index(id_jugador)
                
                if len(ids_jugadores) == 2:  # Si solo hay 2 jugadores, el turno vuelve al jugador que jugó "prohibido"
                    siguiente_jugador = id_jugador  # El turno sigue siendo del jugador que jugó la carta
                else:
                    siguiente_jugador = ids_jugadores[(turno_index + 2) % len(ids_jugadores)]  # Saltar un jugador

                turno_actual[sala] = siguiente_jugador
                emit("jugador_saltado", {"id_saltado": ids_jugadores[(turno_index + 1) % len(ids_jugadores)]}, room=sala)
                carta_inicial_salas[sala] = carta_seleccionada
                emit("carta_actualizada", {"carta": carta_seleccionada}, room=sala)
                estado_actual = {
                    "turno": turno_actual[sala],
                    "nueva_carta": carta_inicial_salas[sala],
                    "jugadores": jugadores[sala],
                    "juegoActivo": True  # El juego sigue activo
                }   
                emit("estado_actualizado", estado_actual, room=sala)
                return
            
        if valor == "+2":
            ids_jugadores = list(jugadores[sala].keys())
            turno_index = ids_jugadores.index(id_jugador)
            siguiente_jugador = ids_jugadores[(turno_index + 1) % len(ids_jugadores)]

            # Emitir un evento al cliente para que llame a robar carta por cada una
            for _ in range(2):
                emit("robar_carta_cliente", {"id": siguiente_jugador, "sala": sala}, room=sala)
            emit("mensajes_carta+2", {"id": siguiente_jugador, "sala": sala, "color": color}, room=sala)
        
        if valor in ["+4", "cambioColor"]:  # Solo para cartas que requieren elección de color
                emit("elegir_color", {"id": id_jugador, "sala": sala, "valor":valor}, room=request.sid)
                return  # Esperamos hasta que el jugador elija el color

        carta_inicial_salas[sala] = carta_seleccionada
        emit("carta_actualizada", {"carta": carta_seleccionada}, room=sala)
        actualizar_turno(sala, id_jugador)



def actualizar_turno(sala,id_jugador):
    # Actualizar el turno actual al siguiente jugador
    
    if id_jugador not in jugadores[sala]:
        print(f"jugador {id_jugador} ya no esta en la sala")
        return
    
    ids_jugadores = list(jugadores[sala].keys())
    turno_index = ids_jugadores.index(id_jugador)
    siguiente_jugador = ids_jugadores[(turno_index + 1) % len(ids_jugadores)]
    turno_actual[sala] = siguiente_jugador

    # Emitir el estado actualizado a todos los jugadores de la sala
    estado_actual = {
        "turno": turno_actual[sala],
        "nueva_carta":carta_inicial_salas[sala],
        "jugadores": jugadores[sala],
        "juegoActivo": True  # El juego sigue activo
    }

    emit("estado_actualizado", estado_actual, room=sala)
    
    
@socketio.on("color_elegido")
def color_elegido(datos):
    id_jugador = datos["id"]
    sala = datos["sala"]
    valor = datos["valor"]
    color_elegido = datos["color"]

    if not sala or not id_jugador or not color_elegido:
        return


    carta_inicial_salas[sala] = {"Color": color_elegido, "valor": "cambioColor"}
    
    # Emitimos el cambio a todos
    emit("color_asignado", {"id": id_jugador, "sala": sala, "color": color_elegido}, room=sala)
    
    if valor == "+4":
        ids_jugadores = list(jugadores[sala].keys())
        turno_index = ids_jugadores.index(id_jugador)
        siguiente_jugador = ids_jugadores[(turno_index + 1) % len(ids_jugadores)]

        # Emitir un evento al cliente para que llame a robar carta por cada una
        for _ in range(4):
            emit("robar_carta_cliente", {"id": siguiente_jugador, "sala": sala}, room=sala)
        emit("mensajes_carta+4", {"id": siguiente_jugador, "sala": sala, "color": color_elegido}, room=sala)
    else:
        emit("mensajes_cartaCambioColor", {"id": id_jugador, "sala": sala, "color": color_elegido}, room=sala)
   
    # Pasar el turno al siguiente jugador
    actualizar_turno(sala, id_jugador)


@socketio.on("solicitar_color")
def solicitar_color(datos):
    id_jugador = datos["id"]
    sala = datos["sala"]

    emit("elegir_color", {"id": id_jugador, "sala": sala}, room=request.sid)



@socketio.on("pasar_turno")
def pasar_turno(datos):
    sala = datos["sala"]
    id_jugador = str(datos["id"])
    
    # Verificar que la sala y el jugador existen
    if sala not in jugadores:
        print(f"Error: la sala {sala} no existe.")
        return

    if id_jugador not in jugadores[sala]:
        print(f"Error: el jugador {id_jugador} no existe en la sala {sala}.")
        return
    
    actualizar_turno(sala,id_jugador)
    



@socketio.on("robar_carta")
def robar_Carta(datos):
    sala = datos["sala"]
    id_jugador = str(datos["id"])
    
    #salir si no existe la sala o el jugador
    if sala not in jugadores or id_jugador not in jugadores[sala]:
        return
    #si hay cartas en el mazo/baraja, se roba una y se le da al jugador
    mazo = barajas[sala]
    if len(mazo) > 0 :    
        carta_robada = mazo.pop()
        jugadores[sala][id_jugador]["mano"].append(carta_robada)
        
        emit("cartas_robadas",{
            "id":id_jugador,"carta_robada": carta_robada,"mano":jugadores[sala][id_jugador]["mano"]},room=sala)
        
        emit("estado_actualizado", {
            "turno": turno_actual[sala],"jugadores": jugadores[sala],"juegoActivo": True,"nueva_carta":carta_inicial_salas[sala]}, room=sala)
    else:
        emit("error", {"mensaje": "El mazo está vacío. No puedes robar más cartas."}, room=request.sid)


@socketio.on("solicitar_salas")
def solicitar_salas():
    lista = []
    for sala in jugadores:
        jugadores_en_sala = [{"id": id_jugador, "nombre": jugadores[sala][id_jugador]["nombre"]} for id_jugador in jugadores[sala]]
        lista.append({
            "nombre": sala,
            "jugadores": len(jugadores[sala]),
            "activa": salas_activas.get(sala, False),
            "jugadores_en_sala": jugadores_en_sala  
        })
    emit("lista_salas", lista, room=request.sid)


@socketio.on("obtener_orden_turnos")
def obtener_orden_turnos(datos):
    sala = datos.get("sala")
    if not sala or sala not in jugadores:
        emit("error", {"mensaje": "Sala no encontrada o inválida."}, room=request.sid)
        return

    turno = turno_actual.get(sala, "")
    emit("orden_turnos", {
        "jugadores": jugadores[sala],
        "turno": turno
    }, room=request.sid)


@socketio.on("cambiar_id")
def cambiar_id(datos):
    id_actual = str(datos.get("id_actual"))
    nuevo_id = str(datos.get("nuevo_id"))

    if not id_actual or not nuevo_id:
        emit("error", {"mensaje": "Datos inválidos para cambiar el ID."}, room=request.sid)
        return

    # Check if the new ID is already in use in any room
    for sala, jugadores_sala in jugadores.items():
        if nuevo_id in jugadores_sala:
            emit("error", {"mensaje": "El nuevo ID ya está en uso en una sala."}, room=request.sid)
            return

    # Update the ID in the global mapping if the player is in a room
    sala = jugador_a_sala.pop(id_actual, None)
    if sala:
        jugadores[sala][nuevo_id] = jugadores[sala].pop(id_actual)
        jugadores[sala][nuevo_id]["sid"] = request.sid
        jugador_a_sala[nuevo_id] = sala

        # Update the host if necessary
        if sala_host[sala] == id_actual:
            sala_host[sala] = nuevo_id

        # Update the turn if necessary
        if turno_actual[sala] == id_actual:
            turno_actual[sala] = nuevo_id

    emit("id_cambiado", {"id_actual": id_actual, "nuevo_id": nuevo_id}, room=request.sid)
    
    emit("mostrar_comenzar", {
            "host": sala_host[sala],
            "jugadores": list(jugadores[sala].values())
        }, room=sala)



if __name__ == "__main__":
    socketio.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
