---
status: Living
updated_at: "2026-09-02"
---

# Domain Context - evaluation_form_service

<!--
CONTEXT.md is the domain glossary, not a PRD and not a scratch pad. NO implementation
detail here (no datastore/broker/framework names, no API contracts) - only domain words
and the boundaries between them. Implementation choices live in the SAD and ADRs;
behaviour lives in PRD.md.

Multi-context repos: each bounded context has its own CONTEXT.md at its root path
(registered in CONTEXT-MAP.md). System-wide terms that span all contexts live in the
repo-root CONTEXT.md. Never duplicate a term across files - pick one owner.

Terms get fixed inline, the moment they surface in an interview / PRD / review, never
batched «I'll consolidate later». Empty H2 -> prune before commit; keep only the sections
that carry real content. ## Glossary is mandatory; the other two are optional.
-->

## Glossary

<!-- One line per term: name · one-sentence canonical definition · one-sentence boundary
     (what it is NOT / the concept it gets confused with). Grouped by domain area, in the
     order the pipeline introduces them; not alphabetical. -->

- form - опитувальник для технічного інтерв'ю на одній із трьох стадій конвеєра; слово без уточнення стадії завжди двозначне. NOT будь-яка конкретна стадія - у коді немає моделі `Form`, є `TemplateForm`, `WorkingForm` і `EvaluationForm`, і вони не взаємозамінні.
- template form - багаторазовий шаблон із темами й питаннями під один tech stack, не прив'язаний ні до вакансії, ні до кандидата; правки живуть у чернетці й стають видимими лише після публікації. NOT working form - той належить одній вакансії й не перевикористовується. _Avoid_: шаблон форми, форма-шаблон, базова форма
- working form - копія шаблону під одну вакансію, яку команда наймання редагує спільно і мусить затвердити, перш ніж по ній можна інтерв'ювати. NOT template form (той без вакансії) і NOT evaluation form (та вже під конкретного кандидата). _Avoid_: робоча форма, форма вакансії
- evaluation form - заморожена копія затвердженої working form під одного кандидата, що несе оцінки, фідбеки і звіт. NOT working form - ту редагують спільно і вона переживає багатьох кандидатів. _Avoid_: форма оцінювання, форма оцінки кандидата, форма оцінки
- stage clone - створення наступної стадії копіюванням значень без зовнішнього ключа назад, щоб зміна ранньої стадії ніколи не переписувала вже зафіксовану історію. NOT посилання на джерело: `template_origin` і `working_form_origin` існують лише для довідки і зникають у NULL, коли джерело видаляють. _Avoid_: копіювання форми, дублювання форми
- snapshot - копія тексту, складності, теми й максимального бала питання, зроблена в мить додавання до форми, щоб форма лишалась історично точною, коли question bank зміниться пізніше. NOT `Question` - оригінал живе далі своїм життям, його можна змінити або деактивувати, і на snapshot це не вплине. _Avoid_: снепшот, снапшот
- question bank - спільне сховище багаторазових питань із темою, складністю й авторством, з якого форми беруть snapshot. NOT питання всередині форми - ті вже snapshot і назад на сховище не впливають. _Avoid_: банк питань, пул питань
- form manager - співробітник, за яким числиться сама форма як запис. NOT hiring manager (той ухвалює рішення про найм), NOT роль `MANAGER` у `Employee.role`, і NOT менеджер моделі Django (`objects`, `all_objects`) - у цьому репо останнє значення вживається частіше за перше.
- approver - інтерв'юер, окремо призначений затверджувати working form; затвердження одностайне, і лише затверджена форма може стати evaluation form. NOT interviewer - кожен approver є інтерв'юером, але інтерв'юер без цього призначення не голосує ні за затвердження, ні за видалення.
- interviewer - співробітник, який проводить інтерв'ю і ставить оцінки та фідбек по кандидату. NOT approver - це вужча підмножина з правом голосу на стадії working form. _Avoid_: суддя, оцінювач
- hiring manager - той, хто ухвалює остаточне рішення про найм по вакансії. NOT form manager (власник запису) і NOT роль `MANAGER`.
- recruiter - співробітник, який веде процес наймання і єдиний, хто може запустити CRM sync. NOT interviewer - оцінок і фідбеку не дає.
- candidate - людина, яку інтерв'юють, ідентифікована посиланням на картку в PeopleForce. NOT employee - `Employee` це внутрішній користувач системи, кандидат акаунта не має.
- employee - внутрішній користувач системи з роллю і власною сеньйорністю, який входить за email і може бути автором питання, інтерв'юером, рекрутером або власником форми. NOT candidate - кандидата в системі представляє окремий запис без акаунта й без ролі.
- vacancy level - сеньйорність, під яку відкрито вакансію, обрана на working form. NOT assessed level (висновок інтерв'юерів про кандидата) і NOT `Employee.level` (сеньйорність самого співробітника). _Avoid_: рівень вакансії
- assessed level - сеньйорність, яку інтерв'юер за підсумком інтерв'ю приписує кандидату у своєму фідбеку. NOT vacancy level - вони навмисне можуть розійтись, і саме це розходження є корисним сигналом.
- difficulty - складність питання Easy/Medium/Hard, збережена як 1/2/3, її заявляє автор питання. NOT score - це властивість питання, а не відповіді.
- max score - стеля бала за одне питання, `difficulty × 3`, тобто 3/6/9. NOT score (те, що кандидат реально отримав) і NOT difficulty (1/2/3, з якої вона рахується).
- score - 0-3, які один інтерв'юер поставив за одне питання одному кандидату: Немає відповіді / Слабка / Середня / Сильна. NOT max score - шкали різні, і 3 бали за легке питання це стеля, а за складне лише третина.
- lacks expertise - позначка інтерв'юера, що він не мав достатньої експертизи оцінити цю відповідь; для завершення форми питання вважається закритим, але бала не дає. NOT оцінка 0 - нуль стверджує, що кандидат не відповів, а це стверджує, що інтерв'юер не компетентний оцінити.
- approval - одностайна згода всіх призначених approver'ів, після якої working form можна клонувати в evaluation form; нуль approver'ів означає «не затверджено». NOT deletion vote - той працює більшістю, і нуль approver'ів там означає протилежне, «ніколи не видалено».
- deletion vote - голос approver'а за прибирання теми або питання з working form, що спрацьовує більшістю від числа approver'ів. NOT approval (одностайне) і NOT саме видалення - голоси лише роблять елемент кандидатом на видалення. _Avoid_: голосування за видалення
- removed item - питання або тема, приховані з форми, але збережені для історії (`is_removed`). У working form так ховаються і питання, і теми, і їх відсіює менеджер за замовчуванням; у template form прапорець є лише в питань, а менеджера немає взагалі, тож прибрані рядки повертаються нарівні з живими, поки не відфільтруєш вручну. NOT deleted form (`is_deleted` - прихована форма цілком) і NOT inactive (`is_active` - деактивований рядок довідника).
- completion - момент, коли всі інтерв'юери здали фідбек: форма замикається, а питання без оцінок і теми, що спорожніли, видаляються назавжди. NOT генерація звіту - вона тут не відбувається, і це єдине місце в системі, де видалення справжнє, а не м'яке. _Avoid_: завершення форми
- CRM sync - дія, яку запускає рекрутер вручну: рендерить звіт, рахує aggregated decision і публікує нотатку в картці кандидата. NOT completion - завершення лише замикає форму, а без CRM sync звіту не існує взагалі. _Avoid_: синхронізація з CRM
- report - статичний HTML-файл одного завершеного оцінювання. NOT побічний ефект завершення: файл з'являється лише коли рекрутер запускає синхронізацію з CRM, тож завершена форма зазвичай не має звіту взагалі.
- PeopleForce note - коментар у картці кандидата зі зведеним рішенням і посиланням на звіт. NOT сам звіт - нотатка лише посилається на нього.
- decision - власна рекомендація одного інтерв'юера: `next_step` або `refuse`. NOT aggregated decision - те рахується окремо з усіх фідбеків і потрапляє в картку кандидата, а це ні.
- aggregated decision - підсумкове рішення по кандидату, яке рахується з усіх фідбеків у мить синхронізації з CRM: «Move Forward», лише якщо всі інтерв'юери сказали `next_step`, інакше «Mixed/Refuse». NOT decision - той належить одному інтерв'юеру і в картку кандидата не потрапляє.
- project - внутрішній продукт або команда, до якої належить вакансія, довідкові дані. NOT Django-проєкт `evaluation_form_service/` - той пакет із налаштуваннями, і збіг слів тут повний.

## Invariants

<!-- Domain rules that hold across the whole feature/codebase - phrased «X always must / can
     never». These are rules ABOVE any single acceptance criterion, not PRD AC. Nothing here
     may restate a Glossary NOT-reference: one rule, one home. -->

- Слуг форми завжди лишається зарезервованим за м'яко видаленою формою, тож ім'я ніколи не перевикористовується.
- Evaluation form ніколи не створюється з working form, яка не затверджена.
- Один інтерв'юер ніколи не має більше одного score за одне питання і більше одного фідбеку за одну форму - обидві пари унікальні на рівні БД.
- Зданий фідбек ніколи не редагується: правити його може лише автор і лише доти, доки не здав.
