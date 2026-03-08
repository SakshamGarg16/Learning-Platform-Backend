# Use official lightweight Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PORT 8000

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . /app/

# Static files for production (requires whitenoise in requirements.txt)
# (Warning: Ensure STATIC_ROOT is set in settings.py)

# Run with Gunicorn
CMD gunicorn REMLearners_Backend.wsgi:application --bind 0.0.0.0:$PORT --workers 3
