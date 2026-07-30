FROM eclipse-mosquitto:2.1.2-alpine

USER root
RUN apk add --no-cache python3

WORKDIR /app
COPY app.py .

EXPOSE 8080
CMD ["python3", "-u", "app.py"]
