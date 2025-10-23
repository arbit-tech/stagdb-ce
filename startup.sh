#!/bin/bash

echo "Starting StagDB..."

# Ensure data directory exists with proper permissions
mkdir -p /app/data
chmod 755 /app/data

# Generate migrations for any model changes
echo "Generating migrations..."
python manage.py makemigrations

# Run migrations
echo "Running migrations..."
python manage.py migrate

# Create superuser
echo "Creating superuser..."
python manage.py create_superuser

# Start Django server
echo "Starting Django server..."
python manage.py runserver 0.0.0.0:8000