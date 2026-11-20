#!/usr/bin/env bash
# Build the frontend for production and upload it to Azure Static Web Apps.
#
#   ./deploy/deploy_frontend.sh            # build + deploy to production
#   DRY_RUN=1 ./deploy/deploy_frontend.sh  # build + checks only, no upload
#
# Reads deploy/frontend.env.production (VITE_* only: all of it becomes PUBLIC in the JS bundle)
# and the deployment token from deploy/.swa-token (git-ignored). Run from the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."
ENVF=deploy/frontend.env.production
[[ -f $ENVF ]] || { echo "Missing $ENVF (copy deploy/frontend.env.production.example)"; exit 1; }

while IFS= read -r line || [[ -n $line ]]; do
  line="${line%%$'\r'}"; [[ $line == VITE_*=* ]] || continue
  key="${line%%=*}"; val="${line#*=}"; val="${val%%[[:space:]]#*}"; val="${val%"${val##*[![:space:]]}"}"
  export "$key=$val"
done < "$ENVF"

[[ ${VITE_API_URL:-} == https://* ]] || { echo "VITE_API_URL must be the https API address (e.g. https://api.kaarigar-ai.online)"; exit 1; }
for k in VITE_SUPABASE_URL VITE_SUPABASE_ANON_KEY; do [[ -n ${!k:-} ]] || { echo "Missing $k"; exit 1; }; done
case "$VITE_SUPABASE_ANON_KEY" in sb_secret_*) echo "Refusing: VITE_SUPABASE_ANON_KEY is a SECRET key"; exit 1;; esac
if [[ $VITE_SUPABASE_ANON_KEY == *.*.* ]]; then
  role=$(cut -d. -f2 <<<"$VITE_SUPABASE_ANON_KEY" | tr '_-' '/+' | base64 -d 2>/dev/null | grep -o '"role":"[a-z_]*"' || true)
  [[ $role == *service_role* ]] && { echo "Refusing: VITE_SUPABASE_ANON_KEY is the service_role key"; exit 1; }
fi

cp -n deploy/staticwebapp.config.json frontend/public/staticwebapp.config.json 2>/dev/null || true
cd frontend
npm ci
npm run build
[[ -f dist/staticwebapp.config.json ]] || { echo "dist/staticwebapp.config.json missing: put it in frontend/public/"; exit 1; }

# never ship a backend secret in the bundle
if [[ -f ../deploy/.env.production ]]; then
  while IFS= read -r line; do
    key="${line%%=*}"; val="${line#*=}"; val="${val%%[[:space:]]#*}"
    case "$key" in SUPABASE_SERVICE_ROLE_KEY|GROQ_API_KEY|SARVAM_API_KEY|DATABASE_URL|SUPABASE_JWT_SECRET)
      if [[ ${#val} -gt 8 ]] && grep -rqF -- "$val" dist; then echo "STOP: $key is inside dist/. Remove it from VITE_* and rebuild."; exit 1; fi;;
    esac
  done < ../deploy/.env.production
fi
echo "Build OK: $(du -sh dist | cut -f1), API → $VITE_API_URL"

[[ ${DRY_RUN:-0} == 1 ]] && { echo "(dry run: not uploaded)"; exit 0; }
TOKEN_FILE=../deploy/.swa-token
[[ -f $TOKEN_FILE ]] || { echo "Missing deploy/.swa-token (Azure portal → Static Web App → Manage deployment token)"; exit 1; }
SWA_CLI_DEPLOYMENT_TOKEN=$(tr -d '[:space:]' < "$TOKEN_FILE") npx --yes @azure/static-web-apps-cli@2 deploy ./dist --env production
