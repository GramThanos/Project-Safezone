# Build stage
FROM node:18-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY public ./public
COPY src ./src
# Keep the webpack runtime as a file instead of letting CRA inline it into
# index.html. An inline <script> would force `script-src 'unsafe-inline'` in the
# Content-Security-Policy that nginx.conf sets, which would defeat most of the
# point of having one.
ENV INLINE_RUNTIME_CHUNK=false
RUN npm run build


# Production stage
FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
