# План: поширення soft delete на TemplateForm та EvaluationForm

## Контекст

Зараз soft delete (позначка `is_deleted` замість фізичного видалення рядка з БД) є лише у
WorkingForm, і то наполовину: поле і менеджер-фільтр існують, але DELETE-ендпоінт не має
`perform_destroy` - DRF за замовчуванням робить hard delete, всупереч докстрінгам. У
TemplateForm та EvaluationForm видалення стирає дані назавжди разом з оцінками, фідбеком і
звітом. Мета - усі три стадії пайплайна ховають видалене; повернути може адмін через адмінку.

## Ключові знахідки розвідки

- **Побічний баг:** DELETE робочої форми зараз стирає її фізично - у WorkingFormViewSet немає
  `perform_destroy`, тож DRF робить hard delete, хоча документація і поле `is_deleted`
  обіцяють soft delete. План це виправляє.
- **Slug-пастка:** фільтруючий менеджер "не бачить" видалені рядки, тому без переходу
  slug-генерації на `all_objects` створення форми з назвою видаленої падало б з
  IntegrityError (порушення унікальності на рівні БД).
- **Звіт - це файл:** посилання в нотатці PeopleForce веде на статичний файл у media
  (`report_file`), а не на API-ендпоінт, тож рішення "звіт лишається доступним" виконується
  автоматично - головне не чіпати файл при видаленні.
- **Адмінки двох стадій порожні:** `working_form/admin.py` і `evaluation_form/admin.py` -
  заглушки; без створення адмінок вимога "restore тільки через адмінку" нездійсненна.

## Рішення власника продукту (зафіксовані через опитування)

| # | Питання | Рішення |
|---|---|---|
| 1 | Відновлення | Тільки адмін через django admin; окремого API-ендпоінта restore немає |
| 2 | Каскад шаблон -> робочі форми | Немає: робочі форми - клони, живуть далі; з видаленого шаблона не можна створити нову |
| 3 | Звіт у CRM | Посилання на звіт з нотатки PeopleForce має працювати далі: `report_file` (файл у media) при soft delete не чіпаємо |
| 4 | Назви/slug | Лишаються зайнятими видаленим рядком (`unique=True` без змін); відновлення безконфліктне |
| 5 | Права | Без змін: шаблони - `IsManagerOrSuperuser`, робочі форми - `IsAdminUser`, оцінювання - `IsRecruiter` |
| 6 | Аудит | Зберігати хто (`deleted_by`) і коли (`deleted_at`) видалив; видно в адмінці |
| 7 | Зберігання | Вічно; адмін може стерти остаточно руками стандартним delete в адмінці |
| 8 | Обмеження | DELETE оцінювання у статусі IN_PROGRESS -> помилка 400; PENDING і COMPLETED видаляються |

## Архітектура: механіка в абстрактному BaseForm

Спільна механіка йде в `template_form/models.py` поряд з `BaseForm` (спільний фундамент усіх
трьох стадій, а не стадія 1):

1. **`SoftDeleteManager`** - менеджер (клас, що будує запити до БД для моделі), який фільтрує
   `is_deleted=False`.
2. **`BaseForm`** отримує:
   - `is_deleted = models.BooleanField(default=False, db_index=True)` - визначення
     символ-у-символ як у `working_form/models.py:140`, щоб makemigrations не згенерував
     AlterField для наявної колонки WorkingForm;
   - `deleted_at = models.DateTimeField(null=True, blank=True)`;
   - `deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
     null=True, blank=True, related_name="%(class)s_deleted")`;
   - `objects = SoftDeleteManager()` (перший оголошений = default), `all_objects = models.Manager()`;
   - методи `soft_delete(user)` і `restore()` - обидва зберігають через
     `save(update_fields=[...])`. `update_fields` тут критичний: `WorkingForm.save()`
     регенерує name/slug у гілці `if self.pk and not update_fields`
     (`working_form/models.py:306`), і без нього видалення перейменує форму;
   - у `BaseForm.save()` (рядок 109-111) slug-генерація переходить з `self.__class__.objects`
     на `self.__class__.all_objects` - інакше slug видаленого рядка вважатиметься вільним і
     створення впаде з IntegrityError (порушення унікальності на рівні БД).
3. **`working_form/models.py`**: видалити `WorkingFormManager` (рядки 10-26), поле
   `is_deleted` (140) і `objects`/`all_objects` (141-142) - успадковується з BaseForm.
4. `Meta.base_manager_name` не задаємо: доступ через FK (`form.template_origin`,
   `evaluation.working_form_origin`) не має ховати видалені рядки - це історичні посилання.

`ReadOnlyTemplateForm` - proxy-модель (той самий стіл у БД, інша обгортка для адмінки),
менеджери успадковує автоматично.

## Views: perform_destroy у трьох viewset-ах

- `working_form/views.py` WorkingFormViewSet (виправлення наявного бага - зараз hard delete):
  `perform_destroy` -> `instance.soft_delete(self.request.user)`.
- `template_form/views.py` TemplateFormViewSet: `destroy` (рядок ~619) лишається (несе
  `@extend_schema`), додається `perform_destroy` аналогічно.
- `evaluation_form/views.py` EvaluationFormViewSet: `perform_destroy` спершу перевіряє
  `instance.status == EvaluationForm.Status.IN_PROGRESS` -> `raise ValidationError(...)`
  (вже імпортовано, рядок 9; конвенція репо - DRF ValidationError/400, не 409). Далі
  `soft_delete`. `report_file` не чіпається взагалі.

Повторний DELETE уже видаленої форми дає 404 (get_object іде через відфільтрований
queryset) - прийнятно. Broadcast (WebSocket-сповіщення команди) при видаленні робочої форми
відсутній і зараз; лишаємо як є, поза scope.

## Switch-list: що переходить на all_objects

| Місце | Причина |
|---|---|
| `template_form/models.py:110` BaseForm.save (slug) | унікальність slug рахує і видалені |
| `working_form/services.py:386` slug-цикл clone_working_to_evaluation | те саме |
| `evaluation_form/models.py:154` old_instance у EvaluationForm.save | редагування з адмінки видаленого рядка |
| Адмінки трьох форм: get_queryset | адмін бачить видалені для restore |

Свідомо лишаються на відфільтрованому `objects` (бажана поведінка, закріпити тестами):
celery-задача `update_evaluation_statuses` (`evaluation_form/tasks.py:31`),
`check_and_complete_evaluation` (`services.py:41`), queryset-и viewset-ів усіх стадій
(клонування з видаленого шаблона -> 404), items видаленої форми
(`template_form/views.py:736`), WebSocket-конект до видаленої форми (consumers), prefetch
`"evaluations"` у CandidateViewSet (reverse-менеджер будується з default).

## Адмінки (django-unfold)

`working_form/admin.py` і `evaluation_form/admin.py` зараз порожні - створити з нуля;
`template_form/admin.py` - доповнити наявні `TemplateFormAdmin` (~240) і
`ReadOnlyTemplateFormAdmin` (~387). Для кожної:

- `get_queryset` на базі `Model.all_objects` (зберегти select_related);
- `list_display` += `is_deleted`, `list_filter` += `is_deleted`;
- `readonly_fields` += `deleted_by`, `deleted_at` (у evaluation ще `report_file`);
- `@admin.action` "Restore selected" -> `queryset.update(is_deleted=False, deleted_by=None,
  deleted_at=None)` - навмисно через `update` (обходить `save()` і регенерацію slug);
- стандартний admin delete (hard) лишається - рішення №7.

`ManagerPermissionMixin` до нових адмінок НЕ домішувати (у наявних застосований нерівномірно,
див. `api/admin.md`); зафіксувати як окреме питання власнику.

## Міграції

Незакомічені `working_form/0002-0003`, `template_form/0002-0003` вже лежать у дереві - не
перегенеровувати.

```bash
python manage.py showmigrations template_form working_form evaluation_form  # обовʼязково перед makemigrations
python manage.py makemigrations template_form working_form evaluation_form
python manage.py migrate
```

Очікувано: `template_form/0004` і `evaluation_form/0004` - AddField x3 (`is_deleted`,
`deleted_at`, `deleted_by`); `working_form/0004` - AddField x2 (тільки `deleted_at`,
`deleted_by`). Якщо для working_form зʼявився AlterField по `is_deleted` - визначення поля в
BaseForm розійшлося з оригіналом, виправити до migrate.

## Порядок робіт

1. `template_form/models.py`: SoftDeleteManager, поля/менеджери/soft_delete/restore у
   BaseForm, фікс slug-генерації.
2. `working_form/models.py`: прибрати дубльовану механіку.
3. `evaluation_form/models.py:154`, `working_form/services.py:386` -> all_objects.
4. Міграції.
5. perform_destroy у трьох viewset-ах.
6. Адмінки.
7. Тести.
8. Оновити правила, що стали хибними: `.claude/rules/data/models.md` ("all_objects існує лише
   в одному застосунку") і `.claude/rules/domain/forms-lifecycle.md` (таблиця прапорів).

## Верифікація

Критичні тест-кейси (`template_form/tests.py`, `working_form/tests.py`,
`evaluation_form/tests.py`):

- DELETE кожної стадії -> 204; рядок у БД: `is_deleted=True`, `deleted_by`, `deleted_at`
  заповнені (перевірка через `all_objects`);
- видалена форма відсутня в list, retrieve за slug -> 404;
- slug лишається зайнятим: нова форма з тим самим name отримує суфіксований slug;
- DELETE оцінювання IN_PROGRESS -> 400; PENDING/COMPLETED -> 204;
- після soft delete COMPLETED-оцінювання `report_file` не порожній, файл існує;
- `update_evaluation_statuses` не чіпає видалену PENDING-форму;
- `create_working_form` з видаленого шаблона -> 404;
- адмінка бачить видалені; restore-action очищає три поля; після restore форма знову в API;
- права на destroy не змінилися (403 для чужих ролей).

```bash
black .
flake8    # має бути нуль знахідок - єдиний сигнал регресії
python manage.py test template_form working_form evaluation_form
python manage.py test
```
