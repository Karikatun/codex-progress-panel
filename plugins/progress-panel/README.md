# codex-progress-panel 0.1.1

[English](#english) | [Русский](#русский)

## English

A local stdio MCP server and full Codex plugin. Each assistant execution gets a separate progress widget. `finish_progress` permanently freezes its actual final snapshot. Pending or blocked stages can remain. Later executions cannot change that history.

### Requirements and npm server

Use macOS or Linux, Node.js 22+, npm/npx, and Python 3.9+ as `python3` in PATH. Windows is unsupported. The full plugin launches Python directly and does not need the Node launcher. The server has no third-party Python dependencies.

This guide covers [`codex-progress-panel@0.1.1`](https://www.npmjs.com/package/codex-progress-panel/v/0.1.1). Configure a stdio MCP server:

```json
{"mcpServers":{"progress":{"command":"npx","args":["-y","codex-progress-panel"]}}}
```

Run the server or read its help:

```sh
npx -y codex-progress-panel
npx -y codex-progress-panel --help
```

Append `--data-dir /absolute/private/directory` to select another state directory. The launcher preserves server arguments and finds its files independently of the caller's directory. stdout contains MCP messages; stderr contains diagnostics. The process stops on stdin EOF, SIGINT, or SIGTERM.

The launcher installs no interpreter, dependencies, or Codex configuration. Public npx checks for `0.1.0` passed in two fresh caches. Version `0.1.1` updates the documentation. The published `0.1.0` tarball remains unchanged.

### English example

![English progress panel](https://raw.githubusercontent.com/Karikatun/codex-progress-panel/prep/v0.1.1/docs/images/progress-panel-en.png)

This actual panel preview uses illustrative English data and the default English UI. Native Codex rendering and placement need separate verification.

### Select the UI language

The UI uses English by default. To use Russian labels, create `~/.codex-progress-panel/config.json`:

```json
{"language":"ru"}
```

With a custom `--data-dir`, put the file beside `progress.sqlite3`. Use a regular UTF-8 file owned by your OS user, with permissions `0600` and one hard link. Its limit is 1024 bytes. The exact object accepts `language` with value `en` or `ru`. Symlinks and group/other permissions are refused.

The server reads the file once at startup, before opening SQLite. A missing file selects English. An invalid file stops startup on stderr without rewriting it. Restart the MCP server after changing the file. Existing widgets keep their language. `--language en` or `--language ru` overrides and skips the file, including an invalid file. Host/browser language does not select the UI language. Supplied task text keeps its original language.

### Full plugin and safe operation

An MCP server entry does not install the `progress-panel` skill. The package also includes `plugin.json`, `mcp.json`, the Python server, HTML UI, and `skills/progress-panel/SKILL.md`. Use a reviewed marketplace installation for the full plugin. The host controls rendering and placement.

The source repository's `distribution/marketplace.npm.json` pins npm version `0.1.1`. A host using that source needs npm and npm marketplace support. Full-plugin installation and native UI from the npm source remain unverified. The local-source route is documented in the repository guide. For version `0.1.1`, use source branch `prep/v0.1.1`.

Start a new chat after installation. Example request: **«Покажи этапы работы в панели и обновляй её по мере выполнения задачи.»**

Keep read and write tokens private. Update and finish require `expected_revision` and a complete snapshot. After a stale revision, read with `get_progress` and retry the intended write once. Stop writes after finalization. Lost tokens require text progress; do not open a replacement widget in that execution. A crash or Stop before successful finish can leave the snapshot unfinished.

### State, updates, and removal

State lives in `~/.codex-progress-panel/progress.sqlite3`, outside `CODEX_HOME`, the package, and caches. A custom data directory must be absolute and private. Its parent must exist. The server refuses package/marketplace state, unsafe ownership or permissions, symlinks, hardlinked databases, and unsafe SQLite sidecars. It does not migrate the former local plugin's data.

The store retains at most 128 executions, including finalized history. It never evicts history automatically. Tokens have no automatic expiry. Removing their execution state revokes them. Same-user database access and host privileges are outside this capability boundary.

Review the latest npm release before using unversioned npx. Review each new plugin release before changing its marketplace version pin. Removal and cache changes preserve private state. Remove the MCP entry or plugin through your host's supported flow. npx needs no global installation. Archive or delete only the exact private directory with explicit authorization. Stop the server first. Confirm that its history is no longer needed.

See the repository guide for all tools, limits, tests, and native acceptance: [English](https://github.com/Karikatun/codex-progress-panel/blob/prep/v0.1.1/README.md), [Русский](https://github.com/Karikatun/codex-progress-panel/blob/prep/v0.1.1/README.ru.md).

## Русский

Локальный stdio MCP-сервер и полный плагин Codex. Каждый запуск ассистента получает отдельный виджет прогресса. `finish_progress` навсегда фиксирует фактический итоговый снимок. В нём могут оставаться ожидающие или заблокированные этапы. Последующие запуски не меняют эту историю.

### Требования и npm-сервер

Используйте macOS или Linux, Node.js 22+, npm/npx и Python 3.9+ под именем `python3` в PATH. Windows не поддерживается. Полный плагин запускает Python напрямую и не требует запускающего модуля Node. У сервера нет сторонних зависимостей Python.

Это руководство для [`codex-progress-panel@0.1.1`](https://www.npmjs.com/package/codex-progress-panel/v/0.1.1). Настройте stdio MCP-сервер:

```json
{"mcpServers":{"progress":{"command":"npx","args":["-y","codex-progress-panel"]}}}
```

Запустите сервер или прочитайте справку:

```sh
npx -y codex-progress-panel
npx -y codex-progress-panel --help
```

Добавьте `--data-dir /absolute/private/directory` для другого каталога данных. Модуль сохраняет аргументы сервера и находит файлы независимо от текущего каталога. stdout содержит сообщения MCP; stderr — диагностику. Процесс завершается при EOF в stdin, SIGINT или SIGTERM.

Модуль не устанавливает интерпретатор, зависимости или конфигурацию Codex. Проверки публичного npx версии `0.1.0` прошли в двух новых кешах. Версия `0.1.1` обновляет документацию. Опубликованный архив `0.1.0` остаётся неизменным.

### Английский пример

![Панель прогресса на английском](https://raw.githubusercontent.com/Karikatun/codex-progress-panel/prep/v0.1.1/docs/images/progress-panel-en.png)

Пример настоящей панели использует демонстрационные английские данные и английский UI по умолчанию. Встроенное отображение и размещение в Codex требуют отдельной проверки.

### Выбор языка интерфейса

По умолчанию интерфейс использует английский. Для русских подписей создайте `~/.codex-progress-panel/config.json`:

```json
{"language":"ru"}
```

При своём `--data-dir` разместите файл рядом с `progress.sqlite3`. Используйте обычный UTF-8 файл вашего пользователя ОС, с правами `0600` и одной жёсткой ссылкой. Лимит — 1024 байта. Точный объект принимает `language` со значением `en` или `ru`. Симлинки и права группы или остальных отклоняются.

Сервер читает файл один раз при запуске, до открытия SQLite. Если файла нет, он выбирает английский. Некорректный файл останавливает запуск с диагностикой в stderr без перезаписи. Перезапустите MCP-сервер после изменения файла. Существующие виджеты сохраняют язык. `--language en` или `--language ru` переопределяет и пропускает файл, даже некорректный. Язык хоста или браузера не выбирает язык UI. Переданный текст задачи сохраняет исходный язык.

### Полный плагин и безопасная работа

MCP-запись не устанавливает skill `progress-panel`. Пакет также содержит `plugin.json`, `mcp.json`, сервер Python, HTML UI и `skills/progress-panel/SKILL.md`. Для полного плагина используйте проверенную установку через marketplace. Хост управляет отображением и размещением.

Файл `distribution/marketplace.npm.json` в репозитории закрепляет npm-версию `0.1.1`. Хосту нужны npm и поддержка npm-источников marketplace. Установка полного плагина и встроенный UI из npm-источника пока не проверены. Установка из локального исходного кода описана в руководстве репозитория. Для версии `0.1.1` используйте исходный код из ветки `prep/v0.1.1`.

После установки начните новый чат. Пример запроса: **«Покажи этапы работы в панели и обновляй её по мере выполнения задачи.»**

Храните токены чтения и записи приватно. Обновление и завершение требуют `expected_revision` и полный снимок. После устаревшей ревизии прочитайте снимок через `get_progress` и повторите нужную запись один раз. Прекратите запись после финализации. При потере токенов используйте текстовые обновления; не открывайте заменяющий виджет в этом запуске. Сбой или Stop до успешного завершения могут оставить снимок незавершённым.

### Данные, обновление и удаление

Данные находятся в `~/.codex-progress-panel/progress.sqlite3`, вне `CODEX_HOME`, пакета и кешей. Другой каталог должен быть абсолютным и приватным. Его родитель должен существовать. Сервер отклоняет данные внутри пакета/marketplace, небезопасного владельца или права, симлинки, жёсткие ссылки на базу и небезопасные вспомогательные файлы SQLite. Он не переносит данные прежнего локального плагина.

Хранилище содержит не более 128 запусков, включая итоговую историю. Автоматического удаления истории нет. У токенов нет автоматического срока действия. Удаление данных запуска отзывает его токены. Доступ к базе от того же пользователя и привилегии хоста находятся вне этой границы защиты.

Проверяйте актуальный npm-выпуск перед использованием npx без версии. Проверяйте новый выпуск плагина перед изменением закреплённой версии marketplace. Удаление и изменения кеша сохраняют приватные данные. Удалите MCP-запись или плагин поддерживаемым хостом способом. Для npx глобальная установка не нужна. Архивируйте или удаляйте только точный приватный каталог с явным разрешением. Сначала остановите сервер. Подтвердите, что история больше не нужна.

Все инструменты, ограничения, тесты и проверка встроенного интерфейса описаны в руководстве репозитория: [English](https://github.com/Karikatun/codex-progress-panel/blob/prep/v0.1.1/README.md), [Русский](https://github.com/Karikatun/codex-progress-panel/blob/prep/v0.1.1/README.ru.md).

[MIT license / Лицензия MIT](LICENSE), copyright 2026 Karikatun.
