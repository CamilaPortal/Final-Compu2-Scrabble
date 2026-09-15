# Justificación técnica y decisiones de diseño

**Materia:** Computación II — Universidad de Mendoza  
**Alumna:** Camila Portal  
**Proyecto:** Scrabble multijugador y multi-sala en red  

---

Este documento fundamenta las decisiones de diseño e ingeniería de software que se tomaron en el desarrollo de la aplicación, relacionando cada solución técnica con los conceptos teóricos evaluados en la materia.

---

## 1. Argumentos por línea de comandos (`argparse`)

### Marco teórico:
En aplicaciones cliente-servidor para Linux, no se deben hardcodear direcciones IP ni puertos en el código. La configuración debe recibirse desde la consola a través del vector de argumentos del proceso (`sys.argv`), garantizando flexibilidad para ejecutar la aplicación en diferentes máquinas y entornos de red sin modificar los archivos fuente.

### Decisión de diseño:
En `app/server/server.py` y `app/client/client.py` se utiliza `argparse` para:
- Configurar de forma flexible el host, el puerto y las credenciales desde la terminal.
- Validar que los argumentos cumplan con los tipos esperados (enteros para los puertos).
- Disponer de un menú de ayuda en consola ejecutando `-h` o `--help`.

---

## 2. Aislamiento por procesos y mecanismos de IPC (`multiprocessing.Queue`)

### Marco teórico (Sistemas operativos):
Cada proceso en Linux posee su propio espacio de memoria virtual protegido por la Unidad de Manejo de Memoria (MMU) del procesador. A diferencia de los hilos (*threads*), los procesos no comparten memoria de manera implícita. Además, en la implementación estándar de CPython, el **GIL (*Global Interpreter Lock*)** impide que múltiples hilos ejecuten código de Python en núcleos de CPU físicos de manera simultánea.

### Decisiones de diseño:

#### A. Procesos independientes por sala (`RoomProcess`):
En lugar de manejar las salas de juego mediante hilos, cada sala activa se lanza en un **proceso hijo dedicado del sistema operativo** (`app/server/server.py`):
1. **Aislamiento y tolerancia a fallos:** Si una partida sufre una excepción no controlada o finaliza abruptamente, el proceso padre (servidor) y las demás salas continúan ejecutándose sin interrupciones.
2. **Paralelismo real multi-core:** Cada proceso de sala ejecuta su propio intérprete de Python en núcleos de procesamiento independientes, superando la limitación del GIL.

#### B. Contexto de arranque `spawn`:
Se configuró explícitamente `multiprocessing.get_context("spawn")`. A diferencia del método `fork()` tradicional de Linux, `spawn` arranca un intérprete de Python limpio y nuevo desde cero, garantizando estabilidad absoluta.

#### C. Comunicación inter-proceso con `multiprocessing.Queue`:
Para comunicar el proceso padre (servidor de sockets) con el proceso hijo (motor de sala):
- Se utilizan dos colas seguras por sala: `action_queue` (padre -> hijo) y `event_queue` (hijo -> padre).
- `multiprocessing.Queue` implementa una estructura FIFO (*First-In, First-Out*) atómica y segura contra condiciones de carrera.
- El servidor lee de estas colas mediante `asyncio.to_thread(event_queue.get, timeout=0.2)`, evitando bloquear el bucle de eventos principal.

---

## 3. Sockets concurrentes y asincronismo de E/S (`asyncio`)

### Marco teórico (redes y multiplexación de E/S):
En un servidor de red, la mayor parte del tiempo se pierde esperando operaciones de Entrada/Salida. El modelo tradicional bloqueante "un hilo por cliente" genera un alto consumo de memoria RAM y degradación de rendimiento por la sobrecarga del cambio de contexto.

### Decisión de diseño:
Para evitar la sobrecarga de crear un hilo por cada cliente, el servidor utiliza `asyncio`:
- **Atención simultánea sin bloqueos:** Mediante `asyncio.start_server`, el servidor atiende a múltiples clientes en un solo hilo. Cuando un socket no tiene datos para leer, el servidor no se frena y sigue atendiendo a los demás jugadores.
- **Bajo consumo de recursos:** Al apoyarse en el mecanismo `epoll` de Linux, puede sostener decenas de conexiones concurrentes consumiendo poca memoria.
- **Gestión de tiempos:** Implementa temporizadores asincrónicos para la cuenta regresiva de las salas (30 segundos) y el vencimiento de turnos por inactividad (60 segundos) sin congelar la partida.

---

## 4. Cola de tareas distribuidas (Celery + Redis)

### Marco teórico (Sistemas distribuidos):
Si el servidor realizara búsquedas complejas en un diccionario de miles de palabras dentro de su Event Loop, la atención de los sockets TCP se congelaría momentáneamente para todos los demás jugadores.

### Decisión de diseño:
Se implementó el **patrón productor-consumidor desacoplado**:
1. **Productor:** Cuando una sala necesita validar una palabra, no busca en disco ni procesa cadenas localmente; encola un mensaje ligero en Redis mediante Celery (`app/game/dictionary.py`).
2. **Broker (Redis):** Actúa como intermediario de almacenamiento en memoria RAM de alta velocidad, enrutando tareas entre contenedores.
3. **Consumidor (Worker de Celery):** Corre en un contenedor dedicado (`app/tasks/word_tasks.py`). Al arrancar, carga el archivo `dictionary.txt` en un conjunto en memoria RAM, logrando verificaciones ortográficas instantáneas.
4. **Pool Prefork:** Celery genera automáticamente un pool de procesos trabajadores según los núcleos de CPU de la máquina host, permitiendo procesar validaciones de múltiples salas en paralelo real.

---

## 5. Persistencia relacional y base de datos

### Marco Teórico:
Para que los usuarios registrados, el historial de partidas y las estadísticas de juego no se pierdan al reiniciar el servidor, se utiliza una base de datos relacional. El modelo relacional permite estructurar los datos mediante tablas vinculadas, garantizando integridad referencial y facilitando consultas como el cálculo del ranking de jugadores.

### Decisiones de Diseño:

#### A. Modelado con SQLAlchemy:
Se definieron modelos en `app/database/models.py` para representar las entidades del juego:
- `User`: Almacena la cuenta del jugador con su contraseña protegida mediante hash y salt aleatoria.
- `Game`: Registra cada partida finalizada (número de sala, fecha y hora de inicio y fin, y duración en segundos).
- `GamePlayer`: Tabla de relación que vincula a cada jugador con la partida jugada, guardando su puntaje final y si resultó ganador.

#### B. Generación de Ranking Histórico:
En `app/database/repository.py`, el servidor realiza consultas agregadas sobre la base de datos para calcular la tabla de posiciones histórica, ordenando a los jugadores por cantidad de partidas ganadas y puntaje acumulado.

#### C. Soporte de Motores:
Por el uso de SQLAlchemy, el sistema soporta de forma transparente tanto **PostgreSQL 15** (en el entorno Docker con volumen persistente) como **SQLite** (`scrabble.db` en modo local), seleccionando el motor automáticamente según la variable de entorno `DATABASE_URL`.

---

## 6. Contenedores con Docker y Docker Compose

### Marco teórico (virtualización a nivel de sistema operativo):
Docker aprovecha las funcionalidades del Kernel de Linux para empaquetar aplicaciones y sus dependencias de forma aislada.

### Decisiones de diseño:
1. **Separación de responsabilidades en 4 microservicios:**
   - `server`: Servidor TCP, gestión de lobby dinámico y subprocesos IPC de juego.
   - `worker`: Celery worker con diccionario en RAM.
   - `redis`: Broker en memoria.
   - `db`: PostgreSQL 15 con volumen dedicado `postgres_data`.
2. **Red privada bridge (`scrabble_network`):** Todos los servicios se comunican mediante interfaces virtuales privadas y resolución DNS interna. Los puertos de Redis (6379) y PostgreSQL (5432) permanecen ocultos; únicamente el puerto TCP 5000 del servidor se expone hacia el host.
3. **Seguridad con usuario sin privilegios (`appuser`):** Siguiendo el principio de menor privilegio, las imágenes no se ejecutan como `root`, previniendo posibles escaladas hacia el host.
4. **Orquestación con comprobaciones de salud (*healthchecks*):** El servidor y los workers verifican que `redis` y `db` respondan satisfactoriamente a `pg_isready` y `redis-cli ping` antes de iniciar, garantizando un ciclo de vida sin condiciones de carrera durante el arranque.
