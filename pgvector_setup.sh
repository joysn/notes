#!/bin/bash
# pgvector Lab Setup Script
# Run this first to set up the Postgres container with pgvector

set -e

CONTAINER_NAME="pgvector-lab"
DB_PASSWORD="vector123"
DB_NAME="vectordb"
HOST_PORT=5432

# Check if port is already in use
if lsof -i :${HOST_PORT} > /dev/null 2>&1; then
    echo "WARNING: Port ${HOST_PORT} is already in use."
    echo "Either stop the existing service or change HOST_PORT in this script."
    echo ""
    echo "To use a different port, edit HOST_PORT above (e.g., 5433)"
    echo "and update DB_PORT in pgvector_demo.py to match."
    exit 1
fi

# Remove old container if it exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Removing existing container '${CONTAINER_NAME}'..."
    docker rm -f ${CONTAINER_NAME}
fi

# Start Postgres with pgvector
echo "Starting PostgreSQL with pgvector..."
docker run -d \
    --name ${CONTAINER_NAME} \
    -e POSTGRES_PASSWORD=${DB_PASSWORD} \
    -e POSTGRES_DB=${DB_NAME} \
    -p ${HOST_PORT}:5432 \
    pgvector/pgvector:pg16

# Wait for Postgres to be ready
echo "Waiting for PostgreSQL to start..."
for i in {1..30}; do
    if docker exec ${CONTAINER_NAME} pg_isready -U postgres > /dev/null 2>&1; then
        echo "PostgreSQL is ready."
        break
    fi
    sleep 1
done

# Verify pgvector extension is available
echo ""
echo "Verifying pgvector..."
docker exec ${CONTAINER_NAME} psql -U postgres -d ${DB_NAME} -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"

echo ""
echo "============================================"
echo "  pgvector is running!"
echo "============================================"
echo "  Container:  ${CONTAINER_NAME}"
echo "  Host:       localhost:${HOST_PORT}"
echo "  Database:   ${DB_NAME}"
echo "  User:       postgres"
echo "  Password:   ${DB_PASSWORD}"
echo ""
echo "  Connect via psql:"
echo "    docker exec -it ${CONTAINER_NAME} psql -U postgres -d ${DB_NAME}"
echo ""
echo "  Install Python deps:"
echo "    pip install sentence-transformers psycopg2-binary"
echo ""
echo "  Run the demo:"
echo "    python pgvector_demo.py"
echo "============================================"
