#!/usr/bin/env bash
# Build the backend image on this laptop, push it to Azure Container Registry, and create or update the Container App.
#
#   ./deploy/deploy_backend.sh              # build, push, deploy (tag = git short hash + time)
#   DRY_RUN=1 ./deploy/deploy_backend.sh    # print every command (secrets masked), run nothing
#   SKIP_BUILD=1 TAG=<tag> ./deploy/deploy_backend.sh   # redeploy an image that is already pushed
#
# Reads deploy/azure.conf (names) and deploy/.env.production (settings + secrets; git-ignored, never commit it).
# Secrets go into Container Apps secrets and reach the app as env vars via secretref; nothing secret is echoed.
# Run from the repo root.
set -euo pipefail

cd "$(dirname "$0")/.."
CONF=deploy/azure.conf
ENVF=deploy/.env.production
[[ -f $CONF ]] || { echo "Missing $CONF (copy deploy/azure.conf.example)"; exit 1; }
[[ -f $ENVF ]] || { echo "Missing $ENVF (copy deploy/backend.env.production.example and fill it)"; exit 1; }
# shellcheck disable=SC1090
source "$CONF"

# Settings that must be Container Apps secrets (key in .env → secret name)
declare -A SECRET_NAMES=(
  [SUPABASE_SERVICE_ROLE_KEY]=sb-service-key
  [DATABASE_URL]=database-url
  [GROQ_API_KEY]=groq-key
  [SARVAM_API_KEY]=sarvam-key
  [MISTRAL_API_KEY]=mistral-key
  [GEMINI_API_KEY]=gemini-key
  [OPENROUTER_API_KEY]=openrouter-key
  [AZURE_SPEECH_KEY]=azure-speech-key
  [DEEPGRAM_API_KEY]=deepgram-key
  [SUPABASE_JWT_SECRET]=sb-jwt-secret
)

run() {   # run a command, or (DRY_RUN=1) print it with secret values masked
  if [[ ${DRY_RUN:-0} == 1 ]]; then
    local out="" a prev="" name
    for a in "$@"; do
      for name in "${SECRET_NAMES[@]}"; do [[ $a == "$name="* ]] && a="$name=****"; done
      [[ $prev == --registry-password ]] && a='****'
      out+=" $(printf '%q' "$a")"; prev=$a
    done
    echo "+$out"
  else
    "$@"
  fi
}

# --- read .env.production: KEY=VALUE lines, strip inline " # comments" and quotes
SECRETS=(); ENVVARS=(); SEEN=()
while IFS= read -r line || [[ -n $line ]]; do
  line="${line%%$'\r'}"
  [[ -z ${line// } || ${line#"${line%%[![:space:]]*}"} == \#* ]] && continue
  [[ $line == *=* ]] || continue
  key="${line%%=*}"; key="${key// /}"
  val="${line#*=}"
  val="${val%%[[:space:]]#*}"                      # drop " # comment"
  val="${val#"${val%%[![:space:]]*}"}"; val="${val%"${val##*[![:space:]]}"}"   # trim
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  [[ -z $val ]] && continue                         # empty = not set (e.g. SUPABASE_JWT_SECRET when using JWKS)
  [[ $key == VITE_* ]] && { echo "Refusing: $key belongs to the frontend, not the backend .env"; exit 1; }
  SEEN+=("$key")
  if [[ -n ${SECRET_NAMES[$key]:-} ]]; then
    SECRETS+=("${SECRET_NAMES[$key]}=$val")
    ENVVARS+=("$key=secretref:${SECRET_NAMES[$key]}")
  else
    ENVVARS+=("$key=$val")
  fi
done < "$ENVF"

for k in SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY DATABASE_URL GROQ_API_KEY SARVAM_API_KEY PUBLIC_APP_URL ALLOWED_ORIGINS APP_ENV; do
  [[ " ${SEEN[*]} " == *" $k "* ]] || { echo "Missing $k in $ENVF"; exit 1; }
done
grep -q '^APP_ENV=production' "$ENVF" || { echo "APP_ENV must be production"; exit 1; }
if grep -Eq '^DATABASE_URL=.*@db\.[a-z0-9]+\.supabase\.co' "$ENVF"; then
  echo "DATABASE_URL is the direct db.<ref>.supabase.co address (IPv6 only): Azure can't reach it."
  echo "Use the Session pooler string (aws-…pooler.supabase.com:5432) from Supabase → Connect."; exit 1
fi

IMAGE_NAME=kaarigar-backend
TAG=${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo manual)-$(date +%Y%m%d%H%M)}
IMAGE="$ACR.azurecr.io/$IMAGE_NAME:$TAG"
echo "Image: $IMAGE"

# --- build + push (local Docker: az acr build is blocked on Azure for Students / free-credit subscriptions)
if [[ ${SKIP_BUILD:-0} != 1 ]]; then
  run docker build -f backend/Dockerfile -t "$IMAGE" .
  run az acr login --name "$ACR"
  run docker push "$IMAGE"
fi

# --- create or update the Container App
if [[ ${DRY_RUN:-0} == 1 ]]; then EXISTS=${APP_EXISTS:-0}
else EXISTS=$(az containerapp show -n "$APP" -g "$RG" --query name -o tsv 2>/dev/null | grep -c . || true); fi

if [[ $EXISTS == 0 ]]; then
  echo "Creating Container App $APP …"
  if [[ ${DRY_RUN:-0} == 1 ]]; then ACR_PASS='****'; else ACR_PASS=$(az acr credential show -n "$ACR" --query 'passwords[0].value' -o tsv); fi
  run az containerapp create -n "$APP" -g "$RG" --environment "$ACA_ENV" \
    --image "$IMAGE" --registry-server "$ACR.azurecr.io" --registry-username "$ACR" --registry-password "$ACR_PASS" \
    --target-port 8000 --ingress external --transport auto \
    --min-replicas 1 --max-replicas 1 --cpu "$CPU" --memory "$MEMORY" \
    --secrets "${SECRETS[@]}" --env-vars "${ENVVARS[@]}" -o none
else
  echo "Updating Container App $APP …"
  run az containerapp secret set -n "$APP" -g "$RG" --secrets "${SECRETS[@]}" -o none
  run az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" \
    --min-replicas 1 --max-replicas 1 --cpu "$CPU" --memory "$MEMORY" \
    --replace-env-vars "${ENVVARS[@]}" -o none
fi

if [[ ${DRY_RUN:-0} == 1 ]]; then echo "(dry run: nothing was changed)"; exit 0; fi
FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)
echo "Waiting for https://$FQDN/health …"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "https://$FQDN/health" >/dev/null 2>&1; then echo "Backend is up: https://$FQDN  (tag $TAG)"; exit 0; fi
  sleep 10
done
echo "Not healthy after 5 minutes. See: az containerapp logs show -n $APP -g $RG --follow"; exit 1
