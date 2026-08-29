# Scrabble multijugador — Descripción del proyecto

**Materia:** Computación II — Universidad de Mendoza  
**Alumno:** Camila Portal  
**Proyecto:** Scrabble multijugador y multi-sala

---

## 1. Descripción del sistema

Quiero armar una aplicación cliente-servidor por terminal para jugar al scrabble en red con soporte **multijugador y multi-sala**. En este sistema, múltiples jugadores podrán conectarse desde sus terminales a un servidor central. El servidor los agrupará en salas de juego dinámicas (de 2 a 4 jugadores) y permitirá disputar varias partidas independientes y simultáneas en tiempo real sobre tableros individuales.

### Flujo general:

1. **Arranque e interfaz por consola (`argparse`):**
   - El **servidor** se inicia mediante terminal indicando los parámetros de red: puerto de escucha, capacidad máxima por sala (por defecto 4) y tiempo límite por turno.
   - El **cliente** se inicia desde la terminal indicando la dirección IP/Host del servidor, el puerto y el nombre o alias del jugador.

2. **Conexión en red y sockets:**
   - El cliente establece una conexión de socket TCP (`SOCK_STREAM`) con el servidor.
   - El servidor escucha y acepta múltiples clientes de forma simultánea.

3. **Gestión de salas dinámicas e inicio flexible:**
   - Cada sala admite entre **2 y 4 jugadores**.
   - Si la sala actual se llena (4/4), la partida inicia de inmediato y los nuevos jugadores que se conecten son asignados automáticamente a una nueva sala (`Sala 2`, `Sala 3`, etc.).
   - Si en una sala entran al menos **2 jugadores** (el mínimo para jugar), se activa una **cuenta regresiva de 30 segundos**. Si la sala no se llena antes de que venza el tiempo (o si los jugadores eligen iniciar voluntariamente), la partida arranca automáticamente con los jugadores presentes (2 o 3 jugadores).

4. **Manejo asincrónico de la red (`asyncio`):**
   - **Atención a varios jugadores y salas a la vez:** El servidor atiende a todos los clientes de todas las salas conectadas en paralelo sin bloquearse y optimizando el uso de memoria.
   - **Límite de tiempo por turno (*Timeout*):** Si a un jugador le toca jugar y pasan 60 segundos sin realizar una acción, el servidor le pasa el turno automáticamente para no trabar la partida.
   - **Actualización en pantalla para los integrantes de la sala:** Cada vez que un jugador realiza una jugada o pasa el turno, el servidor retransmite el tablero actualizado y los puntajes exclusivamente a los participantes de esa sala.

5. **Separación de procesos por sala y comunicación IPC (`multiprocessing.Queue`):**
   - **Aislamiento de partidas en núcleos distintos:** Cada sala de juego activa es administrada por un proceso independiente. Esto permite aprovechar procesadores multi-core y garantiza que si una partida finaliza o sufre un error, las demás salas sigan funcionando sin interrupciones.
   - **Comunicación por sala:** La comunicación entre la red y el motor de cada sala se realiza mediante una cola en memoria (`multiprocessing.Queue`), procesando las acciones en orden de llegada y evitando condiciones de carrera.

6. **Cola de tareas distribuidas (`Celery` + `Redis`):**
   - **Validación de palabras en segundo plano:** Cuando un jugador coloca una palabra, la verificación de validez contra el diccionario local y el cálculo de puntos con multiplicadores se delega a un **Worker de Celery** mediante el broker **Redis**.
   - El worker carga el diccionario en memoria RAM al iniciar para búsquedas instantáneas y opera 100% offline, atendiendo solicitudes de todas las salas en paralelo.

7. **Persistencia de datos (Contenedor de base de datos):**
   - Al concluir cada partida, se guardan automáticamente los resultados (sala, ganador, participantes, puntajes, fecha y duración) en un contenedor dedicado de base de datos relacional conectado por red interna.
   - Permite consultar una tabla histórica de posiciones y mejores puntuaciones (*Ranking*).

8. **Despliegue con Docker Compose (4 Servicios):**
   - Todo el entorno backend se orquesta mediante **Docker Compose** en 4 contenedores independientes:
     1. `server`: Servidor TCP, gestión de salas y subprocesos IPC de juego.
     2. `redis`: Broker de mensajería en memoria.
     3. `worker`: Worker de Celery con diccionario local.
     4. `db`: Contenedor de Base de Datos para persistencia de partidas.
