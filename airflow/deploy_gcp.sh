#!/usr/bin/env bash
# Разворачивает Airflow (standalone, SQLite, без Docker) на лёгкой VM вроде GCP e2-micro (1GB RAM).
# Запускать на самом сервере, из домашней директории пользователя, ПОСЛЕ того как
# папка stolovka_bot скопирована на сервер (например через `gcloud compute scp` или `scp`)
# и в ~/stolovka_bot/.env вписаны реальные ключи (без кавычек — см. .env.example).
set -euo pipefail

PROJECT_DIR="$HOME/stolovka_bot"
AIRFLOW_HOME="$HOME/airflow"
VENV_DIR="$HOME/airflow-venv"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Не найдена $PROJECT_DIR — сначала скопируйте туда проект." >&2
  exit 1
fi

# 1. Своп-файл. На 1GB RAM без него pip install airflow и сам Airflow уходят в OOM.
if ! swapon --show | grep -q '/swapfile'; then
  echo "Создаю 2GB своп-файл..."
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

# 2. Системные зависимости
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip

# 3. Airflow в venv (без Docker/Postgres — экономим память)
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip

AIRFLOW_VERSION="2.10.4"
PYTHON_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

pip install "apache-airflow==${AIRFLOW_VERSION}" --constraint "$CONSTRAINT_URL"
pip install -r "$PROJECT_DIR/requirements.txt"

# 4. DAG
mkdir -p "$AIRFLOW_HOME/dags"
cp "$PROJECT_DIR/airflow/dags/business_lunch_dag.py" "$AIRFLOW_HOME/dags/"

# 5. Таймзона по умолчанию для планировщика
export AIRFLOW_HOME
airflow config set core default_timezone Europe/Moscow || true

echo ""
echo "Готово. Дальше:"
echo "1) В ~/stolovka_bot/.env оставьте как есть (в кавычках) — тут секреты читает python-dotenv,"
echo "   он их сам снимает, в отличие от Docker."
echo "2) Установите systemd-сервис:"
echo "   sudo sed \"s/__USER__/$USER/g\" $PROJECT_DIR/airflow/business-lunch-airflow.service | sudo tee /etc/systemd/system/business-lunch-airflow.service"
echo "3) sudo systemctl daemon-reload && sudo systemctl enable --now business-lunch-airflow"
echo "4) Пароль admin: cat \$AIRFLOW_HOME/simple_auth_manager_passwords.json (или standalone_admin_password.txt в старых версиях)"
echo "5) Веб-интерфейс: http://<VM_PUBLIC_IP>:8080"
echo "6) Включите DAG business_lunch_daily тумблером в UI"
