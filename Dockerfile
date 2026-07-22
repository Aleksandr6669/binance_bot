FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libomp-dev \
    && rm -rf /var/lib/apt/lists/*

# Set up a new user named "user" with UID 1000
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

# Copy requirements and install
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY --chown=user . .

# Set environment variables for production
ENV HOST=0.0.0.0
ENV PORT=7860
ENV FLASK_DEBUG=False

# Hugging Face Spaces expose port 7860 by default
EXPOSE 7860

# Run the app
CMD ["python", "app.py"]
