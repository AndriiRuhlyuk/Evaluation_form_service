# План: привести незакомічені міграції до ладу, застосувати, протестувати, закомітити

**Гілка:** `feature/evaluation-form-improvement`
**Стан на старті:** 8 незакомічених міграцій у 4 застосунках, Docker вимкнений, БД недоступна.

**Рішення власника (зафіксовані):**
1. У локальній базі є дані, які шкода втратити -> резервна копія обов'язкова, знесення бази заборонене.
2. Тема у `WorkingFormTopic` має бути обов'язковою -> намір міграції `0003` правильний,
   але підстановка `default=1` навмання неприйнятна.

---

## Фаза 0 - підняти базу і зняти резервну копію

Нічого не міняємо, поки копії немає.

```bash
docker-compose up -d db redis
python manage.py wait_for_db
docker-compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup_before_migrations.sql
ls -lh backup_before_migrations.sql   # файл має бути не порожній
```

`backup_before_migrations.sql` додати в `.gitignore`, якщо його там ще немає - дамп бази не
місце в репозиторії.

**Стоп-умова:** файл порожній або команда впала -> далі не йти.

---

## Фаза 1 - з'ясувати, що насправді в базі

Критично: **чи міграція 0003 уже застосована** на цій базі. Якщо так, правити її файл не можна
(Django вважає її виконаною і повторно не запустить).

```bash
python manage.py showmigrations template_form working_form evaluation_form employee
```

Далі три запити до даних. `[X]` навпроти `0003` означає, що вона вже пройшла і питання 1
знімається, лишається питання «чи не підмінилися дані раніше».

```bash
python manage.py shell -c "
from working_form.models import WorkingFormTopic
from template_form.models import TemplateFormTopic
from topic.models import Topic
from django.db.models import Count

print('WorkingFormTopic без теми:', WorkingFormTopic.all_objects.filter(topic__isnull=True).count())
print('Topic з id=1 існує:', Topic.objects.filter(id=1).exists())
print('Дублікати (working_form, topic):', WorkingFormTopic.all_objects.values('working_form','topic').annotate(n=Count('id')).filter(n__gt=1).count())
print('Дублікати (form, topic) у template:', TemplateFormTopic.objects.values('form','topic').annotate(n=Count('id')).filter(n__gt=1).count())
"
```

**Що означає результат:**

| Результат | Наслідок |
|---|---|
| рядків без теми `0` | Фаза 2 зводиться до косметики - прибрати `default=1` як міну на майбутнє |
| рядків без теми `> 0` | Фаза 2 обов'язкова, кожен рядок потребує рішення |
| дублікатів `> 0` (будь-де) | Міграція `0003` впаде на обмеженні унікальності - треба чистити до migrate |

---

## Фаза 2 - правка `working_form/migrations/0003_...py`

Виконувати **тільки якщо `showmigrations` показав `[ ]` навпроти 0003.**

Замінити блок `AlterField` для `workingformtopic.topic` (рядки 59-69) на дві операції:
спершу явна перевірка, потім зміна поля без дефолту.

```python
def forbid_orphan_topics(apps, schema_editor):
    """Тема стає обов'язковою. Рядки без теми не підставляємо навмання -
    зупиняємось і показуємо, скільки їх, щоб рішення ухвалила людина."""
    WorkingFormTopic = apps.get_model("working_form", "WorkingFormTopic")
    orphans = WorkingFormTopic.objects.filter(topic__isnull=True)
    count = orphans.count()
    if count:
        raise RuntimeError(
            f"{count} WorkingFormTopic rows have no topic. Assign a topic or delete "
            f"these rows manually, then re-run migrate. IDs: "
            f"{list(orphans.values_list('id', flat=True)[:20])}"
        )
```

В `operations`, **перед** `AlterField`:

```python
migrations.RunPython(forbid_orphan_topics, migrations.RunPython.noop),
migrations.AlterField(
    model_name="workingformtopic",
    name="topic",
    field=models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="working_form_topics",
        to="topic.topic",
    ),
),
```

Прибрано `default=1` і `preserve_default=False`.

**Чому так, а не «полагодити дані в міграції».** Міграція, яка сама вирішує, що робити з
неоднозначними даними, приховує проблему і повторить рішення на кожному середовищі, де її
запустять. Зупинка з переліком id перекладає рішення на людину, яка знає предметну область,
і залишає слід у консолі. Ціна - migrate доведеться запустити двічі.

**Якщо 0003 уже застосована (`[X]`):** файл не чіпаємо. Замість цього перевіряємо, чи не
постраждали дані: `WorkingFormTopic.all_objects.filter(topic_id=1)` - якщо там рядки,
яких там бути не мало, розбираємо вручну і за потреби пишемо окрему виправну міграцію.

---

## Фаза 3 - зачистити дублікати, якщо Фаза 1 їх знайшла

Робиться до `migrate`, вручну, з поглядом на кожен випадок. Дублікат тем в одній формі -
це або помилка вводу, або два рядки з різними питаннями всередині. Друге злиття
автоматом робити не можна: питання з видаленого рядка зникнуть.

---

## Фаза 4 - застосувати міграції

```bash
python manage.py showmigrations          # знову, вже після правок
python manage.py migrate
```

Очікуваний порядок: `employee/0002`, `template_form/0002-0004`, `working_form/0002-0004`,
`evaluation_form/0004`.

**Чого чекати на екрані:** якщо Фаза 1 показала рядки без теми і ти їх не прибрав - migrate
впаде на `working_form/0003` із зрозумілим повідомленням і переліком id. Це запланована
поведінка, а не поломка. Розбираєш рядки, запускаєш migrate вдруге.

**Стоп-умова:** будь-яка помилка, окрім цієї очікуваної -> зупинитись, показати вивід,
не «пробувати ще раз».

---

## Фаза 5 - верифікація

Порядок з `general.md` - спершу форматування, потім перевірка стилю, потім тести.

```bash
black .
flake8                                   # має бути нуль знахідок; будь-який вивід - регресія
python manage.py test template_form working_form evaluation_form
python manage.py test
```

**Важливе застереження про тести.** `manage.py test` створює порожню тестову базу і проганяє
міграції на ній. Порожніх тем і дублікатів там немає, отже проблеми з Фази 1 у тестах не
відтворюються. Зелені тести підтверджують код, але **не** підтверджують, що migrate пройде на
базі з даними. Єдиний доказ другого - успішний вивід Фази 4.

---

## Фаза 6 - коміти

Конвенція з `README.md`: `Add:` нова функціональність, `Fix:` виправлення, `Update:` зміна
наявного, `Remove:` видалення.

У робочому дереві 57 змінених файлів і близько 7000 доданих рядків - це не один коміт.
Пропоную три, від фундаменту до країв:

```bash
git add template_form/models.py working_form/models.py evaluation_form/models.py \
        */migrations/0002_*.py */migrations/0003_*.py */migrations/0004_*.py
git commit -m "Add: form-level soft delete on all three stages with audit fields"

git add template_form/views.py working_form/views.py evaluation_form/views.py \
        template_form/admin.py working_form/admin.py evaluation_form/admin.py
git commit -m "Fix: DELETE on working form no longer hard-deletes; admin restore action"

git add template_form/tests.py working_form/tests.py evaluation_form/tests.py .claude/rules/
git commit -m "Add: soft delete test coverage, update affected rules"
```

Решта змінених файлів (серіалізатори, сервіси, дозволи - робота попередніх сесій цієї гілки)
до цієї задачі не належить і має йти окремими комітами зі своїми повідомленнями.

**Push робиться тільки після явного «ok, go».**

---

## Чого цей план свідомо НЕ робить

- Не чіпає `template_form/0003` - там лише заміна обмеження унікальності, ризик тільки в
  дублікатах, і він знімається у Фазі 1.
- Не оптимізує блокування таблиць. `AlterUniqueTogether` і `db_index=True` беруть повне
  блокування таблиці; на локальній базі це мілісекунди. Для продакшн-розгортання це треба
  переробляти на `CREATE INDEX CONCURRENTLY` - окрема задача, не тут.
- Не об'єднує 8 міграцій у стиснуту (`squashmigrations`). Спокуса є, але стиснення
  незастосованих міграцій на гілці, яку ще ніхто не мерджив, додає ризику більше, ніж прибирає.
