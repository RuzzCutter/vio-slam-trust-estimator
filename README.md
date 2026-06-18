# vio-slam-trust-estimator

Адаптивная оценка достоверности визуальных измерений для VIO (OpenVINS): модуль `trust_estimator` масштабирует шум пиксельных измерений по коэффициенту c(t) ∈ [0, 1].

- План эксперимента: [`эксперимент_v2.md`](эксперимент_v2.md)
- Журнал работ: [`журнал_эксперимента.md`](журнал_эксперимента.md)

---

## Быстрый старт

```bash
# 1. Окружение (один раз)
bash scripts/setup_env.sh
source /opt/ros/jazzy/setup.bash
cd ws_vins && colcon build --symlink-install && source install/setup.bash

# 2. Датасеты EuRoC minimal (один раз)
bash scripts/download_datasets.sh minimal --ros2

# 3. Интерактивный demo
python3 scripts/run_demo.py

# 4. Smoke-test без меню
python3 scripts/run_demo.py --quick          # adaptive, MH_01, 60 с
bash scripts/test_smoke.sh                   # OpenVINS без bag
```

---

## Главная утилита: `run_demo.py`

Интерактивный мастер для прогонов OpenVINS **baseline** (фиксированный шум) и **adaptive** (trust_estimator).

### Интерактивный режим

```bash
python3 scripts/run_demo.py
```

Меню:

| Шаг | Выбор | Описание |
|-----|-------|----------|
| — | Главное меню | `[1]` эксперимент · `[2]` датасеты · `[3]` расширенные параметры |
| 1 | Режим | `adaptive`, `baseline`, `compare` (оба подряд) |
| 2 | Последовательность | все из `config/datasets.yaml` (✓ = bag установлен) |
| 3 | Качество bag | чистый, D1 blur σ=5/9, D3 засветка +40%/+60% |
| 4 | Длительность | 60 с / 120 с / полный bag |
| 5–6 | RViz / ATE | RViz только в одиночном режиме |
| 6–7 | Расширенные | start-offset, retries, trust_tau (опционально) |

### CLI (без меню)

```bash
python3 scripts/run_demo.py --mode baseline   --seq MH_04_difficult --duration 120
python3 scripts/run_demo.py --mode adaptive   --seq MH_04_difficult --eval
python3 scripts/run_demo.py --mode compare    --seq MH_04_difficult --eval
python3 scripts/run_demo.py --mode compare    --seq MH_04_difficult --degrade gaussian:5 --eval
python3 scripts/run_demo.py --datasets        # меню загрузки / custom bag
python3 scripts/run_demo.py --quick           # adaptive MH_01 60 с
python3 scripts/run_demo.py --mode adaptive --seq MH_04_difficult \
  --start-offset 15 --retries 3 --trust-tau 5.0 --eval
```

| Аргумент | Значения | По умолчанию |
|----------|----------|--------------|
| `--mode` | `baseline`, `adaptive`, `compare` | интерактив |
| `--seq` | id из `config/datasets.yaml` | `MH_01_easy` |
| `--duration` | секунды воспроизведения bag | полный bag |
| `--degrade` | `TYPE:LEVEL`, напр. `gaussian:5`, `brightness:40` | нет |
| `--start-offset` | секунды до начала bag | из реестра |
| `--retries` | повторы при расхождении | 3 |
| `--trust-tau` | τ для trust_estimator (adaptive) | 5.0 |
| `--viz` | открыть RViz + bag в одном терминале | выкл. |
| `--eval` | ATE/RPE через evo после прогона | выкл. |
| `--datasets` | меню датасетов | — |
| `--quiet` | меньше вывода в консоль | выкл. |
| `--quick` | adaptive + MH_01 + 60 с | — |

Переменные окружения: `NO_COLOR=1` — отключить цвета; `DEMO_COLOR=1` — принудительно включить (используется внутри).

---

## Низкоуровневый запуск: `run_euroc.sh`

```bash
bash scripts/run_euroc.sh <baseline|adaptive> [SEQUENCE] [OPTIONS]
```

| Опция | Описание |
|-------|----------|
| `--duration SEC` | длина воспроизведения bag (с) |
| `--degrade TYPE:LEVEL` | деградированный bag (см. ниже) |
| `--start-offset S` | начало bag (с); по умолчанию из `config/datasets.yaml` |
| `--trust-tau T` | override `trust_tau` для adaptive |
| `--retries N` | повторы при расхождении траектории (default: 3) |
| `--viz` | RViz + автозапуск bag |
| `--eval` | ATE/RPE после прогона |
| `--quiet` | сокращённый вывод |

Примеры:

```bash
bash scripts/run_euroc.sh baseline MH_01_easy --duration 60
bash scripts/run_euroc.sh adaptive MH_04_difficult --eval
bash scripts/run_euroc.sh adaptive MH_05_difficult --degrade brightness:40 --eval
bash scripts/run_euroc.sh adaptive MH_01_easy --viz
```

---

## Режим «Сравнение» (`--mode compare`)

Последовательно запускает **baseline**, затем **adaptive** на одной последовательности с одинаковыми параметрами bag.

**Почему без RViz:** оба прогона идут **headless**, чтобы:
- нагрузка на CPU/GPU была одинаковой;
- ATE сравнивался честно (RViz может влиять на realtime);
- не открывалось два окна подряд.

RViz доступен только в одиночном режиме: `--mode adaptive --viz` или `bash scripts/run_euroc.sh adaptive ... --viz`.

После прогонов с `--eval` выводится таблица APE/RPE и вердикт по гипотезе (на чистых vs деградированных данных).

---

## Последовательности EuRoC

Каталог: **`config/datasets.yaml`** (+ пользовательские в `config/datasets_custom.yaml`).  
Offset, GT, путь к bag читаются реестром (`scripts/lib/datasets_registry.py`).

| ID | Назначение | Start-offset | Ground truth (ATE) |
|----|------------|--------------|-------------------|
| **MH_01_easy** | Smoke-test (~80 м) | 40 с | **нет** |
| **MH_02_easy** | Опциональный MH | 35 с | **нет** |
| **MH_03_medium** | Опциональный MH | 5 с | **нет** |
| **MH_04_difficult** | Основной benchmark | 15 с | **да** |
| **MH_05_difficult** | Второй сложный сценарий | 5 с | **да** |

### Почему нет GT для MH_01 / MH_02 / MH_03

**Bag с камерой и IMU** для всех MH_0x в EuRoC есть и скачивается нормально.  
**Ground truth для ATE** в этом проекте — готовые текстовые траектории OpenVINS в  
`ws_vins/src/open_vins/ov_data/euroc_mav/`.

Авторы OpenVINS положили туда **не все** последовательности EuRoC, а подмножество для своих бенчмарков:

| Machine Hall | Файл GT в `ov_data` |
|--------------|---------------------|
| MH_01, MH_02, MH_03 | **нет** |
| MH_04, MH_05 | `MH_04_difficult.txt`, `MH_05_difficult.txt` |

Vicon Room (V1_*, V2_*) — GT-файлы в `ov_data` **есть**, но bag'и в minimal/full не скачиваются.

Исходный EuRoC содержит GT (CSV) для всех записей, но для MH_01–03 его нужно **конвертировать в TUM** и указать в `datasets_custom.yaml` (`gt_file: /path/to/gt.txt`), если нужен ATE.

При `--eval` без GT:

```
! Ground truth для MH_02_easy недоступен — ATE пропущен
```

### Предупреждение «траектория расходится»

Скрипт `traj_stats.py` помечает траекторию как расходящуюся, если:
- любая координата |x|, |y| или |z| > **50 м**, или
- скачок между соседними позами > **5 м**.

Сообщение `max координата 1912 m` означает, что фильтр **потерял трекинг** (типичный сбой VIO, не «особенность MH_01»). Возможные причины:
- слишком короткий прогон (60 с при offset 40 с → ~20 с полёта после инициализации);
- ошибка инициализации (см. `openvins.log`);
- баг или неверный конфиг (редко после успешных smoke-тестов).

**Рекомендация:** для сравнения baseline/adaptive — MH_04, полный bag, `--eval`; MH_01 — только smoke «запускается ли VIO».

На **MH_04** прогон с `--start-offset 0` включает фазу подъёма дрона: init проходит с задержкой во время движения, фильтр часто расходится (path ~30 km, ATE n/a). Используйте offset по умолчанию (15 с) или явно `--start-offset 15`.

При расхождении траектории `run_euroc.sh` автоматически повторяет прогон (до 3 раз). Это нормально для MSCKF на MH_04 — baseline без trust иногда нестабилен на «холодном» старте ROS.

---

## Входные данные

| Источник | Путь | Формат |
|----------|------|--------|
| Каталог датасетов | `config/datasets.yaml` | offset, GT, gdrive id, bundles |
| Пользовательские bag | `config/datasets_custom.yaml` | local path или URL |
| EuRoC ROS2 bag | `datasets/euroc/<SEQ>_ros2/` | ROS2 bag (cam0, cam1, imu0) |
| Деградированный bag | `datasets/euroc/degraded/<SEQ>_<type><level>_ros2/` | кэш |
| Конфиг baseline | `ws_vins/.../config/euroc_mav/` | YAML |
| Конфиг adaptive | `ws_vins/.../config/euroc_mav_trust/` | YAML + trust_log |
| Ground truth | `ov_data/euroc_mav/MH_04_difficult.txt` и др. | TUM-подобный текст |

### Датасеты: скачивание и список

```bash
python3 scripts/lib/datasets_registry.py list
bash scripts/download_datasets.sh minimal --ros2              # MH_01, MH_04, MH_05
bash scripts/download_datasets.sh full --ros2                 # + MH_02, MH_03
bash scripts/download_datasets.sh --seq MH_02_easy --ros2       # одна последовательность
python3 scripts/run_demo.py --datasets                          # интерактивно
```

Источники: `ethz-rc` (по умолчанию), `gdrive`, `ethz-legacy` — см. `download_datasets.sh --help`.

---

## Выходные данные

Каждый прогон создаёт каталог:

```
datasets/results/<SEQ>_<mode>_<YYYYMMDD_HHMMSS>/
```

| Файл | Режим | Описание |
|------|-------|----------|
| `trajectory_tum.txt` | оба | оценённая траектория (TUM: `t x y z qx qy qz qw`) |
| `trust_log.csv` | adaptive | лог c(t), f₁…f₄, inliers, … |
| `openvins.log` | оба | stdout/stderr OpenVINS |
| `bag_play.log` | оба | вывод `ros2 bag play` |
| `trajectory_tum_recorder.log` | оба | лог ноды записи траектории |
| `estimator_config.yaml` | adaptive | копия конфига с путём к trust log |
| `kalibr_*.yaml` | adaptive | копии калибровок |
| `metrics/summary.txt` | при `--eval` | `ape_rmse_m=…`, `rpe_rmse_m=…` |
| `metrics/eval.log` | при `--eval` | полный вывод evo |
| `metrics/ape.zip`, `rpe.zip` | при `--eval` | результаты evo |
| `run_meta.json` | оба | seq/mode/degrade, метрики, diverged, c̄ (для batch) |

Строка `RESULT_DIR=...` в конце прогона — маркер для `run_demo.py`.

### Колонки `trust_log.csv`

`timestamp`, `f1`, `f2`, `f3`, `f4`, `c`, `n_inliers`, `n_features`, `e_repr`, `noise_scale`, …

---

## Деградация изображений

| ID | Тип | Параметр в demo | Скрипт |
|----|-----|-----------------|--------|
| D1 | Gaussian blur | `gaussian:5`, `gaussian:9` | `degrade_ros2_bag.py` |
| D3 | Засветка | `brightness:40`, `brightness:60` | `degrade_ros2_bag.py` |

```bash
# Вручную
python3 scripts/degrade_ros2_bag.py \
  --input datasets/euroc/MH_04_difficult_ros2 \
  --output datasets/euroc/degraded/MH_04_difficult_gaussian5_ros2 \
  --type gaussian --level 5

# Деградация папки кадров (offline)
python3 scripts/degrade_dataset.py --input frames/ --output out/ --type gaussian --level 5
```

При первом `--degrade` bag собирается в `datasets/euroc/degraded/` (~7 с для MH_04).

---

## Вспомогательные скрипты

| Скрипт | Назначение |
|--------|------------|
| `record_trajectory.py` | подписка на `/ov_msckf/poseimu` → TUM |
| `evaluate_trajectory.py` | APE/RPE через evo |
| `traj_stats.py` | длина пути, флаг расхождения |
| `run_euroc.sh` | baseline/adaptive прогон EuRoC |
| `run_demo.py` | интерактивный demo (UI, датасеты, расширенные параметры) |
| `run_batch.py` | пакетные compare-прогоны по YAML-плану (без наблюдения) |
| `build_tables.py` | таблицы ATE/RPE для статьи (md / LaTeX / csv) |
| `lib/run_results.py` | разбор каталогов результатов, manifest, вердикт |
| `lib/datasets_registry.py` | реестр датасетов (YAML → offset/GT/bag) |
| `degrade_ros2_bag.py` | деградация камер в ROS2 bag |
| `degrade_dataset.py` | деградация папки кадров (offline, задел) |
| `test_smoke.sh` | OpenVINS без EuRoC |
| `test_tools.sh` | полная проверка toolchain |

---

## Сборка OpenVINS

```bash
source /opt/ros/jazzy/setup.bash
cd ws_vins
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
source install/setup.bash
```

После изменений в `trust_estimator` / `UpdaterMSCKF`:

```bash
colcon build --packages-select ov_msckf --symlink-install
```

Патч совместимости ROS 2 Jazzy: `ov_msckf/src/ros/ROS2Visualizer.h`, `ROSVisualizerHelper.h`.

---

## Критерии гипотезы (кратко)

1. На **деградированных** данных: ATE(adaptive) < ATE(baseline) более чем на 10%.
2. На **чистых** данных: ATE(adaptive) ≤ 1.05 × ATE(baseline).
3. mean c(t) снижается при усилении деградации.

Вердикт выводится автоматически в режиме `compare` с `--eval`.

---

## Пакетные прогоны и таблицы для статьи

План прогонов: `config/batch_paper.yaml` (MH_04/05, clean + D1 + D3).

```bash
# Просмотр плана (без запуска)
python3 scripts/run_batch.py --dry-run

# Ночной batch: 10 compare × 2 прогона ≈ 20 VIO-запусков
python3 scripts/run_batch.py --plan config/batch_paper.yaml

# Продолжить прерванный batch (пропускает успешные строки manifest)
python3 scripts/run_batch.py --resume datasets/results/batches/paper_main_YYYYMMDD_HHMMSS

# Таблицы из batch
python3 scripts/build_tables.py --batch datasets/results/batches/paper_main_... --out paper_tables/

# Таблицы из уже существующих каталогов results/ (автопаринг baseline+adaptive)
python3 scripts/build_tables.py --scan datasets/results --out paper_tables/
```

**Структура batch:**

```
datasets/results/batches/<batch_id>/
├── batch_plan.yaml      # копия плана
├── manifest.jsonl       # одна строка JSON на compare (dirs, APE, verdict)
├── run_01_....log       # полный лог каждого compare
└── batch_summary.txt
```

**Выход `build_tables.py`:** `paper_tables/table_all.md`, …, `table_ablation.md` (режим `--kind ablation`).

### Ablation f₁–f₄

Отключение одного признака за прогон (`trust_use_f*` → false, среднее c по оставшимся 3):

```bash
bash scripts/run_euroc.sh adaptive MH_04_difficult --ablate f1 --degrade gaussian:5 --eval
python3 scripts/run_batch.py --plan config/batch_ablation.yaml   # 20 прогонов
python3 scripts/build_tables.py --batch datasets/results/batches/ablation_d1_... --kind ablation
```

После изменений в `TrustEstimator` пересобрать: `colcon build --packages-select ov_msckf --symlink-install`.

Зависимость batch-планов: `pip install pyyaml` (в venv).

---

## Типичные сценарии

```bash
# Smoke: «VIO живой?»
python3 scripts/run_demo.py --quick

# Демо с RViz
python3 scripts/run_demo.py --mode adaptive --seq MH_01_easy --duration 60 --viz

# Сравнение для статьи (чистые данные)
python3 scripts/run_demo.py --mode compare --seq MH_04_difficult --eval

# Проверка гипотезы (деградация)
python3 scripts/run_demo.py --mode compare --seq MH_04_difficult --degrade gaussian:5 --eval

# Batch без меню (одиночный прогон)
bash scripts/run_euroc.sh baseline MH_05_difficult --eval
bash scripts/run_euroc.sh adaptive MH_05_difficult --degrade brightness:40 --eval

# Batch для таблиц статьи
python3 scripts/run_batch.py --plan config/batch_paper.yaml
python3 scripts/build_tables.py --batch datasets/results/batches/paper_main_... --out paper_tables/

# Ablation f₁–f₄ (на деградации)
python3 scripts/run_batch.py --plan config/batch_ablation.yaml
python3 scripts/build_tables.py --batch datasets/results/batches/ablation_d1_... --kind ablation --out paper_tables/
```

---

## Зависимости

Ubuntu 24.04, ROS 2 Jazzy, Ceres, OpenCV, Python venv (`evo`, `rosbags`, `opencv-python`). Подробности: `scripts/setup_env.sh`.

Старый сервер `robotics.ethz.ch` часто недоступен; датасеты — [ETH Research Collection](https://doi.org/10.3929/ethz-b-000690084).
