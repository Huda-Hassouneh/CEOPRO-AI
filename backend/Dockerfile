# Build from the project root: docker build -f backend/Dockerfile .
FROM node:24-bookworm-slim AS build
WORKDIR /app/backend
COPY backend/package*.json ./
RUN npm ci
COPY backend/ ./
RUN npm run build

FROM node:24-bookworm-slim
WORKDIR /app/backend
COPY --from=build /app/backend/package*.json ./
COPY --from=build /app/backend/node_modules ./node_modules
COPY --from=build /app/backend/dist ./dist
COPY --from=build /app/backend/scripts ./scripts
# Application API and ingestion/notification workers do not require Python.
# Run the market dispatcher on a host with the configured ai/ checkout and Python environment.
USER node
EXPOSE 5000
CMD ["node", "dist/server.js"]
