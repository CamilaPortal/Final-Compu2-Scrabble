#!/bin/bash
# ==============================================================================
# Script de despliegue interactivo para Scrabble Server en Docker
# Materia: Computación II - Universidad de Mendoza
# ==============================================================================

set -e

echo "=================================================="
echo "   DESPLIEGUE DEL SISTEMA SCRABBLE EN RED"
echo "=================================================="

# Solicitar interactivamente la cantidad de workers de Celery a levantar
read -p "Cuantos contenedores de workers deseas levantar? [Por defecto: 1]: " WORKERS_INPUT

# Si el usuario presiona Enter sin escribir nada, asignar 1 por defecto
WORKERS=${WORKERS_INPUT:-1}

# Validar que sea un número entero positivo
if ! [[ "$WORKERS" =~ ^[1-9][0-9]*$ ]]; then
    echo "Entrada no valida ('$WORKERS_INPUT'). Se utilizara 1 worker por defecto."
    WORKERS=1
fi

echo ""
echo "Iniciando cluster con $WORKERS worker(s) de Celery..."
echo "Construyendo y levantando contenedores con Docker Compose..."
echo ""

docker compose up -d --build --scale worker="$WORKERS"

echo ""
echo "=================================================="
echo "  Cluster iniciado exitosamente"
echo "=================================================="
docker compose ps
