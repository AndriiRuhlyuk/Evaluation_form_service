---
status: Living
updated_at: "2026-09-04"
---

# Context Map

<!--
Мапа існує, бо глосаріїв більше одного: канон плюс дві дельти фіч. Вона не
описує bounded contexts у сенсі DDD - у цьому репо домен один, і `form`,
`manager`, `level`, `score` розведені кваліфікованими іменами, а не межами
моделі. Тут мапа розділяє інше: те, що вже покрите кодом, і те, що фіча поки
лише пропонує.

УВАГА. Вендорний sdlc:fix-term перемикає адресу запису за самим фактом існування
файлу з цим імʼям: побачивши його, він перестає дивитися на слаг і починає писати
глосарії в теки з кодом. У цьому репо він навмисно вимкнений
(sdlc/plugin/skills/fix-term/SKILL.md перейменований на SKILL.md.example), а хук
check-glossary-drift.sh стежить, щоб оновлення sdlc/ не повернуло його мовчки.
Пише глосарії скіл fix-term-local.
-->

## Glossaries

- [Канон](./CONTEXT.md): 30 термінів і 4 інваріанти, покриті кодом; сенс, який виграє в будь-якому конфлікті
- [ai-answer-scoring-from-transcript](./docs/features/ai-answer-scoring-from-transcript/CONTEXT.md): незалежна машинна оцінка відповідей з транскрипту, AI-7
- [divergence-report](./docs/features/divergence-report/CONTEXT.md): попитанне порівняння машинного і людського балів, AI-8

## Relationships

- **divergence-report → ai-answer-scoring-from-transcript**: вживає `AI answer score` і `inter-rater agreement`, власних записів для них не заводить; `divergence` визначений саме через межу з `inter-rater agreement`
- **обидві дельти → канон**: `score`, `max score`, `completion`, `report`, `assessed level`, `aggregated decision` і `hiring manager` беруться в канонічному сенсі й тут не перевизначаються
- **канон → дельти**: звʼязку немає навмисно. Канон не знає про пропозиції, інакше він перестав би бути описом того, що працює
