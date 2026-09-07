#!/usr/bin/env bash
# Мехінічна самоперевірка PRD. Довідка: ../SKILL.md крок 12.
#
# Використання:   scripts/validate-prd.sh <slug>
#                 scripts/validate-prd.sh docs/features/<slug>/PRD.md
#
# Перевіряє тільки те, що можна перевірити без судження: наявність секцій,
# заборонені токени, збіг лічильників, повноту рядків, бюджети довжини.
# Осмисленість критеріїв і точок спостереження перевіряє критик - це не
# робота гріпа, і скрипт навмисно не вдає, що вміє це.
#
# Код виходу: 0 - чисто, 1 - є провали, 2 - файл не знайдено.

set -uo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $(basename "$0") <slug|path-to-PRD.md>" >&2
  exit 2
fi

ARG="$1"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -f "$ARG" ]; then
  PRD="$ARG"
elif [ -f "docs/features/${ARG}/PRD.md" ]; then
  PRD="docs/features/${ARG}/PRD.md"
else
  # Документ, писаний іншим інструментом, часто називається інакше:
  # PRD-write-prd.md, prd.md, PRD-v2.md. Шукати рівно PRD.md означало б
  # відмовлятись перевіряти саме ті документи, які найбільше цього потребують.
  shopt -s nullglob nocaseglob 2>/dev/null || true
  CANDIDATES=( "docs/features/${ARG}"/*prd*.md )
  case ${#CANDIDATES[@]} in
    0) echo "FAIL  не знайдено жодного *prd*.md у docs/features/${ARG}/" >&2; exit 2 ;;
    1) PRD="${CANDIDATES[0]}"
       echo "note  PRD.md немає, беру ${PRD}" >&2 ;;
    *) echo "FAIL  у docs/features/${ARG}/ кілька кандидатів, назви потрібний явно:" >&2
       printf '        %s\n' "${CANDIDATES[@]}" >&2; exit 2 ;;
  esac
fi

BUDGETS="${SKILL_DIR}/references/budgets.md"

PRD="$PRD" BUDGETS="$BUDGETS" python3 - <<'PY'
import os, re, sys

prd_path = os.environ["PRD"]
budgets_path = os.environ["BUDGETS"]
text = open(prd_path, encoding="utf-8").read()

fails, warns = [], []
def fail(check, msg): fails.append((check, msg))
def warn(check, msg): warns.append((check, msg))

# ---------- frontmatter ----------
fm = ""
if text.startswith("---"):
    parts = text.split("---", 2)
    if len(parts) >= 3:
        fm, body = parts[1], parts[2]
    else:
        body = text
else:
    body = text
    fail("frontmatter", "документ не починається з frontmatter")

# Провали frontmatter відкладені: чи це провал, чи попередження, залежить від
# того, чи писав документ цей скіл, а це стане відомо після розбору секцій.
REQUIRED_FM = ["status", "owner", "updated_at", "feature_size",
               "stage_touched", "depth", "ticket", "brief"]
fm_issues = [f"немає поля {k}" for k in REQUIRED_FM
             if not re.search(rf"^{k}\s*:", fm, re.M)]
fm_issues += [f"незаповнений плейсхолдер {m.group(0)!r}"
              for m in re.finditer(r"<[^>\n]+>", fm)]

st = re.search(r"^status\s*:\s*(\S+)", fm, re.M)
if st and st.group(1) not in ("Draft", "Approved", "Frozen"):
    fm_issues.append(f"status={st.group(1)!r} не з набору Draft|Approved|Frozen")

# ---------- розбір на секції ----------
# Секція = від '## N. Назва' до наступного '## '.
heads = [(m.start(), m.group(1), m.group(2).strip())
         for m in re.finditer(r"^##\s+(\d+)\.\s*(.+)$", body, re.M)]
bounds = [m.start() for m in re.finditer(r"^##\s", body, re.M)] + [len(body)]

def section_text(start):
    nxt = next(b for b in bounds if b > start)
    return body[start:nxt]

sections = {int(num): (title, section_text(pos)) for pos, num, title in heads}

def strip_comments(s):
    return re.sub(r"<!--.*?-->", "", s, flags=re.S)

def data_rows(section):
    """Рядки markdown-таблиці без роздільника й без шапки.

    Шапку впізнаємо структурно - це рядок перед роздільником, - а не за
    словом «Аспект» чи «Код»: чужий документ пише шапку англійською, і
    перевірка по слову ловила саме її. Знайдено евал-прогоном 2026-09-07.
    """
    rows = re.findall(r"^\|(.+)\|\s*$", section, re.M)
    sep = lambda s: re.match(r"^[\s|:-]+$", s)
    return [r for i, r in enumerate(rows)
            if not sep(r) and not (i + 1 < len(rows) and sep(rows[i + 1]))]

# ---------- секції за РОЛЛЮ, а не за номером ----------
# Документ, писаний іншим інструментом, тримає ті самі секції під іншими
# номерами: метрики під §7 замість §11, відкриті питання під §8 замість §12.
# Прив'язка до номера означає, що на такому документі половина перевірок
# мовчки не спрацьовує, а підсумок «лише один FAIL» виглядає заспокійливо
# й бреше. Знайдено евал-прогоном 2026-09-07.
ROLES = {
    "stories":  r"user\s*stor|історі",
    "criteria": r"acceptance|критері",
    "errors":   r"error\s*catalogue|каталог\s*помилок|коди\s*помилок",
    "nfr":      r"non-?functional|нефункц|\bnfr\b",
    "kpi":      r"metric|\bkpi\b|метрик",
    "oq":       r"open\s*question|відкрит\w*\s*питанн",
}
by_role = {}
for pos, num, title in heads:
    for role, pat in ROLES.items():
        if role not in by_role and re.search(pat, title, re.I):
            by_role[role] = (int(num), strip_comments(section_text(pos)))

def role(name, fallback_num):
    """Текст секції за роллю; якщо назву не впізнано - за номером."""
    if name in by_role:
        return by_role[name][1]
    return strip_comments(sections.get(fallback_num, ("", ""))[1])

for name, fallback in (("stories", 4), ("criteria", 5), ("errors", 6),
                       ("nfr", 7), ("kpi", 11), ("oq", 12)):
    if name not in by_role and fallback not in sections:
        warn("roles", f"не знайдено секцію ролі «{name}» ні за назвою, ні як §{fallback} "
                      "- відповідні перевірки не виконано")

FOREIGN = len(sections) and max(sections) < 12

for n in range(1, 13):
    if n not in sections:
        (warn if FOREIGN else fail)("sections", f"немає секції {n}")
    else:
        content = strip_comments(sections[n][1])
        content = re.sub(r"^##.*$", "", content, count=1, flags=re.M)
        if not content.strip():
            fail("sections", f"секція {n} порожня")

if FOREIGN:
    warns.insert(0, ("sections",
        f"документ має {max(sections)} секцій, не 12 - схоже, його писав не цей скіл; "
        "пороги §5 усе одно чинні, відсутні секції це пункт міграції, а не провал"))

# Поля frontmatter це форма цього скіла. У чужому документі їх немає за
# визначенням, і валити його за це означало б вимагати міграції, якої ніхто
# не просив. Пороги §5 - інша річ: вони чинні скрізь, і нижче не помʼякшені.
for msg in fm_issues:
    (warn if FOREIGN else fail)("frontmatter", msg)

# ---------- §5: заборонені токени ----------
# Джерело переліку: references/ac-floors.md, розділ «Заборонені токени».
sec5 = role("criteria", 5)
FORBIDDEN = [
    (r"\b(GET|POST|PUT|PATCH|DELETE)\b",            "дієслово запиту"),
    (r"(?:^|\s)/[a-z][\w/{}-]*",                    "шлях"),
    (r"\b(200|201|400|401|403|404|409|500|503)\b",  "номер статусу"),
    (r"\b[a-z_]{2,}\.[a-z_]{2,}\b",                 "код у форматі a.b"),
    (r"\{[^}\n]+\}",                                "фрагмент payload"),
    (r"\b(UNIQUE|INSERT|SELECT|UPDATE|FK)\b",       "конструкція сховища"),
]
for pattern, label in FORBIDDEN:
    for m in re.finditer(pattern, sec5):
        line = sec5[:m.start()].count("\n") + 1
        fail("§5 tokens", f"{label}: {m.group(0)!r} (рядок {line} секції)")

# ---------- §5: точка спостереження на кожен критерій ----------
crit_ids = re.findall(r"^###\s+(AC-\d+)", sec5, re.M)
observed = len(re.findall(r"^\*\*Перевіряється:\*\*", sec5, re.M))
if crit_ids and len(crit_ids) != observed:
    fail("§5 observation", f"критеріїв {len(crit_ids)}, точок спостереження {observed}")
if not crit_ids:
    fail("§5 observation", "жодного критерію вигляду '### AC-NN'")
if len(set(crit_ids)) != len(crit_ids):
    dup = [c for c in set(crit_ids) if crit_ids.count(c) > 1]
    fail("§5 observation", f"повторені номери критеріїв: {', '.join(sorted(dup))}")

# ---------- §5: форма одного критерію ----------
# Правило: references/ac-floors.md, розділ «Форма одного критерію».
# Наявність Given/When/Then - провал, тієї ж природи, що й відсутність точки
# спостереження. Злиття акторів і дій - попередження: відрізнити злиття від
# багатогранності гріпом неможливо, а жорстка заборона вчить обходити скрипт.
# Додано 2026-09-07: усі 24 критерії пройшли пороги, і три з них не можна було
# провалити однозначно.
sec4_roles = set(re.findall(r"^\*\*(?:Як|As a)\*\*\s+([A-Za-zА-Яа-яЇїІіЄєҐґ'’-]+)",
                            role("stories", 4), re.M))
SPLIT_MARKERS = (", а потім", ", а далі", ", потім ", ", а тоді")

for block in re.split(r"^###\s+", sec5, flags=re.M)[1:]:
    name = block.split("\n", 1)[0].strip()
    if not name.startswith("AC-"):
        continue
    parts = {}
    for label in ("Given", "When", "Then"):
        m = re.search(rf"^\*\*{label}\*\*\s+(.+)$", block, re.M)
        parts[label] = m.group(1).strip() if m else None
    missing = [k for k, v in parts.items() if not v]
    if missing:
        fail("§5 shape", f"{name}: немає {', '.join(missing)}")
        continue
    when, then = parts["When"], parts["Then"]
    actors = {r for r in sec4_roles if re.search(rf"\b{re.escape(r)}\b", when)}
    if len(actors) > 1:
        warn("§5 shape", f"{name}: у When два актори ({', '.join(sorted(actors))}) "
                         "- критерій не провалиться однозначно")
    if any(mk in when for mk in SPLIT_MARKERS):
        warn("§5 shape", f"{name}: у When дві дії поспіль - розділити або сказати, "
                         "що правило для обох дослівно те саме")
    if len(then.split()) > 25:
        warn("§5 shape", f"{name}: Then має {len(then.split())} слів проти 25 "
                         "- усередині ймовірно кілька критеріїв")
    elif then.count(";") >= 2:
        warn("§5 shape", f"{name}: Then містить {then.count(';') + 1} тверджень")

# ---------- §5: кожна історія має критерій ----------
sec4 = role("stories", 4)
stories = re.findall(r"^###\s+(US-\d+)", sec4, re.M)
served = set(re.findall(r"\((US-\d+)\)", sec5))
for us in stories:
    if us not in served:
        fail("§5 use-case floor", f"{us} не має жодного критерію")

# ---------- §6: каталог помилок ----------
sec6 = role("errors", 6)
rows = data_rows(sec6)
if rows:
    for r in rows:
        cells = [c.strip().strip("`") for c in r.split("|")]
        if len(cells) != 4:
            fail("§6", f"рядок має {len(cells)} колонок замість 4: |{r}|")
            continue
        code, human, crit, who = cells
        if not re.fullmatch(r"[a-z_]+\.[a-z_]+", code):
            fail("§6", f"код {code!r} не за конвенцією area.reason")
        for name, val in (("що бачить людина", human), ("критерій", crit), ("хто побачить", who)):
            if not val or val.startswith("<"):
                fail("§6", f"{code}: порожня колонка «{name}»")
        for ref in re.findall(r"AC-\d+", crit):
            if ref not in crit_ids:
                fail("§6", f"{code} посилається на {ref}, якого в §5 немає")
        if code in human:
            fail("§6", f"{code}: код просочився в текст для людини")

# ---------- §7: число в графі «Ціль», не будь-де в рядку ----------
# Дивитись на весь рядок замало: «затримка списку p95 | швидко» містить
# цифри від «p95» і проходило. Число має стояти саме в цілі.
sec7 = role("nfr", 7)
ADJECTIVES = r"швидк|надійн|масштабов|стабільн|зручн|прийнятн|мінімальн|достатн|" \
             r"\bfast\b|\breliable\b|\bscalable\b|\bhigh\b|\blow\b"
for r in data_rows(sec7):
    cells = [c.strip() for c in r.split("|")]
    target = cells[1] if len(cells) >= 2 else r
    if re.search(r"\bTBD\b", target, re.I):
        continue                      # дозволено, якщо §12 має рядок з власником
    if not re.search(r"\d", target):
        fail("§7", f"ціль без числа: «{target}» у рядку «{cells[0][:40]}»")
    elif re.search(ADJECTIVES, target, re.I):
        fail("§7", f"прикметник у цілі: «{target}» - надія, а не вимога")
    # Третя колонка: джерело числа, не виправдання числа. Правило й приклади -
    # references/nfr-defaults.md. Попередження, бо межа тут тонка: рядок може
    # називати сусідній замір і цим бути валідним. Знайдено 2026-09-07 -
    # усі рядки мали числа, і два з семи не мали вимірювання взагалі.
    how = cells[2].strip() if len(cells) >= 3 else ""
    if not how:
        warn("§7 measurement", f"«{cells[0][:40]}»: колонка «як міряємо» порожня")
    elif len(how.split()) < 3:
        warn("§7 measurement", f"«{cells[0][:40]}»: «{how}» замало, щоб піти й поміряти")
    elif re.match(r"^(бо |як у |при цьому|людина |нікого |це )", how, re.I):
        warn("§7 measurement", f"«{cells[0][:40]}»: «{how[:50]}» пояснює число, "
                               "а не каже, де його взяти")

# ---------- §11: baseline, target, строк ----------
sec11 = role("kpi", 11)
for line in [l for l in sec11.splitlines() if l.strip().startswith("- ")]:
    low = line.lower()
    missing = [w for w in ("baseline", "target") if w not in low]
    if missing:
        fail("§11", f"немає {', '.join(missing)}: {line.strip()[:80]}")
    elif not re.search(r"\bза\b|\bдо\b|місяц|тижн|квартал|рік", low):
        fail("§11", f"немає строку: {line.strip()[:80]}")

# ---------- §12: власник і дата ----------
sec12 = role("oq", 12)
# І українські, і англійські мітки: чужий документ пише owner/due.
OWNER = re.compile(r"власник\s*:|owner\s*:", re.I)
DUE = re.compile(r"\bдо\s*:|due\s*:", re.I)
DEFAULT = re.compile(r"поки що\s*:|default now\s*:", re.I)
for line in [l for l in sec12.splitlines() if l.strip().startswith("- [")]:
    if not OWNER.search(line):
        fail("§12", f"немає власника: {line.strip()[:80]}")
    if not DUE.search(line):
        fail("§12", f"немає дати: {line.strip()[:80]}")
    # Що діє до відповіді. Без цього читач не відрізнить невирішене від
    # нерозвʼязаного. Попередження, бо чужий документ пише це інакше.
    if not FOREIGN and not DEFAULT.search(line):
        warn("§12 default", f"не сказано, що діє до відповіді: {line.strip()[:70]}")

# ---------- бюджети довжини ----------
budgets = {}
try:
    btext = open(budgets_path, encoding="utf-8").read()
    table = btext.split("## Таблиця", 1)[1].split("##", 1)[0]
    for cell in re.finditer(r"§(\d+)[^|]*\|\s*(\d+)", table):
        budgets[int(cell.group(1))] = int(cell.group(2))
except (OSError, IndexError):
    warn("budgets", f"не вдалося прочитати {budgets_path}, бюджети не перевірено")

for n, limit in sorted(budgets.items()):
    if n not in sections:
        continue
    words = len(strip_comments(sections[n][1]).split())
    if words > limit:
        warn("budgets", f"§{n}: {words} слів проти бюджету {limit} "
                        f"(+{words - limit}) - стискати саме цю секцію")

# ---------- звіт ----------
for check, msg in warns:
    print(f"WARN  [{check}] {msg}")
for check, msg in fails:
    print(f"FAIL  [{check}] {msg}")

print()
if fails:
    print(f"{len(fails)} провал(ів), {len(warns)} попередження. Документ не готовий.")
    sys.exit(1)
print(f"Механічні перевірки чисті. Попереджень: {len(warns)}.")
print("Це не означає, що документ добрий - лише що він не поламаний. "
      "Судження лишається за критиком і людиною.")
sys.exit(0)
PY