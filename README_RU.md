# Safe Release Patch Kit

Этот релиз содержит только безопасные разделенные патчи для Yandex Browser.

## Главное
- `PatchKit Launcher.exe`
  - полностью standalone: можно скачать один `.exe` и запускать без установки Python и без соседних `.ps1/.cmd`
  - встроенные `scripts/*.py` уже упакованы внутрь EXE
  - графический launcher с нормальными подписями
  - запуск действий кнопкой или по номеру
  - предупреждение, если Yandex Browser открыт
  - отдельная кнопка закрытия браузера
  - прокручиваемый список действий
- `apply_all.cmd`
  - последовательно запускает все safe-слои
- `verify_all.cmd`
  - последовательно проверяет все safe-слои
- `restore_all.cmd`
  - откатывает new tab backup и banner backup

## Что входит в safe-слои
- `run_apply_context_safe.ps1`
  - Google для выделенного текста
  - `Спросить ChatGPT` в popup
  - рабочие popup-иконки Google/OpenAI
- `run_apply_ntp_link_only.ps1`
  - меняет только ссылку верхней Alice-кнопки на новой вкладке
  - не меняет текст, иконки, `apps.json`, `resources.pak`, locale chunks
- `run_disable_ntp_banner.ps1`
  - отдельно отключает рекламный баннер и виджеты новой вкладки

## Чего здесь нет
- Нет старого broad-патча, который одновременно правил `ru.pak`, `resources.pak`, `apps.json`, locale chunks и web app config для новой вкладки.
- Старые release entrypoint-скрипты удалены из релиза.

## Быстрый запуск
1. Скачать один файл `PatchKit Launcher.exe`.
2. Запустить его на ПК, где уже установлен Yandex Browser.
3. При необходимости launcher сам предупредит, что браузер открыт, и предложит закрыть его.
4. Выбрать нужное действие.
5. Для полного применения выбрать `1. Применить все`.
6. Для полной проверки выбрать `2. Проверить все`.

## Что нужно на чистом ПК
- Windows с PowerShell
- установленный Yandex Browser в обычном профиле пользователя
- больше ничего ставить не нужно

## Действия в launcher
1. `Применить все`
2. `Проверить все`
3. `Закрыть Yandex Browser`
4. `Применить Context Safe`
5. `Применить NTP Link Only`
6. `Отключить NTP Banner`
7. `Проверить Context Safe`
8. `Проверить NTP Link Only`
9. `Проверить NTP Banner`
10. `Откатить New Tab Backup`
11. `Откатить Banner Backup`
12. `Откатить все`

## Ручной запуск без launcher
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

## Сборка launcher из Python
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_patchkit_launcher.ps1
```

Исходник launcher: `patchkit_launcher.py`.
