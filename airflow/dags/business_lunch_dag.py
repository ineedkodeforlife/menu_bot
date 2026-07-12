import os
import sys
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

# В Docker (локальный тест) проект примонтирован в /opt/project.
# На сервере (venv, без Docker) задайте STOLOVKA_PROJECT_DIR=/home/<user>/stolovka_bot.
PROJECT_DIR = os.environ.get("STOLOVKA_PROJECT_DIR", "/opt/project")
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


def run_business_lunch():
    from main import main

    main()


default_args = {
    "owner": "stolovka_bot",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="business_lunch_daily",
    description="Достаёт бизнес-ланч из меню столовой и шлёт в Telegram",
    default_args=default_args,
    schedule="0 9 * * 1-5",  # будни, 09:00 по Europe/Moscow
    start_date=pendulum.datetime(2026, 7, 1, tz="Europe/Moscow"),
    catchup=False,
    tags=["stolovka"],
) as dag:
    PythonOperator(
        task_id="fetch_and_send_lunch",
        python_callable=run_business_lunch,
    )
