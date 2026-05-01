FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
ARG VITE_APP_ORIGIN=https://meetqapp.com
ARG VITE_API_BASE_URL=https://api.meetqapp.com
ARG VITE_WS_BASE_URL=wss://api.meetqapp.com
ARG VITE_LIVEKIT_WS_URL=wss://rtc.meetqapp.com
ENV VITE_APP_ORIGIN=${VITE_APP_ORIGIN}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ENV VITE_WS_BASE_URL=${VITE_WS_BASE_URL}
ENV VITE_LIVEKIT_WS_URL=${VITE_LIVEKIT_WS_URL}
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
