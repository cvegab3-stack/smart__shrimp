# Equivalente Linux de Import-LocalEnv.ps1: carga .env en el entorno del proceso. Se incluye con "source".
# Ignora comentarios y líneas sin forma NOMBRE=valor; acepta archivos guardados en Windows (CRLF).
load_smart_shrimp_env() {
    local env_file="$1/.env" line name value
    if [ ! -f "$env_file" ]; then
        echo "No existe .env. Ejecuta primero bash scripts/setup_linux.sh desde la raíz del proyecto." >&2
        return 1
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        name="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        value="${value#"${value%%[![:space:]]*}"}"   # quita espacios al inicio
        value="${value%"${value##*[![:space:]]}"}"   # y al final
        export "$name=$value"
    done < "$env_file"
    # Igual que en Windows: desarrollo local con SQLite y visión en este mismo equipo.
    export DJANGO_SETTINGS_MODULE=config.settings.local
    export VISION_SERVICE_URL="http://127.0.0.1:${VISION_PORT:-8001}"
}
