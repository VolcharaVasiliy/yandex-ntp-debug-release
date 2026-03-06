# Safe Release Patch Kit

Этот релиз содержит только безопасные разделенные патчи.

## Что есть
- `run_apply_context_safe.ps1`
  - Google для выделенного текста
  - `Спросить ChatGPT` в popup
  - popup-иконки Google/OpenAI
- `run_apply_ntp_link_only.ps1`
  - меняет только ссылку верхней Alice-кнопки на новой вкладке
  - не меняет текст, иконки, `apps.json`, `resources.pak`, locale chunks
- `run_disable_ntp_banner.ps1`
  - отдельно отключает рекламный баннер/виджеты новой вкладки

## Чего здесь нет
- Нет старого broad-патча, который одновременно правил `ru.pak`, `resources.pak`, `apps.json`, locale chunks и web app config для новой вкладки.
- Эти старые release entrypoint-скрипты из релиза удалены.

## Быстрый запуск
1. Закрыть Yandex Browser.
2. Запустить `apply_all.cmd`.
3. Запустить `verify_all.cmd`.

## Ручной запуск по слоям
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_apply_context_safe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_apply_ntp_link_only.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_disable_ntp_banner.ps1
```

Проверка:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_verify_context_safe.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_verify_ntp_link_only.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_verify_ntp_banner.ps1
```

## Откат
- `restore_all.cmd`
- или отдельно:
  - `run_restore_newtab_backup.ps1`
  - `run_restore_ntp_banner.ps1`

## Состав релиза
- `scripts\shared_patchlib.py` используется только как библиотека для safe-скриптов.
- Не запускать `shared_patchlib.py` напрямую.
