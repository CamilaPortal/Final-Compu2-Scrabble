# Guía de instalación y despliegue

**Materia:** Computación II — Universidad de Mendoza  
**Alumna:** Camila Portal  
**Proyecto:** Scrabble multijugador y multi-sala en Red  

---

Este documento detalla los pasos necesarios para instalar, configurar y desplegar el sistema de Scrabble en red, tanto mediante **contenedores Docker (método recomendado)** como en **modo local**.

---

## 1. Requisitos previos del sistema

- **Sistema operativo:** Linux.
- **Python:** Versión 3.10 o superior (el entorno contenerizado utiliza Python 3.12).
- **Docker Engine:** Versión 24.0 o superior.
- **Docker Compose:** Versión v2 o superior (probado con Docker Compose v5.5.1).
- **Git:** Para control de versiones y clonación.

---

## 2. Clonación del repositorio

Abrir una terminal y clonar el repositorio:

```bash
git clone https://github.com/tu-usuario/Final-Compu2-Scrabble.git
cd Final-Compu2-Scrabble
```

---

## 3. Método 1: Despliegue con Docker Compose (Recomendado)

Este método levanta el backend completo (Base de datos PostgreSQL, Broker Redis, Worker Celery y Servidor TCP) de forma aislada y automatizada.

### Paso 1: Construir y levantar los contenedores
Ejecutar desde la raíz del proyecto:
```bash
docker compose up -d --build
```

### Paso 2: Verificar el estado de los servicios
Comprobar que los 4 contenedores estén corriendo:
```bash
docker compose ps
```
Debe visualizarse una salida similar a:
```text
NAME              IMAGE                          STATUS                   PORTS
scrabble_db       postgres:15-alpine             Up (healthy)             5432/tcp
scrabble_redis    redis:7-alpine                 Up (healthy)             6379/tcp
scrabble_server   final-compu2-scrabble-server   Up                       0.0.0.0:5000->5000/tcp
scrabble_worker   final-compu2-scrabble-worker   Up                       5000/tcp
```

### Paso 3: Conectar los clientes de juego
Desde una o más terminales del host, ejecutar:
```bash
python3 -m client.client --port 5000
```
*(Para jugar una partida completa, abrir al menos 2 terminales simultáneas para representar a 2 jugadores distintos).*

### Comandos útiles de administración con Docker:
- **Ver logs en tiempo real:**
  ```bash
  docker compose logs -f server
  docker compose logs -f worker
  ```
- **Inspeccionar procesos del servidor:**
  ```bash
  docker compose exec server ps -ef
  ```
- **Detener los servicios (conservando los datos):**
  ```bash
  docker compose down
  ```
- **Detener y vaciar la base de datos (reinicio total desde cero):**
  ```bash
  docker compose down -v
  ```

---

## 4. Método 2: Despliegue local (sin Docker)

Si se desea ejecutar el sistema directamente sobre la máquina local para desarrollo o depuración paso a paso:

### Paso 1: Crear y activar un entorno virtual
```bash
python3 -m venv venv
source venv/bin/activate
```

### Paso 2: Instalar dependencias del proyecto
```bash
pip install -r requirements.txt
pip install -e .
```

### Paso 3: Iniciar el servicio de Redis
Asegurarse de tener Redis instalado y en ejecución en el sistema local:
```bash
sudo systemctl start redis
```

### Paso 4: Iniciar el worker de Celery
En una terminal con el entorno virtual activo:
```bash
celery -A tasks.celery_app worker --loglevel=info
```

### Paso 5: Iniciar el servidor TCP
En otra terminal con el entorno virtual activo:
```bash
python3 -m server.server --host 0.0.0.0 --port 5000
```
*(En modo local, si no se especifica `DATABASE_URL`, el servidor utilizará automáticamente SQLite generando el archivo local `scrabble.db`).*

### Paso 6: Conectar clientes
En terminales adicionales:
```bash
python3 -m client.client --host 127.0.0.1 --port 5000
```

---

## 5. Variables de entorno soportadas

El sistema permite configurar sus puntos de conexión mediante variables de entorno:

| Variable | Descripción | Valor por defecto (Local) | Valor en Docker Compose |
| :--- | :--- | :--- | :--- |
| **`DATABASE_URL`** | Cadena de conexión para SQLAlchemy. | `sqlite:///scrabble.db` | `postgresql://scrabble_user:scrabble_password@db:5432/scrabble_db` |
| **`REDIS_URL`** | URL del broker de mensajería y backend de Celery. | `redis://localhost:6379/0` | `redis://redis:6379/0` |
