# Build stage
FROM node:22-alpine AS build
WORKDIR /app
# Dependencies first, so a change to the code does not reinstall them. `npm ci`
# installs exactly what package-lock.json pins; the cache mount keeps npm's
# downloads between builds, so even a changed lock file is mostly a local copy.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY index.html vite.config.js ./
COPY public ./public
COPY src ./src
# Vite emits every script as a file and never inlines one into index.html, which
# is what lets the Content-Security-Policy in nginx.conf refuse inline script.
RUN npm run build


# Production stage
FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
