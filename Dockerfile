FROM node:24.22.3-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js tailwind.config.cjs postcss.config.js ./
COPY src ./src
COPY public ./public
# These three values are PUBLIC browser configuration, embedded by Vite.
# Never add backend secrets or service-role keys here.
ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ARG VITE_DEFAULT_INFERENCE_ENGINE=local
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
RUN node -e "const e=process.env; if(!e.VITE_SUPABASE_URL || !e.VITE_SUPABASE_ANON_KEY) throw Error('Public Supabase configuration is required'); const k=e.VITE_SUPABASE_ANON_KEY; if(k.startsWith('sb_secret_')) throw Error('Private key forbidden'); if(k.split('.').length===3 && JSON.parse(Buffer.from(k.split('.')[1], 'base64url')).role!=='anon') throw Error('Only an anon JWT is allowed');" \
    && npm run build

FROM nginx:1.30.8-alpine AS runtime
RUN apk upgrade --no-cache
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
