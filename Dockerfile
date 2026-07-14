FROM node:22-slim AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ENV NEXT_PUBLIC_API_URL=/api
RUN pnpm build

FROM node:22-slim AS runtime
WORKDIR /app
RUN corepack enable
COPY --from=build /app ./
ENV NODE_ENV=production
EXPOSE 3000
CMD ["pnpm", "start"]
