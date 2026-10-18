# first-devops-project

## Архитектура

Проект представляет собой полный DevOps-стек для разработки и мониторинга:

- **Python-app** — основное приложение (Docker)
- **Nginx** — reverse proxy (порт 8080 → 80)
- **Docker Compose** — оркестрация всех сервисов
- **Ansible** — автоматизация конфигурации (playbook.yml, inventory.ini)
- **GitHub Actions** — CI/CD с self-hosted runner на VM
- **Мониторинг**: Prometheus + Grafana + cAdvisor + node-exporter

## Сервисы и порты

| Сервис         | Порт на хосте | Внутренний порт | Описание                          |
|----------------|---------------|-----------------|-----------------------------------|
| Nginx proxy    | 8080          | 80              | Reverse proxy для Python-app      |
| Prometheus     | 9090          | 9090            | Сбор и хранение метрик            |
| Grafana        | 3000          | 3000            | Визуализация метрик               |
| node-exporter  | 9100          | 9100            | Метрики системы (CPU, RAM, disk)  |
| cAdvisor       | 8081          | 8080            | Метрики Docker-контейнеров        |

## Требования

- Docker и Docker Compose
- Ubuntu 20.04+ на VM (192.168.0.218)
- Ansible (для проверки синтаксиса в CI)
- SSH-доступ к VM

## Запуск

```bash
cd ~/ansible-test
docker compose up -d
