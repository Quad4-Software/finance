# syntax=docker/dockerfile:1
# Quad4 Finance frontend - multi-stage Chainguard build.
# Build on the node dev image, serve the static bundle from the minimal
# Chainguard nginx image: no shell, no package manager, nginx user, port 8080.

FROM cgr.dev/chainguard/node:latest-dev AS build

WORKDIR /app

ARG VITE_APP_VERSION
ENV VITE_APP_VERSION=$VITE_APP_VERSION

COPY package.json package-lock.json .npmrc ./
RUN npm ci

COPY . .
RUN npm run build

FROM cgr.dev/chainguard/nginx:latest

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
