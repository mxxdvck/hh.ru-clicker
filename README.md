# HH.ru Clicker - extended fork

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-39d0d8?style=flat-square)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-1432_total-39d0d8?style=flat-square)](tests/)
[![Passed](https://img.shields.io/badge/passed-1432-3fb950?style=flat-square)](tests/)
[![Clients](https://img.shields.io/badge/HH-web%20%7C%20mobile%20%7C%20auto-b967ff?style=flat-square)](app/hh_client_factory.py)
[![WebSocket](https://img.shields.io/badge/realtime-WebSocket-00f0ff?style=flat-square)](app/ws_client.py)

Расширенный форк `Vlad9572324/hh.ru-clicker` для автоматизации поиска работы на hh.ru. В форке существенно переработаны безопасность откликов, LLM-автоматизация, опросники, переписка с работодателями и web-dashboard.

> Upstream: `Vlad9572324/hh.ru-clicker`. Этот репозиторий не является официальным продуктом hh.ru. Пользователь самостоятельно отвечает за соблюдение правил сервиса, корректность откликов и сохранность своих данных.

## Что изменено в этом форке

- Безопасные автоматические отклики с дневными и сессионными лимитами.
- Режим безопасного поиска без отправки откликов и отдельный запуск откликов по уже найденным вакансиям.
- DeepSeek и несколько LLM-профилей с fallback/round-robin стратегиями.
- Автоматическое заполнение HH-анкет и обработка radio/select/checkbox вопросов.
- Ответы работодателям с использованием резюме и профиля кандидата.
- Отдельная обработка рекрутер-ботов, повторных вопросов и служебных сообщений.
- Safety-policy для LLM: неизвестные факты не выдумываются, рискованные ответы уходят на ручную проверку вместо слепой отправки.
- Review Center с черновиками, причинами ручной проверки и кнопкой **Перегенерировать** без автоматической отправки.
- Dashboard Phase 5: обзор состояния, action center, вакансии, воронка откликов, Review Center, настройки, health/status и realtime-обновления.
- Secure storage, backup/restore и защита чувствительных настроек.
- Регрессионные, backend и browser E2E тесты. Текущий локальный gate: **1432 passed**.

## Состояние проекта

| Фаза | Статус | Содержание |
|---|---|---|
| Phase 1-3 | ✅ Готово | отклики, лимиты, safety, поиск и работа с найденными вакансиями |
| Phase 4 | ✅ Готово | DeepSeek, анкеты, LLM-ответы, профиль кандидата и safety-policy |
| Phase 5 | ✅ Готово | dashboard, Review Center, UX, health/status и операционное управление |
| Phase 6 | ⏳ Не реализована | Telegram-уведомления и удалённое управление; сознательно оставлено на потом |

## База, унаследованная от upstream

В проекте сохранена mobile API архитектура upstream: единый `HHClient`, OAuth Bearer, SMS/email OTP, мобильные чаты, отклики, резюме и сервисные операции. Для аккаунта можно использовать режимы `web`, `mobile` или `auto`, а поддерживаемые операции умеют безопасно откатываться на web-flow.

## Быстрый старт

```bash
git clone https://github.com/mxxdvck/hh.ru-clicker.git
cd hh.ru-clicker
docker-compose up -d --build
```

Откройте <http://localhost:8000>. Порт по умолчанию опубликован только на loopback. Для сетевого доступа сначала прочитайте [руководство по безопасности](docs/SECURITY.md).

### Подключение аккаунта через SMS OTP

1. Откройте **⚙️ Настройки → Авторизация по телефону / email**.
2. Введите телефон, запросите SMS и укажите одноразовый код.
3. Дождитесь создания браузерной сессии и импорта OAuth.
4. В карточке аккаунта выберите `mobile`, `web` или `auto` и запустите аккаунт.

## Интерфейс и основные сценарии

| Раздел | Назначение |
|---|---|
| Главная / Overview | состояние аккаунтов, health и быстрые действия |
| Вакансии | безопасный поиск и работа с уже найденными вакансиями |
| Отклики | история и воронка откликов |
| Review Center | LLM-черновики, ручная проверка и перегенерация |
| Настройки | лимиты, режимы, LLM, backup/restore и параметры аккаунтов |
| HH Хэдди | встроенный чат с помощником HH |

Автоответы специально разделяют безопасные стандартные кейсы и ситуации, где нужен человек. Служебные сообщения не получают ответов, повторные безопасные вопросы могут использовать ранее подтверждённый ответ, а приглашения на собеседование, неоднозначные условия и неподтверждённые факты остаются на review.

## Проверка

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

Для текущей ревизии: **1432 passed**. Актуальный итог всегда проверяйте локальным `pytest -q`.

## Документация

- [Руководство пользователя](docs/USER_GUIDE.md)
- [Mobile migration guide](docs/MOBILE_MIGRATION_GUIDE.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Защита данных](docs/SECURITY.md)
- [API reference](docs/API_REFERENCE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Changelog](CHANGELOG.md)
