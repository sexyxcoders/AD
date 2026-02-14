
## 🐳 `docker-compose.yml`
```yaml
version: '3.8'

services:
  bot:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: adimyze-bot
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data/user_states:/app/user_states
      - ./logs:/app/logs
      - ./config.ini:/app/config.ini:ro
    depends_on:
      - mongodb
    networks:
      - adimyze-network
    healthcheck:
      test: ["CMD", "python", "-c", "import sys; sys.exit(0)"]
      interval: 30s
      timeout: 10s
      retries: 3

  mongodb:
    image: mongo:6.0
    container_name: adimyze-mongodb
    restart: unless-stopped
    environment:
      MONGO_INITDB_ROOT_USERNAME: ${MONGO_USER:-admin}
      MONGO_INITDB_ROOT_PASSWORD: ${MONGO_PASSWORD:-changeme}
      MONGO_INITDB_DATABASE: adimyze_db
    volumes:
      - ./data/mongodb:/data/db
      - ./data/mongodb-backups:/backups
    ports:
      - "27017:27017"
    networks:
      - adimyze-network
    healthcheck:
      test: echo 'db.runCommand("ping").ok' | mongosh localhost:27017/test --quiet
      interval: 10s
      timeout: 5s
      retries: 5

  mongo-express:
    image: mongo-express:1.0
    container_name: adimyze-mongo-express
    restart: unless-stopped
    environment:
      ME_CONFIG_MONGODB_ADMINUSERNAME: ${MONGO_USER:-admin}
      ME_CONFIG_MONGODB_ADMINPASSWORD: ${MONGO_PASSWORD:-changeme}
      ME_CONFIG_MONGODB_SERVER: mongodb
      ME_CONFIG_BASICAUTH_USERNAME: admin
      ME_CONFIG_BASICAUTH_PASSWORD: ${MONGO_EXPRESS_PASSWORD:-changeme}
    ports:
      - "8081:8081"
    depends_on:
      - mongodb
    networks:
      - adimyze-network

networks:
  adimyze-network:
    driver: bridge

volumes:
  mongodb_
  user_states: