FROM python:3.11-slim

WORKDIR /app

COPY API/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY API/ .

EXPOSE 5000

CMD ["python", "-u", "app.py"]