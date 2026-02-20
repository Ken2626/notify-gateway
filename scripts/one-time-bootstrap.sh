#!/usr/bin/env bash
set -euo pipefail

say() {
  printf '%s\n' "$*"
}

warn() {
  printf 'WARN: %s\n' "$*" >&2
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

run() {
  say "+ $*"
  "$@"
}

run_sensitive() {
  local label="$1"
  shift
  say "+ ${label}"
  "$@"
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

prompt_with_default() {
  local var_name="$1"
  local prompt_text="$2"
  local default_value="$3"
  local input=""

  if [[ -n "$default_value" ]]; then
    read -r -p "${prompt_text} [${default_value}]: " input || true
    input="${input:-$default_value}"
  else
    read -r -p "${prompt_text}: " input || true
  fi

  input="$(trim "$input")"
  printf -v "$var_name" '%s' "$input"
}

prompt_required() {
  local var_name="$1"
  local prompt_text="$2"
  local default_value="${3:-}"
  local value=""

  while true; do
    prompt_with_default value "$prompt_text" "$default_value"
    if [[ -n "$value" ]]; then
      printf -v "$var_name" '%s' "$value"
      return
    fi
    warn "This value is required."
  done
}

prompt_secret() {
  local var_name="$1"
  local prompt_text="$2"
  local input=""
  read -r -s -p "${prompt_text}: " input || true
  printf '\n'
  input="$(trim "$input")"
  printf -v "$var_name" '%s' "$input"
}

confirm() {
  local prompt_text="$1"
  local default_answer="${2:-y}"
  local input=""
  local suffix="[Y/n]"

  if [[ "$default_answer" == "n" ]]; then
    suffix="[y/N]"
  fi

  read -r -p "${prompt_text} ${suffix}: " input || true
  input="$(trim "$input")"
  input="$(printf '%s' "$input" | tr '[:upper:]' '[:lower:]')"

  if [[ -z "$input" ]]; then
    input="$default_answer"
  fi

  [[ "$input" == "y" || "$input" == "yes" ]]
}

check_dependency() {
  local bin_name="$1"
  if ! command -v "$bin_name" >/dev/null 2>&1; then
    die "Missing required command: ${bin_name}"
  fi
}

run_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    run "$@"
    return
  fi

  if command -v sudo >/dev/null 2>&1; then
    run sudo "$@"
    return
  fi

  die "Root privileges are required to install dependencies. Install sudo or run this script as root."
}

APT_UPDATED=0

ensure_system_paths() {
  if [[ ! -d /usr/local/bin ]]; then
    run_as_root mkdir -p /usr/local/bin
  fi
}

apt_repair_if_needed() {
  warn "apt install failed. Attempting dpkg/apt repair and retry."
  ensure_system_paths
  run_as_root dpkg --configure -a || true
  run_as_root env DEBIAN_FRONTEND=noninteractive apt-get -f install -y || true
}

apt_update_if_needed() {
  if [[ "${APT_UPDATED}" -eq 0 ]]; then
    run_as_root apt-get update
    APT_UPDATED=1
  fi
}

apt_install_packages() {
  if run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"; then
    return 0
  fi

  apt_repair_if_needed
  run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

install_gcloud_with_apt() {
  local tmp_key=""
  local tmp_list=""

  check_dependency apt-get

  say "Installing gcloud (google-cloud-cli) via apt..."
  ensure_system_paths
  apt_update_if_needed
  apt_install_packages apt-transport-https ca-certificates gnupg curl

  tmp_key="$(mktemp)"
  tmp_list="$(mktemp)"
  curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor >"${tmp_key}"
  run_as_root install -m 0644 "${tmp_key}" /usr/share/keyrings/cloud.google.gpg

  cat >"${tmp_list}" <<'EOF'
deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main
EOF
  run_as_root install -m 0644 "${tmp_list}" /etc/apt/sources.list.d/google-cloud-sdk.list
  rm -f "${tmp_key}" "${tmp_list}"

  APT_UPDATED=0
  apt_update_if_needed
  apt_install_packages google-cloud-cli
}

install_gh_with_apt() {
  check_dependency apt-get
  say "Installing GitHub CLI (gh) via apt..."
  ensure_system_paths
  apt_update_if_needed
  apt_install_packages gh
}

ensure_gcloud_available() {
  if command -v gcloud >/dev/null 2>&1; then
    return
  fi

  warn "Missing required command: gcloud"
  say "This script can auto-install gcloud on Debian/Ubuntu (apt)."

  if ! confirm "Install gcloud now?" "y"; then
    die "gcloud is required. Install google-cloud-cli and rerun."
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    die "Auto-install is only supported on apt-based systems. Please install gcloud manually and rerun."
  fi

  install_gcloud_with_apt

  if ! command -v gcloud >/dev/null 2>&1; then
    die "gcloud installation did not complete successfully."
  fi
}

ensure_gh_available() {
  if command -v gh >/dev/null 2>&1; then
    return 0
  fi

  warn "Missing optional command: gh"
  say "Without gh, GitHub secret/variable must be set manually."

  if ! confirm "Install gh now?" "y"; then
    return 1
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    warn "Auto-install for gh is only supported on apt-based systems."
    return 1
  fi

  if ! install_gh_with_apt; then
    warn "Failed to install gh automatically."
    return 1
  fi

  command -v gh >/dev/null 2>&1
}

guess_github_repo_from_git() {
  local repo_root="$1"
  local remote_url=""

  if ! command -v git >/dev/null 2>&1; then
    return 0
  fi

  if ! git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi

  remote_url="$(git -C "$repo_root" config --get remote.origin.url || true)"
  if [[ -z "$remote_url" ]]; then
    return 0
  fi

  if [[ "$remote_url" =~ ^git@github\.com:([^/]+)/([^/]+)(\.git)?$ ]]; then
    printf '%s %s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]%.git}"
    return 0
  fi

  if [[ "$remote_url" =~ ^https://github\.com/([^/]+)/([^/]+)(\.git)?$ ]]; then
    printf '%s %s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]%.git}"
    return 0
  fi
}

random_hex_32() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
    return 0
  fi

  if command -v xxd >/dev/null 2>&1; then
    xxd -p -l 32 /dev/urandom
    return 0
  fi

  die "Cannot generate random token: install openssl or xxd."
}

service_exists() {
  local service_name="$1"
  local project_id="$2"
  local region="$3"
  gcloud run services describe "$service_name" --project "$project_id" --region "$region" >/dev/null 2>&1
}

append_env_kv() {
  local current="$1"
  local key="$2"
  local value="$3"
  local delim="$4"

  if [[ -z "$current" ]]; then
    printf '%s=%s' "$key" "$value"
  else
    printf '%s%s%s=%s' "$current" "$delim" "$key" "$value"
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

say "notify-gateway one-time bootstrap (interactive)"
say "This script sets up GCP + GitHub OIDC + Cloud Run initial config."
say

ensure_gcloud_available

if ! gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n1 | grep -q .; then
  warn "No active gcloud account found."
  if confirm "Run gcloud auth login now?" "y"; then
    run gcloud auth login
  else
    die "gcloud auth is required."
  fi
fi

DEFAULT_PROJECT="$(gcloud config get-value project 2>/dev/null || true)"
if [[ "$DEFAULT_PROJECT" == "(unset)" ]]; then
  DEFAULT_PROJECT=""
fi

DEFAULT_REGION="us-west1"
DEFAULT_GAR_REPO="notify-gateway"
DEFAULT_SERVICE_NAME="notify-gateway"
DEFAULT_SA_ID="notify-gateway-gha"
DEFAULT_WIF_POOL_ID="github-pool"
DEFAULT_WIF_PROVIDER_ID="github-oidc"

GIT_GUESS="$(guess_github_repo_from_git "$REPO_ROOT" || true)"
DEFAULT_GITHUB_OWNER="$(printf '%s' "$GIT_GUESS" | awk '{print $1}')"
DEFAULT_GITHUB_REPO="$(printf '%s' "$GIT_GUESS" | awk '{print $2}')"
if [[ -z "$DEFAULT_GITHUB_REPO" ]]; then
  DEFAULT_GITHUB_REPO="notify-gateway"
fi

prompt_required PROJECT_ID "GCP project id" "$DEFAULT_PROJECT"
prompt_required REGION "Cloud Run region" "$DEFAULT_REGION"
prompt_required GAR_REPO "Artifact Registry repo name" "$DEFAULT_GAR_REPO"
prompt_required SERVICE_NAME "Cloud Run service name" "$DEFAULT_SERVICE_NAME"
prompt_required GITHUB_OWNER "GitHub owner/user/org" "$DEFAULT_GITHUB_OWNER"
prompt_required GITHUB_REPO "GitHub repository name" "$DEFAULT_GITHUB_REPO"
prompt_required SA_ID "Service Account id (without domain)" "$DEFAULT_SA_ID"
prompt_required WIF_POOL_ID "Workload Identity Pool id" "$DEFAULT_WIF_POOL_ID"
prompt_required WIF_PROVIDER_ID "Workload Identity Provider id" "$DEFAULT_WIF_PROVIDER_ID"

SA_EMAIL="${SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

say
say "Summary:"
say "- PROJECT_ID: ${PROJECT_ID}"
say "- REGION: ${REGION}"
say "- GAR_REPO: ${GAR_REPO}"
say "- SERVICE_NAME: ${SERVICE_NAME}"
say "- GITHUB_REPO: ${GITHUB_OWNER}/${GITHUB_REPO}"
say "- SA_EMAIL: ${SA_EMAIL}"
say

if ! confirm "Continue with these settings?" "y"; then
  die "Cancelled by user."
fi

run gcloud config set project "${PROJECT_ID}"
run gcloud config set run/region "${REGION}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
if [[ -z "$PROJECT_NUMBER" ]]; then
  die "Failed to get project number for ${PROJECT_ID}"
fi

say
say "Enabling required GCP services..."
run gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com

say
say "Ensuring Artifact Registry repository exists..."
if gcloud artifacts repositories describe "${GAR_REPO}" --location "${REGION}" >/dev/null 2>&1; then
  say "Repository exists: ${REGION}/${GAR_REPO}"
else
  run gcloud artifacts repositories create "${GAR_REPO}" \
    --repository-format docker \
    --location "${REGION}" \
    --description "notify-gateway images"
fi

say
say "Ensuring Service Account exists..."
if gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  say "Service Account exists: ${SA_EMAIL}"
else
  run gcloud iam service-accounts create "${SA_ID}" \
    --display-name "notify-gateway github deployer"
fi

say
say "Granting IAM roles to Service Account..."
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  run gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SA_EMAIL}" \
    --role "${ROLE}"
done

say
say "Ensuring Workload Identity Pool exists..."
if gcloud iam workload-identity-pools describe "${WIF_POOL_ID}" \
  --project "${PROJECT_ID}" \
  --location global >/dev/null 2>&1; then
  say "Workload Identity Pool exists: ${WIF_POOL_ID}"
else
  run gcloud iam workload-identity-pools create "${WIF_POOL_ID}" \
    --project "${PROJECT_ID}" \
    --location global \
    --display-name "GitHub Actions Pool"
fi

ATTRIBUTE_CONDITION="assertion.repository=='${GITHUB_OWNER}/${GITHUB_REPO}'"

say
say "Ensuring OIDC provider exists..."
if gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
  --project "${PROJECT_ID}" \
  --location global \
  --workload-identity-pool "${WIF_POOL_ID}" >/dev/null 2>&1; then
  say "OIDC provider exists: ${WIF_PROVIDER_ID}"
else
  run gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER_ID}" \
    --project "${PROJECT_ID}" \
    --location global \
    --workload-identity-pool "${WIF_POOL_ID}" \
    --display-name "GitHub OIDC Provider" \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --attribute-mapping "google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" \
    --attribute-condition "${ATTRIBUTE_CONDITION}"
fi

say
say "Granting workloadIdentityUser binding..."
run gcloud iam service-accounts add-iam-policy-binding "${SA_EMAIL}" \
  --project "${PROJECT_ID}" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/attribute.repository/${GITHUB_OWNER}/${GITHUB_REPO}"

WIF_PROVIDER_RESOURCE="$(gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
  --project "${PROJECT_ID}" \
  --location global \
  --workload-identity-pool "${WIF_POOL_ID}" \
  --format='value(name)')"

if [[ -z "$WIF_PROVIDER_RESOURCE" ]]; then
  die "Failed to resolve WIF provider resource name."
fi

say
say "GitHub repository values:"
say "- Variable: GCP_PROJECT_ID=${PROJECT_ID}"
say "- Secret:   GCP_WORKLOAD_IDENTITY_PROVIDER=${WIF_PROVIDER_RESOURCE}"
say "- Secret:   GCP_SERVICE_ACCOUNT_EMAIL=${SA_EMAIL}"

if confirm "Set GitHub variable/secret automatically with gh CLI?" "y"; then
  if ! ensure_gh_available; then
    warn "Skipping gh auto-write. Please set GitHub variable/secrets manually."
  else
    if ! gh auth status >/dev/null 2>&1; then
      run gh auth login
    fi
    run gh variable set GCP_PROJECT_ID --repo "${GITHUB_OWNER}/${GITHUB_REPO}" --body "${PROJECT_ID}"
    run gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "${GITHUB_OWNER}/${GITHUB_REPO}" --body "${WIF_PROVIDER_RESOURCE}"
    run gh secret set GCP_SERVICE_ACCOUNT_EMAIL --repo "${GITHUB_OWNER}/${GITHUB_REPO}" --body "${SA_EMAIL}"
  fi
else
  warn "Skipped gh auto-write. Please set the GitHub variable/secrets manually."
fi

say
if confirm "Auto-generate NOTIFY_GATEWAY_TOKEN and ALERTMANAGER_WEBHOOK_TOKEN?" "y"; then
  NOTIFY_GATEWAY_TOKEN="$(random_hex_32)"
  ALERTMANAGER_WEBHOOK_TOKEN="$(random_hex_32)"
else
  prompt_required NOTIFY_GATEWAY_TOKEN "Input NOTIFY_GATEWAY_TOKEN"
  prompt_required ALERTMANAGER_WEBHOOK_TOKEN "Input ALERTMANAGER_WEBHOOK_TOKEN"
fi

BASE_ENV="NOTIFY_GATEWAY_TOKEN=${NOTIFY_GATEWAY_TOKEN}"
BASE_ENV="$(append_env_kv "${BASE_ENV}" "ALERTMANAGER_WEBHOOK_TOKEN" "${ALERTMANAGER_WEBHOOK_TOKEN}" "@")"
BASE_ENV="$(append_env_kv "${BASE_ENV}" "ENABLED_CHANNELS" "tg,wecom,serverchan" "@")"
BASE_ENV="$(append_env_kv "${BASE_ENV}" "ROUTE_CRITICAL" "tg,wecom" "@")"
BASE_ENV="$(append_env_kv "${BASE_ENV}" "ROUTE_WARNING" "wecom" "@")"
BASE_ENV="$(append_env_kv "${BASE_ENV}" "ROUTE_INFO" "tg" "@")"
BASE_ENV="$(append_env_kv "${BASE_ENV}" "DEDUPE_WINDOW_MS" "45000" "@")"

say
if service_exists "${SERVICE_NAME}" "${PROJECT_ID}" "${REGION}"; then
  say "Cloud Run service exists. Updating runtime settings and env vars..."
  run_sensitive "gcloud run services update ${SERVICE_NAME} (with sensitive env vars)" gcloud run services update "${SERVICE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --min-instances 0 \
    --max-instances 1 \
    --cpu 1 \
    --memory 512Mi \
    --concurrency 20 \
    --timeout 30 \
    --update-env-vars "^@^${BASE_ENV}"
else
  say "Cloud Run service does not exist. Creating service with temporary image..."
  run_sensitive "gcloud run deploy ${SERVICE_NAME} (with sensitive env vars)" gcloud run deploy "${SERVICE_NAME}" \
    --project "${PROJECT_ID}" \
    --region "${REGION}" \
    --image "us-docker.pkg.dev/cloudrun/container/hello" \
    --platform managed \
    --allow-unauthenticated \
    --min-instances 0 \
    --max-instances 1 \
    --cpu 1 \
    --memory 512Mi \
    --concurrency 20 \
    --timeout 30 \
    --set-env-vars "^@^${BASE_ENV}"
fi

if confirm "Configure channel credentials now?" "n"; then
  TG_BOT_TOKEN=""
  TG_CHAT_ID=""
  WECOM_WEBHOOK_URL=""
  SERVERCHAN_SENDKEY=""

  prompt_secret TG_BOT_TOKEN "TG_BOT_TOKEN (leave empty then press Enter to skip)"
  prompt_with_default TG_CHAT_ID "TG_CHAT_ID (optional, skip with Enter)" ""
  prompt_with_default WECOM_WEBHOOK_URL "WECOM_WEBHOOK_URL (optional, skip with Enter)" ""
  prompt_secret SERVERCHAN_SENDKEY "SERVERCHAN_SENDKEY (optional, skip with Enter)"

  CHANNEL_ENV=""
  if [[ -n "$TG_BOT_TOKEN" ]]; then
    CHANNEL_ENV="$(append_env_kv "${CHANNEL_ENV}" "TG_BOT_TOKEN" "${TG_BOT_TOKEN}" "@")"
  fi
  if [[ -n "$TG_CHAT_ID" ]]; then
    CHANNEL_ENV="$(append_env_kv "${CHANNEL_ENV}" "TG_CHAT_ID" "${TG_CHAT_ID}" "@")"
  fi
  if [[ -n "$WECOM_WEBHOOK_URL" ]]; then
    CHANNEL_ENV="$(append_env_kv "${CHANNEL_ENV}" "WECOM_WEBHOOK_URL" "${WECOM_WEBHOOK_URL}" "@")"
  fi
  if [[ -n "$SERVERCHAN_SENDKEY" ]]; then
    CHANNEL_ENV="$(append_env_kv "${CHANNEL_ENV}" "SERVERCHAN_SENDKEY" "${SERVERCHAN_SENDKEY}" "@")"
  fi

  if [[ -n "$CHANNEL_ENV" ]]; then
    run_sensitive "gcloud run services update ${SERVICE_NAME} (channel credentials)" gcloud run services update "${SERVICE_NAME}" \
      --project "${PROJECT_ID}" \
      --region "${REGION}" \
      --update-env-vars "^@^${CHANNEL_ENV}"
  else
    say "No channel credentials provided. Skipping channel update."
  fi
fi

say
say "Bootstrap completed."
say
say "Next:"
say "1) Push code to main to trigger deployment:"
say "   git push origin main"
say "2) Check workflow: GitHub -> Actions -> Build And Deploy Cloud Run"
say "3) Verify service:"
say "   gcloud run services describe ${SERVICE_NAME} --project ${PROJECT_ID} --region ${REGION} --format='value(status.url,status.latestReadyRevisionName)'"
say
say "Tokens were set on Cloud Run runtime env."
say "For security, token values are not printed by this script."
