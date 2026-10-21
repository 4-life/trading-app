FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
# The public domain, allowed to post actions (react-router.config.ts); empty locally.
ARG DOMAIN=""
ENV DOMAIN=$DOMAIN
RUN npm run build

FROM node:22-slim
WORKDIR /app
COPY --from=build /app/build ./build
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
# The node image's unprivileged user, not root.
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
