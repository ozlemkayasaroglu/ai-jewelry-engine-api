# Python 3.11.9 resmi image
FROM python:3.11.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create directories for uploads and outputs
RUN mkdir -p uploads outputs

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
