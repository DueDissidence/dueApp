# DEVELOPMENT IMAGE
FROM node:21-alpine AS dev

WORKDIR /frontend

ENV PATH=/frontend/node_modules/.bin:$PATH
ENV CHOKIDAR_USEPOLLING=true
ENV WATCHPACK_POLLING=true

COPY package.json ./
COPY package-lock.json ./
RUN npm ci

COPY . ./

EXPOSE 3000

CMD ["npm", "start"]


# PRODUCTION IMAGE
FROM node:21-alpine AS build

WORKDIR /frontend

ENV PATH=/frontend/node_modules/.bin:$PATH

COPY package.json ./
COPY package-lock.json ./
RUN npm ci

COPY . ./
RUN npm run build


# Stage 2: Serve the React application with Nginx
FROM nginx:1.25-alpine AS production

COPY --from=build /frontend/build /usr/share/nginx/html
COPY --from=build /frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]