# Mejoras futuras

**Materia:** Computación II — Universidad de Mendoza  
**Alumna:** Camila Portal  
**Proyecto:** Scrabble multijugador y multi-sala en red  

---

Este documento detalla las mejoras y ampliaciones planificadas como evolución futura del sistema:

---

## 1. Persistencia de estado de partida activa (Guardar y reanudar)

- **Situación actual:** La base de datos almacena los resultados definitivos de las partidas al finalizar (`save_finished_game`). Si el servidor se apaga de repente a mitad de una partida, el estado del tablero en curso se pierde.
- **Mejora planificada:**
  - Serializar el estado intermedio de la partida (tablero de 15x15, atril de cada jugador, fichas restantes en la bolsa y turno activo) en PostgreSQL o en Redis tras cada jugada válida.
  - Implementar un mecanismo de reconexión: si un jugador pierde la conexión de red, dispone de una ventana de gracia (por ejemplo, 120 segundos) para reconectarse con sus credenciales y reincorporarse a su partida en curso sin perder su posición ni sus fichas.

---

## 2. Salas privadas

- **Salas privadas con contraseña:** Permitir que un jugador cree una sala con código de acceso privado para jugar exclusivamente con amigos.

---

## 3. Observabilidad y métricas en tiempo real

- **Métricas con Prometheus:**
  - Conexiones concurrentes activas en el servidor TCP.
  - Cantidad de salas de juego simultáneas.
  - Tiempo de respuesta de las tareas de validación de palabras de Celery en Redis.
  - Tasa de aciertos y errores de palabras enviadas por los jugadores.
- **Tableros en Grafana:** Paneles visuales para supervisar el consumo de CPU, memoria de los contenedores de Docker y tráfico de red en vivo.
