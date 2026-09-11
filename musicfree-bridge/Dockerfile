FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY bridge.js ./
ENV PLUGINS_DIR=/plugins
ENV DATA_DIR=/data
ENV PORT=5001
EXPOSE 5001
CMD ["node", "bridge.js"]
